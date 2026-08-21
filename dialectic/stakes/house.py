# stakes/house.py — the third forecaster.
#
# ARCHITECTURE: one predicate and one writer for "the participant's own
# forecast". Every reader that partitions a forecast history asks THIS
# module whether a row is the house's, and every writer of a house forecast
# goes through `record_house_forecast`.
#
# WHY a module for two small functions: `presence.py` earned the same shape
# for the same reason. A stranded 'online' row silently disabled push,
# annotator and curator for one member of one room because five readers each
# had their own idea of what "present" meant. The failure here is quieter and
# worse: `api/rounds._round_state` splits a question's history into `mine` and
# `others` on `user_id != viewer_id`, and a house row landing in `others`
# would set `revealed = True` — unsealing one human's blind forecast to the
# other the instant the machine posted its own. The blindness rule is the
# whole reason the Round is worth playing. It gets exactly one definition.
#
# TRADEOFF: the house writes its row DIRECTLY rather than through
# `CommitmentManager.record_confidence`, which would otherwise mirror it into
# tradingDesk's `prediction_confidence` via `stakes_relay`. The desk's scorer
# ignores `actor` (see llm/question_round.py's header), so relaying the
# machine's number would silently pollute the humans' desk-side track record
# with a third forecaster it cannot tell apart.

from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from models import EventType

# The value of `commitment_confidence.actor` for the participant's own
# forecast. Migration 019 constrains the column to exactly these two.
HOUSE = "house"
HUMAN = "human"


def is_house(row) -> bool:
    """True when this forecast row is the participant's own.

    Accepts anything mapping-shaped — an asyncpg Record, a dict, a row built
    in a test. Rows written before migration 019 have no `actor` key at all
    and are human by construction, which is what the `.get` default encodes.
    """
    try:
        return (row.get("actor") or HUMAN) == HOUSE
    except AttributeError:
        return getattr(row, "actor", HUMAN) == HOUSE


def split_by_actor(history) -> tuple[list, list]:
    """(human rows, house rows), order preserved within each.

    The one call every partitioning reader should make before it does
    anything else, so a house row can never be mistaken for a person.
    """
    humans, house = [], []
    for row in history:
        (house if is_house(row) else humans).append(row)
    return humans, house


async def record_house_forecast(
    db,
    *,
    commitment_id,
    room_id,
    thread_id,
    confidence: float,
    reasoning: Optional[str] = None,
) -> dict:
    """Append one house forecast to a question's history.

    Deliberately the same append-only shape as a human's: the house may
    revise, and every revision is scored on the same time-weighted rule, so
    it can be caught updating late exactly like anyone else.
    """
    now = datetime.now(timezone.utc)
    confidence = max(0.0, min(1.0, float(confidence)))
    await db.execute(
        """INSERT INTO commitment_confidence
           (commitment_id, user_id, confidence, recorded_at, reasoning, actor)
           VALUES ($1, NULL, $2, $3, $4, $5)""",
        commitment_id, confidence, now, reasoning, HOUSE,
    )
    await db.execute(
        """INSERT INTO events
           (id, timestamp, event_type, room_id, thread_id, user_id, payload)
           VALUES ($1, $2, $3, $4, $5, NULL, $6)""",
        uuid4(), now, EventType.COMMITMENT_CONFIDENCE_UPDATED.value,
        room_id, thread_id,
        {
            "commitment_id": str(commitment_id),
            "confidence": confidence,
            "reasoning": reasoning,
            "actor": HOUSE,
        },
    )
    return {
        "commitment_id": commitment_id,
        "confidence": confidence,
        "reasoning": reasoning,
        "recorded_at": now,
        "actor": HOUSE,
    }
