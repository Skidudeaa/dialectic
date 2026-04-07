"""
Market data adapter — wraps Yahoo Finance + Polymarket fetchers.

WHY: Normalizes the raw fetch output from thesisgraph.fetch_prices and
polymarket.fetch_markets into consistent API-friendly dicts.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Set

log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent.parent.parent
BOOKS_DIR = _ROOT / "books"

import thesisgraph  # type: ignore[import-untyped]
import polymarket as polymarket_mod  # type: ignore[import-untyped]


def _collect_symbols_from_books() -> tuple[Set[str], List[str]]:
    """Scan all book configs for Yahoo Finance symbols and Polymarket slugs."""
    yahoo_symbols: Set[str] = set()
    poly_slugs: List[str] = []

    for path in sorted(BOOKS_DIR.glob("*-graph.json")):
        try:
            cfg = thesisgraph.load_config(str(path))
        except Exception:
            continue

        # Instruments have ticker fields
        for inst in cfg.get("instruments", []):
            ticker = inst.get("ticker", "")
            if ticker:
                yahoo_symbols.add(ticker)

        # Feeds with source: "polymarket" have slug fields
        for node in cfg.get("nodes", []):
            for feed in node.get("feeds", []):
                if feed.get("source") == "polymarket":
                    slug = feed.get("slug", "")
                    if slug and slug not in poly_slugs:
                        poly_slugs.append(slug)

    return yahoo_symbols, poly_slugs


def fetch_quotes() -> List[Dict[str, Any]]:
    """Fetch Yahoo Finance prices for all configured symbols across books."""
    yahoo_symbols, _ = _collect_symbols_from_books()
    if not yahoo_symbols:
        return []

    results: List[Dict[str, Any]] = []
    # WHY: Use the first book's config structure to drive fetch_prices,
    # then supplement with any missing symbols from other books.
    for path in sorted(BOOKS_DIR.glob("*-graph.json")):
        try:
            cfg = thesisgraph.load_config(str(path))
            prices = thesisgraph.fetch_prices(cfg)
            for sym, price in prices.items():
                if isinstance(price, (int, float)):
                    results.append({"symbol": sym, "price": price, "source": "yahoo"})
                    yahoo_symbols.discard(sym)
        except Exception as e:
            log.warning("Price fetch failed for %s: %s", path.name, e)
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

        for inst in cfg.get("instruments", []):
            ticker = inst.get("ticker", "")
            if ticker and ticker not in seen:
                seen.add(ticker)
                items.append({
                    "symbol": ticker,
                    "label": inst.get("label", ticker),
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
