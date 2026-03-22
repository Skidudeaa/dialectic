"""
Periodic timers for stuck/orphan detection and maintenance.

ARCHITECTURE: Timer-driven sweeps complement event-driven checks.
WHY: If an agent is truly stuck (no events arriving), only a timer
can detect it — there is no event to trigger on.
TRADEOFF: 10-second timer granularity means up to 10s delay in
detecting a stuck agent. Acceptable since thresholds are 60s+.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

import aiosqlite

from cc_sidecar.constants import (
    BASH_EXTENDED_THRESHOLD_S,
    ORPHAN_SCAN_INTERVAL_S,
    ORPHAN_THRESHOLD_S,
    RAW_EVENT_RETENTION_DAYS,
    SESSION_RETENTION_DAYS,
    STUCK_ALERT_THRESHOLD_S,
    STUCK_WARN_THRESHOLD_S,
    VACUUM_INTERVAL_S,
)
from cc_sidecar.models import AgentState, AlertKind, AlertSeverity
from cc_sidecar.reducer.machine import ReducerRegistry
from cc_sidecar.store import queries

logger = logging.getLogger(__name__)


class OrphanDetector:
    """
    Periodically scans active agents for stuck/orphaned states.

    WHY: Agents can become stuck due to missing SubagentStop events,
    compaction edge cases, or background permission denials.
    The detector uses different thresholds for different contexts:
    - 60s warn, 120s alert for standard agents
    - 180s for agents whose last tool was Bash (long-running commands)
    - No stuck marking for awaiting_perm (expected human wait)
    """

    def __init__(
        self,
        db: aiosqlite.Connection,
        registry: ReducerRegistry,
        broadcast_fn: Optional[object] = None,
    ) -> None:
        self.db = db
        self.registry = registry
        self.broadcast_fn = broadcast_fn
        self._task: Optional[asyncio.Task[None]] = None

    def start(self) -> None:
        """Start the periodic scan loop."""
        self._task = asyncio.create_task(self._scan_loop())
        logger.info("Orphan detector started (interval=%ds)", ORPHAN_SCAN_INTERVAL_S)

    def stop(self) -> None:
        """Stop the periodic scan loop."""
        if self._task:
            self._task.cancel()
            self._task = None

    async def _scan_loop(self) -> None:
        """Main timer loop."""
        try:
            while True:
                await asyncio.sleep(ORPHAN_SCAN_INTERVAL_S)
                await self.scan()
        except asyncio.CancelledError:
            logger.debug("Orphan detector stopped")

    async def scan(self) -> list[str]:
        """
        Scan all active agents and detect stuck/orphaned states.

        Returns a list of alert messages generated.
        """
        now_ms = int(time.time() * 1000)
        alerts: list[str] = []

        for machine in self.registry.get_active_agents():
            # Skip agents awaiting human input — that is expected
            if machine.state == AgentState.AWAITING_PERM:
                continue

            elapsed_s = (now_ms - machine.last_event_at_ms) / 1000

            # Determine threshold based on last tool
            threshold = STUCK_WARN_THRESHOLD_S
            if machine.last_tool_name == "Bash":
                threshold = BASH_EXTENDED_THRESHOLD_S

            # Check thresholds in order: orphan > alert > warn
            if elapsed_s >= ORPHAN_THRESHOLD_S:
                if machine.state != AgentState.ORPHANED:
                    machine.mark_orphaned()
                    msg = (
                        f"Agent {machine.agent_pk} orphaned: "
                        f"no events for {int(elapsed_s)}s"
                    )
                    logger.warning(msg)
                    await queries.update_agent_state(
                        self.db,
                        agent_pk=machine.agent_pk,
                        state=machine.state.value,
                        state_source=machine.state_source.value,
                    )
                    await queries.insert_alert(
                        self.db,
                        session_id=machine.session_id,
                        severity=AlertSeverity.ERROR.value,
                        kind=AlertKind.ORPHANED.value,
                        message=msg,
                    )
                    await self.db.commit()
                    alerts.append(msg)

            elif elapsed_s >= STUCK_ALERT_THRESHOLD_S:
                msg = (
                    f"Agent {machine.agent_pk} stuck: "
                    f"no events for {int(elapsed_s)}s (state={machine.state.value})"
                )
                logger.warning(msg)
                await queries.insert_alert(
                    self.db,
                    session_id=machine.session_id,
                    severity=AlertSeverity.WARN.value,
                    kind=AlertKind.STUCK.value,
                    message=msg,
                )
                await self.db.commit()
                alerts.append(msg)

            elif elapsed_s >= threshold:
                msg = (
                    f"Agent {machine.agent_pk} may be stuck: "
                    f"no events for {int(elapsed_s)}s"
                )
                logger.info(msg)
                alerts.append(msg)

        return alerts


class MaintenanceTimer:
    """
    Periodic maintenance: retention cleanup and incremental vacuum.

    WHY: Raw events and old sessions accumulate without bound.
    This timer applies the configured retention policy and
    reclaims disk space via incremental vacuum.
    """

    def __init__(self, db: aiosqlite.Connection) -> None:
        self.db = db
        self._task: Optional[asyncio.Task[None]] = None

    def start(self) -> None:
        """Start the maintenance loop."""
        self._task = asyncio.create_task(self._maintenance_loop())
        logger.info("Maintenance timer started (interval=%ds)", VACUUM_INTERVAL_S)

    def stop(self) -> None:
        """Stop the maintenance loop."""
        if self._task:
            self._task.cancel()
            self._task = None

    async def _maintenance_loop(self) -> None:
        """Run maintenance tasks periodically."""
        try:
            while True:
                await asyncio.sleep(VACUUM_INTERVAL_S)
                await self._run_maintenance()
        except asyncio.CancelledError:
            logger.debug("Maintenance timer stopped")

    async def _run_maintenance(self) -> None:
        """Execute retention cleanup and vacuum."""
        now_ms = int(time.time() * 1000)

        # Delete old raw events
        cutoff = now_ms - (RAW_EVENT_RETENTION_DAYS * 86400 * 1000)
        deleted_events = await queries.delete_old_events(self.db, cutoff)
        if deleted_events:
            logger.info("Cleaned up %d old events", deleted_events)

        # Delete old ended sessions
        session_cutoff = now_ms - (SESSION_RETENTION_DAYS * 86400 * 1000)
        deleted_sessions = await queries.delete_old_sessions(self.db, session_cutoff)
        if deleted_sessions:
            logger.info("Cleaned up %d old sessions", deleted_sessions)

        # Incremental vacuum
        from cc_sidecar.store.database import run_incremental_vacuum
        await run_incremental_vacuum(self.db)
        logger.debug("Incremental vacuum completed")
