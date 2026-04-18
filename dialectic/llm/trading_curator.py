# llm/trading_curator.py — Trading Curator engine for offline alerts

"""
ARCHITECTURE: LLM mode for when a trading snapshot arrives and a participant is offline.
WHY: Trading data shifts while people are away — the curator flags what changed
     and suggests what to discuss when they return.
TRADEOFF: Extra LLM call per snapshot (Haiku = cheap) vs silent data arrival.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from uuid import UUID, uuid4

from models import (
    Message, EventType, SpeakerType, MessageType,
)

logger = logging.getLogger(__name__)


TRADING_CURATOR_IDENTITY = '''You are a trading curator in a collaborative thesis room.
When new market data arrives and a participant is offline:

1. SIGNAL: Flag nodes that changed state (approaching → fired, new confluences)
2. COUNTDOWN: Highlight approaching deadlines
3. RISK: Note portfolio vulnerabilities if triggers are approaching stops
4. ACTION: Suggest what to discuss when the offline person returns
5. DISAGREE: If the data contradicts something said in recent conversation, flag it

Keep it brief. One paragraph max. This is an alert, not an essay.'''


class TradingCuratorEngine:
    """
    ARCHITECTURE: Generates contextualized trading alerts when a snapshot arrives
    and at least one room participant is offline.
    WHY: Offline traders need a quick summary of what shifted while they were away,
         not a raw data dump.
    TRADEOFF: Inherits the annotator pattern but is triggered by external data
              (snapshot push) rather than a human message.
    """

    def __init__(self, db, memory_manager, llm_provider):
        self.db = db
        self.memory = memory_manager
        self.provider = llm_provider

    async def should_alert(self, room_id: UUID) -> bool:
        """
        Check if any room member is offline.

        ARCHITECTURE: Different from AnnotatorEngine.should_annotate() which checks
        "is the OTHER user offline". Here we check if ANY member is offline, because
        the snapshot comes from an external script, not a human sender.
        """
        offline_count = await self.db.fetchval(
            """SELECT COUNT(*) FROM room_memberships rm
               WHERE rm.room_id = $1
               AND rm.user_id NOT IN (
                   SELECT user_id FROM user_presence
                   WHERE room_id = $1 AND status = 'online'
               )""",
            room_id,
        )
        return offline_count > 0

    async def is_duplicate(
        self,
        room_id: UUID,
        thread_id: UUID,
        window_minutes: int = 5,
    ) -> bool:
        """
        Check whether a trading curator alert was already generated recently.

        ARCHITECTURE: Filters on metadata->>'source' = 'trading_curator' rather
        than fragile content LIKE '%Trading%' matching.
        WHY: Metadata-tagged dedup is deterministic; the LIKE predicate
             over-matched any annotator message that happened to mention
             "Trading" and missed legitimate curator alerts that didn't.
        TRADEOFF: Requires the messages.metadata column (migration 003) and
                  curator inserts to set metadata.source — but both are now
                  guaranteed.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
        count = await self.db.fetchval(
            """SELECT COUNT(*) FROM messages
               WHERE thread_id = $1
               AND speaker_type = $2
               AND created_at > $3
               AND metadata->>'source' = 'trading_curator'""",
            thread_id,
            SpeakerType.LLM_ANNOTATOR.value,
            cutoff,
        )
        return count > 0

    async def generate_alert(
        self,
        room_id: UUID,
        thread_id: UUID,
        snapshot: dict,
    ) -> Optional[Message]:
        """
        Generate a trading curator alert if conditions are met.

        ARCHITECTURE: Uses cheap LLM (Haiku) with curator identity to produce
        a brief alert. Returns None if no alert is needed (everyone online,
        or duplicate within window).
        WHY: Alerts should be fast and inexpensive — one paragraph, not an essay.
        TRADEOFF: Haiku quality vs cost; alerts are supplementary, not core.
        """
        if not await self.should_alert(room_id):
            return None

        if await self.is_duplicate(room_id, thread_id):
            return None

        # Build snapshot summary for prompt context
        snapshot_summary = _format_snapshot_for_prompt(snapshot)

        # Get recent thread messages for conversation context
        from operations import get_thread_messages
        thread_messages = await get_thread_messages(self.db, thread_id, include_ancestry=True)
        recent = thread_messages[-10:]

        messages_text = "\n".join(
            f"[{m.speaker_type.value if hasattr(m.speaker_type, 'value') else m.speaker_type}] "
            f"{m.content[:200]}"
            for m in recent
        )

        # Use existing provider infrastructure with Haiku (cheap, fast)
        from .providers import get_provider, ProviderName, LLMRequest

        provider = get_provider(ProviderName.ANTHROPIC)

        request = LLMRequest(
            messages=[{
                "role": "user",
                "content": (
                    f"A new trading snapshot just arrived.\n\n"
                    f"Snapshot summary:\n{snapshot_summary}\n\n"
                    f"Recent conversation in this thread:\n{messages_text}\n\n"
                    f"Generate a brief trading alert for the offline participant(s)."
                ),
            }],
            system=TRADING_CURATOR_IDENTITY,
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            temperature=0.3,
        )

        try:
            response = await provider.complete(request)

            # Persist as LLM_ANNOTATOR message
            alert_id = uuid4()
            now = datetime.now(timezone.utc)

            metadata = {
                "source": "trading_curator",
                "snapshot_timestamp": snapshot.get("timestamp"),
                "snapshot_v": snapshot.get("v"),
            }
            row = await self.db.fetchrow(
                """INSERT INTO messages
                   (id, thread_id, sequence, created_at, speaker_type, user_id,
                    message_type, content, metadata)
                   VALUES (
                       $1, $2,
                       (SELECT COALESCE(MAX(sequence), 0) + 1
                        FROM messages WHERE thread_id = $2),
                       $3, $4, NULL, $5, $6, $7
                   )
                   RETURNING sequence""",
                alert_id, thread_id, now,
                SpeakerType.LLM_ANNOTATOR.value, MessageType.TEXT.value,
                response.content, metadata,
            )
            alert_sequence = row['sequence']

            # Log trading curator event
            await self.db.execute(
                """INSERT INTO events
                   (id, timestamp, event_type, room_id, thread_id, payload)
                   VALUES ($1, $2, $3, $4, $5, $6)""",
                uuid4(), now, EventType.ANNOTATION_CREATED.value,
                room_id, thread_id,
                {
                    "message_id": str(alert_id),
                    "speaker_type": SpeakerType.LLM_ANNOTATOR.value,
                    "content_preview": response.content[:100],
                    "source": "trading_curator",
                },
            )

            return Message(
                id=alert_id,
                thread_id=thread_id,
                sequence=alert_sequence,
                created_at=now,
                speaker_type=SpeakerType.LLM_ANNOTATOR,
                message_type=MessageType.TEXT,
                content=response.content,
            )

        except Exception as e:
            logger.warning("Trading curator alert failed (non-critical): %s", e)
            return None


def _format_snapshot_for_prompt(snapshot: dict) -> str:
    """
    Format a raw snapshot dict into a compact text block for the LLM prompt.

    ARCHITECTURE: Separate from format_thesis_summary (which targets memory storage)
    because the curator prompt needs a slightly different emphasis — state changes
    and countdowns over phase metadata.
    """
    lines = []

    # Title if present
    title = snapshot.get("title")
    if title:
        lines.append(f"Graph: {title}")

    # Timestamp
    lines.append(f"Timestamp: {snapshot.get('timestamp', 'unknown')}")

    # Node states — focus on fired and approaching
    node_states = snapshot.get("nodeStates", {})
    fired = [k for k, v in node_states.items() if v == "fired"]
    approaching = [k for k, v in node_states.items() if v == "approaching"]
    if fired:
        lines.append(f"Fired nodes: {', '.join(fired)}")
    if approaching:
        lines.append(f"Approaching nodes: {', '.join(approaching)}")
    if not fired and not approaching:
        lines.append("No active signals")

    # Cascade phase
    phase = snapshot.get("cascadePhase")
    if phase:
        lines.append(f"Phase: {phase.get('number', '?')} — {phase.get('key', 'unknown')} ({phase.get('status', 'unknown')})")

    # Countdowns
    countdowns = snapshot.get("countdowns")
    if countdowns:
        for cd in countdowns:
            lines.append(f"Countdown: {cd.get('nodeId', '?')} — {cd.get('daysRemaining', '?')} days ({cd.get('deadline', '')})")

    # Confluence scores
    confluence = snapshot.get("confluenceScores")
    if confluence:
        parts = [f"{k}: {v:.2f}" for k, v in confluence.items()]
        lines.append(f"Confluence: {', '.join(parts)}")

    # Market snapshot
    market = snapshot.get("marketSnapshot")
    if market:
        parts = [f"{k}: {v}" for k, v in market.items()]
        lines.append(f"Market: {', '.join(parts)}")

    # Scenario impacts
    scenarios = snapshot.get("scenarioImpacts")
    if scenarios:
        for name, data in scenarios.items():
            prob = data.get("probability", "?")
            impact = data.get("netImpact", "?")
            lines.append(f"Scenario '{name}': {prob} probability, ${impact} net impact")

    return "\n".join(lines)
