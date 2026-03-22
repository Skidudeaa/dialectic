"""
Event ingestion pipeline: normalize → redact → dedup → insert → reduce → broadcast.

ARCHITECTURE: Each event flows through a linear pipeline. Every stage
is independently testable. The pipeline is called once per event.
WHY: Clean separation prevents subtle bugs from interleaved concerns.
TRADEOFF: Slight per-event overhead from multiple function calls vs
a monolithic handler — negligible at 35 events/sec.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any, Optional

import aiosqlite

from cc_sidecar.constants import PAYLOAD_TRUNCATE_BYTES, TOOL_ALIASES
from cc_sidecar.daemon.redact import redact_payload
from cc_sidecar.reducer.extractor import extract_resource, normalize_tool_name
from cc_sidecar.reducer.machine import ReducerRegistry
from cc_sidecar.store import queries

logger = logging.getLogger(__name__)


class IngestPipeline:
    """
    Processes raw events from the emit CLI or spool replay.

    Holds references to the database, reducer registry, and broadcast
    callback for WebSocket fan-out.
    """

    def __init__(
        self,
        db: aiosqlite.Connection,
        registry: ReducerRegistry,
        broadcast_fn: Optional[Any] = None,
    ) -> None:
        self.db = db
        self.registry = registry
        self.broadcast_fn = broadcast_fn

    async def process_event(self, envelope_json: str) -> bool:
        """
        Process a single event through the full pipeline.

        Returns True if the event was ingested (not a duplicate).
        Returns False if deduplicated or failed.
        """
        # ── 1. Parse ──
        try:
            envelope = json.loads(envelope_json)
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse event JSON: %s", e)
            await queries.insert_dead_event(
                self.db,
                raw_payload=envelope_json[:10000],
                parse_error=str(e),
            )
            await self.db.commit()
            return False

        # ── 2. Extract envelope fields ──
        received_at_ms = envelope.get("received_at_ms", int(time.time() * 1000))
        mono_seq = envelope.get("mono_seq", 0)
        emitter_version = envelope.get("emitter_version", "unknown")
        hook_event = envelope.get("hook_event", "")
        session_id = envelope.get("session_id", "")
        agent_id = envelope.get("agent_id")
        payload = envelope.get("payload", envelope)

        if not session_id:
            # Try to extract from payload directly
            session_id = payload.get("session_id", "unknown")

        if not hook_event:
            hook_event = payload.get("hook_event_name", "unknown")

        # ── 3. Normalize tool names ──
        if "tool_name" in payload:
            payload["tool_name"] = normalize_tool_name(payload["tool_name"])

        # ── 4. Redact secrets ──
        redacted_payload = redact_payload(payload)

        # ── 5. Compute dedup hash (upstream payload only) ──
        # WHY: Hash excludes envelope metadata (received_at_ms, mono_seq)
        # so that spool replays produce the same hash as live ingestion.
        payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        dedup_hash = hashlib.sha256(payload_bytes).hexdigest()

        # ── 6. Truncate large payloads ──
        payload_json = json.dumps(redacted_payload, separators=(",", ":"))
        payload_size = len(payload_bytes)
        if len(payload_json) > PAYLOAD_TRUNCATE_BYTES:
            # Store truncated with marker
            truncated = payload_json[:PAYLOAD_TRUNCATE_BYTES]
            payload_json = truncated + ',"_truncated":true}'

        # ── 7. Determine source kind ──
        source_kind = "hook"
        if hook_event == "StatuslineUpdate":
            source_kind = "statusline"

        # ── 8. Insert (dedup via UNIQUE on dedup_hash) ──
        row_id = await queries.insert_raw_event(
            self.db,
            received_at_ms=received_at_ms,
            mono_seq=mono_seq,
            session_id=session_id,
            agent_id=agent_id,
            source_kind=source_kind,
            event_name=hook_event,
            payload_json=payload_json,
            payload_size=payload_size,
            dedup_hash=dedup_hash,
            emitter_version=emitter_version,
        )

        if row_id is None:
            # Deduplicated — skip reduce and broadcast
            return False

        # ── 9. Reduce: update derived state ──
        await self._reduce(session_id, agent_id, hook_event, payload, received_at_ms)

        # ── 10. Commit transaction ──
        await self.db.commit()

        # ── 11. Broadcast to WebSocket clients ──
        if self.broadcast_fn:
            resource = None
            tool_name = payload.get("tool_name")
            if tool_name:
                tool_input = payload.get("tool_input", {})
                resource = extract_resource(tool_name, tool_input)

            await self.broadcast_fn({
                "type": "event",
                "event": {
                    "id": row_id,
                    "received_at_ms": received_at_ms,
                    "session_id": session_id,
                    "agent_id": agent_id,
                    "event_name": hook_event,
                    "tool_name": tool_name,
                    "resource_summary": resource,
                    "source_kind": source_kind,
                },
            })

        return True

    async def _reduce(
        self,
        session_id: str,
        agent_id: Optional[str],
        event_name: str,
        payload: dict[str, Any],
        received_at_ms: int,
    ) -> None:
        """Apply event to the reducer and persist derived state."""

        # ── Session lifecycle ──
        if event_name == "SessionStart":
            await queries.upsert_session(
                self.db,
                session_id=session_id,
                source=payload.get("source"),
                model=payload.get("model"),
                cwd=payload.get("cwd"),
                project_dir=payload.get("project_dir"),
                started_at_ms=received_at_ms,
            )
            # Ensure main agent exists
            self.registry.get_or_create_main(session_id)

        elif event_name == "SessionEnd":
            await queries.end_session(
                self.db,
                session_id=session_id,
                end_reason=payload.get("reason"),
            )

        elif event_name == "PostCompact":
            await queries.increment_compaction(self.db, session_id)

        elif event_name == "StatuslineUpdate":
            await self._handle_statusline(session_id, payload)
            return  # Statusline doesn't route through agent reducer

        # ── Route to agent state machine ──
        machine, new_state = self.registry.route_event(
            session_id=session_id,
            agent_id=agent_id,
            event_name=event_name,
            payload=payload,
        )

        if new_state is not None:
            await queries.update_agent_state(
                self.db,
                agent_pk=machine.agent_pk,
                state=machine.state.value,
                state_source=machine.state_source.value,
                last_tool_name=machine.last_tool_name,
                last_resource=machine.last_resource,
                last_summary=machine.last_summary,
                is_compacting=1 if machine.is_compacting else 0,
                stopped_at_ms=machine.stopped_at_ms,
            )

        # ── Persist agent record on lifecycle events ──
        if event_name in ("SubagentStart", "SessionStart"):
            await queries.upsert_agent(
                self.db,
                agent_pk=machine.agent_pk,
                session_id=session_id,
                agent_id=machine.agent_id,
                parent_agent_pk=machine.parent_agent_pk,
                agent_type=machine.agent_type,
                state=machine.state.value,
                state_source=machine.state_source.value,
                visibility_mode=machine.visibility_mode.value,
                started_at_ms=machine.started_at_ms,
            )

        # ── Tool call tracking ──
        if event_name == "PreToolUse":
            tool_use_id = payload.get("tool_use_id", "")
            tool_name = normalize_tool_name(payload.get("tool_name", "?"))
            tool_input = payload.get("tool_input", {})
            summary = extract_resource(tool_name, tool_input)

            if tool_use_id:
                await queries.insert_tool_call(
                    self.db,
                    tool_use_id=tool_use_id,
                    session_id=session_id,
                    agent_pk=machine.agent_pk,
                    tool_name=tool_name,
                    input_summary=summary,
                    started_at_ms=received_at_ms,
                )

        elif event_name == "PostToolUse":
            tool_use_id = payload.get("tool_use_id", "")
            if tool_use_id:
                await queries.complete_tool_call(
                    self.db,
                    tool_use_id=tool_use_id,
                    status="success",
                )

        elif event_name == "PostToolUseFailure":
            tool_use_id = payload.get("tool_use_id", "")
            error = payload.get("error", "")
            if tool_use_id:
                status = "denied" if "denied" in str(error).lower() else "failure"
                await queries.complete_tool_call(
                    self.db,
                    tool_use_id=tool_use_id,
                    status=status,
                    error=str(error)[:500],
                )

        # ── File tracking ──
        if event_name == "PostToolUse":
            tool_name = normalize_tool_name(payload.get("tool_name", ""))
            if tool_name in ("Write", "Edit"):
                file_path = payload.get("tool_input", {}).get("file_path", "")
                if file_path:
                    await queries.upsert_file(
                        self.db,
                        session_id=session_id,
                        path=file_path,
                        last_writer_agent_pk=machine.agent_pk,
                        ownership_source="observed",
                    )

        # ── Alert generation ──
        if event_name == "Notification":
            notification_type = payload.get("type", "")
            if notification_type == "permission_prompt":
                await queries.insert_alert(
                    self.db,
                    session_id=session_id,
                    severity="warn",
                    kind="permission_denied",
                    message=payload.get("message", "Permission prompt"),
                )

        if event_name == "PreCompact":
            await queries.insert_alert(
                self.db,
                session_id=session_id,
                severity="info",
                kind="compaction",
                message="Context compaction started",
            )

        if event_name == "ConfigChange":
            source = payload.get("source", "unknown")
            file_path = payload.get("file_path", "")
            await queries.insert_alert(
                self.db,
                session_id=session_id,
                severity="info",
                kind="config_change" if source != "skills" else "skill_change",
                message=f"Config changed: {source} ({file_path})",
            )

    async def _handle_statusline(
        self,
        session_id: str,
        payload: dict[str, Any],
    ) -> None:
        """Extract and persist statusline metadata."""
        cost = payload.get("cost", {})
        ctx = payload.get("context_window", {})
        worktree = payload.get("worktree", {})
        model = payload.get("model", {})

        await queries.update_session_statusline(
            self.db,
            session_id=session_id,
            context_used_pct=ctx.get("used_percentage"),
            context_remaining_pct=ctx.get("remaining_percentage"),
            total_cost_usd=cost.get("total_cost_usd"),
            total_duration_ms=cost.get("total_duration_ms"),
            total_lines_added=cost.get("total_lines_added"),
            total_lines_removed=cost.get("total_lines_removed"),
            worktree_path=worktree.get("path"),
            worktree_branch=worktree.get("branch"),
            model=model.get("display_name") or model.get("id"),
        )
        await self.db.commit()
