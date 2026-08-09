"""
Market data adapter — wraps Yahoo Finance + Polymarket fetchers.

WHY: Normalizes the raw fetch output from thesisgraph.fetch_prices and
polymarket.fetch_markets into consistent API-friendly dicts.
"""

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Set

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


def _collect_symbols_from_books() -> tuple[Set[str], List[str]]:
    """Scan all book configs for Yahoo Finance symbols and Polymarket slugs."""
    yahoo_symbols: Set[str] = set()
    poly_slugs: List[str] = []

    for path in sorted(BOOKS_DIR.glob("*-graph.json")):
        try:
            cfg = thesisgraph.load_config(str(path))
        except Exception:
            continue

        for ticker, _ in _iter_instruments(cfg):
            if ticker:
                yahoo_symbols.add(ticker)

        for node in cfg.get("nodes", []):
            for feed in node.get("feeds", []):
                if feed.get("source") == "polymarket":
                    slug = feed.get("slug", "")
                    if slug and slug not in poly_slugs:
                        poly_slugs.append(slug)

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
            cfg = thesisgraph.load_config(str(path))
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


def fetch_polymarket_probs() -> List[Dict[str, Any]]:
    """Fetch Polymarket probabilities for all configured slugs."""
    _, poly_slugs = _collect_symbols_from_books()
    if not poly_slugs:
        return []

    try:
        probs = polymarket_mod.fetch_markets(poly_slugs)
        return [{"slug": slug, "probability": prob} for slug, prob in probs.items()]
    except Exception as e:
        log.warning("Polymarket fetch failed: %s", e)
        return []


def get_watchlist() -> List[Dict[str, Any]]:
    """Combined watchlist from all books' instruments."""
    items: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    for path in sorted(BOOKS_DIR.glob("*-graph.json")):
        try:
            cfg = thesisgraph.load_config(str(path))
        except Exception:
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
                    slug = feed.get("slug", "")
                    if slug and slug not in seen:
                        seen.add(slug)
                        items.append({
                            "symbol": slug,
                            "label": feed.get("label", slug),
                            "last_price": None,
                            "change_pct": None,
                            "source": "polymarket",
                        })
    return items
