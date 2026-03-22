"""
Named query functions for cc-sidecar SQLite store.

ARCHITECTURE: Thin wrappers over SQL — each function does one thing.
WHY: Centralizes all SQL in one file for auditability and testing.
TRADEOFF: Verbose but explicit. No ORM magic to debug.
"""
from __future__ import annotations

import time
from typing import Any, Optional

import aiosqlite


# ============================================================
# Raw events
# ============================================================

async def insert_raw_event(
    db: aiosqlite.Connection,
    *,
    received_at_ms: int,
    mono_seq: int,
    session_id: str,
    agent_id: Optional[str],
    source_kind: str,
    event_name: str,
    payload_json: str,
    payload_size: int,
    dedup_hash: str,
    emitter_version: str,
) -> Optional[int]:
    """
    Insert a raw event. Returns the row ID, or None if deduplicated.

    WHY: INSERT OR IGNORE on dedup_hash silently drops duplicates —
    this is the idempotency mechanism for spool replay.
    """
    cursor = await db.execute(
        """INSERT OR IGNORE INTO raw_events
           (received_at_ms, mono_seq, session_id, agent_id, source_kind,
            event_name, payload_json, payload_size, dedup_hash, emitter_version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (received_at_ms, mono_seq, session_id, agent_id, source_kind,
         event_name, payload_json, payload_size, dedup_hash, emitter_version),
    )
    if cursor.rowcount == 0:
        return None  # Deduplicated
    return cursor.lastrowid


async def get_recent_events(
    db: aiosqlite.Connection,
    session_id: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Fetch the most recent events for a session, newest first."""
    cursor = await db.execute(
        """SELECT id, received_at_ms, session_id, agent_id, event_name,
                  payload_json, source_kind
           FROM raw_events
           WHERE session_id = ?
           ORDER BY received_at_ms DESC
           LIMIT ?""",
        (session_id, limit),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


# ============================================================
# Sessions
# ============================================================

async def upsert_session(
    db: aiosqlite.Connection,
    *,
    session_id: str,
    source: Optional[str] = None,
    model: Optional[str] = None,
    cwd: Optional[str] = None,
    project_dir: Optional[str] = None,
    started_at_ms: Optional[int] = None,
) -> None:
    """Create or update a session record, preserving existing values."""
    now_ms = int(time.time() * 1000)
    await db.execute(
        """INSERT INTO sessions (session_id, source, model, cwd, project_dir,
                                started_at_ms, last_seen_at_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(session_id) DO UPDATE SET
               model = COALESCE(excluded.model, sessions.model),
               cwd = COALESCE(excluded.cwd, sessions.cwd),
               project_dir = COALESCE(excluded.project_dir, sessions.project_dir),
               last_seen_at_ms = excluded.last_seen_at_ms""",
        (session_id, source, model, cwd, project_dir, started_at_ms or now_ms, now_ms),
    )


async def update_session_statusline(
    db: aiosqlite.Connection,
    *,
    session_id: str,
    context_used_pct: Optional[float] = None,
    context_remaining_pct: Optional[float] = None,
    total_cost_usd: Optional[float] = None,
    total_duration_ms: Optional[int] = None,
    total_lines_added: Optional[int] = None,
    total_lines_removed: Optional[int] = None,
    worktree_path: Optional[str] = None,
    worktree_branch: Optional[str] = None,
    model: Optional[str] = None,
) -> None:
    """Update session metadata from statusline data."""
    now_ms = int(time.time() * 1000)
    await db.execute(
        """UPDATE sessions SET
               context_used_pct = COALESCE(?, context_used_pct),
               context_remaining_pct = COALESCE(?, context_remaining_pct),
               total_cost_usd = COALESCE(?, total_cost_usd),
               total_duration_ms = COALESCE(?, total_duration_ms),
               total_lines_added = COALESCE(?, total_lines_added),
               total_lines_removed = COALESCE(?, total_lines_removed),
               worktree_path = COALESCE(?, worktree_path),
               worktree_branch = COALESCE(?, worktree_branch),
               model = COALESCE(?, model),
               last_seen_at_ms = ?
           WHERE session_id = ?""",
        (context_used_pct, context_remaining_pct, total_cost_usd,
         total_duration_ms, total_lines_added, total_lines_removed,
         worktree_path, worktree_branch, model, now_ms, session_id),
    )


async def end_session(
    db: aiosqlite.Connection,
    *,
    session_id: str,
    end_reason: Optional[str] = None,
) -> None:
    """Mark a session as ended."""
    now_ms = int(time.time() * 1000)
    await db.execute(
        """UPDATE sessions SET
               ended_at_ms = ?,
               end_reason = ?,
               last_seen_at_ms = ?
           WHERE session_id = ?""",
        (now_ms, end_reason, now_ms, session_id),
    )


async def increment_compaction(
    db: aiosqlite.Connection,
    session_id: str,
) -> None:
    """Increment compaction counter and record timestamp."""
    now_ms = int(time.time() * 1000)
    await db.execute(
        """UPDATE sessions SET
               compaction_count = compaction_count + 1,
               last_compacted_at_ms = ?
           WHERE session_id = ?""",
        (now_ms, session_id),
    )


async def get_session(
    db: aiosqlite.Connection,
    session_id: str,
) -> Optional[dict[str, Any]]:
    """Fetch a single session by ID."""
    cursor = await db.execute(
        "SELECT * FROM sessions WHERE session_id = ?",
        (session_id,),
    )
    row = await cursor.fetchone()
    return dict(row) if row else None


async def get_active_sessions(
    db: aiosqlite.Connection,
) -> list[dict[str, Any]]:
    """Fetch all sessions that haven't ended."""
    cursor = await db.execute(
        "SELECT * FROM sessions WHERE ended_at_ms IS NULL ORDER BY started_at_ms DESC"
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


# ============================================================
# Agents
# ============================================================

async def upsert_agent(
    db: aiosqlite.Connection,
    *,
    agent_pk: str,
    session_id: str,
    agent_id: Optional[str] = None,
    parent_agent_pk: Optional[str] = None,
    agent_type: str,
    state: str = "idle",
    state_source: str = "observed",
    visibility_mode: str = "lifecycle_only",
    started_at_ms: Optional[int] = None,
) -> None:
    """Create or update an agent record, preserving started_at_ms and agent_type."""
    now_ms = int(time.time() * 1000)
    await db.execute(
        """INSERT INTO agents
           (agent_pk, session_id, agent_id, parent_agent_pk, agent_type,
            state, state_source, visibility_mode, started_at_ms, last_event_at_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(agent_pk) DO UPDATE SET
               last_event_at_ms = excluded.last_event_at_ms,
               state = excluded.state,
               state_source = excluded.state_source""",
        (agent_pk, session_id, agent_id, parent_agent_pk, agent_type,
         state, state_source, visibility_mode, started_at_ms or now_ms, now_ms),
    )


async def update_agent_state(
    db: aiosqlite.Connection,
    *,
    agent_pk: str,
    state: str,
    state_source: str = "observed",
    last_tool_name: Optional[str] = None,
    last_resource: Optional[str] = None,
    last_summary: Optional[str] = None,
    is_compacting: Optional[int] = None,
    stopped_at_ms: Optional[int] = None,
) -> None:
    """Update an agent's derived state."""
    now_ms = int(time.time() * 1000)

    # Build dynamic SET clause to avoid overwriting with NULLs
    sets = ["state = ?", "state_source = ?", "last_event_at_ms = ?"]
    params: list[Any] = [state, state_source, now_ms]

    if last_tool_name is not None:
        sets.append("last_tool_name = ?")
        params.append(last_tool_name)
    if last_resource is not None:
        sets.append("last_resource = ?")
        params.append(last_resource)
    if last_summary is not None:
        sets.append("last_summary = ?")
        params.append(last_summary)
    if is_compacting is not None:
        sets.append("is_compacting = ?")
        params.append(is_compacting)
    if stopped_at_ms is not None:
        sets.append("stopped_at_ms = ?")
        params.append(stopped_at_ms)

    params.append(agent_pk)
    await db.execute(
        f"UPDATE agents SET {', '.join(sets)} WHERE agent_pk = ?",
        params,
    )


async def get_agents_for_session(
    db: aiosqlite.Connection,
    session_id: str,
) -> list[dict[str, Any]]:
    """Fetch all agents for a session."""
    cursor = await db.execute(
        "SELECT * FROM agents WHERE session_id = ? ORDER BY started_at_ms",
        (session_id,),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def get_active_agents(
    db: aiosqlite.Connection,
) -> list[dict[str, Any]]:
    """Fetch all agents not in terminal states."""
    cursor = await db.execute(
        """SELECT * FROM agents
           WHERE state NOT IN ('finished', 'orphaned')
           ORDER BY last_event_at_ms DESC"""
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


# ============================================================
# Tool calls
# ============================================================

async def insert_tool_call(
    db: aiosqlite.Connection,
    *,
    tool_use_id: str,
    session_id: str,
    agent_pk: str,
    tool_name: str,
    status: str = "started",
    started_at_ms: Optional[int] = None,
    input_summary: Optional[str] = None,
) -> None:
    """
    Insert a new tool call record.

    WHY: INSERT OR IGNORE for idempotency on replay. Never INSERT OR REPLACE
    because that would reset a completed tool call back to 'started'.
    """
    now_ms = int(time.time() * 1000)
    await db.execute(
        """INSERT OR IGNORE INTO tool_calls
           (tool_use_id, session_id, agent_pk, tool_name, status,
            started_at_ms, input_summary)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (tool_use_id, session_id, agent_pk, tool_name, status,
         started_at_ms or now_ms, input_summary),
    )


async def complete_tool_call(
    db: aiosqlite.Connection,
    *,
    tool_use_id: str,
    status: str,
    error: Optional[str] = None,
) -> None:
    """
    Mark a tool call as completed (success, failure, or denied).

    WHY: Conditional update (WHERE status = 'started') prevents replay
    from overwriting a completed status.
    """
    now_ms = int(time.time() * 1000)
    await db.execute(
        """UPDATE tool_calls
           SET status = ?, ended_at_ms = ?, error = ?
           WHERE tool_use_id = ? AND status = 'started'""",
        (status, now_ms, error, tool_use_id),
    )


# ============================================================
# Files
# ============================================================

async def upsert_file(
    db: aiosqlite.Connection,
    *,
    session_id: str,
    path: str,
    last_writer_agent_pk: Optional[str] = None,
    ownership_source: str = "observed",
    added_lines: Optional[int] = None,
    removed_lines: Optional[int] = None,
    git_status: Optional[str] = None,
) -> None:
    """Track a file modification."""
    now_ms = int(time.time() * 1000)
    await db.execute(
        """INSERT INTO files
           (session_id, path, last_writer_agent_pk, ownership_source,
            added_lines, removed_lines, git_status, last_changed_at_ms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(session_id, path) DO UPDATE SET
               last_writer_agent_pk = COALESCE(excluded.last_writer_agent_pk, files.last_writer_agent_pk),
               ownership_source = excluded.ownership_source,
               added_lines = COALESCE(excluded.added_lines, files.added_lines),
               removed_lines = COALESCE(excluded.removed_lines, files.removed_lines),
               git_status = COALESCE(excluded.git_status, files.git_status),
               last_changed_at_ms = excluded.last_changed_at_ms""",
        (session_id, path, last_writer_agent_pk, ownership_source,
         added_lines, removed_lines, git_status, now_ms),
    )


# ============================================================
# Alerts
# ============================================================

async def insert_alert(
    db: aiosqlite.Connection,
    *,
    session_id: str,
    severity: str,
    kind: str,
    message: str,
) -> int:
    """Insert an alert and return its ID."""
    now_ms = int(time.time() * 1000)
    cursor = await db.execute(
        """INSERT INTO alerts (session_id, severity, kind, message, created_at_ms)
           VALUES (?, ?, ?, ?, ?)""",
        (session_id, severity, kind, message, now_ms),
    )
    return cursor.lastrowid  # type: ignore[return-value]


async def resolve_alert(
    db: aiosqlite.Connection,
    alert_id: int,
) -> None:
    """Mark an alert as resolved."""
    now_ms = int(time.time() * 1000)
    await db.execute(
        "UPDATE alerts SET resolved_at_ms = ? WHERE id = ?",
        (now_ms, alert_id),
    )


async def get_active_alerts(
    db: aiosqlite.Connection,
    session_id: str,
) -> list[dict[str, Any]]:
    """Fetch unresolved alerts for a session."""
    cursor = await db.execute(
        """SELECT * FROM alerts
           WHERE session_id = ? AND resolved_at_ms IS NULL
           ORDER BY created_at_ms DESC""",
        (session_id,),
    )
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


# ============================================================
# Dead events
# ============================================================

async def insert_dead_event(
    db: aiosqlite.Connection,
    *,
    raw_payload: str,
    parse_error: str,
) -> None:
    """Store an unparseable event for debugging."""
    now_ms = int(time.time() * 1000)
    await db.execute(
        """INSERT INTO dead_events (received_at_ms, raw_payload, parse_error)
           VALUES (?, ?, ?)""",
        (now_ms, raw_payload, parse_error),
    )


# ============================================================
# Retention / cleanup
# ============================================================

async def delete_old_events(
    db: aiosqlite.Connection,
    older_than_ms: int,
) -> int:
    """Delete raw events older than the given timestamp. Returns count deleted."""
    cursor = await db.execute(
        "DELETE FROM raw_events WHERE received_at_ms < ?",
        (older_than_ms,),
    )
    await db.commit()
    return cursor.rowcount


async def delete_old_sessions(
    db: aiosqlite.Connection,
    older_than_ms: int,
) -> int:
    """Delete ended sessions older than the given timestamp."""
    cursor = await db.execute(
        "DELETE FROM sessions WHERE ended_at_ms IS NOT NULL AND ended_at_ms < ?",
        (older_than_ms,),
    )
    await db.commit()
    return cursor.rowcount
