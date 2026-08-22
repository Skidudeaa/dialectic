# stakes/manager.py — Commitment lifecycle management

from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID, uuid4
import logging
import math

from models import EventType

from api import stakes_relay

logger = logging.getLogger(__name__)


class CommitmentManager:
    """
    ARCHITECTURE: CRUD + lifecycle management for predictions and commitments.
    WHY: Intellectual accountability — conversations with stakes are thinking.
    TRADEOFF: Additional DB tables vs making thinking visible and accountable.
    """

    def __init__(self, db):
        self.db = db

    async def create_commitment(
        self,
        room_id: UUID,
        claim: str,
        resolution_criteria: str,
        created_by_user_id: Optional[UUID] = None,
        thread_id: Optional[UUID] = None,
        source_message_id: Optional[UUID] = None,
        deadline: Optional[datetime] = None,
        category: str = "prediction",
        initial_confidence: Optional[float] = None,
    ) -> dict:
        """Create a new commitment/prediction with optional initial confidence."""
        now = datetime.now(timezone.utc)
        commitment_id = uuid4()

        await self.db.execute(
            """INSERT INTO commitments
               (id, room_id, thread_id, source_message_id, claim, resolution_criteria,
                category, created_at, created_by_user_id, deadline, status)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'active')""",
            commitment_id, room_id, thread_id, source_message_id,
            claim, resolution_criteria, category, now,
            created_by_user_id, deadline,
        )

        # Record initial confidence if provided
        if initial_confidence is not None:
            await self.db.execute(
                """INSERT INTO commitment_confidence
                   (commitment_id, user_id, confidence, recorded_at)
                   VALUES ($1, $2, $3, $4)""",
                commitment_id, created_by_user_id, initial_confidence, now,
            )

        # Emit event
        await self.db.execute(
            """INSERT INTO events (id, timestamp, event_type, room_id, thread_id, user_id, payload)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            uuid4(), now, EventType.COMMITMENT_CREATED.value,
            room_id, thread_id, created_by_user_id,
            {
                "commitment_id": str(commitment_id),
                "claim": claim,
                "category": category,
                "initial_confidence": initial_confidence,
            },
        )

        # Mirror into the desk's claims ledger. Fire-and-forget by contract:
        # the relay task holds no DB connection (everything it needs is
        # captured here) and a down desk is a debug log, never a failed
        # create. Hooked HERE because both doors — stakes/routes.py and
        # transport/handlers.py — converge on this method.
        try:
            stakes_relay.relay_created(
                {
                    "id": commitment_id,
                    "claim": claim,
                    "resolution_criteria": resolution_criteria,
                    "category": category,
                    "deadline": deadline,
                },
                source_label=await self._relay_source_label(created_by_user_id),
                confidence=initial_confidence,
                # On THIS path the creator is the forecaster — they stated the
                # confidence as they made the claim. Both are passed anyway so
                # the key shape is uniform across all three relays.
                forecaster_id=created_by_user_id,
                proposer_label=await self._relay_source_label(created_by_user_id),
            )
        except Exception:
            logger.debug(
                "stakes relay scheduling failed for %s", commitment_id,
                exc_info=True,
            )

        return {
            "id": commitment_id,
            "room_id": room_id,
            "thread_id": thread_id,
            "source_message_id": source_message_id,
            "claim": claim,
            "resolution_criteria": resolution_criteria,
            "category": category,
            "created_at": now,
            "created_by_user_id": created_by_user_id,
            "deadline": deadline,
            "status": "active",
            "initial_confidence": initial_confidence,
        }

    async def _relay_source_label(self, user_id: Optional[UUID]) -> str:
        """Leaderboard grouping label: display name, or "LLM" for a NULL
        user (the stakes convention everywhere else in this file)."""
        if user_id is None:
            return "LLM"
        try:
            row = await self.db.fetchrow(
                "SELECT display_name FROM users WHERE id = $1", user_id,
            )
        except Exception:
            row = None
        name = row["display_name"] if row else None
        return name or "human"

    async def record_confidence(
        self,
        commitment_id: UUID,
        user_id: Optional[UUID] = None,
        confidence: float = 0.5,
        reasoning: Optional[str] = None,
        peer_forecast: Optional[float] = None,
    ) -> dict:
        """Record or update a participant's confidence level.

        `peer_forecast` (migration 019) is this forecaster's guess at what the
        OTHER one will say. It rides the same row because the two are entered
        and revised in one tap, and it is deliberately NOT relayed to the desk
        below: the desk scores claims, and a bet on your friend is not a claim
        about the world.
        """
        now = datetime.now(timezone.utc)

        # Verify commitment exists and is active. SELECT * because the
        # ledger relay below needs the claim/criteria/deadline to build an
        # idempotent ensure-create for the desk.
        row = await self.db.fetchrow(
            "SELECT * FROM commitments WHERE id = $1",
            commitment_id,
        )
        if not row:
            raise ValueError("Commitment not found")
        if row["status"] != "active":
            raise ValueError("Cannot update confidence on a non-active commitment")

        await self.db.execute(
            """INSERT INTO commitment_confidence
               (commitment_id, user_id, confidence, recorded_at, reasoning,
                peer_forecast)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            commitment_id, user_id, confidence, now, reasoning, peer_forecast,
        )

        # Emit event
        await self.db.execute(
            """INSERT INTO events (id, timestamp, event_type, room_id, thread_id, user_id, payload)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            uuid4(), now, EventType.COMMITMENT_CONFIDENCE_UPDATED.value,
            row["room_id"], row["thread_id"], user_id,
            {
                "commitment_id": str(commitment_id),
                "confidence": confidence,
                "reasoning": reasoning,
            },
        )

        # Mirror the restatement into the ledger's append-only history.
        # seq comes from the room's own table so the idempotency key is
        # stable across retries of the SAME event but distinct per event.
        try:
            seq_row = await self.db.fetchrow(
                "SELECT COUNT(*) AS n FROM commitment_confidence WHERE commitment_id = $1",
                commitment_id,
            )
            seq = int(seq_row["n"]) if seq_row and seq_row["n"] is not None else 1
            commitment = dict(row)
            commitment.setdefault("id", commitment_id)
            stakes_relay.relay_confidence(
                commitment,
                # THE FORECASTER, not the creator. `user_id` is who moved the
                # slider; `created_by_user_id` is who wrote the question, and
                # for a Sunday Round question that is nobody at all. Labelling
                # by creator put both humans' round forecasts on one desk row
                # called "LLM" -- see this module's header and
                # docs/reviews/2026-08-21_round-forecast-attribution.md.
                source_label=await self._relay_source_label(user_id),
                seq=seq,
                confidence=confidence,
                reasoning=reasoning,
                forecaster_id=user_id,
                proposer_label=await self._relay_source_label(
                    commitment.get("created_by_user_id")
                ),
            )
        except Exception:
            logger.debug(
                "stakes relay scheduling failed for %s", commitment_id,
                exc_info=True,
            )

        return {
            "commitment_id": commitment_id,
            "user_id": user_id,
            "confidence": confidence,
            "reasoning": reasoning,
            "recorded_at": now,
        }

    async def resolve(
        self,
        commitment_id: UUID,
        resolution: str,
        resolved_by_user_id: UUID,
        resolution_notes: Optional[str] = None,
    ) -> dict:
        """Resolve a commitment (correct/incorrect/partial/voided)."""
        valid = {"correct", "incorrect", "partial", "voided"}
        if resolution not in valid:
            raise ValueError(f"Invalid resolution. Must be one of: {valid}")

        now = datetime.now(timezone.utc)

        # SELECT * — the ledger relay below needs the full row (see
        # record_confidence for why).
        row = await self.db.fetchrow(
            "SELECT * FROM commitments WHERE id = $1",
            commitment_id,
        )
        if not row:
            raise ValueError("Commitment not found")
        if row["status"] != "active":
            raise ValueError("Commitment is not active")

        new_status = "voided" if resolution == "voided" else "resolved"

        await self.db.execute(
            """UPDATE commitments
               SET resolved_at = $1, resolved_by_user_id = $2,
                   resolution = $3, resolution_notes = $4, status = $5
               WHERE id = $6""",
            now, resolved_by_user_id, resolution, resolution_notes,
            new_status, commitment_id,
        )

        # Emit event
        await self.db.execute(
            """INSERT INTO events (id, timestamp, event_type, room_id, thread_id, user_id, payload)
               VALUES ($1, $2, $3, $4, $5, $6, $7)""",
            uuid4(), now, EventType.COMMITMENT_RESOLVED.value,
            row["room_id"], row["thread_id"], resolved_by_user_id,
            {
                "commitment_id": str(commitment_id),
                "claim": row["claim"],
                "resolution": resolution,
                "resolution_notes": resolution_notes,
            },
        )

        # Mirror the verdict into the ledger. The LAST recorded confidence
        # travels along only to make the ensure-create possible when the
        # commitment never reached the desk while active; a commitment with
        # no confidence at all stays un-relayed (nothing to score).
        try:
            # ONE RELAY PER HUMAN FORECASTER, each carrying that person's own
            # last number. The ledger holds a row per (commitment, forecaster)
            # since 2026-08-22, so a single relay would resolve whichever row
            # it happened to build and leave every other forecaster's claim
            # open forever — which scores as "never answered", not as right or
            # wrong. DISTINCT ON gives the latest row per person in one pass.
            #
            # EXCLUDE BY ACTOR, NEVER BY A NULL user_id. The house writes
            # straight to commitment_confidence (stakes/house.py) and is not
            # mirrored to the desk, so it has to be dropped — but `user_id IS
            # NOT NULL` is the wrong instrument for that, and it is precisely
            # the confusion stakes/house.py was created to end. A NULL user_id
            # ALSO means a legitimate un-attributed claim: create_commitment
            # accepts `created_by_user_id=None` with an initial confidence and
            # relays it as "LLM". Filtering on NULL would relay that claim's
            # creation and then never resolve it, leaving it open forever.
            conf_rows = await self.db.fetch(
                """SELECT DISTINCT ON (user_id) user_id, confidence
                   FROM commitment_confidence
                   WHERE commitment_id = $1 AND actor <> 'house'
                   ORDER BY user_id, recorded_at DESC""",
                commitment_id,
            )
            commitment = dict(row)
            commitment.setdefault("id", commitment_id)
            proposer_label = await self._relay_source_label(
                commitment.get("created_by_user_id")
            )
            for conf in conf_rows:
                stakes_relay.relay_resolved(
                    commitment,
                    source_label=await self._relay_source_label(conf["user_id"]),
                    resolution=resolution,
                    resolution_notes=resolution_notes,
                    last_confidence=conf["confidence"],
                    forecaster_id=conf["user_id"],
                    proposer_label=proposer_label,
                )
        except Exception:
            logger.debug(
                "stakes relay scheduling failed for %s", commitment_id,
                exc_info=True,
            )

        return {
            "id": commitment_id,
            "resolution": resolution,
            "resolution_notes": resolution_notes,
            "resolved_at": now,
            "resolved_by_user_id": resolved_by_user_id,
            "status": new_status,
        }

    async def get_room_commitments(
        self,
        room_id: UUID,
        status: Optional[str] = None,
        include_confidence: bool = True,
    ) -> list[dict]:
        """Get all commitments for a room with confidence history."""
        query = "SELECT * FROM commitments WHERE room_id = $1"
        params: list = [room_id]

        if status:
            query += " AND status = $2"
            params.append(status)

        query += " ORDER BY created_at DESC"
        rows = await self.db.fetch(query, *params)

        commitments = []
        for row in rows:
            c = dict(row)
            if include_confidence:
                conf_rows = await self.db.fetch(
                    """SELECT cc.*, u.display_name
                       FROM commitment_confidence cc
                       LEFT JOIN users u ON cc.user_id = u.id
                       WHERE cc.commitment_id = $1
                       ORDER BY cc.recorded_at DESC""",
                    row["id"],
                )
                c["confidence_history"] = [
                    {
                        "user_id": cr["user_id"],
                        "display_name": cr["display_name"] if cr["user_id"] else "LLM",
                        "confidence": cr["confidence"],
                        "reasoning": cr["reasoning"],
                        "recorded_at": cr["recorded_at"],
                    }
                    for cr in conf_rows
                ]
            commitments.append(c)

        return commitments

    async def get_commitment(self, commitment_id: UUID) -> dict:
        """Get a single commitment with full confidence history."""
        row = await self.db.fetchrow(
            "SELECT * FROM commitments WHERE id = $1", commitment_id,
        )
        if not row:
            raise ValueError("Commitment not found")

        c = dict(row)

        conf_rows = await self.db.fetch(
            """SELECT cc.*, u.display_name
               FROM commitment_confidence cc
               LEFT JOIN users u ON cc.user_id = u.id
               WHERE cc.commitment_id = $1
               ORDER BY cc.recorded_at DESC""",
            commitment_id,
        )
        c["confidence_history"] = [
            {
                "user_id": cr["user_id"],
                "display_name": cr["display_name"] if cr["user_id"] else "LLM",
                "confidence": cr["confidence"],
                "reasoning": cr["reasoning"],
                "recorded_at": cr["recorded_at"],
            }
            for cr in conf_rows
        ]

        return c

    async def get_calibration(
        self,
        user_id: Optional[UUID] = None,
        room_id: Optional[UUID] = None,
    ) -> dict:
        """
        Compute calibration curve: for each confidence bucket (0-0.1, 0.1-0.2, ...),
        what fraction were actually correct?
        Good calibration: 70% confident predictions are correct ~70% of the time.

        ARCHITECTURE: Bucketed accuracy computation over resolved commitments.
        WHY: Calibration is the gold-standard measure of prediction quality.
        TRADEOFF: Requires enough resolved predictions per bucket to be meaningful.
        """
        # Get the last confidence recorded before resolution for each commitment
        query = """
            SELECT cc.confidence, c.resolution
            FROM commitment_confidence cc
            JOIN commitments c ON cc.commitment_id = c.id
            WHERE c.status = 'resolved'
              AND c.resolution IN ('correct', 'incorrect', 'partial')
              AND cc.recorded_at = (
                  SELECT MAX(cc2.recorded_at) FROM commitment_confidence cc2
                  WHERE cc2.commitment_id = cc.commitment_id
                    AND cc2.user_id IS NOT DISTINCT FROM cc.user_id
                    AND cc2.recorded_at <= c.resolved_at
              )
        """
        params: list = []
        conditions = []

        if user_id is not None:
            conditions.append(f"cc.user_id = ${len(params) + 1}")
            params.append(user_id)

        if room_id is not None:
            conditions.append(f"c.room_id = ${len(params) + 1}")
            params.append(room_id)

        if conditions:
            query += " AND " + " AND ".join(conditions)

        rows = await self.db.fetch(query, *params)

        # Bucket into 0.1 increments
        buckets: dict[str, dict] = {}
        for i in range(10):
            low = i / 10
            high = (i + 1) / 10
            label = f"{low:.1f}-{high:.1f}"
            buckets[label] = {"total": 0, "correct": 0, "partial": 0}

        for row in rows:
            conf = row["confidence"]
            resolution = row["resolution"]
            bucket_idx = min(int(conf * 10), 9)
            low = bucket_idx / 10
            high = (bucket_idx + 1) / 10
            label = f"{low:.1f}-{high:.1f}"

            buckets[label]["total"] += 1
            if resolution == "correct":
                buckets[label]["correct"] += 1
            elif resolution == "partial":
                buckets[label]["partial"] += 0.5  # Count partial as half

        # Compute accuracy per bucket
        calibration = []
        total_predictions = 0
        total_correct = 0
        brier_sum = 0.0

        for label, data in buckets.items():
            total = data["total"]
            total_predictions += total
            correct = data["correct"] + data["partial"]
            total_correct += correct

            accuracy = correct / total if total > 0 else None
            mid = (float(label.split("-")[0]) + float(label.split("-")[1])) / 2

            calibration.append({
                "bucket": label,
                "midpoint": mid,
                "total": total,
                "correct": correct,
                "accuracy": accuracy,
            })

            # Brier score contribution
            if total > 0:
                for row in rows:
                    conf = row["confidence"]
                    bucket_idx = min(int(conf * 10), 9)
                    row_label = f"{bucket_idx / 10:.1f}-{(bucket_idx + 1) / 10:.1f}"
                    if row_label == label:
                        outcome = 1.0 if row["resolution"] == "correct" else (
                            0.5 if row["resolution"] == "partial" else 0.0
                        )
                        brier_sum += (conf - outcome) ** 2

        brier_score = brier_sum / total_predictions if total_predictions > 0 else None

        return {
            "calibration": calibration,
            "total_predictions": total_predictions,
            "total_correct": total_correct,
            "brier_score": brier_score,
            "user_id": user_id,
            "room_id": room_id,
        }

    async def get_expiring_soon(
        self,
        room_id: UUID,
        days: int = 7,
    ) -> list[dict]:
        """Get commitments with deadlines approaching within N days."""
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=days)

        rows = await self.db.fetch(
            """SELECT * FROM commitments
               WHERE room_id = $1
                 AND status = 'active'
                 AND deadline IS NOT NULL
                 AND deadline <= $2
               ORDER BY deadline ASC""",
            room_id, cutoff,
        )

        return [dict(row) for row in rows]

    async def check_relevant_commitments(
        self,
        room_id: UUID,
        message_content: str,
    ) -> list[dict]:
        """
        Find active commitments that are semantically related to the current message.
        Uses keyword overlap heuristic for speed; full semantic search deferred.

        ARCHITECTURE: Lightweight keyword match against active claims.
        WHY: Surfacing relevant predictions during conversation drives accountability.
        TRADEOFF: Keyword overlap misses nuanced semantic connections but is instant.
        """
        rows = await self.db.fetch(
            """SELECT * FROM commitments
               WHERE room_id = $1 AND status = 'active'
               ORDER BY created_at DESC
               LIMIT 50""",
            room_id,
        )

        if not rows:
            return []

        # Simple keyword overlap scoring
        msg_words = set(message_content.lower().split())
        # Filter out very common words
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "shall", "can",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "it", "this", "that", "these", "those", "i", "you", "we",
            "they", "he", "she", "and", "or", "but", "not", "no", "so",
            "if", "then", "than", "just", "about", "up", "out",
        }
        msg_words -= stop_words

        if not msg_words:
            return []

        relevant = []
        for row in rows:
            claim_words = set(row["claim"].lower().split()) - stop_words
            if not claim_words:
                continue
            overlap = len(msg_words & claim_words)
            score = overlap / max(len(claim_words), 1)
            if score >= 0.3:  # At least 30% keyword overlap
                c = dict(row)
                c["relevance_score"] = score
                relevant.append(c)

        # Sort by relevance, return top 3
        relevant.sort(key=lambda x: x["relevance_score"], reverse=True)
        return relevant[:3]
