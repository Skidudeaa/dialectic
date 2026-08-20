# presence.py — the one definition of "present right now".
#
# ARCHITECTURE: a single staleness predicate, shared by every reader of
# user_presence, expressed twice — once as SQL for the queries that filter in
# the database, once as Python for the endpoint that classifies rows it has
# already fetched.
#
# WHY this module exists: `status` alone is not the answer. Nothing resets
# presence at process start, and an ungraceful restart leaves a row saying
# 'online' with a heartbeat hours old. Four readers used to disagree about
# that row — only the presence endpoint applied the TTL, while the push
# fan-out, the annotator gate and the trading curator read `status` raw. A
# single stranded row therefore silently disabled a member's push, the
# annotator and the curator FOR THAT ROOM, permanently and with no error
# anywhere. The bug is not that the TTL was wrong; it is that it was one
# reader's private opinion.
#
# TRADEOFF: the SQL form duplicates the Python form's rule in another
# language. They are pinned together by tests/test_presence_predicate.py,
# which runs both against the same rows and asserts they agree.

from datetime import datetime, timedelta, timezone
from typing import Optional

# A client heartbeats every 30s (useDialecticSocket.ts HEARTBEAT_INTERVAL), so
# 90s is three missed beats — long enough to survive a slow network, short
# enough that a closed laptop stops looking present.
PRESENCE_STALE_AFTER = timedelta(seconds=90)
PRESENCE_STALE_SECONDS = int(PRESENCE_STALE_AFTER.total_seconds())

def online_sql(alias: str = "") -> str:
    """The SQL form of is_present(), for queries that filter in the database.

    `alias` qualifies the columns when user_presence is joined under a name
    (e.g. online_sql("up") -> "up.status = 'online' AND up.last_heartbeat ...").
    """
    prefix = f"{alias}." if alias else ""
    return (
        f"{prefix}status = 'online' AND "
        f"{prefix}last_heartbeat > now() - interval "
        f"'{PRESENCE_STALE_SECONDS} seconds'"
    )


# The unaliased form, for queries selecting from user_presence directly.
ONLINE_SQL = online_sql()


def is_present(
    status: Optional[str],
    last_heartbeat: Optional[datetime],
    *,
    now: Optional[datetime] = None,
) -> bool:
    """Whether this row means the user is actually here right now."""
    if status != "online":
        return False
    if last_heartbeat is None:
        return False
    current = now or datetime.now(timezone.utc)
    return last_heartbeat > current - PRESENCE_STALE_AFTER
