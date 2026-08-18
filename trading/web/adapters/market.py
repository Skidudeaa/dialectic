"""
Market data adapter — wraps Yahoo Finance + Polymarket fetchers.

WHY: Normalizes the raw fetch output from thesisgraph.fetch_prices and
polymarket.fetch_markets into consistent API-friendly dicts.
"""

import json
import logging
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

# WHY a TTL cache: fetch_quotes fans out to Yahoo per book with inter-batch
# sleeps (~18.5s measured on the healthy path). The coordinator refreshes
# every 300s anyway, so a 240s cache means callers (the Dialectic LLM tool,
# the ticker UI) pay the cold path at most once per cycle and get ms after.
_QUOTES_CACHE: dict = {"at": 0.0, "data": None}
QUOTES_CACHE_TTL_S = 240.0

_ROOT = Path(__file__).resolve().parent.parent.parent
BOOKS_DIR = _ROOT / "books"

from tools.thesis_graph import thesisgraph  # type: ignore[import-untyped]
from tools.data_fetch import polymarket as polymarket_mod  # type: ignore[import-untyped]
from web.adapters.thesis import load_book_config


def _iter_instruments(cfg: dict):
    """Yield (ticker, label) pairs from book instruments.

    WHY: instruments is dict[nodeId, list[dict]] where each inner dict has
    'id' (ticker) and 'role' (label). Not a flat list.
    """
    instruments = cfg.get("instruments", {})
    if isinstance(instruments, dict):
        for node_id, inst_list in instruments.items():
            if isinstance(inst_list, list):
                for inst in inst_list:
                    if isinstance(inst, dict):
                        yield inst.get("id", ""), inst.get("role", inst.get("id", ""))
    elif isinstance(instruments, list):
        for inst in instruments:
            if isinstance(inst, dict):
                yield inst.get("id", ""), inst.get("role", inst.get("id", ""))


def _polymarket_feed_id(feed: dict[str, Any]) -> str:
    """The ONE place a Polymarket feed's market id is resolved.

    ARCHITECTURE (design 2026-08-16 §3.1): `market` first, legacy `slug`
    second, empty ignored. `market` wins a conflict because it is the field
    current books author and the thesis engine consumes — thesisgraph.py:158
    already validates a polymarket feed as `slug or market`, so accepting both
    here is honoring a contract the project had already written down, not
    inventing one.

    WHY a helper rather than an inline `or` at each site: there were two read
    sites, both read ONLY `slug`, and every book on disk writes `market` while
    none writes `slug`. So the collector discovered zero markets and
    fetch_polymarket_probs returned [] without ever contacting Polymarket —
    permanently, for iran-hormuz and trump-tariffs alike, and indistinguishably
    from "no markets configured". A second inline copy is how the two sites
    drifted from the validator in the first place; one helper is what stops it
    happening again.
    """
    for key in ("market", "slug"):
        value = feed.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def polymarket_markets_from_book(cfg: dict[str, Any]) -> list[str]:
    """Return unique Polymarket IDs from one book in authored order."""
    market_ids: list[str] = []
    for node in cfg.get("nodes", []) or []:
        for feed in node.get("feeds", []) or []:
            if not isinstance(feed, dict) or feed.get("source") != "polymarket":
                continue
            market_id = _polymarket_feed_id(feed)
            if market_id and market_id not in market_ids:
                market_ids.append(market_id)
    return market_ids


def _collect_symbols_from_books() -> tuple[Set[str], List[str]]:
    """Scan all book configs for Yahoo symbols and Polymarket market IDs."""
    yahoo_symbols: Set[str] = set()
    poly_slugs: List[str] = []

    for path in sorted(BOOKS_DIR.glob("*-graph.json")):
        try:
            cfg = load_book_config(path)
        except Exception:
            continue
        if cfg is None:
            continue

        for ticker, _ in _iter_instruments(cfg):
            if ticker:
                yahoo_symbols.add(ticker)

        for market_id in polymarket_markets_from_book(cfg):
            if market_id not in poly_slugs:
                poly_slugs.append(market_id)

    return yahoo_symbols, poly_slugs


def _extract_quotes_from_cfg(cfg: dict) -> List[Dict[str, Any]]:
    """Pull fetched prices out of a cfg MUTATED by thesisgraph.fetch_prices.

    WHY: fetch_prices returns the cfg itself (docstring: "Mutates and returns
    cfg"), writing prices into node["current"] (nodes with a yahoo feed) and
    inst["ref"] (instrument tickers). The old code iterated the returned
    cfg's top-level keys expecting {symbol: price} — none are numeric, so
    /api/market/quotes had NEVER returned a single quote. Extract from where
    the values actually land.
    """
    quotes: List[Dict[str, Any]] = []
    for node in cfg.get("nodes", []):
        for feed in node.get("feeds", []):
            if feed.get("source") == "yahoo" and feed.get("symbol"):
                current = node.get("current")
                if isinstance(current, (int, float)):
                    quotes.append({
                        "symbol": feed["symbol"],
                        "price": current,
                        "source": "yahoo",
                        "node_id": node.get("id"),
                    })
                break  # one quote per node even if multiple feeds
    instruments = cfg.get("instruments", {})
    if isinstance(instruments, dict):
        for _nid, inst_list in instruments.items():
            if not isinstance(inst_list, list):
                continue
            for inst in inst_list:
                ref = inst.get("ref") if isinstance(inst, dict) else None
                if inst.get("id") and isinstance(ref, (int, float)) and ref:
                    quotes.append({
                        "symbol": inst["id"],
                        "price": ref,
                        "source": "yahoo",
                    })
    return quotes


def fetch_quotes(force_refresh: bool = False) -> List[Dict[str, Any]]:
    """Fetch Yahoo Finance prices for all configured symbols across books.

    Served from a short TTL cache; the cold path re-fetches Yahoo per book
    (slow — inter-batch sleeps inside thesisgraph.fetch_prices).
    """
    now = time.monotonic()
    if (not force_refresh and _QUOTES_CACHE["data"] is not None
            and now - _QUOTES_CACHE["at"] < QUOTES_CACHE_TTL_S):
        return _QUOTES_CACHE["data"]

    yahoo_symbols, _ = _collect_symbols_from_books()
    if not yahoo_symbols:
        return []

    results: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for path in sorted(BOOKS_DIR.glob("*-graph.json")):
        try:
            cfg = load_book_config(path)
            if cfg is None:
                continue
            thesisgraph.fetch_prices(cfg)
            for quote in _extract_quotes_from_cfg(cfg):
                if quote["symbol"] not in seen:
                    seen.add(quote["symbol"])
                    results.append(quote)
        except Exception as e:
            log.warning("Price fetch failed for %s: %s", path.name, e)

    if results:
        _QUOTES_CACHE["at"] = now
        _QUOTES_CACHE["data"] = results
    return results


_YAHOO_CHART_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/"


def fetch_daily_close(symbol: str) -> Optional[float]:
    """Last daily close for one symbol from the Yahoo v8 chart API, or None.

    WHY not fetch_quotes: the nightly equity mark needs the official daily
    CLOSE, not an intraday spark price — and must not pay fetch_quotes'
    per-book fan-out for one symbol. range=5d rides out weekends/holidays;
    the last non-null close is the most recent completed session. Any
    failure returns None — the caller owns the fallback policy.
    """
    encoded = urllib.parse.quote(symbol, safe="=^.-")
    url = f"{_YAHOO_CHART_BASE}{encoded}?range=5d&interval=1d"
    try:
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        results = (data.get("chart") or {}).get("result") or []
        if not results:
            return None
        quote = results[0].get("indicators", {}).get("quote", [{}])[0]
        closes = [c for c in (quote.get("close") or []) if c is not None]
        return float(closes[-1]) if closes else None
    except Exception as e:
        log.warning("fetch_daily_close(%s) failed: %s", symbol, e)
        return None


def fetch_polymarket_probs(
    market_ids: Optional[list[str]] = None,
) -> List[Dict[str, Any]]:
    """Fetch strict explicit probabilities or the legacy global market list.

    Explicit IDs are the book-scoped verification path: missing values are
    omitted and transport/API failures raise. With no IDs, preserve the global
    browser contract: use the client's 15-second best-effort defaults and keep
    every authored market, including null probabilities.

    The response key remains `slug` because that is the existing wire contract;
    only the book-side key was ever ambiguous.
    """
    global_read = market_ids is None
    if global_read:
        _, market_ids = _collect_symbols_from_books()
    if not market_ids:
        return []

    if global_read:
        probabilities = polymarket_mod.fetch_markets(market_ids)
        return [
            {"slug": market_id, "probability": probabilities.get(market_id)}
            for market_id in market_ids
        ]

    # WHY strict here: this backs a verification tool. A transport/API failure
    # must fail the tool call, not turn into a successful "no_data" claim.
    probabilities = polymarket_mod.fetch_markets(
        market_ids,
        timeout=5,
        retries=2,
        raise_on_error=True,
        parallel=True,
    )
    return [
        {"slug": market_id, "probability": probability}
        for market_id, probability in probabilities.items()
        if isinstance(probability, (int, float))
    ]


def get_watchlist() -> List[Dict[str, Any]]:
    """Combined watchlist from all books' instruments."""
    items: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    for path in sorted(BOOKS_DIR.glob("*-graph.json")):
        try:
            cfg = load_book_config(path)
        except Exception:
            continue
        if cfg is None:
            continue

        for ticker, label in _iter_instruments(cfg):
            if ticker and ticker not in seen:
                seen.add(ticker)
                items.append({
                    "symbol": ticker,
                    "label": label,
                    "last_price": None,
                    "change_pct": None,
                    "source": "yahoo",
                })

        for node in cfg.get("nodes", []):
            for feed in node.get("feeds", []):
                if feed.get("source") == "polymarket":
                    market_id = _polymarket_feed_id(feed)
                    if market_id and market_id not in seen:
                        seen.add(market_id)
                        items.append({
                            "symbol": market_id,
                            "label": feed.get("label", market_id),
                            "last_price": None,
                            "change_pct": None,
                            "source": "polymarket",
                        })
    return items
