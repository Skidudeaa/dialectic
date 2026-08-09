"""
v2 durable event schema — persisted state transitions and health changes.

WHY: State transitions are currently ephemeral WebSocket broadcasts. If a
client is disconnected when a node fires, the change is lost. Durable events
in SQLite survive process restarts, support alert timelines, and feed the
"why changed" drawer in the frontend.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Meaningful state changes worth persisting and alerting on.

    WHY: Emit durable events only for changes that affect operator decisions.
    Do NOT emit noisy events for every price tick that does not alter state.
    """
    node_state_changed = "node.state_changed"
    phase_changed = "phase.changed"
    countdown_threshold_crossed = "countdown.threshold_crossed"
    feed_health_changed = "feed.health_changed"
    override_applied = "override.applied"
    override_cleared = "override.cleared"
    journal_created = "journal.created"
    snapshot_recomputed = "snapshot.recomputed"


class EventSeverity(str, Enum):
    """Alert severity — drives UI treatment and notification priority.

    WHY mapping:
      critical = fired node or high-salience phase jump — demands attention
      warning  = approaching, degraded feed, active override — worth noticing
      info     = monitoring changes, journal, reconnect — background awareness
    """
    critical = "critical"
    warning = "warning"
    info = "info"


# WHY: Severity is derived from event type + context, not stored separately
# in the config. This mapping provides defaults; the diffing logic can
# override (e.g., a node firing is critical, but a node going to monitoring
# is info even though both are node.state_changed).
_DEFAULT_SEVERITY: dict[EventType, EventSeverity] = {
    EventType.node_state_changed: EventSeverity.warning,
    EventType.phase_changed: EventSeverity.critical,
    EventType.countdown_threshold_crossed: EventSeverity.warning,
    EventType.feed_health_changed: EventSeverity.warning,
    EventType.override_applied: EventSeverity.info,
    EventType.override_cleared: EventSeverity.info,
    EventType.journal_created: EventSeverity.info,
    EventType.snapshot_recomputed: EventSeverity.info,
}


def severity_for_state_change(old_state: str, new_state: str) -> EventSeverity:
    """Compute severity for a node.state_changed event.

    WHY: Not all state changes are equally important. A node firing is
    critical (demands a trading decision). A node returning to stable
    is info. approaching is a heads-up (warning).
    """
    if new_state == "fired":
        return EventSeverity.critical
    if new_state == "approaching":
        return EventSeverity.warning
    return EventSeverity.info


def default_severity(event_type: EventType) -> EventSeverity:
    """Look up default severity for an event type."""
    return _DEFAULT_SEVERITY.get(event_type, EventSeverity.info)


class AlertEvent(BaseModel):
    """A single durable event record persisted in alert_events table.

    WHY: This is the unit of the alert timeline. Each event is immutable once
    written. The dedupe_key prevents duplicate events when the same state
    change is detected across overlapping evaluation cycles.
    """
    event_id: str
    thesis_id: str
    revision: Optional[int] = None
    event_type: EventType
    severity: EventSeverity
    node_id: Optional[str] = None
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    occurred_at: str
    dedupe_key: str


def make_dedupe_key(
    thesis_id: str,
    event_type: EventType,
    node_id: Optional[str],
    revision: Optional[int],
) -> str:
    """Build a deterministic dedupe key for an event.

    WHY: The UNIQUE constraint on dedupe_key in alert_events prevents
    duplicate events. Two evaluation cycles that detect the same state
    change will produce the same key and the second INSERT is ignored.

    Format: {thesis_id}:{event_type}:{node_id}:{revision}
    """
    parts = [
        thesis_id,
        event_type.value,
        node_id or "",
        str(revision) if revision is not None else "",
    ]
    return ":".join(parts)
