# llm/protocol_manager.py — Protocol lifecycle state machine

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from models import (
    Event, EventType,
    ProtocolType, ProtocolStatus, ProtocolState,
)
from .protocol_library import get_protocol_definition

logger = logging.getLogger(__name__)


class ProtocolManager:
    """
    ARCHITECTURE: Protocol lifecycle state machine with DB persistence.
    WHY: Protocols need durable state across WebSocket reconnections.
    TRADEOFF: DB round-trip per state check vs in-memory (lost on restart).
    """

    def __init__(self, db):
        self.db = db

    async def invoke(
        self,
        thread_id: UUID,
        room_id: UUID,
        protocol_type: str,
        user_id: Optional[UUID] = None,
        config: Optional[dict] = None,
    ) -> ProtocolState:
        """
        Start a new protocol on a thread.

        Raises:
            ValueError: If protocol_type is unknown or thread already has an active protocol.
        """
        definition = get_protocol_definition(protocol_type)

        # Check for existing active protocol on this thread
        existing = await self.get_active(thread_id)
        if existing is not None:
            raise ValueError(
                f"Thread already has an active protocol: {existing.protocol_type.value} "
                f"(status={existing.status.value}). Abort it first."
            )

        now = datetime.now(timezone.utc)
        protocol_id = uuid4()
        config = config or {}

        # Insert protocol record
        await self.db.execute(
            """INSERT INTO thread_protocols
               (id, thread_id, room_id, protocol_type, status,
                current_phase, total_phases, invoked_by_user_id, invoked_at, config)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
            protocol_id, thread_id, room_id,
            protocol_type, ProtocolStatus.ACTIVE.value,
            0, definition.total_phases,
            user_id, now, config,
        )

        # Log initial phase
        await self.db.execute(
            """INSERT INTO protocol_phases (protocol_id, phase_number, phase_name, started_at)
               VALUES ($1, $2, $3, $4)""",
            protocol_id, 0, definition.phase_names[0], now,
        )

        # Emit event
        await self._emit_event(
            event_type=EventType.PROTOCOL_INVOKED,
            room_id=room_id,
            thread_id=thread_id,
            user_id=user_id,
            payload={
                "protocol_id": str(protocol_id),
                "protocol_type": protocol_type,
                "total_phases": definition.total_phases,
                "phase_names": definition.phase_names,
                "config": config,
            },
        )

        return ProtocolState(
            id=protocol_id,
            thread_id=thread_id,
            room_id=room_id,
            protocol_type=ProtocolType(protocol_type),
            status=ProtocolStatus.ACTIVE,
            current_phase=0,
            total_phases=definition.total_phases,
            invoked_by_user_id=user_id,
            invoked_at=now,
            config=config,
        )

    async def get_active(self, thread_id: UUID) -> Optional[ProtocolState]:
        """
        Get the active protocol for a thread, if any.

        Returns None if no protocol is active (status in 'active', 'invoked', 'concluding').
        """
        row = await self.db.fetchrow(
            """SELECT * FROM thread_protocols
               WHERE thread_id = $1
                 AND status IN ('invoked', 'active', 'concluding')
               ORDER BY invoked_at DESC
               LIMIT 1""",
            thread_id,
        )

        if row is None:
            return None

        return self._row_to_state(row)

    async def advance_phase(self, protocol_id: UUID) -> ProtocolState:
        """
        Advance protocol to next phase.

        Raises:
            ValueError: If protocol not found, not active, or already at last phase.
        """
        row = await self.db.fetchrow(
            "SELECT * FROM thread_protocols WHERE id = $1", protocol_id
        )
        if row is None:
            raise ValueError(f"Protocol {protocol_id} not found")

        state = self._row_to_state(row)
        if state.status not in (ProtocolStatus.ACTIVE, ProtocolStatus.INVOKED):
            raise ValueError(f"Protocol is {state.status.value}, cannot advance")

        next_phase = state.current_phase + 1
        definition = get_protocol_definition(state.protocol_type.value)

        if next_phase >= definition.total_phases:
            raise ValueError(
                f"Protocol is at final phase ({state.current_phase + 1}/{definition.total_phases}). "
                "Use conclude() instead."
            )

        now = datetime.now(timezone.utc)

        # Close current phase
        await self.db.execute(
            """UPDATE protocol_phases SET ended_at = $1
               WHERE protocol_id = $2 AND phase_number = $3""",
            now, protocol_id, state.current_phase,
        )

        # Advance protocol
        await self.db.execute(
            """UPDATE thread_protocols
               SET current_phase = $1, phase_advanced_at = $2, status = 'active'
               WHERE id = $3""",
            next_phase, now, protocol_id,
        )

        # Open next phase
        await self.db.execute(
            """INSERT INTO protocol_phases (protocol_id, phase_number, phase_name, started_at)
               VALUES ($1, $2, $3, $4)""",
            protocol_id, next_phase, definition.phase_names[next_phase], now,
        )

        # Emit event
        await self._emit_event(
            event_type=EventType.PROTOCOL_PHASE_ADVANCED,
            room_id=state.room_id,
            thread_id=state.thread_id,
            payload={
                "protocol_id": str(protocol_id),
                "protocol_type": state.protocol_type.value,
                "previous_phase": state.current_phase,
                "new_phase": next_phase,
                "phase_name": definition.phase_names[next_phase],
            },
        )

        state.current_phase = next_phase
        state.status = ProtocolStatus.ACTIVE
        return state

    async def conclude(
        self,
        protocol_id: UUID,
        synthesis_memory_id: Optional[UUID] = None,
    ) -> ProtocolState:
        """
        Conclude a protocol after synthesis is complete.

        Raises:
            ValueError: If protocol not found or not in concludable state.
        """
        row = await self.db.fetchrow(
            "SELECT * FROM thread_protocols WHERE id = $1", protocol_id
        )
        if row is None:
            raise ValueError(f"Protocol {protocol_id} not found")

        state = self._row_to_state(row)
        if state.status not in (ProtocolStatus.ACTIVE, ProtocolStatus.CONCLUDING):
            raise ValueError(f"Protocol is {state.status.value}, cannot conclude")

        now = datetime.now(timezone.utc)

        # Close final phase
        await self.db.execute(
            """UPDATE protocol_phases SET ended_at = $1
               WHERE protocol_id = $2 AND phase_number = $3""",
            now, protocol_id, state.current_phase,
        )

        # Update protocol status
        await self.db.execute(
            """UPDATE thread_protocols
               SET status = 'concluded', concluded_at = $1, synthesis_memory_id = $2
               WHERE id = $3""",
            now, synthesis_memory_id, protocol_id,
        )

        # Emit event
        await self._emit_event(
            event_type=EventType.PROTOCOL_CONCLUDED,
            room_id=state.room_id,
            thread_id=state.thread_id,
            payload={
                "protocol_id": str(protocol_id),
                "protocol_type": state.protocol_type.value,
                "synthesis_memory_id": str(synthesis_memory_id) if synthesis_memory_id else None,
            },
        )

        state.status = ProtocolStatus.CONCLUDED
        state.synthesis_memory_id = synthesis_memory_id
        return state

    async def abort(
        self,
        protocol_id: UUID,
        user_id: Optional[UUID] = None,
        reason: Optional[str] = None,
    ) -> ProtocolState:
        """
        Abort an active protocol.

        Raises:
            ValueError: If protocol not found or already concluded/aborted.
        """
        row = await self.db.fetchrow(
            "SELECT * FROM thread_protocols WHERE id = $1", protocol_id
        )
        if row is None:
            raise ValueError(f"Protocol {protocol_id} not found")

        state = self._row_to_state(row)
        if state.status in (ProtocolStatus.CONCLUDED, ProtocolStatus.ABORTED):
            raise ValueError(f"Protocol is already {state.status.value}")

        now = datetime.now(timezone.utc)

        # Close current phase
        await self.db.execute(
            """UPDATE protocol_phases SET ended_at = $1
               WHERE protocol_id = $2 AND phase_number = $3 AND ended_at IS NULL""",
            now, protocol_id, state.current_phase,
        )

        # Update protocol status
        await self.db.execute(
            """UPDATE thread_protocols SET status = 'aborted', concluded_at = $1
               WHERE id = $2""",
            now, protocol_id,
        )

        # Emit event
        await self._emit_event(
            event_type=EventType.PROTOCOL_ABORTED,
            room_id=state.room_id,
            thread_id=state.thread_id,
            user_id=user_id,
            payload={
                "protocol_id": str(protocol_id),
                "protocol_type": state.protocol_type.value,
                "aborted_at_phase": state.current_phase,
                "reason": reason,
            },
        )

        state.status = ProtocolStatus.ABORTED
        return state

    async def is_final_phase(self, protocol_id: UUID) -> bool:
        """Check if the protocol is on its last phase."""
        row = await self.db.fetchrow(
            "SELECT current_phase, total_phases FROM thread_protocols WHERE id = $1",
            protocol_id,
        )
        if row is None:
            return False
        return row["current_phase"] >= row["total_phases"] - 1

    # ============================================================
    # INTERNAL HELPERS
    # ============================================================

    def _row_to_state(self, row) -> ProtocolState:
        """Convert a DB row to a ProtocolState model."""
        return ProtocolState(
            id=row["id"],
            thread_id=row["thread_id"],
            room_id=row["room_id"],
            protocol_type=ProtocolType(row["protocol_type"]),
            status=ProtocolStatus(row["status"]),
            current_phase=row["current_phase"],
            total_phases=row["total_phases"],
            invoked_by_user_id=row["invoked_by_user_id"],
            invoked_at=row["invoked_at"],
            config=row["config"] if row["config"] else {},
            synthesis_memory_id=row.get("synthesis_memory_id"),
        )

    async def _emit_event(
        self,
        event_type: EventType,
        room_id: UUID,
        thread_id: UUID,
        payload: dict,
        user_id: Optional[UUID] = None,
    ) -> None:
        """Log an event to the events table."""
        now = datetime.now(timezone.utc)
        event = Event(
            id=uuid4(),
            timestamp=now,
            event_type=event_type,
            room_id=room_id,
            thread_id=thread_id,
            user_id=user_id,
            payload=payload,
        )
        await self.db.execute(
            """INSERT INTO events (id, timestamp, event_type, room_id, thread_id, user_id, payload)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            event.id, event.timestamp, event.event_type.value,
            event.room_id, event.thread_id, event.user_id, event.payload,
        )
