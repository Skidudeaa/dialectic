# llm/tools.py — the tool registry the LLM participant is handed each turn

import json
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Awaitable, Callable, Optional
from uuid import UUID

from . import cairn_client as cn
from . import defuddle_client as dc
from . import tradingdesk_client as td

logger = logging.getLogger(__name__)

# Every tool here is READ-ONLY by design. Write commands (and every ui.*
# command in tradingDesk's registry — ui.focus_panel broadcasts to every
# connected client) are deliberately excluded: a participant that can move
# the humans' screens or mutate the book is a different, much larger trust
# decision than one that can look things up.
# The one exception shape is draft_prediction, and it is an exception in
# KIND, not in effect: the executor validates and shapes a proposal and
# performs NO write. The write happens only when a human taps Accept in the
# room (api/prediction_relay.py relays it to tradingDesk) — Claude proposes,
# a human disposes. The etiquette: never log a prediction from inside this
# registry, and never present the draft as logged until the Accept lands.

THESIS_CHAR_CAP = 6000
TOOL_RESULT_CHAR_CAP = 8000

# read_article truncates the extracted body at this many characters BEFORE
# _shrink runs. WHY not let _shrink handle it: _shrink drops whole keys, and
# the biggest key here is "content" — dropping it would hand the model an
# article with everything except the article. A clean cut at a character
# boundary keeps what survives trustworthy and says where it stopped.
ARTICLE_CONTENT_CAP = 6000

# MEASURED 2026-08-09: /api/market/quotes takes ~18.5s (it re-fetches Yahoo
# per book, uncached), while every other endpoint answers in milliseconds.
# At the 10s default this tool could NEVER succeed — a tool that always times
# out is worse than no tool, because the room waits 10s to learn nothing.
QUOTES_TIMEOUT_S = 20.0

# Keys dropped from any tradingDesk payload before it reaches the model:
# per-tick traces and history arrays are the bulk of the bytes and none of
# the meaning at conversation altitude.
# WHY these three and not, say, "log": the marker is a substring test, so a
# broad one silently eats legitimate keys ("catalog", "logic"). Verified
# against every live payload — only horizonTrace matches.
_HEAVY_KEY_MARKERS = ("trace", "history", "series")

# Thesis fields worth protecting when the payload has to shrink.
_THESIS_CORE_KEYS = frozenset({
    "v", "timestamp", "title", "nodeStates", "cascadePhase",
    "confluenceScores", "countdowns", "marketSnapshot",
    "scenarioImpacts", "portfolioSummary", "feedFreshness",
})


@dataclass
class Tool:
    """
    ARCHITECTURE: One callable the model may invoke, plus everything the
    three surfaces need — the API schema, the human-facing activity phrase,
    and its own timeout.
    WHY: name/description/input_schema go to Anthropic, label goes to the
    UI ("checking live prices"), execute is ours. Keeping them on one object
    means a new tool cannot ship half-wired.
    TRADEOFF: a fatter dataclass vs three parallel registries drifting apart.
    """
    name: str
    description: str
    input_schema: dict
    execute: Callable[[dict], Awaitable[dict]]
    label: str
    timeout_s: float = 10.0


@dataclass
class ToolRegistry:
    """
    ARCHITECTURE: Immutable per-turn collection of Tools, built per room.
    WHY: tool availability is room-scoped (a room with no linked book still
    gets memory/transcript search), so the registry is built per request
    rather than being a module singleton.
    """
    tools: list[Tool] = field(default_factory=list)

    def schemas(self) -> list[dict]:
        """Anthropic tool-schema dicts, in registration order."""
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in self.tools
        ]

    def get(self, name: str) -> Optional[Tool]:
        for t in self.tools:
            if t.name == name:
                return t
        return None

    def labels(self) -> dict[str, str]:
        """name -> human-facing activity phrase, for the streaming UI."""
        return {t.name: t.label for t in self.tools}

    def names(self) -> list[str]:
        return [t.name for t in self.tools]


# ── payload hygiene ──────────────────────────────────────────────────


def _is_heavy_key(key: str) -> bool:
    low = key.lower()
    return any(marker in low for marker in _HEAVY_KEY_MARKERS)


def _size(value: Any) -> int:
    try:
        return len(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return len(str(value))


def _shrink(payload: Any, limit: int, core: frozenset = frozenset()) -> Any:
    """Drop trace/history arrays, then the largest non-core keys, until the
    serialized payload fits under `limit`.

    WHY not a blind string truncation: cutting mid-JSON hands the model a
    fragment it will read as data. Dropping whole keys and NAMING them keeps
    every value that survives trustworthy, and tells the model what it is
    not seeing so it can ask for that slice specifically.
    """
    if not isinstance(payload, dict):
        if _size(payload) <= limit:
            return payload
        return {
            "_truncated": "Response too large to show in full.",
            "preview": json.dumps(payload, default=str)[:limit],
        }

    trimmed = {k: v for k, v in payload.items() if not _is_heavy_key(k)}
    dropped = [k for k in payload if _is_heavy_key(k)]

    while _size(trimmed) > limit and trimmed:
        droppable = [k for k in trimmed if k not in core] or list(trimmed)
        biggest = max(droppable, key=lambda k: _size(trimmed[k]))
        del trimmed[biggest]
        dropped.append(biggest)

    if dropped:
        trimmed["_truncated"] = (
            "Omitted to fit the context window: "
            + ", ".join(sorted(dropped))
            + ". Everything shown is complete and current."
        )
    return trimmed


def serialize_tool_result(value: Any, limit: int = TOOL_RESULT_CHAR_CAP) -> str:
    """JSON for a tool_result block, hard-capped with a visible marker."""
    try:
        text = json.dumps(value, default=str)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) > limit:
        return text[:limit] + f"\n…[truncated at {limit} characters]"
    return text


# ── book id resolution ───────────────────────────────────────────────


def resolve_book_id(room, explicit: Optional[str] = None) -> str:
    """Which tradingDesk book this room is talking about.

    Order: what the model asked for, then the room's binding
    (rooms.linked_book_id), then anything the pushed snapshot carries.
    WHY the model's value wins: a two-book conversation is legitimate, and
    the alternative is silently answering about the wrong thesis.
    """
    if explicit and str(explicit).strip():
        return str(explicit).strip()

    linked = getattr(room, "linked_book_id", None)
    if linked:
        return str(linked)

    config = getattr(room, "trading_config", None) or {}
    if isinstance(config, dict):
        # "thesisId" is the key the v3 snapshot contract actually carries.
        for key in ("book_id", "bookId", "book", "thesisId"):
            value = config.get(key)
            if value:
                return str(value)

    raise ValueError(
        "This room is not bound to a thesis book. Pass book_id explicitly "
        "(for example 'iran-hormuz-graph') or answer from the conversation."
    )


# ── tradingDesk-backed executors ─────────────────────────────────────


async def _snapshot_prices(room, wanted: list) -> dict:
    """Second source for prices when the live feed returns nothing.

    WHY this exists at all: tradingDesk's /api/market/quotes currently cannot
    return a quote (web/adapters/market.py fetch_quotes iterates the book
    CONFIG that fetch_prices returns, not a symbol->price map), so the primary
    path is empty 100% of the time. The desk's own evaluated snapshot does
    carry real levels in marketSnapshot.
    WHY it is a genuinely different path, not a retry: different endpoint,
    different data, answers in milliseconds — and it self-disables the moment
    the live feed returns anything.
    TRADEOFF: snapshot levels are as-of a timestamp, not the current tick. They
    are labelled that way in the payload and in the note, because a stale price
    presented as live is worse than no price at all.
    """
    fallback: dict = {
        "note": (
            "The live price feed returned nothing — it is empty or down. Do not "
            "substitute a remembered price."
        )
    }
    try:
        book_id = resolve_book_id(room)
        state = await td.run_command("thesis.open", {"book_id": book_id})
    except (ValueError, td.TradingDeskError) as e:
        logger.info("Snapshot price fallback unavailable: %s", e)
        return fallback

    snapshot = (state or {}).get("marketSnapshot") if isinstance(state, dict) else None
    if not isinstance(snapshot, dict) or not snapshot:
        return fallback

    if wanted:
        upper = {str(s).upper() for s in wanted}
        narrowed = {k: v for k, v in snapshot.items() if str(k).upper() in upper}
        if narrowed:
            snapshot = narrowed
        else:
            # marketSnapshot is keyed by market FIELD (brent, wti, dxy, us10y),
            # not by ticker, so a ticker filter routinely matches nothing. That
            # means "show everything and say so" — never "there is no data",
            # which would be a note promising levels it does not carry.
            fallback["filter_note"] = (
                "The snapshot is keyed by market field, not ticker, so "
                f"{sorted(upper)} matched nothing. Showing every field."
            )

    # NOTE: snapshot is known non-empty here — the guard above returned, and
    # the filter branch keeps the full set rather than narrowing to nothing.
    fallback["snapshot_prices"] = snapshot
    fallback["source"] = "thesis snapshot, NOT the live tick"
    fallback["as_of"] = (state or {}).get("timestamp")
    fallback["note"] = (
        "The live price feed returned nothing, so these levels come from the "
        "desk's last evaluated snapshot (see as_of). Cite them as of that time "
        "— never as the current price — or say you could not get a live quote."
    )
    return fallback


def _build_trading_tools(room) -> list[Tool]:
    async def get_live_quotes(args: dict) -> dict:
        quotes = await td.get("/api/market/quotes", timeout=QUOTES_TIMEOUT_S)
        if not isinstance(quotes, list):
            return {"quotes": [], "note": "tradingDesk returned an unexpected shape."}

        wanted = args.get("symbols") or []
        if isinstance(wanted, str):
            wanted = [wanted]
        if wanted:
            upper = {str(s).upper() for s in wanted}
            filtered = [q for q in quotes
                        if str(q.get("symbol", "")).upper() in upper]
            missing = sorted(upper - {str(q.get("symbol", "")).upper() for q in quotes})
        else:
            filtered, missing = quotes, []

        out: dict = {"count": len(filtered), "quotes": filtered, "source": "live feed"}
        # Only meaningful when the feed answered at all — with an empty feed
        # EVERY symbol would land here and read as "we don't track it".
        if missing and quotes:
            out["not_watched"] = missing
        if not quotes:
            out.update(await _snapshot_prices(room, wanted))
        return _shrink(out, THESIS_CHAR_CAP)

    async def get_polymarket_odds(args: dict) -> dict:
        odds = await td.get("/api/market/polymarket")
        if not isinstance(odds, list):
            return {"markets": [], "note": "tradingDesk returned an unexpected shape."}
        out: dict = {"count": len(odds), "markets": odds}
        if not odds:
            out["note"] = "No Polymarket slugs are configured or the feed is down."
        return _shrink(out, THESIS_CHAR_CAP)

    async def get_thesis_state(args: dict) -> dict:
        book_id = resolve_book_id(room, args.get("book_id"))
        state = await td.run_command("thesis.open", {"book_id": book_id})
        shrunk = _shrink(state, THESIS_CHAR_CAP, core=_THESIS_CORE_KEYS)
        if isinstance(shrunk, dict):
            shrunk["book_id"] = book_id
        return shrunk

    async def diff_thesis_last_hour(args: dict) -> dict:
        book_id = resolve_book_id(room, args.get("book_id"))
        delta = await td.run_command("thesis.diff.last_hour", {"book_id": book_id})
        shrunk = _shrink(delta, THESIS_CHAR_CAP)
        if isinstance(shrunk, dict):
            shrunk["book_id"] = book_id
            if shrunk.get("hasChanges") is False:
                shrunk["summary"] = "Nothing moved between the last two snapshots."
        return shrunk

    async def evaluate_scenario(args: dict) -> dict:
        book_id = resolve_book_id(room, args.get("book_id") or args.get("thesis_id"))
        scenario_id = str(args.get("scenario_id") or "").strip()
        if not scenario_id:
            raise ValueError("scenario_id is required — read it off the thesis state.")

        params = {}
        against = args.get("against_revision")
        if against is not None:
            params["against_revision"] = against

        result = await td.post(
            f"/api/v1/theses/{book_id}/scenarios/{scenario_id}/evaluate",
            params=params or None,
        )
        shrunk = _shrink(result, THESIS_CHAR_CAP)
        if isinstance(shrunk, dict):
            # WHY provenance: a what-if is only meaningful against a named
            # snapshot. Echoing the revision back means a claim made from
            # this result can be re-checked later against the same base.
            shrunk["provenance"] = {
                "book_id": book_id,
                "scenario_id": scenario_id,
                "base_revision": (result or {}).get("baseRevision")
                if isinstance(result, dict) else None,
                "against_revision": against,
                "hypothetical": True,
            }
        return shrunk

    async def get_open_trades(args: dict) -> dict:
        result = await td.run_command("outcomes.open_trades", {})
        return _shrink(result, THESIS_CHAR_CAP)

    async def get_morning_brief(args: dict) -> dict:
        book_id = resolve_book_id(room, args.get("book_id"))
        result = await td.run_command("outcomes.morning_brief", {"book_id": book_id})
        return _shrink(result, THESIS_CHAR_CAP)

    async def get_thesis_news(args: dict) -> dict:
        book_id = resolve_book_id(room, args.get("book_id"))
        news = await td.service_get(f"/api/bridge/news/{book_id}")
        if not isinstance(news, dict):
            return {"articles": [], "book_id": book_id,
                    "note": "tradingDesk returned an unexpected shape."}
        # A note-only answer (GDELT unconfigured or down, articles []) is NOT
        # an error — pass it through so the model can say "feed's quiet"
        # instead of inventing headlines.
        shrunk = _shrink(news, THESIS_CHAR_CAP)
        if isinstance(shrunk, dict):
            shrunk["book_id"] = book_id
            articles = shrunk.get("articles")
            shrunk["count"] = len(articles) if isinstance(articles, list) else 0
        return shrunk

    return [
        Tool(
            name="get_live_quotes",
            description=(
                "Current prices for every instrument on the trading desk watchlist "
                "(Brent, XOP, XLE, and whatever else the books reference). Use this "
                "for ANY question about a current price or level — never cite a price "
                "from memory or from the thesis snapshot when you can check. Pass "
                "symbols to narrow it; omit them to see the whole watchlist. Read "
                "the 'source' field before you quote a number: if it says the live "
                "feed was empty, the levels are as of the snapshot's as_of time and "
                "must be reported that way."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "symbols": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tickers to filter to, e.g. ['XOP','BZ=F']. Omit for all.",
                    }
                },
            },
            execute=get_live_quotes,
            label="checking live prices",
            timeout_s=QUOTES_TIMEOUT_S,
        ),
        Tool(
            name="get_polymarket_odds",
            description=(
                "Current Polymarket probabilities for the prediction markets the "
                "books track. Use it when the conversation turns on how likely an "
                "event is — the market's number is evidence you do not have to "
                "guess at, and it is the honest counterweight when one of us is "
                "talking a scenario up."
            ),
            input_schema={"type": "object", "properties": {}},
            execute=get_polymarket_odds,
            label="checking Polymarket odds",
        ),
        Tool(
            name="get_thesis_state",
            description=(
                "The live evaluated thesis snapshot: node states (fired / approaching "
                "/ monitoring / stable), confluence scores, cascade phase, countdowns, "
                "scenario probabilities and portfolio impact. Use it whenever the "
                "question is about where the thesis actually stands right now, or "
                "before agreeing with a claim about a node's state. The snapshot in "
                "your prompt can be hours old; this is current."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "book_id": {
                        "type": "string",
                        "description": "Book slug, e.g. 'iran-hormuz-graph'. Defaults to this room's book.",
                    }
                },
            },
            execute=get_thesis_state,
            label="pulling the live thesis",
        ),
        Tool(
            name="diff_thesis_last_hour",
            description=(
                "What changed between the two most recent thesis snapshots — node "
                "state flips, confluence moves, countdown and portfolio changes. Use "
                "it for 'what moved', 'anything new', or when someone returns after "
                "being away and needs the delta rather than the whole picture."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "book_id": {
                        "type": "string",
                        "description": "Book slug. Defaults to this room's book.",
                    }
                },
            },
            execute=diff_thesis_last_hour,
            label="checking what moved in the last hour",
        ),
        Tool(
            name="evaluate_scenario",
            description=(
                "Read-only what-if: evaluate a named scenario against a committed "
                "thesis revision and get back which nodes would change state and the "
                "per-instrument portfolio impact. Nothing is written and live state is "
                "untouched. Use it when someone asks 'what happens if X' about a "
                "scenario that already exists in the book — get scenario_id from the "
                "thesis state's scenarioImpacts. Always report the result as "
                "hypothetical, with the base revision it was computed against."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "scenario_id": {
                        "type": "string",
                        "description": "Scenario slug from the thesis, e.g. 'closed-may'.",
                    },
                    "book_id": {
                        "type": "string",
                        "description": "Book slug. Defaults to this room's book.",
                    },
                    "against_revision": {
                        "type": "integer",
                        "description": "Committed revision to evaluate against. Omit for the latest.",
                    },
                },
                "required": ["scenario_id"],
            },
            execute=evaluate_scenario,
            label="running the what-if",
        ),
        Tool(
            name="get_open_trades",
            description=(
                "Every open trade across the books, with the predicates each one is "
                "resting on. Use it before reasoning about exposure, before saying "
                "what we are in or out of, and when a node fires that a live trade "
                "depends on."
            ),
            input_schema={"type": "object", "properties": {}},
            execute=get_open_trades,
            label="checking open trades",
        ),
        Tool(
            name="get_morning_brief",
            description=(
                "The desk's generated morning brief for a book — hot nodes, what is "
                "approaching, deadlines, scenario probabilities. Use it when someone "
                "asks for the state of play as a whole rather than one number."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "book_id": {
                        "type": "string",
                        "description": "Book slug. Defaults to this room's book.",
                    }
                },
            },
            execute=get_morning_brief,
            label="pulling the brief",
        ),
        Tool(
            name="get_thesis_news",
            description=(
                "Recent news headlines for a thesis book, pulled from the desk's "
                "GDELT feed and capped at 15 with title, url, date and source "
                "domain. Use it when the conversation turns on what is actually "
                "happening out there around a thesis — fresh events, not the "
                "thesis structure itself. An empty articles list with a note "
                "means the feed is unconfigured or down, NOT that nothing "
                "happened; report the note rather than inventing headlines."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "book_id": {
                        "type": "string",
                        "description": "Book slug. Defaults to this room's book.",
                    }
                },
            },
            execute=get_thesis_news,
            label="checking latest headlines",
        ),
    ]


# ── dialectic-internal executors ─────────────────────────────────────


async def _speaker_attribution(db, memory_ids: list[UUID]) -> dict:
    """memory id -> {speaker, when}. Best-effort: recall still works unattributed."""
    if not memory_ids:
        return {}
    try:
        rows = await db.fetch(
            """SELECT m.id, m.created_at, u.display_name
               FROM memories m
               LEFT JOIN users u ON u.id = m.speaker_user_id
               WHERE m.id = ANY($1::uuid[])""",
            list(memory_ids),
        )
    except Exception as e:
        logger.warning("Memory attribution lookup failed: %s", e)
        return {}
    return {
        row["id"]: {
            "speaker": row["display_name"],
            "when": row["created_at"].strftime("%Y-%m-%d")
            if row["created_at"] else None,
        }
        for row in rows
    }


def _build_dialectic_tools(room, db) -> list[Tool]:
    async def search_memories(args: dict) -> dict:
        from memory.manager import MemoryManager

        query = str(args.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        limit = max(1, min(int(args.get("limit") or 5), 10))

        manager = MemoryManager(db)
        matches = await manager.search_memories(
            room_id=room.id, query=query, limit=limit
        )
        attribution = await _speaker_attribution(db, [m.memory_id for m in matches])

        results = []
        for m in matches:
            meta = attribution.get(m.memory_id, {})
            results.append({
                "key": m.key,
                "content": m.content,
                # WHY speaker + date: "we agreed X" is a different claim from
                # "Dan said X in June". Attribution is what stops recall being
                # laundered into consensus.
                "said_by": meta.get("speaker") or "unattributed",
                "recorded": meta.get("when"),
                "lanes": m.lanes,
            })
        out = {"query": query, "count": len(results), "memories": results}
        if not results:
            out["note"] = "Nothing in shared memory matches. Say so rather than inventing one."
        return _shrink(out, TOOL_RESULT_CHAR_CAP)

    async def search_transcript(args: dict) -> dict:
        query = str(args.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        limit = max(1, min(int(args.get("limit") or 10), 10))
        speaker = str(args.get("speaker") or "").strip() or None

        rows = await db.fetch(
            """SELECT m.content, m.speaker_type, m.created_at, u.display_name
               FROM messages m
               JOIN threads t ON t.id = m.thread_id
               LEFT JOIN users u ON u.id = m.user_id
               WHERE t.room_id = $1
                 AND m.is_deleted = FALSE
                 AND m.content ILIKE $2
                 AND ($3::text IS NULL
                      OR u.display_name ILIKE $3
                      OR m.speaker_type ILIKE $3)
               ORDER BY m.created_at DESC
               LIMIT $4""",
            room.id,
            f"%{query}%",
            f"%{speaker}%" if speaker else None,
            limit,
        )

        # Newest-first for the LIMIT, chronological for the model — an
        # exchange read backwards inverts who conceded what.
        results = [
            {
                "said_by": row["display_name"] or row["speaker_type"],
                "speaker_type": row["speaker_type"],
                "when": row["created_at"].isoformat() if row["created_at"] else None,
                "content": row["content"],
            }
            for row in reversed(list(rows))
        ]
        out = {"query": query, "count": len(results), "messages": results}
        if not results:
            out["note"] = (
                "No message in this room contains that text. It may have been "
                "said in different words, or not at all — do not assert it was."
            )
        return _shrink(out, TOOL_RESULT_CHAR_CAP)

    async def draft_prediction(args: dict) -> dict:
        """Validate and shape a prediction proposal. NO write — ever.

        The returned proposal lands in the tool trace via its provenance,
        the orchestrator hoists it to messages.metadata.proposal, and the
        room renders an Accept button against it. The write to tradingDesk's
        prediction tracker is the human's tap (api/prediction_relay.py), so
        this executor touches nothing but its own arguments.
        """
        statement = str(args.get("statement") or "").strip()
        if not statement:
            raise ValueError("statement is required — the claim being put on record.")

        try:
            confidence = float(args.get("confidence"))
        except (TypeError, ValueError):
            raise ValueError("confidence must be a number between 0 and 1 (0.7 = 70%).")
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1 (0.7 = 70%).")

        deadline = str(args.get("deadline") or "").strip()
        try:
            date.fromisoformat(deadline)
        except ValueError:
            raise ValueError("deadline must be an ISO date, e.g. 2026-09-30.")

        proposal: dict = {
            "statement": statement,
            "confidence": confidence,
            "deadline": deadline,
        }
        book = str(args.get("linked_book_id") or "").strip()
        if book:
            proposal["linked_book_id"] = book

        return {
            # The model sees exactly what the human will be asked to accept.
            "proposal": proposal,
            # WHY provenance: the tool loop lifts this onto the trace entry
            # (tool_loop._execute), which is how the orchestrator knows to
            # hoist the draft to metadata.proposal for the Accept button.
            "provenance": {"kind": "prediction_draft"},
        }

    async def propose_thesis(args: dict) -> dict:
        """Shape a thesis proposal from the conversation. NO write — ever.

        Same trust shape as draft_prediction: the proposal is hoisted to
        metadata.thesis_proposal, the room renders it as a card, and the
        card's tap opens the Create Thesis panel pre-filled — where the
        cascade is drafted, reviewed and, only then, created by the human.
        """
        if getattr(room, "is_home", False):
            # Home connects the schemes; durable theses live in their rooms.
            raise ValueError("Propose it in the scheme's room.")
        if getattr(room, "linked_book_id", None):
            raise ValueError(
                f"this room already argues '{room.linked_book_id}' — one "
                "thesis per room. The humans must retire the current one "
                "(trading panel) before a new one can be proposed."
            )
        title = str(args.get("title") or "").strip()
        if not title:
            raise ValueError("title is required — the thesis needs a name.")
        if len(title) > 120:
            raise ValueError("title must be 120 characters or fewer.")
        claim = str(args.get("claim") or "").strip()
        if not claim:
            raise ValueError(
                "claim is required — one causal statement distilling what "
                "the conversation is actually staking."
            )
        if len(claim) > 2000:
            raise ValueError("claim must be 2000 characters or fewer.")
        budget = args.get("monthly_budget", 5000)
        try:
            budget = int(budget)
        except (TypeError, ValueError):
            raise ValueError("monthly_budget must be a whole dollar amount.")
        if not 0 <= budget <= 10_000_000:
            raise ValueError("monthly_budget must be between 0 and 10,000,000.")

        return {
            "proposal": {"title": title, "claim": claim,
                         "monthly_budget": budget},
            "provenance": {"kind": "thesis_proposal"},
        }

    async def read_article(args: dict) -> dict:
        """Fetch a URL via the defuddle sidecar and shape the article.

        Failure shape matches the other tools: extract_article raises
        DefuddleError and the tool loop turns it into an is_error
        tool_result that names the reason — the turn never dies on a dead
        sidecar or a site that refused the fetch.
        """
        url = str(args.get("url") or "").strip()
        if not url:
            raise ValueError("url is required — the page to read.")
        if not url.startswith(("http://", "https://")):
            raise ValueError("url must be an http(s) address.")

        article = await dc.extract_article(url)
        if not isinstance(article, dict):
            return {"url": url, "note": "The extractor returned an unexpected shape."}

        content = str(article.get("content") or "")
        truncated = len(content) > ARTICLE_CONTENT_CAP
        out = {
            "url": article.get("url") or url,
            "title": article.get("title"),
            "author": article.get("author"),
            "site": article.get("site"),
            "published": article.get("published"),
            "word_count": article.get("word_count"),
            "content": content[:ARTICLE_CONTENT_CAP] if truncated else content,
        }
        if truncated:
            out["content_note"] = (
                f"Article body cut at {ARTICLE_CONTENT_CAP} characters to fit "
                "the context window — what is shown is the opening, complete "
                f"to that point, of a {article.get('word_count') or '?'}-word "
                "piece. Do not quote from beyond the cut."
            )
        if not out["content"]:
            out["note"] = (
                "The extractor found no article body at that URL (it may be "
                "paywalled, a JS-only app, or not an article). Say so rather "
                "than inventing its contents."
            )
        return _shrink(out, TOOL_RESULT_CHAR_CAP)

    async def save_reading(args: dict) -> dict:
        """Validate and shape a library proposal. NO write — ever.

        Same trust shape as draft_prediction: the proposal is hoisted to
        metadata.reading_proposal, the room renders an Accept button, and
        only the human's tap (api/reading_relay.py) files the article.
        """
        url = str(args.get("url") or "").strip()
        if not url:
            raise ValueError("url is required — the article to file.")
        if not url.startswith(("http://", "https://")):
            raise ValueError("url must be an http(s) address.")
        summary = str(args.get("summary") or "").strip()
        if not summary:
            raise ValueError(
                "summary is required — what the room should remember of this "
                "piece, in your own words."
            )
        if len(summary) > 1000:
            raise ValueError("summary must be 1000 characters or fewer.")
        claims = args.get("key_claims") or []
        if isinstance(claims, str):
            claims = [claims]
        claims = [str(c).strip() for c in claims if str(c).strip()][:10]

        # WHY re-fetch: the library files the page, not the model's memory of
        # it. If the URL yields no body, there is nothing to file — and a
        # hallucinated article must fail here, not land in recall.
        article = await dc.extract_article(url)
        if not isinstance(article, dict) or not str(article.get("content") or "").strip():
            raise ValueError(
                "that URL did not yield a readable article — read it first "
                "with read_article, and only file what actually came back."
            )

        return {
            "proposal": {
                "url": url,
                "title": article.get("title"),
                "site": article.get("site"),
                "published": article.get("published"),
                "summary": summary,
                "key_claims": claims,
            },
            "provenance": {"kind": "reading_draft"},
        }

    async def search_reading(args: dict) -> dict:
        from llm import reading as reading_mod

        query = str(args.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        limit = max(1, min(int(args.get("limit") or 5), 10))

        results = await reading_mod.search_reading(db, room.id, query, limit)
        out = {"query": query, "count": len(results), "readings": results}
        if not results:
            out["note"] = (
                "Nothing in the reading library matches. Say so rather than "
                "inventing an article we never filed."
            )
        return _shrink(out, TOOL_RESULT_CHAR_CAP)

    return [
        Tool(
            name="search_memories",
            description=(
                "Search this room's shared memory — the facts, positions and "
                "commitments we have saved, each attributed to whoever said it. Use "
                "it when someone refers to something we established earlier, when you "
                "are about to attribute a position to Amo or Dan, or when a claim "
                "sounds like something one of them already ruled on. Results carry "
                "the speaker and the date; keep both when you cite them."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to look for. Include a name to bias toward that speaker.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results, 1-10. Default 5.",
                    },
                },
                "required": ["query"],
            },
            execute=search_memories,
            label="searching our shared memory",
        ),
        Tool(
            name="search_transcript",
            description=(
                "Full-text search over what was actually said in this room, in order. "
                "Use it when the exact words matter — who proposed a level, whether a "
                "caveat was stated, what someone actually committed to. Prefer this "
                "over reconstructing a past exchange from memory; if it is not in the "
                "transcript, do not claim it was said."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Substring to match, case-insensitive.",
                    },
                    "speaker": {
                        "type": "string",
                        "description": (
                            "Optional: a display name ('Dan') or speaker type "
                            "('llm_primary' for your own past turns)."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results, 1-10. Default 10.",
                    },
                },
                "required": ["query"],
            },
            execute=search_transcript,
            label="re-reading the transcript",
        ),
        Tool(
            name="draft_prediction",
            description=(
                "Draft a falsifiable prediction for the room — a statement, "
                "your confidence, and a deadline. Calling this logs NOTHING: "
                "the draft is shown to the humans with an Accept button, and "
                "only their tap writes it to the tradingDesk prediction "
                "tracker. Use it when the conversation produces a real "
                "forecast ('Brent closes above $90 by end of Q3'), not for "
                "hypotheticals or scenario talk. Never claim the prediction "
                "is logged until a human accepts it — say you drafted it."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "statement": {
                        "type": "string",
                        "description": "The falsifiable claim, e.g. 'Brent closes above $90 by end of Q3'.",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "Probability between 0 and 1, e.g. 0.7.",
                    },
                    "deadline": {
                        "type": "string",
                        "description": "ISO date the prediction resolves by, e.g. 2026-09-30.",
                    },
                    "linked_book_id": {
                        "type": "string",
                        "description": "Optional book slug this prediction rides on, e.g. 'iran-hormuz-graph'.",
                    },
                },
                "required": ["statement", "confidence", "deadline"],
            },
            execute=draft_prediction,
            label="drafting a prediction",
        ),
        Tool(
            name="propose_thesis",
            description=(
                "Propose that this conversation becomes a tracked thesis — "
                "a titled causal claim the desk will model as a DAG and "
                "trade against. Calling this creates NOTHING: the proposal "
                "is shown to the humans as a card that opens the Create "
                "Thesis panel pre-filled, where Claude drafts the cascade "
                "for their review and only their tap creates it. Use it "
                "when the argument has crystallized into a distinct, "
                "falsifiable macro thesis this room is not already "
                "tracking — 'we should book this' moments — never for "
                "passing scenarios or a thesis the room already argues. "
                "Distill the claim from what was actually said."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short thesis name, e.g. 'Sovereign Debt Doom Loop'.",
                    },
                    "claim": {
                        "type": "string",
                        "description": (
                            "One causal statement distilling the conversation's "
                            "thesis — the shock, the transmission, the payoff."
                        ),
                    },
                    "monthly_budget": {
                        "type": "integer",
                        "description": "Optional monthly budget in dollars. Default 5000.",
                    },
                },
                "required": ["title", "claim"],
            },
            execute=propose_thesis,
            label="proposing a thesis",
        ),
        Tool(
            name="read_article",
            description=(
                "Fetch a web page and return its main article content as "
                "Markdown with metadata (title, author, site, published date, "
                "word count); clutter like comments, sidebars and navigation "
                "is stripped. Use it after get_thesis_news to read the full "
                "text behind a headline — a headline alone is not evidence — "
                "or whenever someone shares a link worth reading. Long "
                "articles are cut at the content_note boundary; never quote "
                "past it. If the fetch fails or returns no content, say so — "
                "never invent an article's contents."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The http(s) URL of the page to read.",
                    },
                },
                "required": ["url"],
            },
            execute=read_article,
            label="reading the article",
            # The sidecar fetches upstream (15s budget) and then parses; the
            # client's own 20s timeout must fire before the loop's.
            timeout_s=25.0,
        ),
        Tool(
            name="save_reading",
            description=(
                "Propose filing an article into the room's reading library — "
                "the durable record of what we have actually read, searchable "
                "later with search_reading. Calling this files NOTHING: the "
                "draft is shown to the humans with an Accept button, and only "
                "their tap writes it. Use it when a read_article result is "
                "worth keeping — a piece the argument keeps coming back to, "
                "or evidence behind a thesis node — not for every link. The "
                "page is re-fetched at filing time, so summarize what it "
                "actually said. Never claim something is filed until a human "
                "accepts it."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The http(s) URL of the article to file.",
                    },
                    "summary": {
                        "type": "string",
                        "description": (
                            "What the room should remember of the piece, in "
                            "your own words. Max 1000 characters."
                        ),
                    },
                    "key_claims": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional: up to 10 load-bearing claims, one per string.",
                    },
                },
                "required": ["url", "summary"],
            },
            execute=save_reading,
            label="drafting a library entry",
            # Re-fetches the page through the sidecar, like read_article.
            timeout_s=25.0,
        ),
        Tool(
            name="search_reading",
            description=(
                "Search the room's reading library — articles we actually "
                "fetched and filed, with summaries and ranked extracts from "
                "the full text. Use it when the conversation turns on "
                "something we read before ('didn't that FT piece say the "
                "opposite?'), or before citing an article from memory. If it "
                "is not in the library, we did not keep it — say so."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to look for — topic, claim, author, outlet.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results, 1-10. Default 5.",
                    },
                },
                "required": ["query"],
            },
            execute=search_reading,
            label="searching what we've read",
        ),
    ]


# ── cairn dev-memory tools ───────────────────────────────────────────

_CAIRN_OFF_VALUES = frozenset({"0", "false", "no", "off"})


def _cairn_tools_enabled() -> bool:
    """Group-level kill switch, default ON per house style — the deploy
    itself is the enablement act. DIALECTIC_TOOLS_ENABLED remains the
    global emergency-off above this."""
    import os
    return os.getenv("CAIRN_TOOLS_ENABLED", "").strip().lower() not in _CAIRN_OFF_VALUES


_EMPTY_DEV_MEMORY_NOTE = (
    "Nothing in dev memory matches. Say so rather than inventing."
)


def _build_cairn_tools() -> list[Tool]:
    """Read-only tools over cairn, the passive dev-session memory on this
    host. Failures surface at call time as CairnError → the loop's is_error
    result; a down cairn never kills a turn."""

    async def search_dev_sessions(args: dict) -> dict:
        query = str(args.get("query") or "").strip()
        if not query:
            raise ValueError("query is required — what dev work are you looking for?")
        limit = min(int(args.get("limit") or 5), 10)
        data = await cn.post("/api/search/sessions",
                             json={"query": query, "limit": limit})
        out = {
            "query": query,
            "count": data.get("count", 0),
            "sessions": data.get("results", []),
        }
        if not out["sessions"]:
            out["note"] = _EMPTY_DEV_MEMORY_NOTE
        return _shrink(out, TOOL_RESULT_CHAR_CAP)

    async def recent_dev_activity(args: dict) -> dict:
        limit = min(int(args.get("limit") or 10), 20)
        params = {"limit": limit}
        project = str(args.get("project") or "").strip()
        if project:
            params["project"] = project
        sessions = await cn.get("/api/sessions", params=params)
        if not isinstance(sessions, list):
            return {"sessions": [], "note": "cairn returned an unexpected shape."}
        out = {"count": len(sessions), "sessions": sessions}
        if project:
            out["project"] = project
        if not sessions:
            out["note"] = _EMPTY_DEV_MEMORY_NOTE
        return _shrink(out, TOOL_RESULT_CHAR_CAP)

    async def get_dev_session(args: dict) -> dict:
        session_id = str(args.get("session_id") or "").strip()
        if not session_id:
            raise ValueError(
                "session_id is required — get one from search_dev_sessions "
                "or recent_dev_activity."
            )
        session = await cn.get(f"/api/sessions/{session_id}")
        events = await cn.get(f"/api/sessions/{session_id}/events",
                              params={"limit": 50})
        out = {
            "session": session,
            "events": events if isinstance(events, list) else [],
            "event_count_shown": len(events) if isinstance(events, list) else 0,
        }
        return _shrink(out, TOOL_RESULT_CHAR_CAP)

    async def search_dev_insights(args: dict) -> dict:
        query = str(args.get("query") or "").strip()
        if not query:
            raise ValueError("query is required — what problem/solution/decision?")
        limit = min(int(args.get("limit") or 5), 10)
        data = await cn.post("/api/search/insights",
                             json={"query": query, "limit": limit})
        out = {
            "query": query,
            "count": data.get("count", 0),
            "insights": data.get("results", []),
        }
        if not out["insights"]:
            out["note"] = _EMPTY_DEV_MEMORY_NOTE
        return _shrink(out, TOOL_RESULT_CHAR_CAP)

    return [
        Tool(
            name="search_dev_sessions",
            description=(
                "Full-text search over Amo's passively captured dev-work sessions "
                "(file edits, commits, terminal activity across his projects on "
                "this host). Use it when the conversation touches what Amo was "
                "building, fixing or working on — 'what was I doing with X', 'when "
                "did we touch Y' — instead of guessing from memory. Results are "
                "ranked by relevance and recency."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to look for, e.g. 'search indexes mongo'.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results, 1-10. Default 5.",
                    },
                },
                "required": ["query"],
            },
            execute=search_dev_sessions,
            label="searching dev memory",
        ),
        Tool(
            name="recent_dev_activity",
            description=(
                "Amo's most recent dev sessions, newest first — which projects "
                "were touched, when, and how much happened in each. Use it for "
                "'what has Amo worked on today/this week', or to orient before "
                "drilling into one session. Pass project to narrow to a single repo."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max sessions, 1-20. Default 10.",
                    },
                    "project": {
                        "type": "string",
                        "description": "Project name to filter to, e.g. 'cairn'.",
                    },
                },
            },
            execute=recent_dev_activity,
            label="checking recent dev activity",
        ),
        Tool(
            name="get_dev_session",
            description=(
                "One dev session in full: its metadata plus the captured event "
                "stream (file edits, commits, terminal commands, logged notes). "
                "Use it to drill into a session surfaced by search_dev_sessions or "
                "recent_dev_activity when the question needs the actual sequence "
                "of what happened, not just that a session exists."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session id, e.g. 'session_680c8515251d'.",
                    },
                },
                "required": ["session_id"],
            },
            execute=get_dev_session,
            label="reading a dev session",
        ),
        Tool(
            name="search_dev_insights",
            description=(
                "Search the distilled insights extracted from dev sessions — "
                "problems hit, solutions found, decisions made. Use it when the "
                "question is 'how did we solve X before' or 'why did we choose Y', "
                "where the answer is a conclusion rather than a raw activity log."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "What to look for, e.g. 'mongo text index conflict'.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results, 1-10. Default 5.",
                    },
                },
                "required": ["query"],
            },
            execute=search_dev_insights,
            label="searching dev insights",
        ),
    ]


def build_registry(room, db) -> ToolRegistry:
    """
    ARCHITECTURE: Build the per-room tool set — the tradingDesk reads, memory
    and transcript search, the (write-free) prediction draft, and the cairn
    dev-memory reads.
    WHY per room: the executors close over this room's id and book binding,
    so a tool can never read another room's transcript or the wrong book.
    (The cairn tools are host-global read-onlys, so they close over nothing.)
    TRADEOFF: rebuilt per turn (cheap — closures, no I/O) rather than cached,
    because a room's linked book can change between messages.
    """
    tools = _build_trading_tools(room) + _build_dialectic_tools(room, db)
    if _cairn_tools_enabled():
        tools += _build_cairn_tools()
    return ToolRegistry(tools=tools)
