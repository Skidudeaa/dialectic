# replay/engine.py — Event Replay Engine

import asyncpg
from datetime import datetime, timezone
from typing import AsyncIterator, Optional
from uuid import UUID

from replay.models import (
    RoomSnapshot, RoomState, ThreadState, MessageState, MemoryState,
    MemberState, ProtocolState, ReplayEvent, LLMDecisionReplay, StateDiff,
)


class EventReplayEngine:
    """
    ARCHITECTURE: Materializes room state at any event sequence via replay.
    WHY: Event sourcing enables temporal queries — "what did the room look like at time T?"
    TRADEOFF: O(N) replay per query vs maintaining snapshots (complex but O(1)).
    """

    def __init__(self, db: asyncpg.Connection):
        self.db = db

    async def state_at(self, room_id: UUID, target_sequence: int) -> RoomSnapshot:
        """
        Materialize complete room state at a specific event sequence.
        Replays all events up to target_sequence and builds state.
        """
        events = await self.db.fetch(
            "SELECT * FROM events WHERE room_id = $1 AND sequence <= $2 ORDER BY sequence",
            room_id, target_sequence,
        )

        snapshot = RoomSnapshot.empty(room_id, target_sequence)

        # Index structures for efficient lookups during replay
        threads_by_id: dict[UUID, ThreadState] = {}
        memories_by_id: dict[UUID, MemoryState] = {}
        message_counts: dict[UUID, int] = {}  # thread_id -> count
        protocols_by_id: dict[UUID, ProtocolState] = {}

        for event in events:
            event_type = event["event_type"]
            payload = event["payload"] or {}
            user_id = event["user_id"]
            thread_id = event["thread_id"]

            # --- Room lifecycle ---
            if event_type == "room_created":
                snapshot.room = RoomState(name=payload.get("name"))

            elif event_type == "room_settings_updated":
                if snapshot.room is None:
                    snapshot.room = RoomState()
                if "interjection_turn_threshold" in payload:
                    snapshot.room.interjection_turn_threshold = payload["interjection_turn_threshold"]
                if "semantic_novelty_threshold" in payload:
                    snapshot.room.semantic_novelty_threshold = payload["semantic_novelty_threshold"]
                if "auto_interjection_enabled" in payload:
                    snapshot.room.auto_interjection_enabled = payload["auto_interjection_enabled"]

            # --- Threads ---
            elif event_type == "thread_created":
                ts = ThreadState(
                    id=thread_id or UUID(payload["thread_id"]) if "thread_id" in payload else thread_id,
                    title=payload.get("title"),
                )
                # Use thread_id from event row first, fall back to payload
                tid = thread_id or (UUID(payload["thread_id"]) if "thread_id" in payload else None)
                if tid:
                    ts.id = tid
                    threads_by_id[tid] = ts
                    message_counts.setdefault(tid, 0)
                    snapshot.threads.append(ts)

            elif event_type == "thread_forked":
                new_tid = UUID(payload["new_thread_id"]) if "new_thread_id" in payload else thread_id
                parent_tid = UUID(payload["parent_thread_id"]) if "parent_thread_id" in payload else None
                fork_msg = UUID(payload["fork_point_message_id"]) if "fork_point_message_id" in payload else None
                ts = ThreadState(
                    id=new_tid,
                    title=payload.get("title"),
                    parent_thread_id=parent_tid,
                    fork_point_message_id=fork_msg,
                )
                threads_by_id[new_tid] = ts
                message_counts.setdefault(new_tid, 0)
                snapshot.threads.append(ts)

            # --- Messages ---
            elif event_type == "message_created":
                msg_tid = thread_id or (UUID(payload["thread_id"]) if "thread_id" in payload else None)
                msg = MessageState(
                    id=UUID(payload["message_id"]) if "message_id" in payload else event["id"],
                    thread_id=msg_tid or room_id,  # fallback
                    sequence=payload.get("sequence", 0),
                    speaker_type=payload.get("speaker_type", "human"),
                    user_id=UUID(payload["user_id"]) if payload.get("user_id") else user_id,
                    message_type=payload.get("message_type", "text"),
                    content=payload.get("content", ""),
                    references_message_id=UUID(payload["references_message_id"]) if payload.get("references_message_id") else None,
                    model_used=payload.get("model_used"),
                    prompt_hash=payload.get("prompt_hash"),
                    token_count=payload.get("token_count"),
                    protocol_id=UUID(payload["protocol_id"]) if payload.get("protocol_id") else None,
                    protocol_phase=payload.get("protocol_phase"),
                )
                snapshot.messages.append(msg)
                if msg_tid and msg_tid in message_counts:
                    message_counts[msg_tid] += 1
                    threads_by_id[msg_tid].message_count = message_counts[msg_tid]

            elif event_type == "message_edited":
                msg_id = UUID(payload["message_id"]) if "message_id" in payload else None
                if msg_id:
                    for m in snapshot.messages:
                        if m.id == msg_id:
                            if "content" in payload:
                                m.content = payload["content"]
                            break

            elif event_type == "message_deleted":
                msg_id = UUID(payload["message_id"]) if "message_id" in payload else None
                if msg_id:
                    for m in snapshot.messages:
                        if m.id == msg_id:
                            m.is_deleted = True
                            break

            # --- Memories ---
            elif event_type == "memory_added":
                mem = MemoryState(
                    id=UUID(payload["memory_id"]) if "memory_id" in payload else event["id"],
                    key=payload.get("key", ""),
                    content=payload.get("content", ""),
                    scope=payload.get("scope", "room"),
                    owner_user_id=UUID(payload["owner_user_id"]) if payload.get("owner_user_id") else None,
                    created_by_user_id=user_id,
                )
                memories_by_id[mem.id] = mem
                snapshot.memories.append(mem)

            elif event_type == "memory_edited":
                mem_id = UUID(payload["memory_id"]) if "memory_id" in payload else None
                if mem_id and mem_id in memories_by_id:
                    mem = memories_by_id[mem_id]
                    if "new_content" in payload:
                        mem.content = payload["new_content"]
                    if "new_version" in payload:
                        mem.version = payload["new_version"]

            elif event_type == "memory_invalidated":
                mem_id = UUID(payload["memory_id"]) if "memory_id" in payload else None
                if mem_id and mem_id in memories_by_id:
                    mem = memories_by_id[mem_id]
                    mem.status = "invalidated"
                    mem.invalidation_reason = payload.get("reason")
                    mem.invalidated_at = event["timestamp"]

            elif event_type == "memory_promoted":
                mem_id = UUID(payload["memory_id"]) if "memory_id" in payload else None
                if mem_id and mem_id in memories_by_id:
                    memories_by_id[mem_id].scope = "global"

            elif event_type == "memory_referenced":
                pass  # Cross-room reference — no state mutation in current room

            # --- Collections ---
            elif event_type == "collection_created":
                pass  # Collections are user-level, not room-snapshot state

            elif event_type == "collection_memory_added":
                pass

            elif event_type == "collection_memory_removed":
                pass

            # --- Members ---
            elif event_type == "user_joined":
                if user_id:
                    snapshot.members.append(MemberState(
                        user_id=user_id,
                        joined_at=event["timestamp"],
                    ))

            elif event_type == "user_modifier_updated":
                pass  # User-level setting, not room state

            # --- Protocols ---
            elif event_type == "protocol_invoked":
                proto = ProtocolState(
                    id=UUID(payload["protocol_id"]) if "protocol_id" in payload else event["id"],
                    thread_id=thread_id or room_id,
                    protocol_type=payload.get("protocol_type", ""),
                    status="invoked",
                    current_phase=0,
                    total_phases=payload.get("total_phases", 0),
                    invoked_by_user_id=user_id,
                    config=payload.get("config", {}),
                )
                protocols_by_id[proto.id] = proto
                snapshot.active_protocol = proto

            elif event_type == "protocol_phase_advanced":
                proto_id = UUID(payload["protocol_id"]) if "protocol_id" in payload else None
                if proto_id and proto_id in protocols_by_id:
                    proto = protocols_by_id[proto_id]
                    proto.current_phase = payload.get("phase_number", proto.current_phase + 1)
                    proto.status = "active"
                    snapshot.active_protocol = proto

            elif event_type == "protocol_concluded":
                proto_id = UUID(payload["protocol_id"]) if "protocol_id" in payload else None
                if proto_id and proto_id in protocols_by_id:
                    protocols_by_id[proto_id].status = "concluded"
                snapshot.active_protocol = None

            elif event_type == "protocol_aborted":
                proto_id = UUID(payload["protocol_id"]) if "protocol_id" in payload else None
                if proto_id and proto_id in protocols_by_id:
                    protocols_by_id[proto_id].status = "aborted"
                snapshot.active_protocol = None

            # --- Async dialogue ---
            elif event_type == "annotation_created":
                pass  # Annotations are message-level metadata

            elif event_type == "briefing_requested":
                pass  # Read-only action, no state mutation

            elif event_type in ("commitment_created", "commitment_confidence_updated",
                                "commitment_resolved"):
                pass  # Commitments tracked in separate table, not in snapshot state

            elif event_type == "trading_snapshot_received":
                pass  # Trading snapshots are room-level metadata, not replay-mutable state

        # Set final timestamp
        if events:
            snapshot.at_timestamp = events[-1]["timestamp"]

        # Resolve member display names
        if snapshot.members:
            member_ids = [m.user_id for m in snapshot.members]
            user_rows = await self.db.fetch(
                "SELECT id, display_name FROM users WHERE id = ANY($1)",
                member_ids,
            )
            name_map = {r["id"]: r["display_name"] for r in user_rows}
            for m in snapshot.members:
                m.display_name = name_map.get(m.user_id)

        return snapshot

    async def replay_stream(
        self,
        room_id: UUID,
        start_sequence: Optional[int] = None,
        end_sequence: Optional[int] = None,
        speed: float = 1.0,
    ) -> AsyncIterator[ReplayEvent]:
        """
        ARCHITECTURE: Yields events with timing for replay playback.
        WHY: Clients can recreate real-time conversation pacing.
        TRADEOFF: Server-side delay vs client-side timing (server simpler for SSE).
        """
        query = (
            "SELECT e.*, u.display_name "
            "FROM events e "
            "LEFT JOIN users u ON e.user_id = u.id "
            "WHERE e.room_id = $1"
        )
        params: list = [room_id]
        idx = 2

        if start_sequence is not None:
            query += f" AND e.sequence >= ${idx}"
            params.append(start_sequence)
            idx += 1

        if end_sequence is not None:
            query += f" AND e.sequence <= ${idx}"
            params.append(end_sequence)
            idx += 1

        query += " ORDER BY e.sequence"

        events = await self.db.fetch(query, *params)

        prev_timestamp: Optional[datetime] = None
        for event in events:
            delay_ms = 0
            if prev_timestamp:
                delta = (event["timestamp"] - prev_timestamp).total_seconds()
                adjusted = delta / max(speed, 0.1)
                delay_ms = int(min(adjusted, 5.0) * 1000)  # Cap at 5s
                delay_ms = max(delay_ms, 50)  # Min 50ms

            yield ReplayEvent(
                sequence=event["sequence"],
                event_type=event["event_type"],
                timestamp=event["timestamp"],
                delay_ms=delay_ms,
                payload=event["payload"] or {},
                user_display_name=event.get("display_name"),
            )

            prev_timestamp = event["timestamp"]

    async def get_llm_decision_context(self, message_id: UUID) -> LLMDecisionReplay:
        """
        ARCHITECTURE: Reconstructs what the LLM "saw" when it made a response.
        WHY: Debuggability — trace back to exact context that produced an output.
        TRADEOFF: Requires message-level metadata; incomplete if events are sparse.
        """
        msg = await self.db.fetchrow(
            "SELECT * FROM messages WHERE id = $1", message_id
        )
        if not msg:
            raise ValueError(f"Message {message_id} not found")

        # Get thread and room info
        thread = await self.db.fetchrow(
            "SELECT * FROM threads WHERE id = $1", msg["thread_id"]
        )
        room_id = thread["room_id"] if thread else None

        # Count messages that were in context (all prior messages in thread)
        messages_in_context = await self.db.fetchval(
            "SELECT COUNT(*) FROM messages WHERE thread_id = $1 AND sequence < $2 AND NOT is_deleted",
            msg["thread_id"], msg["sequence"],
        ) or 0

        # Count active memories at the time of this message
        memories_available = 0
        if room_id:
            memories_available = await self.db.fetchval(
                "SELECT COUNT(*) FROM memories WHERE room_id = $1 AND status = 'active' AND created_at <= $2",
                room_id, msg["created_at"],
            ) or 0

        # Check if there's an interjection event for this message
        interjection_reason = None
        event = await self.db.fetchrow(
            "SELECT payload FROM events WHERE event_type = 'message_created' AND payload->>'message_id' = $1",
            str(message_id),
        )
        if event and event["payload"]:
            interjection_reason = event["payload"].get("interjection_reason")

        return LLMDecisionReplay(
            message_id=message_id,
            model_used=msg["model_used"],
            prompt_hash=msg["prompt_hash"],
            token_count=msg["token_count"],
            messages_in_context=messages_in_context,
            memories_available=memories_available,
            interjection_reason=interjection_reason,
            speaker_type=msg["speaker_type"],
        )

    async def diff_states(
        self, room_id: UUID, seq_a: int, seq_b: int
    ) -> StateDiff:
        """
        ARCHITECTURE: Show what changed between two points in time.
        WHY: Enables "what happened?" for catch-up, auditing, debugging.
        TRADEOFF: Re-scans events in range — O(N) but N is bounded by range.
        """
        lo, hi = min(seq_a, seq_b), max(seq_a, seq_b)

        events = await self.db.fetch(
            "SELECT * FROM events WHERE room_id = $1 AND sequence > $2 AND sequence <= $3 ORDER BY sequence",
            room_id, lo, hi,
        )

        diff = StateDiff(from_sequence=lo, to_sequence=hi)
        settings_changed: set[str] = set()

        for event in events:
            et = event["event_type"]
            payload = event["payload"] or {}

            if et == "message_created":
                diff.messages_added += 1
            elif et == "memory_added":
                diff.memories_added += 1
            elif et == "memory_edited":
                diff.memories_edited += 1
            elif et == "memory_invalidated":
                diff.memories_invalidated += 1
            elif et == "thread_forked":
                diff.threads_forked += 1
            elif et == "room_settings_updated":
                settings_changed.update(payload.keys())

            diff.events.append({
                "sequence": event["sequence"],
                "event_type": et,
                "timestamp": event["timestamp"].isoformat(),
                "summary": _event_summary(et, payload),
            })

        diff.settings_changed = sorted(settings_changed)
        return diff

    async def get_timeline(
        self, room_id: UUID, bucket_count: int = 50
    ) -> list[dict]:
        """
        ARCHITECTURE: Time-bucketed event density for timeline scrubber.
        WHY: Enables heat map visualization — red = intense, blue = quiet.
        TRADEOFF: Fixed bucket count vs adaptive — simple and predictable.
        """
        bounds = await self.db.fetchrow(
            "SELECT MIN(sequence) as min_seq, MAX(sequence) as max_seq FROM events WHERE room_id = $1",
            room_id,
        )
        if not bounds or bounds["min_seq"] is None:
            return []

        min_seq = bounds["min_seq"]
        max_seq = bounds["max_seq"]
        total = max_seq - min_seq + 1
        bucket_size = max(1, total // bucket_count)

        events = await self.db.fetch(
            "SELECT sequence, event_type, timestamp FROM events WHERE room_id = $1 ORDER BY sequence",
            room_id,
        )

        buckets: list[dict] = []
        current_bucket: dict = {
            "start_sequence": min_seq,
            "end_sequence": min_seq + bucket_size - 1,
            "start_time": None,
            "end_time": None,
            "event_count": 0,
            "event_types": {},
        }

        for event in events:
            seq = event["sequence"]
            while seq > current_bucket["end_sequence"]:
                if current_bucket["event_count"] > 0:
                    buckets.append(current_bucket)
                next_start = current_bucket["end_sequence"] + 1
                current_bucket = {
                    "start_sequence": next_start,
                    "end_sequence": next_start + bucket_size - 1,
                    "start_time": None,
                    "end_time": None,
                    "event_count": 0,
                    "event_types": {},
                }

            current_bucket["event_count"] += 1
            et = event["event_type"]
            current_bucket["event_types"][et] = current_bucket["event_types"].get(et, 0) + 1

            ts = event["timestamp"]
            if current_bucket["start_time"] is None:
                current_bucket["start_time"] = ts.isoformat()
            current_bucket["end_time"] = ts.isoformat()

        if current_bucket["event_count"] > 0:
            buckets.append(current_bucket)

        return buckets


def _event_summary(event_type: str, payload: dict) -> str:
    """Generate a human-readable summary of an event."""
    if event_type == "message_created":
        speaker = payload.get("speaker_type", "unknown")
        content = payload.get("content", "")
        preview = content[:80] + "..." if len(content) > 80 else content
        return f"{speaker}: {preview}"
    elif event_type == "memory_added":
        return f"Memory added: {payload.get('key', '?')}"
    elif event_type == "memory_edited":
        return f"Memory edited (v{payload.get('new_version', '?')})"
    elif event_type == "memory_invalidated":
        return f"Memory invalidated: {payload.get('reason', 'no reason')}"
    elif event_type == "thread_forked":
        return f"Thread forked: {payload.get('title', 'untitled')}"
    elif event_type == "room_settings_updated":
        keys = ", ".join(payload.keys())
        return f"Settings changed: {keys}"
    elif event_type == "protocol_invoked":
        return f"Protocol invoked: {payload.get('protocol_type', '?')}"
    elif event_type == "protocol_concluded":
        return "Protocol concluded"
    elif event_type == "user_joined":
        return "User joined room"
    elif event_type == "trading_snapshot_received":
        return "Trading snapshot updated"
    else:
        return event_type
