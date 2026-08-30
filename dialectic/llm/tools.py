# llm/tools.py — the tool registry the LLM participant is handed each turn

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Awaitable, Callable, Optional, cast
from uuid import UUID

from . import cairn_client as cn
from . import defuddle_client as dc
from . import documents as documents_mod
from . import tradingdesk_client as td
from .world import WORLD_QUERY_INNER_TIMEOUT_S

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

# The seam's timeout law: an outer asyncio guard EQUAL to the inner HTTP
# timeout is a race, not a budget. Measured live 2026-08-20 at 18.78s against
# a 20s ceiling — 94% of budget, so the two were within a jitter of each other
# and whichever fired first decided whether the room got a descriptive
# TradingDeskError or a bare timeout. Same +4.0 margin the Polymarket tool
# already uses below.
QUOTES_TOOL_TIMEOUT_S = QUOTES_TIMEOUT_S + 4.0

# The tool loop's asyncio timeout must outlive the HTTP client's complete
# Polymarket budget and stay under half the 60s whole-turn budget.
POLYMARKET_TOOL_TIMEOUT_S = td.POLYMARKET_TIMEOUT_S + 4.0
NEWS_TOOL_TIMEOUT_S = 29.0

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
_POLYMARKET_CORE_KEYS = frozenset({
    "status", "freshness", "configured_markets", "missing_markets",
})
_NEWS_CORE_KEYS = frozenset({"status", "source", "query", "freshness"})
_FRESHNESS_STATES = {"live", "cached", "stale", "not_applicable"}
_POLYMARKET_STATUSES = {
    "ok", "partial", "no_data", "not_configured", "unavailable",
}
_NEWS_STATUSES = {
    "ok", "no_matches", "not_configured", "rate_limited", "unavailable",
}
# The news payload's provenance vocabulary — gdelt today, rss reserved so
# the watchlist wire can flow through the same tool contract later. A small
# allowed set, not a dropped check: an unnamed source still fails loudly.
_NEWS_ALLOWED_SOURCES = frozenset({"gdelt", "rss"})


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
    # 14.0, not 10.0: both tradingdesk_client and cairn_client default their
    # HTTP timeout to 10.0, so a 10.0 guard here raced the inner client on
    # every tool that set neither (nine of them). The guard must outlive what
    # it guards. Still far under the 60s whole-turn budget.
    timeout_s: float = 14.0


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


# Owner decision 2026-08-29: forced turns (wire interjections, silence
# follow-ups) get a NARROW tool set rather than the full room registry or
# none at all. See FORCED_TOOL_MAX_ITERATIONS/_BUDGET_S in llm/orchestrator.py
# for the scheduler-tick reasoning that bounds how far this can run.
FORCED_TURN_TOOLS = ("draft_prediction", "read_article", "search_memories")


def narrow_registry(registry: ToolRegistry, names) -> ToolRegistry:
    """The subset of `registry` whose names are in `names`, in place order.

    WHY a filter rather than a new class: a forced turn is the same
    room-scoped registry a primary turn would get (same closures over this
    room's id and book binding) — it should only ever be handed FEWER tools,
    never a differently-built set.
    """
    return ToolRegistry([t for t in registry.tools if t.name in names])


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


def _is_utc_timestamp(value: Any) -> bool:
    """Return whether a value is an ISO-8601 timestamp at UTC offset zero."""
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


def _shape_error(source: str, detail: str) -> td.TradingDeskError:
    return td.TradingDeskError(
        f"tradingDesk {source} bridge returned an unexpected shape: {detail}",
    )


def _validate_freshness(value: Any, source: str) -> dict[str, Any]:
    """Validate the shared provider-observation clock before it reaches the model."""
    if not isinstance(value, dict):
        raise _shape_error(source, "freshness must be an object")
    required = {
        "state", "attempted_at", "observed_at", "served_at",
        "age_seconds", "ttl_seconds",
    }
    if not required.issubset(value):
        raise _shape_error(source, "freshness fields are incomplete")
    state = value.get("state")
    attempted = value.get("attempted_at")
    observed = value.get("observed_at")
    served = value.get("served_at")
    age = value.get("age_seconds")
    ttl = value.get("ttl_seconds")
    if state not in _FRESHNESS_STATES or not _is_utc_timestamp(served):
        raise _shape_error(source, "freshness state or served_at is invalid")
    if attempted is not None and not _is_utc_timestamp(attempted):
        raise _shape_error(source, "freshness attempted_at is invalid")
    if observed is not None and not _is_utc_timestamp(observed):
        raise _shape_error(source, "freshness observed_at is invalid")
    if age is not None and (
        isinstance(age, bool) or not isinstance(age, int) or age < 0
    ):
        raise _shape_error(source, "freshness age_seconds is invalid")
    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or ttl <= 0:
        raise _shape_error(source, "freshness ttl_seconds is invalid")
    if state == "live" and not (
        _is_utc_timestamp(attempted) and _is_utc_timestamp(observed) and age == 0
    ):
        raise _shape_error(source, "live freshness lacks a current observation")
    if state == "cached" and not (
        _is_utc_timestamp(attempted)
        and _is_utc_timestamp(observed)
        and isinstance(age, int)
    ):
        raise _shape_error(source, "cached freshness lacks an aged observation")
    if state == "stale" and ((observed is None) != (age is None)):
        raise _shape_error(source, "stale freshness observation and age disagree")
    if state == "not_applicable" and any(
        item is not None for item in (attempted, observed, age)
    ):
        raise _shape_error(source, "not-applicable freshness claims an observation")
    return value


def _validate_polymarket_payload(payload: Any) -> dict[str, Any]:
    """Enforce scoped market status, coverage, numeric, and freshness invariants."""
    source = "polymarket"
    if not isinstance(payload, dict) or payload.get("status") not in _POLYMARKET_STATUSES:
        raise _shape_error(source, "status is missing or unknown")
    configured = payload.get("configured_markets")
    missing = payload.get("missing_markets")
    markets = payload.get("markets")
    if not all(isinstance(value, list) for value in (configured, missing, markets)):
        raise _shape_error(source, "coverage fields must be lists")
    configured = cast(list[Any], configured)
    missing = cast(list[Any], missing)
    markets = cast(list[Any], markets)
    if (
        any(not isinstance(slug, str) or not slug for slug in configured)
        or len(set(configured)) != len(configured)
        or any(not isinstance(slug, str) or slug not in configured for slug in missing)
        or len(set(missing)) != len(missing)
    ):
        raise _shape_error(source, "configured or missing market ids are invalid")
    seen: set[str] = set()
    for row in markets:
        if not isinstance(row, dict):
            raise _shape_error(source, "market row must be an object")
        slug = row.get("slug")
        probability = row.get("probability")
        if not isinstance(slug, str) or slug not in configured or slug in seen:
            raise _shape_error(source, "market slug is unconfigured or duplicated")
        if (
            isinstance(probability, bool)
            or not isinstance(probability, (int, float))
            or not 0.0 <= probability <= 1.0
        ):
            raise _shape_error(source, "market probability is invalid")
        seen.add(slug)
    expected_missing = [slug for slug in configured if slug not in seen]
    if missing != expected_missing:
        raise _shape_error(source, "missing_markets disagrees with current rows")

    status = payload["status"]
    if status == "ok" and (not configured or expected_missing):
        raise _shape_error(source, "ok status lacks complete coverage")
    if status == "partial" and (not markets or not expected_missing):
        raise _shape_error(source, "partial status lacks mixed coverage")
    if status == "no_data" and (not configured or markets):
        raise _shape_error(source, "no_data status is inconsistent")
    if status == "not_configured" and (configured or missing or markets):
        raise _shape_error(source, "not_configured status has market data")
    if status == "unavailable" and (markets or missing != configured):
        raise _shape_error(source, "unavailable status has current data")

    freshness = _validate_freshness(payload.get("freshness"), source)
    state = freshness["state"]
    if status in {"ok", "partial", "no_data"} and state not in {"live", "cached"}:
        raise _shape_error(source, "current status has stale freshness")
    if status == "not_configured" and state != "not_applicable":
        raise _shape_error(source, "not_configured freshness is not applicable")
    if status == "unavailable" and state != "stale":
        raise _shape_error(source, "unavailable freshness is not stale")
    return payload


def _validate_news_payload(
    payload: Any,
    focused_query: Optional[str],
) -> dict[str, Any]:
    """Enforce GDELT source, query echo, status, list, and freshness contracts."""
    source = "news"
    if not isinstance(payload, dict) or payload.get("status") not in _NEWS_STATUSES:
        raise _shape_error(source, "status is missing or unknown")
    if (payload.get("source") not in _NEWS_ALLOWED_SOURCES
            or not isinstance(payload.get("articles"), list)):
        raise _shape_error(source, "source or articles is invalid")
    query = payload.get("query")
    if query is not None and not isinstance(query, str):
        raise _shape_error(source, "query is invalid")
    if focused_query is not None and query != focused_query:
        raise td.TradingDeskError(
            "tradingDesk news query echo mismatch: "
            f"requested {focused_query!r}, received {query!r}",
        )
    status = payload["status"]
    articles = payload["articles"]
    if status == "ok" and not articles:
        raise _shape_error(source, "ok status has no articles")
    if status in {"no_matches", "not_configured", "rate_limited", "unavailable"} and articles:
        raise _shape_error(source, f"{status} status has current articles")
    if status == "not_configured" and query is not None:
        raise _shape_error(source, "not_configured status has a query")

    freshness = _validate_freshness(payload.get("freshness"), source)
    state = freshness["state"]
    if status in {"ok", "no_matches"} and state not in {"live", "cached"}:
        raise _shape_error(source, "current status has stale freshness")
    if status == "not_configured" and state != "not_applicable":
        raise _shape_error(source, "not_configured freshness is not applicable")
    if status in {"rate_limited", "unavailable"} and state != "stale":
        raise _shape_error(source, "degraded status is not stale")
    return payload


def _degraded_evidence_message(source: str, payload: dict[str, Any]) -> str:
    """Name a failed current check and any timestamped historical observation."""
    status = payload["status"]
    freshness = payload["freshness"]
    query = f" for query {payload.get('query')!r}" if source == "GDELT" else ""
    parts = [f"{source} {status}{query}"]
    retry = payload.get("retry_after_seconds")
    if retry is not None:
        parts.append(f"retry after {retry}s")
    observed = freshness.get("observed_at")
    age = freshness.get("age_seconds")
    if observed is not None:
        parts.append(f"last observed at {observed} ({age}s old)")
    prior = payload.get("last_observation")
    if isinstance(prior, dict):
        parts.append(f"last observation: {json.dumps(prior, default=str)}")
    return "; ".join(parts)


# ── resolution spec validation ───────────────────────────────────────

# Mirror of tradingDesk's PredictionCreate._validate_resolution_spec
# (trading/web/models.py) — the strict shape check at td's own door.
# Mirrored here so a malformed spec dies at DRAFT time with a message the
# model can act on, and re-checked at the Accept write (metadata is a
# document, not a trust boundary). td stays authoritative: whatever passes
# here is forwarded verbatim and judged again at its door.
RESOLUTION_SPEC_KEYS = {
    "price_cross": {"kind", "symbol", "comparator", "threshold"},
    "polymarket": {"kind", "market_id"},
}


def validate_resolution_spec(spec: Any) -> dict:
    """Strict resolution_spec shape check; raises ValueError on any drift.

    An unknown or misspelled key silently ignored here would surface as a
    claim that never auto-resolves — the exact evasion the deterministic
    resolver exists to close.
    """
    if not isinstance(spec, dict):
        raise ValueError("resolution_spec must be an object.")
    kind = spec.get("kind")
    expected = RESOLUTION_SPEC_KEYS.get(kind)
    if expected is None:
        raise ValueError(
            f"resolution_spec.kind must be one of {sorted(RESOLUTION_SPEC_KEYS)}."
        )
    if set(spec) != expected:
        raise ValueError(
            f"resolution_spec for kind={kind!r} requires exactly keys {sorted(expected)}."
        )
    if kind == "price_cross":
        if not isinstance(spec["symbol"], str) or not spec["symbol"]:
            raise ValueError("resolution_spec.symbol must be a non-empty string.")
        if spec["comparator"] not in ("above", "below"):
            raise ValueError("resolution_spec.comparator must be 'above' or 'below'.")
        if not isinstance(spec["threshold"], (int, float)) or isinstance(spec["threshold"], bool):
            raise ValueError("resolution_spec.threshold must be a number.")
    elif kind == "polymarket":
        if not isinstance(spec["market_id"], str) or not spec["market_id"]:
            raise ValueError("resolution_spec.market_id must be a non-empty string.")
    return dict(spec)


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
        book_id = resolve_book_id(room, args.get("book_id"))
        result = await td.service_get(
            f"/api/bridge/polymarket/{book_id}",
            timeout=td.POLYMARKET_TIMEOUT_S,
        )
        validated = _validate_polymarket_payload(result)
        if validated["status"] == "unavailable":
            raise td.TradingDeskError(
                _degraded_evidence_message("Polymarket", validated),
            )
        out = _shrink(
            validated, THESIS_CHAR_CAP, core=_POLYMARKET_CORE_KEYS,
        )
        if not isinstance(out, dict):
            raise td.TradingDeskError(
                "tradingDesk polymarket result could not be represented"
            )
        out["book_id"] = book_id
        visible_markets = out.get("markets")
        out["count"] = len(visible_markets) if isinstance(visible_markets, list) else 0
        return out

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
        query = str(args.get("query") or "").strip() or None
        if query is not None and not 5 <= len(query) <= 500:
            raise ValueError(
                "query must be between 5 and 500 characters after trimming",
            )
        # The 25s HTTP budget clears the bridge's one 20s provider attempt;
        # this tool's 29s guard remains below half the whole-turn budget.
        news = await td.service_get(f"/api/bridge/news/{book_id}",
                                    params={"query": query} if query else None,
                                    timeout=td.NEWS_TIMEOUT_S)
        validated = _validate_news_payload(news, query)
        if validated["status"] in {"rate_limited", "unavailable"}:
            raise td.TradingDeskError(
                _degraded_evidence_message("GDELT", validated),
            )
        shrunk = _shrink(validated, THESIS_CHAR_CAP, core=_NEWS_CORE_KEYS)
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
            timeout_s=QUOTES_TOOL_TIMEOUT_S,
        ),
        Tool(
            name="get_polymarket_odds",
            description=(
                "Current Polymarket probabilities configured for this room's thesis "
                "book. The status distinguishes live data, configured markets with "
                "no current data, and a book with no Polymarket coverage. Use it as "
                "probability evidence only when the book actually tracks a market."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "book_id": {
                        "type": "string",
                        "description": (
                            "Book slug. Defaults to this room's bound book."
                        ),
                    },
                },
            },
            execute=get_polymarket_odds,
            label="checking Polymarket odds",
            timeout_s=POLYMARKET_TOOL_TIMEOUT_S,
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
                "domain. Omit query for the book's standing watch; provide one "
                "focused GDELT query when asked to verify a specific external "
                "claim outside that watch. Report the exact query and status. "
                "no_matches means only that GDELT returned no matches — it is not "
                "evidence that the event did not happen."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "book_id": {
                        "type": "string",
                        "description": "Book slug. Defaults to this room's book.",
                    },
                    "query": {
                        "type": "string",
                        "minLength": 5,
                        "maxLength": 500,
                        "description": (
                            "One focused GDELT query for a specific claim. Omit to "
                            "use the book's standing watch query."
                        ),
                    },
                },
            },
            execute=get_thesis_news,
            label="checking latest headlines",
            timeout_s=NEWS_TOOL_TIMEOUT_S,
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
        if not book:
            # Default to the room's own binding. prediction_watch's deadline
            # sweep finds the room via linked_book_id, so an unlinked
            # prediction was the never-resolves evasion — drafted, accepted,
            # and invisible to the grader forever. An explicit argument
            # still wins; an unbound room still drafts unlinked.
            book = str(getattr(room, "linked_book_id", None) or "").strip()
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

    async def propose_trade(args: dict) -> dict:
        """Validate and shape a paper-trade proposal. NO write — ever.

        Same trust shape as draft_prediction: the proposal is hoisted to
        metadata.trade_proposal, the room renders an Accept button, and only
        the human's tap (api/trading_relay.py trades/accept) fills it on the
        paper book — logging the paired forecast into the claims ledger
        first, so the fill carries its prediction_id.

        WHY prediction XOR discretionary: a trade with neither is silently
        unevaluable — it moves paper money while dodging the scoreboard. The
        75.0-confidence poison taught the other half: never auto-mint a
        forecast the model did not actually state.
        """
        if not getattr(room, "linked_book_id", None):
            # Mirror of propose_thesis's refusal, inverted: a trade needs
            # the book a thesis creates, and Home never has one.
            raise ValueError(
                "this room holds no thesis book — a paper trade needs one. "
                "Propose the thesis first (propose_thesis); trades ride its "
                "book."
            )
        symbol = str(args.get("symbol") or "").strip().upper()
        if not symbol:
            raise ValueError("symbol is required — the instrument to trade, e.g. 'XOP'.")
        if len(symbol) > 32:
            raise ValueError("symbol must be 32 characters or fewer.")
        if symbol == "CASH":
            raise ValueError(
                "'CASH' is the deposit sentinel, not a tradable symbol."
            )
        side = args.get("side")
        if side not in ("buy", "sell"):
            raise ValueError("side must be 'buy' or 'sell'.")
        try:
            dollars = float(args.get("dollars"))
        except (TypeError, ValueError):
            raise ValueError("dollars must be a number — the position size, e.g. 2000.")
        if not 0 < dollars <= 10_000_000:
            raise ValueError("dollars must be between 0 and 10,000,000.")
        rationale = str(args.get("rationale") or "").strip()
        if not rationale:
            raise ValueError(
                "rationale is required — why this trade, in your own words."
            )
        if len(rationale) > 2000:
            raise ValueError("rationale must be 2000 characters or fewer.")
        node_id = str(args.get("node_id") or "").strip()

        prediction = args.get("prediction")
        discretionary = bool(args.get("discretionary"))
        if prediction is not None and not isinstance(prediction, dict):
            raise ValueError("prediction must be an object.")
        has_prediction = isinstance(prediction, dict) and bool(prediction)
        if has_prediction == discretionary:
            raise ValueError(
                "every trade is either a scored forecast or labeled "
                "unscored: pass exactly one of `prediction` (statement, "
                "confidence, deadline — the claim this trade stakes) or "
                "`discretionary: true` (an explicit unscored-discretionary "
                "trade). Neither means the trade dodges the scoreboard; "
                "both contradict each other."
            )

        proposal: dict = {
            "symbol": symbol,
            "side": side,
            "dollars": dollars,
            "rationale": rationale,
        }
        if node_id:
            proposal["node_id"] = node_id
        if has_prediction:
            statement = str(prediction.get("statement") or "").strip()
            if not statement:
                raise ValueError(
                    "prediction.statement is required — the claim being put on record."
                )
            try:
                confidence = float(prediction.get("confidence"))
            except (TypeError, ValueError):
                raise ValueError(
                    "prediction.confidence must be a number between 0 and 1 (0.7 = 70%)."
                )
            if not 0.0 <= confidence <= 1.0:
                raise ValueError(
                    "prediction.confidence must be between 0 and 1 (0.7 = 70%)."
                )
            deadline = str(prediction.get("deadline") or "").strip()
            try:
                date.fromisoformat(deadline)
            except ValueError:
                raise ValueError(
                    "prediction.deadline must be an ISO date, e.g. 2026-09-30."
                )
            forecast: dict = {
                "statement": statement,
                "confidence": confidence,
                "deadline": deadline,
            }
            spec = prediction.get("resolution_spec")
            if spec is not None:
                forecast["resolution_spec"] = validate_resolution_spec(spec)
            proposal["prediction"] = forecast
        else:
            proposal["discretionary"] = True

        return {
            "proposal": proposal,
            "provenance": {"kind": "trade_proposal"},
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

    async def write_document(args: dict) -> dict:
        """Render the model's markdown to a PDF and file it on the room.

        The row is written NOW with message_id NULL; the orchestrator binds
        it to this turn's message once that message exists (documents_mod
        .bind_documents), and the client shows it as a download on the
        bubble. provenance is how the orchestrator finds it in the trace.
        """
        title = str(args.get("title") or "").strip()
        content = str(args.get("content") or "")
        doc = await documents_mod.store_document(db, room.id, title, content)
        return {
            "document": {
                "filename": doc["original_name"],
                "bytes": doc["bytes"],
                "status": (
                    "Filed. It will appear as a download on your message — "
                    "do not paste the content into the chat as well."
                ),
            },
            "provenance": {"kind": "document", "attachment_id": doc["id"]},
        }

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
                "forecast ('Brent closes above $90 by end of Q3') — a "
                "falsifiable statement with a deadline that the room is "
                "actually debating is the trigger, at any horizon: a "
                "two-day aggressive call and a two-year rotation both "
                "belong here. Never for hypotheticals or scenario talk. "
                "Never claim the prediction is logged until a human accepts "
                "it — say you drafted it."
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
                        "description": (
                            "Optional book slug this prediction rides on, "
                            "e.g. 'iran-hormuz-graph'. Defaults to this "
                            "room's bound book when omitted."
                        ),
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
            name="propose_trade",
            description=(
                "Propose a paper trade on this room's book — symbol, side, "
                "dollar size, and why. Calling this places NOTHING: the "
                "proposal is shown to the humans with an Accept button, and "
                "only their tap fills it (tradingDesk prices the fill off "
                "its own quote feed). A trade must carry exactly one of: a "
                "`prediction` (statement, confidence, deadline — the "
                "falsifiable forecast this trade stakes, logged to the "
                "claims ledger on Accept, auto-resolvable when it carries a "
                "price_cross resolution_spec) or `discretionary: true` (an "
                "explicit label that this trade is unscored). Use it when "
                "the room's argument produces a position worth actual "
                "paper money, not for every view. Sells close or trim an "
                "existing position — the book is long-only, so a sell past "
                "flat is refused at fill time. Never claim a trade is "
                "filled until a human accepts it."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "The instrument to trade, e.g. 'XOP' or 'CL=F'.",
                    },
                    "side": {
                        "type": "string",
                        "enum": ["buy", "sell"],
                        "description": "buy opens/adds; sell closes/trims (long-only book).",
                    },
                    "dollars": {
                        "type": "number",
                        "description": "Position size in dollars; the desk computes shares at fill time.",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Why this trade, in your own words. Max 2000 characters.",
                    },
                    "node_id": {
                        "type": "string",
                        "description": "Optional thesis node this trade expresses, e.g. 'brent'.",
                    },
                    "prediction": {
                        "type": "object",
                        "description": (
                            "The falsifiable forecast this trade stakes: "
                            "{statement, confidence 0-1, deadline ISO date, "
                            "optional resolution_spec {kind:'price_cross', "
                            "symbol, comparator:'above'|'below', threshold}}."
                        ),
                        "properties": {
                            "statement": {"type": "string"},
                            "confidence": {"type": "number"},
                            "deadline": {"type": "string"},
                            "resolution_spec": {"type": "object"},
                        },
                        "required": ["statement", "confidence", "deadline"],
                    },
                    "discretionary": {
                        "type": "boolean",
                        "description": (
                            "true labels the trade explicitly unscored — the "
                            "exception, never the default. Mutually exclusive "
                            "with prediction."
                        ),
                    },
                },
                "required": ["symbol", "side", "dollars", "rationale"],
            },
            execute=propose_trade,
            label="proposing a paper trade",
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
        Tool(
            name="write_document",
            description=(
                "Produce a downloadable PDF and attach it to your reply. Use "
                "it when someone asks for a document, a write-up, a report, a "
                "brief, a newsletter, a memo, a PDF — anything meant to be "
                "kept or sent rather than read in the chat. Write the FULL "
                "piece in `content` as markdown (headings, lists, tables, "
                "bold all render); it is the deliverable, so make it complete "
                "and well-structured. The file attaches to your message "
                "automatically: your chat reply should then be one or two "
                "sentences saying what the document covers, not the content "
                "again. One call per document."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Document title — becomes the heading and the filename.",
                    },
                    "content": {
                        "type": "string",
                        "description": (
                            "The whole document, in markdown. Up to 60,000 characters."
                        ),
                    },
                },
                "required": ["title", "content"],
            },
            execute=write_document,
            label="writing the document",
            # Headless Chrome render (RENDER_TIMEOUT_S=20) + disk + one INSERT;
            # the guard must outlive the render's own timeout and stay under
            # half the 60s loop budget, like read_article.
            timeout_s=25.0,
        ),
    ]


# ── cairn dev-memory tools ───────────────────────────────────────────

_CAIRN_OFF_VALUES = frozenset({"0", "false", "no", "off"})


def _world_tools_enabled() -> bool:
    from llm.world import world_tools_enabled
    return world_tools_enabled()


def _build_world_tools(room, db) -> list[Tool]:
    """The World Lens: read current room authority, or propose for review.

    ``world_query`` is read-only. ``propose_geo_scope`` remains the sole
    participant geography writer and can only append a machine proposal.
    """
    from llm import world as world_mod

    async def propose_geo_scope(args: dict) -> dict:
        return await world_mod.propose_geo_scope(db, room.id, args)

    async def world_query(args: dict) -> dict:
        return await world_mod.world_query(db, room.id, room.name, args)

    return [
        Tool(
            name="world_query",
            description=world_mod.WORLD_QUERY_DESCRIPTION,
            input_schema=world_mod.WORLD_QUERY_SCHEMA,
            execute=world_query,
            label="reading the world",
            timeout_s=WORLD_QUERY_INNER_TIMEOUT_S + 4.0,
        ),
        Tool(
            name="propose_geo_scope",
            description=world_mod.PROPOSE_GEO_SCOPE_DESCRIPTION,
            input_schema=world_mod.PROPOSE_GEO_SCOPE_SCHEMA,
            execute=propose_geo_scope,
            label="placing it on the world",
        ),
    ]


def _cairn_tools_enabled() -> bool:
    """Group-level kill switch, default ON per house style — the deploy
    itself is the enablement act. DIALECTIC_TOOLS_ENABLED remains the
    global emergency-off above this."""
    import os
    return os.getenv("CAIRN_TOOLS_ENABLED", "").strip().lower() not in _CAIRN_OFF_VALUES


_EMPTY_DEV_MEMORY_NOTE = (
    "Nothing in dev memory matches. Say so rather than inventing."
)


# The cairn tools read Amo's passively captured dev sessions for EVERY project
# on this host — including somaNotes, a clinical product that is nobody else's
# business and carries PHI-adjacent material. Every tool in this group is
# registered into every room unconditionally, and those rooms have two other
# humans in them. `project` was a model-supplied hint, so a call that omitted
# it returned the lot.
#
# The fence is therefore on the PROJECT, not the room: this monorepo's own
# work is exactly what Dan asked to see ("I'm not sure what we built here"),
# and nothing else may leave the host. Enforced in the executors, never in the
# prompt — a prompt rule is a request, and this is a boundary.
CAIRN_ALLOWED_PROJECTS = frozenset({"dialectic", "DwoodAmo", "trading"})


def _cairn_project_of(row: Any) -> str:
    return str((row or {}).get("project") or "") if isinstance(row, dict) else ""


def _cairn_allowed(rows: Any) -> list:
    """Drop every row belonging to a project outside this monorepo."""
    if not isinstance(rows, list):
        return []
    return [r for r in rows if _cairn_project_of(r) in CAIRN_ALLOWED_PROJECTS]


def _build_cairn_tools() -> list[Tool]:
    """Read-only tools over cairn, the passive dev-session memory on this
    host. Failures surface at call time as CairnError → the loop's is_error
    result; a down cairn never kills a turn.

    Every result is filtered through _cairn_allowed — see CAIRN_ALLOWED_PROJECTS.
    """

    async def search_dev_sessions(args: dict) -> dict:
        query = str(args.get("query") or "").strip()
        if not query:
            raise ValueError("query is required — what dev work are you looking for?")
        limit = min(int(args.get("limit") or 5), 10)
        data = await cn.post("/api/search/sessions",
                             json={"query": query, "limit": limit})
        sessions = _cairn_allowed(data.get("results", []))
        out = {
            "query": query,
            "count": len(sessions),
            "sessions": sessions,
        }
        if not out["sessions"]:
            out["note"] = _EMPTY_DEV_MEMORY_NOTE
        return _shrink(out, TOOL_RESULT_CHAR_CAP)

    async def recent_dev_activity(args: dict) -> dict:
        limit = min(int(args.get("limit") or 10), 20)
        params = {"limit": limit}
        project = str(args.get("project") or "").strip()
        if project and project not in CAIRN_ALLOWED_PROJECTS:
            raise ValueError(
                f"{project!r} is not readable from here. Dev memory is scoped "
                f"to {sorted(CAIRN_ALLOWED_PROJECTS)}."
            )
        if project:
            params["project"] = project
        sessions = await cn.get("/api/sessions", params=params)
        if not isinstance(sessions, list):
            return {"sessions": [], "note": "cairn returned an unexpected shape."}
        sessions = _cairn_allowed(sessions)
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
        # An id fetched by hand must not walk around the project fence.
        if _cairn_project_of(session) not in CAIRN_ALLOWED_PROJECTS:
            raise ValueError(
                "That session belongs to a project that is not readable here."
            )
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
        insights = _cairn_allowed(data.get("results", []))
        out = {
            "query": query,
            "count": len(insights),
            "insights": insights,
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
    if _world_tools_enabled():
        tools += _build_world_tools(room, db)
    if _cairn_tools_enabled():
        tools += _build_cairn_tools()
    return ToolRegistry(tools=tools)
