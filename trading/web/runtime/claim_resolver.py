"""
ClaimResolver — deterministic auto-resolution for claims carrying a resolution_spec.

ARCHITECTURE: Rides the tail of the coordinator's tick sweep (see
RuntimeCoordinator._run_all_ticks). Per cycle it reads the claims ledger
through the repository's public API, evaluates every unresolved prediction
whose resolution_spec the Phase-1 door validated, and applies verdicts via
resolve_prediction_once — so re-runs are idempotent and a human's prior
resolution always wins (a PredictionResolutionConflict stands the resolver
down, never raises out of the tick).

WHY no LLM: this is the house autonomy fence. The resolver performs
deterministic data checks only — a price against a threshold, a closed
prediction market against its reported outcome. Anything requiring judgment
stays on the human flow through prediction_watch.

THE POLYMARKET SIDE CONTRACT: a claim with a polymarket resolution_spec
asserts the market's YES side. A market that closes with the Yes outcome
resolves the claim correct; closed with No resolves it incorrect. Authors
phrasing a claim as the No side must invert the statement, not the spec.

THE PRICE_CROSS ORACLE CONTRACT: daily bars are the oracle, the spot quote
is only a short-circuit. A 300s spot poll misses intraday crosses (a stock
that touches the threshold and falls back between ticks would read as a
false "incorrect" at deadline), so a claim resolves off the symbol's daily
highs/lows over [created_at .. min(today, deadline)] via the Yahoo v8 chart
API: 'above' crosses when any bar HIGH >= threshold, 'below' when any bar
LOW <= threshold. A cross found in bars resolves correct even after the
deadline has passed — the bars prove it happened inside the window. The
spot quote may short-circuit a cross that is true right now (skipping the
chart call), but the absence of a spot cross proves nothing. Bars
unavailable → skip the claim this cycle; a resolution never rests on
missing data. Every applied verdict stamps a compact JSON evidence object
into resolution_notes (the bar that crossed, or the checked window with its
max-high/min-low) so no resolution rests on an API response that vanished.

TRADEOFF (spot source): the short-circuit reads
web.adapters.market.fetch_quotes — the same 240s-TTL cached path the LLM
tools and the ticker use — rather than the per-thesis marketSnapshot the
tick just committed. (The late-cross watch reads bars only; see
_maybe_flag_late_cross for why spot is excluded there.) Snapshots key
prices by book-internal ids while specs name Yahoo symbols; one shared, symbol-keyed path beats a namespace-mapping
layer, and the TTL cache bounds the cost to at most one cold fetch per
cycle, taken after every thesis lock has been released.
"""

import asyncio
import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote as _urlquote
from urllib.request import Request, urlopen

from tools.data_fetch import polymarket as polymarket_mod  # type: ignore[import-untyped]

from web.adapters.market import fetch_quotes
from web.persistence.repository import PredictionResolutionConflict, Repository

log = logging.getLogger(__name__)

#: Audit actions written by this module. auto_resolve rows record applied
#: verdicts; late_cross rows are the durable "right but early" ledger (see
#: the ponytail note in _maybe_flag_late_cross).
AUTO_RESOLVE_ACTION = "prediction.auto_resolve"
LATE_CROSS_ACTION = "prediction.late_cross"

#: A closed Polymarket market only resolves a claim when its Yes price has
#: collapsed to a settled extreme. Between these bounds a "closed" market is
#: ambiguous (halted, disputed, mid-settlement) and the claim is left alone.
POLYMARKET_YES_MIN = 0.99
POLYMARKET_NO_MAX = 0.01

#: Days past its deadline that an incorrect price_cross claim stays on the
#: late-cross watch (plan Phase 2 laboratory hook).
LATE_CROSS_WINDOW_DAYS = 30


def _spec_source_key(prediction_id: str, spec: Dict[str, Any]) -> str:
    """Stable idempotency key: sha256 of the canonical-JSON spec + claim id.

    WHY the prediction id rides into the hash: two claims may carry the
    identical spec, and resolve_prediction_once keys conflicts off the
    stored resolution_source_key — each claim needs its own.
    """
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256((canonical + prediction_id).encode()).hexdigest()[:16]
    return f"auto:{spec['kind']}:{digest}"


def _crossed(price: float, comparator: str, threshold: float) -> bool:
    """WHY >= / <=: matches the engine's own threshold gate
    (eval_node_state's `current >= th["level"]`) — touching the level IS
    the cross, on both sides."""
    if comparator == "above":
        return price >= threshold
    return price <= threshold


def _parse_deadline(deadline: Any) -> Optional[date]:
    """ISO date (or the date half of an ISO datetime); None when unparseable.

    Never resolve on data we cannot read — an unparseable deadline skips
    the claim every cycle rather than guessing a window.
    """
    if not isinstance(deadline, str) or len(deadline) < 10:
        return None
    try:
        return date.fromisoformat(deadline[:10])
    except ValueError:
        return None


#: Yahoo's `range` parameter takes discrete values, not a day count — the
#: smallest range covering the claim's calendar window is chosen (same
#: ladder idea as thesisgraph._range_for_bars, but keyed on calendar days
#: since a claim window is authored in dates, not trading bars).
_YAHOO_CHART_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"
_YAHOO_RANGE_DAYS = (
    ("5d", 4), ("1mo", 25), ("3mo", 80), ("6mo", 170),
    ("1y", 350), ("2y", 700), ("5y", 1800),
)


def _range_for_days(days: int) -> str:
    for name, covers in _YAHOO_RANGE_DAYS:
        if days <= covers:
            return name
    return "max"


def fetch_daily_bars(
    symbol: str, start: date, end: date
) -> Optional[List[Dict[str, Any]]]:
    """Daily high/low bars for [start .. end] via the Yahoo v8 chart API.

    Same URL/parse pattern as thesisgraph.fetch_ohlcv_for_derived (v8 chart,
    interval=1d, timestamps paired index-by-index with indicators.quote) —
    not reused directly because that function is shaped around a book cfg's
    derivedIndicators specs, not a bare symbol+window.

    Returns bars as {"date": date, "high": float|None, "low": float|None},
    chronological, filtered to the window. None means the FETCH failed
    (transport/parse) and the caller must skip; [] is a valid "no trading
    days in window" answer.
    """
    days = max((datetime.now(timezone.utc).date() - start).days, 1)
    url = (
        f"{_YAHOO_CHART_BASE}{_urlquote(symbol, safe='=^.-')}"
        f"?range={_range_for_days(days)}&interval=1d"
    )
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        results = (data.get("chart", {}) or {}).get("result") or []
        if not results:
            return None
        quote = results[0].get("indicators", {}).get("quote", [{}])[0]
        timestamps = results[0].get("timestamp") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        bars: List[Dict[str, Any]] = []
        for i, ts in enumerate(timestamps):
            if ts is None:
                continue
            bar_date = datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
            if not (start <= bar_date <= end):
                continue
            high = highs[i] if i < len(highs) else None
            low = lows[i] if i < len(lows) else None
            bars.append({
                "date": bar_date,
                "high": float(high) if high is not None else None,
                "low": float(low) if low is not None else None,
            })
        return bars
    except Exception:  # noqa: BLE001 — a chart fault is a skip, never a crash
        log.warning("daily bar fetch failed for %s", symbol, exc_info=True)
        return None


def _bar_cross(
    bars: List[Dict[str, Any]], comparator: str, threshold: float
) -> Optional[Dict[str, Any]]:
    """First bar whose high (above) / low (below) crosses the threshold."""
    field = "high" if comparator == "above" else "low"
    for bar in bars:
        value = bar.get(field)
        if value is not None and _crossed(value, comparator, threshold):
            return bar
    return None


def fetch_polymarket_market_state(market_id: str) -> Optional[Dict[str, Any]]:
    """Gamma lookup that CAN see closed markets, unlike the shared client.

    WHY not polymarket_mod._search_markets: that helper pins
    `active=true&closed=false` on the URL, which by construction filters out
    the closed markets this resolver exists to observe. The events path has
    no such filter, so we try it first (mirroring fetch_single_market's
    order) and fall back to an unfiltered /markets slug lookup. Reuses the
    client's single-point _make_request seam and its matching/extraction
    helpers so slug semantics stay identical across the codebase.

    Returns {"closed": bool, "yes_probability": float|None} or None when the
    market cannot be found or the fetch fails — the caller skips silently.
    """
    try:
        matched: Optional[dict] = None
        for event in polymarket_mod._search_events(market_id, timeout=10):
            matched = polymarket_mod._match_market_in_results(
                event.get("markets", []) or [], market_id
            )
            if matched is not None:
                break
        if matched is None:
            url = (
                f"{polymarket_mod.GAMMA_API_BASE}/markets"
                f"?slug={_urlquote(market_id, safe='')}"
            )
            results = json.loads(polymarket_mod._make_request(url, timeout=10))
            if isinstance(results, dict):
                data = results.get("data")
                results = data if isinstance(data, list) else [results]
            if not isinstance(results, list):
                results = []
            matched = polymarket_mod._match_market_in_results(results, market_id)
        if matched is None:
            return None
        return {
            "closed": bool(matched.get("closed")),
            "yes_probability": polymarket_mod._extract_probability_from_market(matched),
        }
    except Exception:  # noqa: BLE001 — a Gamma fault is a skip, never a crash
        log.warning("polymarket state fetch failed for %s", market_id, exc_info=True)
        return None


def polymarket_verdict(state: Optional[Dict[str, Any]]) -> Optional[str]:
    """Map a market state to a claim verdict under the YES-side contract.

    Pure function so the mapping is testable without any network seam.
    """
    if not state or not state.get("closed"):
        return None
    yes = state.get("yes_probability")
    if not isinstance(yes, (int, float)):
        return None
    if yes >= POLYMARKET_YES_MIN:
        return "correct"
    if yes <= POLYMARKET_NO_MAX:
        return "incorrect"
    return None


class ClaimResolver:
    """One instance per coordinator; all persistence goes through the repo's
    public API (list_predictions / resolve_prediction_once / add_audit_row /
    list_audit) — this module owns no SQL.

    The fetcher seams exist for tests: quote_fetcher replaces the cached
    Yahoo spot path, bar_fetcher the v8 daily-bars oracle, and
    market_state_fetcher the Gamma lookup.
    """

    def __init__(
        self,
        repo: Repository,
        ws_manager: Any = None,
        quote_fetcher: Callable[[], List[Dict[str, Any]]] = fetch_quotes,
        bar_fetcher: Callable[
            [str, date, date], Optional[List[Dict[str, Any]]]
        ] = fetch_daily_bars,
        market_state_fetcher: Callable[
            [str], Optional[Dict[str, Any]]
        ] = fetch_polymarket_market_state,
    ) -> None:
        self._repo = repo
        self._ws = ws_manager
        self._fetch_quotes = quote_fetcher
        self._fetch_bars = bar_fetcher
        self._fetch_market_state = market_state_fetcher
        # Lazily hydrated from audit_log so a restart cannot re-flag a late
        # cross the previous process already recorded.
        self._late_cross_flagged: Optional[set] = None

    async def run_once(self) -> Dict[str, int]:
        """One resolution sweep. Returns counts for logging/tests; never raises
        past the individual claim (the coordinator wraps the call anyway)."""
        rows = await asyncio.to_thread(self._repo.list_predictions)
        pending = [
            r for r in rows
            if r.get("resolution") is None and isinstance(r.get("resolution_spec"), dict)
        ]
        late_watch = [r for r in rows if self._on_late_cross_watch(r)]
        summary = {"resolved": 0, "skipped": 0, "late_crosses": 0}
        if not pending and not late_watch:
            return summary

        price_map = await self._price_map_if_needed(pending)

        for row in pending:
            kind = row["resolution_spec"].get("kind")
            if kind == "price_cross":
                verdict, notes = await self._price_cross_verdict(row, price_map)
            elif kind == "polymarket":
                verdict, notes = await self._polymarket_verdict_for(row)
            else:
                # The door validates kinds; an unknown one here is stored
                # data from a future schema — skip, never guess.
                verdict, notes = None, None
            if verdict is None:
                summary["skipped"] += 1
                continue
            if await self._apply(row, verdict, notes or ""):
                summary["resolved"] += 1

        for row in late_watch:
            if await self._maybe_flag_late_cross(row):
                summary["late_crosses"] += 1

        if summary["resolved"] or summary["late_crosses"]:
            log.info(
                "claim_resolver: resolved=%d late_crosses=%d skipped=%d",
                summary["resolved"], summary["late_crosses"], summary["skipped"],
            )
        return summary

    # ── evaluation ──────────────────────────────────────────────────

    async def _price_map_if_needed(
        self, pending: List[dict]
    ) -> Dict[str, float]:
        """Fetch quotes only when some claim actually needs a spot price this
        cycle — a polymarket-only ledger must not touch Yahoo at all. The
        late-cross watch reads bars, never spot, so it doesn't count."""
        needs = any(
            r["resolution_spec"].get("kind") == "price_cross" for r in pending
        )
        if not needs:
            return {}
        try:
            quotes = await asyncio.to_thread(self._fetch_quotes)
        except Exception:  # noqa: BLE001 — no quotes means skip, never resolve
            log.warning("claim_resolver: quote fetch failed", exc_info=True)
            return {}
        return {
            q["symbol"]: float(q["price"])
            for q in quotes or []
            if isinstance(q, dict) and q.get("symbol")
            and isinstance(q.get("price"), (int, float))
        }

    async def _price_cross_verdict(
        self, row: dict, price_map: Dict[str, float]
    ) -> tuple:
        """(verdict, evidence-JSON notes) for one price_cross claim;
        (None, None) skips. Bars are the oracle; spot only short-circuits
        (see the module contract)."""
        spec = row["resolution_spec"]
        deadline = _parse_deadline(row.get("deadline"))
        created = _parse_deadline(row.get("created_at"))
        if deadline is None or created is None:
            log.warning(
                "claim_resolver: unparseable window (%r..%r) on %s — skipping",
                row.get("created_at"), row.get("deadline"), row.get("id"),
            )
            return None, None
        today = datetime.now(timezone.utc).date()
        comparator, threshold = spec["comparator"], spec["threshold"]

        # Spot short-circuit — only inside the open window, where "true right
        # now" implies "true inside [created .. deadline]".
        if today <= deadline:
            price = price_map.get(spec["symbol"])
            if price is not None and _crossed(price, comparator, threshold):
                return "correct", json.dumps({
                    "auto": "price_cross",
                    "provider": "yahoo_spot",
                    "observed": {
                        "date": today.isoformat(),
                        "price": price,
                        "threshold": threshold,
                        "comparator": comparator,
                    },
                })

        window_end = min(today, deadline)
        bars = await asyncio.to_thread(
            self._fetch_bars, spec["symbol"], created, window_end
        )
        if bars is None:
            return None, None  # fetch failed — never resolve on missing data

        hit = _bar_cross(bars, comparator, threshold)
        if hit is not None:
            # A bar inside the window proves the cross happened before the
            # deadline — correct, even when today is already past it.
            field = "high" if comparator == "above" else "low"
            return "correct", json.dumps({
                "auto": "price_cross",
                "provider": "yahoo_v8_daily",
                "observed": {
                    "date": hit["date"].isoformat(),
                    field: hit[field],
                    "threshold": threshold,
                    "comparator": comparator,
                },
            })

        if today > deadline:
            if not bars:
                # A window Yahoo answers with zero bars is indistinguishable
                # from missing data — skip; the human flow covers it.
                return None, None
            highs = [b["high"] for b in bars if b["high"] is not None]
            lows = [b["low"] for b in bars if b["low"] is not None]
            extreme = (
                {"max_high": max(highs)} if comparator == "above" and highs
                else {"min_low": min(lows)} if comparator == "below" and lows
                else {}
            )
            return "incorrect", json.dumps({
                "auto": "price_cross",
                "provider": "yahoo_v8_daily",
                "observed": {
                    "window": {
                        "start": created.isoformat(),
                        "end": deadline.isoformat(),
                    },
                    "bars": len(bars),
                    **extreme,
                    "threshold": threshold,
                    "comparator": comparator,
                },
            })
        return None, None  # window still open, no cross yet

    async def _polymarket_verdict_for(self, row: dict) -> tuple:
        spec = row["resolution_spec"]
        state = await asyncio.to_thread(self._fetch_market_state, spec["market_id"])
        verdict = polymarket_verdict(state)
        if verdict is None:
            return None, None  # open, ambiguous, or unreachable — skip
        outcome = "Yes" if verdict == "correct" else "No"
        return verdict, json.dumps({
            "auto": "polymarket",
            "provider": "gamma",
            "market_id": spec["market_id"],
            "outcome": outcome,
        })

    # ── application ─────────────────────────────────────────────────

    async def _apply(self, row: dict, resolution: str, notes: str) -> bool:
        """Resolve + audit + broadcast. Human's prior verdict wins silently."""
        source_key = _spec_source_key(row["id"], row["resolution_spec"])
        try:
            record, changed = await asyncio.to_thread(
                self._repo.resolve_prediction_once,
                row["id"], resolution, source_key, notes,
            )
        except PredictionResolutionConflict:
            log.info(
                "claim_resolver: %s already resolved by a human — "
                "auto verdict %r stands down", row["id"], resolution,
            )
            return False
        if record is None or not changed:
            return False
        try:
            await asyncio.to_thread(
                self._repo.add_audit_row,
                actor="claim_resolver",
                action=AUTO_RESOLVE_ACTION,
                target=row["id"],
                reason=notes,
                payload={
                    "resolution": resolution,
                    "resolution_spec": row["resolution_spec"],
                    "source_key": source_key,
                },
            )
        except Exception:  # noqa: BLE001 — audit is a trail, not a gate
            log.warning("claim_resolver: audit write failed for %s", row["id"],
                        exc_info=True)
        await self._broadcast(
            f"Auto-resolved {resolution}: \"{(row.get('statement') or '')[:60]}\""
        )
        return True

    async def _broadcast(self, detail: str) -> None:
        """system-message pattern shared with routes/predictions.py; a WS
        fault must never undo or block a committed resolution."""
        if self._ws is None:
            return
        try:
            await self._ws.broadcast_all("system", {"detail": detail}, user="system")
        except Exception:  # noqa: BLE001
            log.warning("claim_resolver: ws broadcast failed", exc_info=True)

    # ── late-cross watch (laboratory hook) ──────────────────────────

    def _on_late_cross_watch(self, row: dict) -> bool:
        spec = row.get("resolution_spec")
        if (
            row.get("resolution") != "incorrect"
            or not isinstance(spec, dict)
            or spec.get("kind") != "price_cross"
        ):
            return False
        deadline = _parse_deadline(row.get("deadline"))
        if deadline is None:
            return False
        today = datetime.now(timezone.utc).date()
        return 0 <= (today - deadline).days <= LATE_CROSS_WINDOW_DAYS

    async def _maybe_flag_late_cross(self, row: dict) -> bool:
        """First post-deadline cross on an incorrect claim → durable flag.

        The resolution stands untouched — this records "right but early"
        for the Phase-8 per-source split, nothing more. Two durable homes,
        deliberately: Repository.stamp_late_cross merges the JSON into
        resolution_notes (the queryable field Phase 8 splits on), and the
        audit row keeps the evidence (spec + crossing bar) beside every
        other resolver action.

        WHY bars, not spot, with NO spot short-circuit: delay_days is the
        statistic Phase 8 splits on, and it must date from the FIRST
        crossing bar — a spot hit stamped "today" overstates the delay
        whenever the cross happened days ago, and a spot poll misses a
        spike that falls back between ticks entirely. Today's intraday
        move already shows in today's (partial) daily bar, so spot would
        add nothing but a less accurate date.
        """
        if "late_cross" in (row.get("resolution_notes") or ""):
            return False
        flagged = await asyncio.to_thread(self._hydrate_late_cross_flags)
        if row["id"] in flagged:
            return False
        spec = row["resolution_spec"]
        deadline = _parse_deadline(row.get("deadline"))
        if deadline is None:
            return False
        today = datetime.now(timezone.utc).date()
        # Watch window (deadline, min(today, deadline + 30d)] — strictly
        # post-deadline bars; an at-deadline cross belongs to resolution.
        bars = await asyncio.to_thread(
            self._fetch_bars,
            spec["symbol"],
            deadline + timedelta(days=1),
            min(today, deadline + timedelta(days=LATE_CROSS_WINDOW_DAYS)),
        )
        if not bars:
            return False  # fetch failed or no post-deadline bars yet — retry next tick
        hit = _bar_cross(bars, spec["comparator"], spec["threshold"])
        if hit is None:
            return False
        field = "high" if spec["comparator"] == "above" else "low"
        stamp_obj = {
            "date": hit["date"].isoformat(),
            "delay_days": (hit["date"] - deadline).days,
        }
        stamp = json.dumps({"late_cross": stamp_obj})
        try:
            await asyncio.to_thread(
                self._repo.stamp_late_cross, row["id"], stamp_obj,
            )
        except Exception:  # noqa: BLE001 — the audit row below still records it
            log.warning("claim_resolver: late-cross notes stamp failed for %s",
                        row["id"], exc_info=True)
        try:
            await asyncio.to_thread(
                self._repo.add_audit_row,
                actor="claim_resolver",
                action=LATE_CROSS_ACTION,
                target=row["id"],
                reason=stamp,
                payload={
                    "resolution_spec": spec,
                    "bar": {"date": hit["date"].isoformat(), field: hit[field]},
                },
            )
        except Exception:  # noqa: BLE001
            log.warning("claim_resolver: late-cross audit failed for %s",
                        row["id"], exc_info=True)
            return False
        flagged.add(row["id"])
        log.info("claim_resolver: %s crossed after its deadline (%s)",
                 row["id"], stamp)
        return True

    def _hydrate_late_cross_flags(self) -> set:
        """Audit-backed dedup set, loaded once per process. WHY from audit
        (not notes): the audit row and the notes stamp are written by the
        same pass, but audit rows are queryable by action in one call —
        reading them on first use makes the flag idempotent across
        restarts, not just within one process lifetime."""
        if self._late_cross_flagged is None:
            try:
                rows = self._repo.list_audit(action=LATE_CROSS_ACTION, limit=1000)
                self._late_cross_flagged = {r["target"] for r in rows}
            except Exception:  # noqa: BLE001
                log.warning("claim_resolver: audit hydrate failed", exc_info=True)
                self._late_cross_flagged = set()
        return self._late_cross_flagged
