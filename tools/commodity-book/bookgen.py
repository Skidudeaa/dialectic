#!/usr/bin/env python3
"""
Active Commodity Book Generator

Transforms a JSON book configuration into a complete interactive HTML
trading dashboard with position tracking, P&L, trigger state machine,
auditable journal, and live price fetching via Yahoo Finance.

Usage:
    python3 bookgen.py config.json -o output.html
    python3 bookgen.py config.json -o output.html --fetch
    python3 bookgen.py config.json -o output.html --validate --screenshot --publish

WHY: The manual workflow to build an active commodity book involves
research, data extraction, HTML generation, validation, screenshot,
and publishing — 6+ distinct steps. This script collapses them into
one command with a declarative JSON config as the single source of truth.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# =========================================================================
# WALKTHROUGH — printed by `bookgen.py walkthrough`
# =========================================================================

WALKTHROUGH = r"""
ACTIVE COMMODITY BOOK GENERATOR — WALKTHROUGH
══════════════════════════════════════════════

WHAT IT DOES
  Takes a JSON config file describing a commodity investment thesis and
  generates a complete interactive HTML dashboard with:
  - Position tracking with P&L per instrument
  - 9-type escalation trigger state machine with date-tracked closes
  - SGOV deployment ledger
  - Auditable journal (trades, reviews, trigger events, notes)
  - Live price fetch via Yahoo Finance (allorigins CORS proxy)
  - Export/import/reset of all state

QUICK START
  1. Copy the example config:
     cp tools/commodity-book/iran-hormuz-2026.json my-book.json

  2. Edit my-book.json with your thesis (instruments, triggers, rules)

  3. Generate:
     python3 tools/commodity-book/bookgen.py my-book.json -o my-book.html

  4. Open my-book.html in a browser. Click "Fetch Live" for real-time prices.

PIPELINE FLAGS
  --fetch           Fetch live prices from Yahoo Finance before generating
  --validate        Run structural validator on output HTML
  --screenshot      Generate OG cover image via headless Chrome
  --publish         Publish to Reading Room (needs RR_PASSWORD env var)
  --update-config   Fetch prices and write them back INTO the JSON config
  --dry-run         Validate config and show summary, don't write HTML
  --force           Overwrite output file without asking

FULL PIPELINE EXAMPLE
  python3 tools/commodity-book/bookgen.py my-book.json \
    -o my-book.html --fetch --validate --screenshot --publish --username amo

JSON CONFIG SCHEMA
══════════════════

REQUIRED FIELDS:
  title           string    Book title shown in header
  monthlyBudget   integer   Total monthly deployment (e.g. 8000)
  instruments     array     Core portfolio instruments (see below)
  triggers        array     Escalation triggers (see below)
  rules           array     Execution rule strings (HTML OK)
  marketFields    array     Editable market data inputs (see below)

OPTIONAL FIELDS:
  subtitle        string    Description / instructions text
  claim           string    One-sentence thesis
  asOf            string    Reference date (ISO format)
  categories      object    Category name → {color, label}
  overlays        array     Conditional overlay instruments
  fetchSymbols    object    Yahoo Finance symbol mappings
  situationUpdate object    Current intelligence briefing
  provenance      object    Sources, methodology, limitations

INSTRUMENT SCHEMA:
  {
    "id": "XOP",              # Ticker symbol (unique)
    "monthly": 1400,          # $/month allocation
    "role": "High-beta E&P",  # Description
    "category": "producers",  # Must match a key in categories
    "ref": 188.18,            # Reference price (gap adjustment anchor)
    "targetLow": 210,         # Target range low (null if no target)
    "targetHigh": 225,        # Target range high
    "stop": 171,              # Stop loss level (null if no stop)
    "isReserve": false        # true for SGOV-like deployment ammo
  }

TRIGGER SCHEMA (numeric):
  {
    "id": "brent-per",        # Unique ID
    "name": "Brent Persistence",
    "metricKey": "brent",     # Must match a key in marketFields
    "operator": ">",          # ">" or "<"
    "threshold": 115,         # Numeric threshold
    "closesRequired": 3,      # Consecutive closes needed (optional)
    "action": "Deploy $400",  # What to do when triggered
    "detail": "...",          # Expanded instructions
    "context": "...",         # "How to read" explanation
    "isConstraint": false,    # true = blocks action rather than triggers it
    "isReversal": false       # true = de-escalation (inverted logic)
  }

TRIGGER SCHEMA (binary):
  {
    "id": "rigs",
    "name": "Rig Confirmation",
    "binaryKey": "rigsFlat",  # Toggle state key
    "action": "Open OIH",
    "detail": "...",
    "context": "..."
  }

OVERLAY SCHEMA:
  {
    "id": "oil-esc",
    "name": "Oil Escalation",
    "triggerIds": ["brent-per"],    # Which triggers unlock this
    "condition": "Brent > $115",    # Human-readable condition
    "instruments": [
      { "id": "OXY", "ref": 65.32, "targetLow": 72, "targetHigh": 76,
        "stop": 60, "note": "After confirmation" }
    ]
  }

MARKET FIELD SCHEMA:
  { "key": "brent", "label": "BRENT $/bbl", "value": 112.57, "step": 0.01 }

FETCH SYMBOLS (for --fetch and browser Fetch Live button):
  {
    "commodities": { "BZ=F": "brent", "CL=F": "wti", "GC=F": "goldSpot" },
    "instruments": ["XOP", "XLE", "GLD", "CF", "NTR"]
  }
  Yahoo symbol → marketFields key for commodities.
  Ticker list for instruments (must match instrument IDs).
"""


# =========================================================================
# CONFIG VALIDATION
# =========================================================================

REQUIRED_TOP = ["title", "monthlyBudget", "instruments", "triggers", "rules", "marketFields"]
REQUIRED_INST = ["id", "monthly", "role", "category", "ref"]
REQUIRED_TRIG = ["id", "name", "action", "detail", "context"]
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def load_config(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: config file not found: {path}", file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: invalid JSON in {path}: {e}", file=sys.stderr)
        sys.exit(1)


def validate_config(cfg: dict) -> tuple[list[str], list[str]]:
    """Validate config. Returns (errors, warnings)."""
    errors = []
    warnings = []

    # Required top-level fields
    for field in REQUIRED_TOP:
        if field not in cfg:
            errors.append(f"missing required field '{field}'")

    # Instruments
    if "instruments" in cfg:
        total = sum(i.get("monthly", 0) for i in cfg["instruments"])
        budget = cfg.get("monthlyBudget", 0)
        if total != budget:
            errors.append(f"allocations sum to ${total:,}, budget is ${budget:,}")

        seen_ids = set()
        for i, inst in enumerate(cfg["instruments"]):
            iid = inst.get("id", f"[{i}]")
            for f in REQUIRED_INST:
                if f not in inst:
                    errors.append(f"instrument {iid}: missing '{f}'")
            if iid in seen_ids:
                errors.append(f"instrument {iid}: duplicate ID")
            seen_ids.add(iid)
            if inst.get("ref", 0) <= 0:
                errors.append(f"instrument {iid}: ref price must be > 0")
            if inst.get("stop") and inst.get("targetLow"):
                if inst["stop"] >= inst["targetLow"]:
                    errors.append(f"instrument {iid}: stop ({inst['stop']}) >= targetLow ({inst['targetLow']})")
            if inst.get("monthly", 0) < 0:
                errors.append(f"instrument {iid}: monthly allocation must be >= 0")
            has_reserve = any(x.get("isReserve") for x in cfg["instruments"])
        if not has_reserve:
            warnings.append("no instrument marked isReserve — SGOV deployment tracking will not work")

    # Triggers
    if "triggers" in cfg:
        mkt_keys = {m["key"] for m in cfg.get("marketFields", [])}
        seen_tids = set()
        for i, t in enumerate(cfg["triggers"]):
            tid = t.get("id", f"[{i}]")
            for f in REQUIRED_TRIG:
                if f not in t:
                    errors.append(f"trigger {tid}: missing '{f}'")
            if tid in seen_tids:
                errors.append(f"trigger {tid}: duplicate ID")
            seen_tids.add(tid)

            has_metric = "metricKey" in t and "operator" in t
            has_binary = "binaryKey" in t
            if not has_metric and not has_binary:
                errors.append(f"trigger {tid}: needs metricKey+operator or binaryKey")
            if has_metric and t.get("metricKey") not in mkt_keys:
                errors.append(f"trigger {tid}: metricKey '{t['metricKey']}' not in marketFields")
            if has_metric and t.get("operator") not in (">", "<"):
                errors.append(f"trigger {tid}: operator must be '>' or '<'")
            if t.get("closesRequired") and not has_metric:
                warnings.append(f"trigger {tid}: closesRequired set on binary trigger (ignored)")

    # Overlays
    if "overlays" in cfg:
        trig_ids = {t["id"] for t in cfg.get("triggers", [])}
        for o in cfg.get("overlays", []):
            oid = o.get("id", "?")
            for tid in o.get("triggerIds", []):
                if tid not in trig_ids:
                    errors.append(f"overlay {oid}: references unknown trigger '{tid}'")
            if not o.get("instruments"):
                warnings.append(f"overlay {oid}: no instruments defined")

    # Categories
    if "categories" in cfg:
        inst_cats = {i.get("category") for i in cfg.get("instruments", [])}
        defined_cats = set(cfg["categories"].keys())
        missing = inst_cats - defined_cats
        if missing:
            errors.append(f"instruments reference undefined categories: {missing}")
        for name, cat in cfg["categories"].items():
            if "color" in cat and not HEX_RE.match(cat["color"]):
                errors.append(f"category '{name}': color '{cat['color']}' is not valid hex (#RRGGBB)")

    # Fetch symbols
    if "fetchSymbols" in cfg:
        inst_ids = {i["id"] for i in cfg.get("instruments", [])}
        ov_ids = set()
        for o in cfg.get("overlays", []):
            for i in o.get("instruments", []):
                ov_ids.add(i["id"])
        for sym in cfg["fetchSymbols"].get("instruments", []):
            if sym not in inst_ids and sym not in ov_ids:
                warnings.append(f"fetchSymbols: '{sym}' not found in instruments or overlays")

    return errors, warnings


# =========================================================================
# PRICE FETCHER
# =========================================================================

def fetch_prices(cfg: dict, retries: int = 2) -> dict:
    """Fetch current prices from Yahoo Finance with retry. Mutates and returns cfg."""
    fetch_cfg = cfg.get("fetchSymbols", {})
    commodity_map = fetch_cfg.get("commodities", {})
    inst_syms = fetch_cfg.get("instruments", [])
    all_syms = list(commodity_map.keys()) + inst_syms

    # Add curve calc symbols if configured
    curve_cfg = fetch_cfg.get("curveCalc")
    if curve_cfg:
        for k in ("front", "deferred"):
            sym = curve_cfg.get(k)
            if sym and sym not in all_syms:
                all_syms.append(sym)

    if not all_syms:
        print("  No fetchSymbols configured, skipping", file=sys.stderr)
        return cfg

    # WHY: Yahoo Finance blocks direct server-side requests (403/400).
    # Route through allorigins.win proxy — same path the browser uses.
    import urllib.parse
    # TRADEOFF: query1 is more reliable than query2 for server-side requests
    # via allorigins. Batch into groups of 8 to avoid URL length limits.
    yahoo_base = "https://query1.finance.yahoo.com/v7/finance/spark"
    batch_size = 8
    all_results = []

    for i in range(0, len(all_syms), batch_size):
        batch = all_syms[i:i + batch_size]
        yahoo_url = f"{yahoo_base}?symbols={','.join(batch)}&range=1d&interval=1d"
        proxy_url = f"https://api.allorigins.win/get?url={urllib.parse.quote(yahoo_url, safe='')}"

        for attempt in range(1, retries + 1):
            try:
                req = Request(proxy_url, headers={"User-Agent": "Mozilla/5.0"})
                with urlopen(req, timeout=20) as resp:
                    envelope = json.loads(resp.read())
                    batch_data = json.loads(envelope["contents"])
                    all_results.extend(batch_data.get("spark", {}).get("result", []))
                break
            except (URLError, TimeoutError, OSError) as e:
                if attempt < retries:
                    time.sleep(2)
                else:
                    print(f"  Batch {i // batch_size + 1} failed: {e}", file=sys.stderr)
            except Exception as e:
                print(f"  Batch {i // batch_size + 1} error: {e}", file=sys.stderr)
                break
        if i + batch_size < len(all_syms):
            time.sleep(1.5)  # Rate-limit courtesy between batches

    if not all_results:
        print("  Warning: no usable price data returned", file=sys.stderr)
        return cfg

    # Reassemble into the expected structure
    data = {"spark": {"result": all_results}}

    count = 0
    updated = []
    for item in data.get("spark", {}).get("result", []):
        sym = item["symbol"]
        meta = item.get("response", [{}])[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        if price is None:
            continue

        if sym in commodity_map:
            mkt_key = commodity_map[sym]
            for mf in cfg["marketFields"]:
                if mf["key"] == mkt_key:
                    old = mf["value"]
                    mf["value"] = round(price, 2)
                    updated.append(f"{mkt_key}: ${old} -> ${mf['value']}")
                    count += 1
        else:
            for inst in cfg["instruments"]:
                if inst["id"] == sym:
                    old = inst["ref"]
                    inst["ref"] = round(price, 2)
                    updated.append(f"{sym}: ${old} -> ${inst['ref']}")
                    count += 1
            for ov in cfg.get("overlays", []):
                for inst in ov.get("instruments", []):
                    if inst["id"] == sym:
                        inst["ref"] = round(price, 2)
                        count += 1

    missing = set(all_syms) - {item["symbol"] for item in data.get("spark", {}).get("result", [])}
    print(f"  Fetched {count}/{len(all_syms)} prices from Yahoo Finance")
    if missing:
        print(f"  Missing: {', '.join(sorted(missing))}", file=sys.stderr)

    # WHY: Auto-calculate Brent curve spread from front and deferred futures.
    # This replaces the manual curveSpread estimate with real market data.
    if curve_cfg:
        front_sym = curve_cfg.get("front")
        deferred_sym = curve_cfg.get("deferred")
        target_key = curve_cfg.get("targetKey", "curveSpread")
        fetched = {item["symbol"]: item["response"][0]["meta"].get("regularMarketPrice")
                   for item in data.get("spark", {}).get("result", []) if item.get("response")}
        front_price = fetched.get(front_sym)
        deferred_price = fetched.get(deferred_sym)
        if front_price and deferred_price and deferred_price > 0:
            spread = round((front_price - deferred_price) / deferred_price * 100, 1)
            for mf in cfg["marketFields"]:
                if mf["key"] == target_key:
                    old = mf["value"]
                    mf["value"] = spread
                    print(f"  Curve spread: {front_sym} ${front_price:.2f} / {deferred_sym} ${deferred_price:.2f} = {spread}% (was {old}%)")

    return cfg


def update_config_file(config_path: str, cfg: dict) -> None:
    """Write fetched prices back into the JSON config file."""
    with open(config_path, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"  Config updated: {config_path}")


# =========================================================================
# DATA TRANSFORM (config JSON → compact JS format)
# =========================================================================

def inst_to_js(inst: dict) -> dict:
    """Config instrument → compact JS object."""
    d = {
        "id": inst["id"],
        "mo": inst["monthly"],
        "role": inst["role"],
        "cat": inst["category"],
        "ref": inst["ref"],
        "tL": inst.get("targetLow"),
        "tH": inst.get("targetHigh"),
        "stp": inst.get("stop"),
    }
    if inst.get("isReserve"):
        d["rsv"] = 1
    return d


def trig_to_js(t: dict) -> dict:
    """Config trigger → compact JS object."""
    d = {"id": t["id"], "nm": t["name"], "act": t["action"], "det": t["detail"], "htr": t["context"]}
    if "metricKey" in t:
        d["mk"] = t["metricKey"]
    if "operator" in t:
        d["op"] = t["operator"]
    if "threshold" in t:
        d["th"] = t["threshold"]
    if "closesRequired" in t:
        d["cls"] = t["closesRequired"]
    if "binaryKey" in t:
        d["bin"] = t["binaryKey"]
    if t.get("isConstraint"):
        d["cstr"] = 1
    if t.get("isReversal"):
        d["rvs"] = 1
    if "altMetric" in t:
        d["alt"] = {"mk": t["altMetric"]["key"], "th": t["altMetric"]["threshold"]}
    return d


def overlay_to_js(o: dict) -> dict:
    """Config overlay → compact JS object."""
    insts = []
    for i in o.get("instruments", []):
        d = {"id": i["id"], "ref": i["ref"], "tL": i["targetLow"], "tH": i["targetHigh"], "stp": i["stop"]}
        if "note" in i:
            d["note"] = i["note"]
        insts.append(d)
    return {
        "id": o["id"],
        "nm": o["name"],
        "trig": o["triggerIds"],
        "cond": o["condition"],
        "insts": insts,
    }


def mkt_to_js(m: dict) -> dict:
    """Config market field → compact JS object."""
    return {"k": m["key"], "lbl": m["label"], "v": m["value"], "step": m["step"]}


# =========================================================================
# HTML GENERATION
# =========================================================================

def build_category_css(cats: dict) -> str:
    """Generate CSS custom properties for categories."""
    lines = []
    for name, cfg in cats.items():
        lines.append(f"  --c-{name}:{cfg['color']};")
    return "\n".join(lines)


def build_cats_js(cats: dict) -> str:
    """Generate JS category→CSS var mapping."""
    entries = [f"{k}:'var(--c-{k})'" for k in cats]
    return "{" + ",".join(entries) + "}"


def build_defaults_js(cfg: dict) -> str:
    """Generate the DEFAULTS object for initial book state."""
    market = {mf["key"]: mf["value"] for mf in cfg["marketFields"]}
    binaries = {}
    for t in cfg["triggers"]:
        if "binaryKey" in t:
            binaries[t["binaryKey"]] = False

    init_note = f"Book initialized. {cfg.get('claim', '')}".replace("'", "\\'")
    today = datetime.now().strftime("%Y-%m-%d")

    return json.dumps({
        "v": 2,
        "market": market,
        "prices": {},
        "positions": {},
        "trigSt": {},
        "sgov": {"budget": next((i["monthly"] for i in cfg["instruments"] if i.get("isReserve")), 0), "ledger": []},
        "journal": [{"id": 1, "date": today, "type": "setup", "text": init_note}],
        "binary": binaries,
        "ui": {"tab": "dash", "jFilt": "all", "expanded": []},
    }, separators=(",", ":"))


def build_fetch_syms_js(cfg: dict) -> str:
    """Generate the fetch symbol arrays for the browser-side fetch function."""
    fc = cfg.get("fetchSymbols", {})
    commodity_map = fc.get("commodities", {})
    inst_syms = fc.get("instruments", [])
    all_syms = list(commodity_map.keys()) + inst_syms
    map_js = json.dumps(commodity_map, separators=(",", ":"))
    syms_js = json.dumps(all_syms, separators=(",", ":"))
    return f"const FETCH_MAP={map_js};\nconst FETCH_SYMS={syms_js};"


def build_situation_html(cfg: dict) -> str:
    """Generate the situation update HTML."""
    su = cfg.get("situationUpdate")
    if not su:
        return ""
    date = su.get("date", "")
    lines = [f"<h3>Situation Update ({date})</h3>"]
    for sec in su.get("sections", []):
        lines.append(f'<p><strong>{sec["label"]}:</strong> {sec["text"]}</p>')
    return "\n  ".join(lines)


def build_provenance_html(cfg: dict) -> str:
    """Generate provenance footer content."""
    p = cfg.get("provenance", {})
    parts = []
    for key, label in [("sources", "Sources"), ("methodology", "Methodology"),
                        ("limitations", "Limitations")]:
        if key in p:
            parts.append(f"<h3>{label}</h3>\n  <p>{p[key]}</p>")
    if "disclaimer" in p:
        parts.append(f'<p class="disc">{p["disclaimer"]}</p>')
    return "\n  ".join(parts)


def generate_html(cfg: dict) -> str:
    """Generate the complete active commodity book HTML from config."""
    title = cfg["title"]
    budget = cfg["monthlyBudget"]
    claim = cfg.get("claim", "")
    subtitle = cfg.get("subtitle", "")

    cats_css = build_category_css(cfg.get("categories", {}))
    cats_js = build_cats_js(cfg.get("categories", {}))
    insts_js = json.dumps([inst_to_js(i) for i in cfg["instruments"]], separators=(",", ":"))
    trigs_js = json.dumps([trig_to_js(t) for t in cfg["triggers"]], separators=(",", ":"))
    overlays_js = json.dumps([overlay_to_js(o) for o in cfg.get("overlays", [])], separators=(",", ":"))
    rules_js = json.dumps(cfg["rules"])
    mkt_js = json.dumps([mkt_to_js(m) for m in cfg["marketFields"]], separators=(",", ":"))
    defaults_js = build_defaults_js(cfg)
    fetch_js = build_fetch_syms_js(cfg)
    situation_html = build_situation_html(cfg)
    provenance_html = build_provenance_html(cfg)

    # WHY: Using .replace() with unique markers instead of f-strings because
    # the template contains hundreds of literal curly braces (CSS + JS).
    html = get_template()
    replacements = {
        "__TITLE__": title,
        "__SUBTITLE__": subtitle,
        "__BUDGET__": str(budget),
        "__BUDGET_FMT__": f"{budget:,}",
        "__CLAIM__": claim,
        "__CATS_CSS__": cats_css,
        "__CATS_JS__": cats_js,
        "__INSTS_JS__": insts_js,
        "__TRIGS_JS__": trigs_js,
        "__OVERLAYS_JS__": overlays_js,
        "__RULES_JS__": rules_js,
        "__MKT_JS__": mkt_js,
        "__DEFAULTS_JS__": defaults_js,
        "__FETCH_JS__": fetch_js,
        "__SITUATION__": situation_html,
        "__PROVENANCE__": provenance_html,
    }
    for marker, value in replacements.items():
        html = html.replace(marker, value)

    return html


# =========================================================================
# PIPELINE INTEGRATION
# =========================================================================

def find_skill_script(name: str) -> str | None:
    """Locate an infographic-gen skill script."""
    candidates = [
        Path(__file__).parent.parent.parent / ".." / ".claude" / "skills" / "infographic-gen" / "scripts" / name,
        Path.home() / ".claude" / "skills" / "infographic-gen" / "scripts" / name,
    ]
    for p in candidates:
        resolved = p.resolve()
        if resolved.is_file():
            return str(resolved)
    return None


def run_validate(html_path: str) -> bool:
    script = find_skill_script("validate.py")
    if not script:
        print("  Warning: validate.py not found, skipping validation", file=sys.stderr)
        return True
    result = subprocess.run([sys.executable, script, html_path], capture_output=True, text=True, timeout=30)
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)
    return result.returncode == 0


def run_screenshot(html_path: str, output_dir: str = ".") -> str | None:
    script = find_skill_script("screenshot.py")
    if not script:
        print("  Warning: screenshot.py not found, skipping", file=sys.stderr)
        return None
    base = Path(html_path).stem
    out = str(Path(output_dir) / f"{base}-og.png")
    result = subprocess.run(
        [sys.executable, script, html_path, "--crop-hero", "--output", out],
        capture_output=True, text=True, timeout=20,
    )
    if result.returncode == 0 and os.path.isfile(out):
        print(f"  Screenshot: {out}")
        return out
    print(f"  Warning: screenshot failed: {result.stderr}", file=sys.stderr)
    return None


def run_publish(html_path: str, cfg: dict, args) -> None:
    script = find_skill_script("publish.py")
    if not script:
        print("  Error: publish.py not found", file=sys.stderr)
        return

    cmd = [
        sys.executable, script, html_path,
        "--title", cfg["title"],
        "--subtitle", cfg.get("subtitle", ""),
        "--category", args.category or "ANALYSIS",
        "--publish",
        "--username", args.username or "admin",
        "--api-url", args.api_url or "http://127.0.0.1:8100",
    ]
    if args.slug:
        cmd.extend(["--slug", args.slug])

    env = os.environ.copy()
    result = subprocess.run(cmd, env=env, capture_output=False, text=True, timeout=30)


# =========================================================================
# HTML TEMPLATE
# =========================================================================

def get_template() -> str:
    """Return the complete HTML template with __PLACEHOLDER__ markers.

    WHY: The template is the full working HTML from the active commodity book,
    with data constants replaced by markers. The JS logic (calculations,
    renders, events) is identical for every book — only the data arrays change.
    """
    return r"""<!--
  __CLAIM__
-->
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>__TITLE__</title>
<meta name="description" content="__SUBTITLE__">
<meta property="og:title" content="__TITLE__">
<meta property="og:description" content="__SUBTITLE__">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{--bg0:#120C06;--bg1:#160E08;--s0:rgba(255,255,255,.04);--s1:rgba(255,255,255,.06);--s2:rgba(255,255,255,.09);--b0:rgba(255,255,255,.05);--b1:rgba(255,255,255,.085);--r-sm:6px;--r-md:14px;--r-pill:20px;--sp-1:4px;--sp-2:8px;--sp-3:12px;--sp-4:16px;--sp-6:24px;--sp-8:32px;--e-out:cubic-bezier(.22,1,.36,1);--dur-fast:.2s;--dur-med:.35s;--t1:#FFF7EE;--t2:rgba(255,247,238,.72);--t3:rgba(255,247,238,.50);--t4:rgba(255,247,238,.38);--font-display:'Outfit',system-ui,sans-serif;--font-mono:'JetBrains Mono','Fira Code',monospace;
__CATS_CSS__
--c-up:#4CC4B4;--c-dn:#C44C4C;--c-warn:#E69A4C;--c-cstr:#AD7FA8}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}html{scroll-behavior:smooth}body{background:linear-gradient(180deg,var(--bg0),var(--bg1));background-attachment:fixed;color:var(--t1);font-family:var(--font-display);font-size:14px;line-height:1.5;min-height:100vh;-webkit-font-smoothing:antialiased}::-webkit-scrollbar{width:6px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:var(--b1);border-radius:3px}a.skip-link{position:absolute;top:-60px;left:var(--sp-4);background:var(--bg1);color:var(--t1);padding:var(--sp-2) var(--sp-4);border-radius:var(--r-sm);font-family:var(--font-mono);font-size:12px;z-index:999;text-decoration:none;border:1px solid var(--b1);transition:top var(--dur-fast) var(--e-out)}a.skip-link:focus{top:var(--sp-2);outline:2px solid var(--c-warn)}.page{max-width:1200px;margin:0 auto;padding:0 var(--sp-4) var(--sp-8)}.app-hdr{position:sticky;top:0;z-index:100;background:var(--bg0);border-bottom:1px solid var(--b0);padding:var(--sp-3) var(--sp-4) 0;max-width:1200px;margin:0 auto}.hdr-row{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:var(--sp-2);flex-wrap:wrap;gap:var(--sp-2)}.hdr-title{font-size:18px;font-weight:800}.hdr-title .mono{font-family:var(--font-mono);color:var(--c-warn)}.hdr-regime{font-family:var(--font-mono);font-size:12px;display:flex;align-items:center;gap:var(--sp-2)}.regime-tag{padding:2px 10px;border-radius:var(--r-pill);font-weight:700;font-size:11px;letter-spacing:1px}.hdr-export{display:flex;gap:var(--sp-2);align-items:center;flex-wrap:wrap}.btn-sm{font-family:var(--font-mono);font-size:11px;padding:4px 10px;border:1px solid var(--b1);border-radius:var(--r-sm);background:var(--s0);color:var(--t3);cursor:pointer;transition:all var(--dur-fast)}.btn-sm:hover{background:var(--s2);color:var(--t1)}.tab-bar{display:flex;gap:var(--sp-1);padding-bottom:var(--sp-2);overflow-x:auto}.tab-btn{font-family:var(--font-mono);font-size:12px;font-weight:600;letter-spacing:1px;padding:var(--sp-2) var(--sp-4);border:none;border-bottom:2px solid transparent;background:none;color:var(--t4);cursor:pointer;transition:all var(--dur-fast)}.tab-btn:hover{color:var(--t2)}.tab-btn.active{color:var(--t1);border-bottom-color:var(--c-warn)}.tab-pane{display:none;padding-top:var(--sp-6)}.tab-pane.active{display:block}.sec-label{font-family:var(--font-mono);font-size:11px;font-weight:600;letter-spacing:2.5px;text-transform:uppercase;color:var(--t4);margin-bottom:var(--sp-4);display:flex;align-items:center;gap:var(--sp-2)}.sec-label::after{content:'';flex:1;height:1px;background:var(--b0)}.g3{display:grid;grid-template-columns:repeat(3,1fr);gap:var(--sp-4)}.g2{display:grid;grid-template-columns:repeat(2,1fr);gap:var(--sp-4)}.stats-bar{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:var(--sp-3);margin-bottom:var(--sp-6)}.stat-card{background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-md);padding:var(--sp-3) var(--sp-4);text-align:center}.stat-val{font-family:var(--font-mono);font-size:22px;font-weight:700;line-height:1.2}.stat-lbl{font-family:var(--font-mono);font-size:11px;letter-spacing:1.5px;color:var(--t4);margin-top:2px}.pl-up{color:var(--c-up)}.pl-dn{color:var(--c-dn)}.pl-flat{color:var(--t3)}.action-panel{background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-md);padding:var(--sp-4) var(--sp-6);margin-bottom:var(--sp-6)}.ap-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:var(--sp-3)}.ap-title{font-family:var(--font-mono);font-size:11px;font-weight:600;letter-spacing:2px;text-transform:uppercase;color:var(--t3)}.ap-date{font-family:var(--font-mono);font-size:11px;color:var(--t4)}.act-list{list-style:none}.act-item{display:flex;align-items:flex-start;gap:var(--sp-3);padding:var(--sp-2) 0;border-bottom:1px solid var(--b0);font-size:13px}.act-item:last-child{border-bottom:none}.act-badge{font-family:var(--font-mono);font-size:11px;font-weight:700;letter-spacing:1px;padding:2px 8px;border-radius:var(--r-sm);white-space:nowrap;min-width:60px;text-align:center;flex-shrink:0}.b-act{background:rgba(76,196,180,.15);color:var(--c-up)}.b-watch{background:rgba(230,154,76,.15);color:var(--c-warn)}.b-hold{background:rgba(255,247,238,.06);color:var(--t3)}.b-block{background:rgba(196,76,76,.12);color:var(--c-dn)}.act-text{color:var(--t2)}.act-text strong{color:var(--t1);font-weight:600}.act-next{font-family:var(--font-mono);font-size:11px;color:var(--t4);padding-top:var(--sp-3);margin-top:var(--sp-2);border-top:1px solid var(--b0)}.metrics-bar{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:var(--sp-3);padding:var(--sp-4);background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-md);margin-bottom:var(--sp-6)}.m-item{text-align:center}.m-lbl{font-family:var(--font-mono);font-size:11px;font-weight:500;letter-spacing:1px;color:var(--t4);display:block;margin-bottom:2px}.m-inp{font-family:var(--font-mono);font-size:15px;font-weight:700;color:var(--t1);background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-sm);padding:3px var(--sp-2);width:100%;max-width:110px;text-align:center}.m-inp:focus{outline:none;border-color:var(--c-warn);background:var(--s1)}.i-card{background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-md);padding:var(--sp-4);position:relative;overflow:hidden;transition:border-color var(--dur-fast)}.i-card:hover{border-color:var(--b1)}.i-card::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;border-radius:var(--r-md) var(--r-md) 0 0}.i-head{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:2px}.i-ticker{font-family:var(--font-mono);font-size:17px;font-weight:700}.i-alloc{font-family:var(--font-mono);font-size:12px;color:var(--t2)}.i-alloc .pct{font-size:11px;color:var(--t4);margin-left:var(--sp-1)}.i-role{font-size:12px;color:var(--t3);margin-bottom:var(--sp-2)}.pos-summary{font-family:var(--font-mono);font-size:12px;padding:var(--sp-2) var(--sp-3);background:var(--s1);border-radius:var(--r-sm);margin-bottom:var(--sp-3)}.pos-row{display:flex;justify-content:space-between;padding:1px 0}.pos-row .lbl{color:var(--t3)}.pos-row .val{font-weight:600}.pos-empty{font-size:12px;color:var(--t4);font-style:italic;margin-bottom:var(--sp-3)}.price-row{display:flex;align-items:center;gap:var(--sp-2);margin-bottom:var(--sp-2)}.p-lbl{font-family:var(--font-mono);font-size:11px;color:var(--t4)}.p-inp{font-family:var(--font-mono);font-size:13px;font-weight:600;color:var(--t1);background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-sm);padding:2px var(--sp-2);width:85px;text-align:right}.p-inp:focus{outline:none;border-color:var(--c-warn);background:var(--s1)}.p-adj{font-family:var(--font-mono);font-size:11px;color:var(--c-warn);margin-left:auto}.range-bar{margin-bottom:var(--sp-1)}.r-track{position:relative;height:5px;background:rgba(255,255,255,.06);border-radius:3px}.r-fill{position:absolute;top:0;left:0;bottom:0;border-radius:3px;transition:width var(--dur-med) var(--e-out)}.r-mark{position:absolute;top:50%;width:10px;height:10px;border-radius:50%;transform:translate(-50%,-50%);border:2px solid var(--t1);z-index:2;transition:left var(--dur-med) var(--e-out)}.r-labels{display:flex;justify-content:space-between;font-family:var(--font-mono);font-size:11px;margin-top:2px}.r-labels .stp{color:var(--c-dn)}.r-labels .tgt{color:var(--c-up)}.r-metrics{display:flex;justify-content:space-between;font-family:var(--font-mono);font-size:11px;margin-top:1px}.r-metrics .up{color:var(--c-up)}.r-metrics .rr{color:var(--t3)}.r-metrics .dn{color:var(--t4)}.sgov-meter{margin-top:var(--sp-2)}.sgov-track{height:7px;background:rgba(110,143,173,.15);border-radius:4px;overflow:hidden}.sgov-fill{height:100%;background:var(--c-up);border-radius:4px;transition:width var(--dur-med) var(--e-out)}.sgov-labels{display:flex;justify-content:space-between;font-family:var(--font-mono);font-size:11px;color:var(--t3);margin-top:2px}.pos-form{display:none;padding:var(--sp-3);background:var(--s1);border-radius:var(--r-sm);margin-top:var(--sp-2)}.pos-form.open{display:block}.pf-row{display:flex;gap:var(--sp-2);margin-bottom:var(--sp-2);flex-wrap:wrap}.pf-inp{font-family:var(--font-mono);font-size:12px;padding:4px var(--sp-2);background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-sm);color:var(--t1);min-width:0}.pf-inp:focus{outline:none;border-color:var(--c-warn)}.pf-inp.w-date{width:120px}.pf-inp.w-num{width:80px}.pf-inp.w-note{flex:1;min-width:120px}select.pf-inp{appearance:none;padding-right:20px;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%23FFF7EE' d='M3 5l3 3 3-3'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 6px center}.pf-btns{display:flex;gap:var(--sp-2)}.btn-add{font-family:var(--font-mono);font-size:11px;font-weight:700;padding:4px 12px;border:none;border-radius:var(--r-sm);cursor:pointer;transition:all var(--dur-fast)}.btn-add.primary{background:var(--c-up);color:var(--bg0)}.btn-add.primary:hover{filter:brightness(1.1)}.btn-add.ghost{background:transparent;border:1px solid var(--b1);color:var(--t3)}.btn-add.ghost:hover{color:var(--t1)}.btn-open-form{font-family:var(--font-mono);font-size:11px;color:var(--t4);background:none;border:1px dashed var(--b0);border-radius:var(--r-sm);padding:4px 10px;cursor:pointer;margin-top:var(--sp-2);width:100%;transition:all var(--dur-fast)}.btn-open-form:hover{border-color:var(--b1);color:var(--t2)}.lot-list{margin-top:var(--sp-2)}.lot-row{display:grid;grid-template-columns:72px 1fr 1fr auto;gap:var(--sp-1);padding:2px 0;border-bottom:1px solid var(--b0);font-family:var(--font-mono);font-size:11px;color:var(--t3);align-items:center}.lot-row:last-child{border-bottom:none}.lot-date{color:var(--t4)}.lot-buy{color:var(--c-up)}.lot-sell{color:var(--c-dn)}.t-card{background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-md);padding:var(--sp-4);border-left:3px solid var(--t4);transition:all var(--dur-fast)}.t-card:hover{background:var(--s1)}.t-card.st-appr{border-left-color:var(--c-warn)}.t-card.st-trig{border-left-color:var(--c-up);background:rgba(76,196,180,.03)}.t-card.st-cstr{border-left-color:var(--c-cstr)}.t-card.st-rev{border-left-color:var(--c-dn)}.t-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:var(--sp-2)}.t-name{font-weight:700;font-size:14px}.t-badge{font-family:var(--font-mono);font-size:11px;font-weight:700;letter-spacing:1px;padding:2px 8px;border-radius:var(--r-sm)}.bg-mon{background:rgba(255,247,238,.06);color:var(--t4)}.bg-appr{background:rgba(230,154,76,.15);color:var(--c-warn)}.bg-trig{background:rgba(76,196,180,.15);color:var(--c-up)}.bg-cstr{background:rgba(173,127,168,.12);color:var(--c-cstr)}.t-metric{display:flex;align-items:center;gap:var(--sp-2);margin-bottom:var(--sp-2);font-family:var(--font-mono);font-size:12px}.t-metric .lbl{color:var(--t3)}.t-metric .val{font-weight:600;font-size:14px}.t-metric .thr{color:var(--t4);margin-left:auto}.prog-wrap{display:flex;align-items:center;gap:var(--sp-2);margin-bottom:var(--sp-2)}.prog-track{flex:1;height:4px;background:rgba(255,255,255,.06);border-radius:2px;overflow:hidden}.prog-fill{height:100%;border-radius:2px;transition:width var(--dur-med) var(--e-out)}.prog-pct{font-family:var(--font-mono);font-size:11px;color:var(--t3);min-width:42px;text-align:right}.close-log{margin-bottom:var(--sp-2)}.cl-head{display:flex;align-items:center;gap:var(--sp-2);margin-bottom:var(--sp-1)}.cl-count{font-family:var(--font-mono);font-size:12px;font-weight:600}.cl-req{font-family:var(--font-mono);font-size:11px;color:var(--t4)}.btn-log-close{font-family:var(--font-mono);font-size:11px;padding:3px 8px;border:1px solid var(--c-up);border-radius:var(--r-sm);background:transparent;color:var(--c-up);cursor:pointer;margin-left:auto;transition:all var(--dur-fast)}.btn-log-close:hover{background:rgba(76,196,180,.1)}.cl-dates{font-family:var(--font-mono);font-size:11px;color:var(--t4)}.toggle-row{display:flex;align-items:center;gap:var(--sp-3);margin-bottom:var(--sp-2)}.tgl{position:relative;width:40px;height:22px;flex-shrink:0}.tgl input{opacity:0;width:0;height:0;position:absolute}.tgl-trk{position:absolute;inset:0;background:rgba(255,255,255,.08);border-radius:11px;cursor:pointer;transition:background var(--dur-fast)}.tgl-trk::after{content:'';position:absolute;top:2px;left:2px;width:18px;height:18px;background:var(--t3);border-radius:50%;transition:transform var(--dur-fast) var(--e-out),background var(--dur-fast)}.tgl input:checked+.tgl-trk{background:rgba(76,196,180,.3)}.tgl input:checked+.tgl-trk::after{transform:translateX(18px);background:var(--c-up)}.tgl input:focus-visible+.tgl-trk{outline:2px solid var(--c-warn);outline-offset:2px}.tgl-txt{font-size:12px;color:var(--t3)}.t-action{margin-top:var(--sp-2);padding:var(--sp-3);border-radius:var(--r-sm);display:none}.t-action.vis{display:block;background:rgba(76,196,180,.05);border:1px solid rgba(76,196,180,.15)}.t-action.vis-c{display:block;background:rgba(173,127,168,.05);border:1px solid rgba(173,127,168,.15)}.t-action.vis-r{display:block;background:rgba(196,76,76,.05);border:1px solid rgba(196,76,76,.15)}.ta-label{font-family:var(--font-mono);font-size:11px;font-weight:700;letter-spacing:1.5px;display:block;margin-bottom:2px}.ta-label.act{color:var(--c-up)}.ta-label.cst{color:var(--c-cstr)}.ta-label.rev{color:var(--c-dn)}.ta-text{font-size:13px;font-weight:600;display:block;margin-bottom:2px}.ta-detail{font-size:12px;color:var(--t3)}.htr-btn{font-family:var(--font-mono);font-size:11px;color:var(--t4);background:none;border:none;cursor:pointer;padding:var(--sp-1) 0;margin-top:var(--sp-1)}.htr-btn:hover{color:var(--t2)}.htr{font-size:12px;color:var(--t3);line-height:1.5;padding-top:var(--sp-2);display:none}.htr.open{display:block}.o-card{background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-md);padding:var(--sp-4);position:relative;transition:all var(--dur-med) var(--e-out)}.o-card.locked{opacity:.5}.o-card.unlocked{opacity:1;border-color:var(--b1)}.o-lock{font-family:var(--font-mono);font-size:11px;font-weight:700;letter-spacing:1px;padding:2px 8px;border-radius:var(--r-sm);position:absolute;top:var(--sp-3);right:var(--sp-3)}.lk-on{background:rgba(255,247,238,.06);color:var(--t4)}.lk-off{background:rgba(76,196,180,.15);color:var(--c-up)}.o-name{font-weight:700;font-size:15px;margin-bottom:var(--sp-1)}.o-trig{font-size:12px;color:var(--t3);margin-bottom:var(--sp-3)}.oi-row{display:grid;grid-template-columns:55px 1fr 1fr 1fr;gap:var(--sp-2);padding:var(--sp-2) 0;border-bottom:1px solid var(--b0);font-family:var(--font-mono);font-size:12px;align-items:center}.oi-row:last-child{border-bottom:none}.oi-tk{font-weight:700}.oi-tgt{color:var(--c-up)}.oi-stp{color:var(--c-dn)}.o-note{font-size:11px;color:var(--t4);margin-top:var(--sp-2);font-style:italic}.j-form{display:flex;gap:var(--sp-2);padding:var(--sp-4);background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-md);margin-bottom:var(--sp-4);flex-wrap:wrap;align-items:flex-end}.j-form label{display:flex;flex-direction:column;gap:2px;font-family:var(--font-mono);font-size:11px;color:var(--t4)}.j-inp{font-family:var(--font-mono);font-size:12px;padding:4px var(--sp-2);background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-sm);color:var(--t1)}.j-inp:focus{outline:none;border-color:var(--c-warn)}.j-note{flex:1;min-width:200px}.j-filters{display:flex;gap:var(--sp-2);margin-bottom:var(--sp-4);flex-wrap:wrap}.j-filt{font-family:var(--font-mono);font-size:11px;padding:4px 10px;border:1px solid var(--b0);border-radius:var(--r-pill);background:none;color:var(--t4);cursor:pointer;transition:all var(--dur-fast)}.j-filt:hover{color:var(--t2)}.j-filt.active{border-color:var(--c-warn);color:var(--t1);background:rgba(230,154,76,.08)}.j-entry{display:flex;gap:var(--sp-3);padding:var(--sp-3) 0;border-bottom:1px solid var(--b0)}.j-entry:last-child{border-bottom:none}.j-date{font-family:var(--font-mono);font-size:11px;color:var(--t4);min-width:68px;flex-shrink:0}.j-type{font-family:var(--font-mono);font-size:11px;font-weight:700;min-width:56px;flex-shrink:0;text-transform:uppercase;letter-spacing:.5px}.j-type.trade{color:var(--c-warn)}.j-type.review{color:var(--c-up)}.j-type.trigger{color:var(--c-up)}.j-type.note{color:var(--t3)}.j-type.setup{color:var(--c-cstr)}.j-empty{font-size:13px;color:var(--t4);text-align:center;padding:var(--sp-8)}.prov{background:var(--s0);border:1px solid var(--b0);border-radius:var(--r-md);padding:var(--sp-4) var(--sp-6);font-size:12px;color:var(--t3);line-height:1.6;margin-top:var(--sp-8)}.prov h3{font-family:var(--font-mono);font-size:11px;font-weight:600;letter-spacing:2px;text-transform:uppercase;color:var(--t4);margin:var(--sp-3) 0 var(--sp-2)}.prov h3:first-child{margin-top:0}.prov p{margin-bottom:var(--sp-2)}.prov .disc{margin-top:var(--sp-4);padding-top:var(--sp-3);border-top:1px solid var(--b0);font-weight:600;color:var(--t4)}.rules{list-style:none;counter-reset:rule}.rule{counter-increment:rule;display:flex;gap:var(--sp-3);padding:var(--sp-3) 0;border-bottom:1px solid var(--b0);font-size:13px;color:var(--t2)}.rule:last-child{border-bottom:none}.rule-n{font-family:var(--font-mono);font-size:12px;font-weight:700;color:var(--t4);min-width:24px;flex-shrink:0}.rule strong{color:var(--t1);font-weight:600}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border-width:0}
@media print{body{background:#fff;color:#1a1a1a}.page{max-width:100%;padding:0}.app-hdr{position:static}.i-card,.t-card,.o-card,.action-panel,.prov,.stat-card{background:#f8f6f4;border-color:#ddd;break-inside:avoid}.t-action{display:block!important;background:#f0f8f6;border-color:#ccc}.htr{display:block!important}.o-card.locked{opacity:.7}.btn-sm,.btn-open-form,.btn-log-close,.tgl,.htr-btn,.j-form,.j-filters,.tab-bar{display:none!important}.tab-pane{display:block!important}.p-inp,.m-inp{border:1px solid #ccc;color:#1a1a1a;background:#fff}.r-fill{print-color-adjust:exact;-webkit-print-color-adjust:exact}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;transition-duration:.01ms!important}html{scroll-behavior:auto}}
@media(max-width:900px){.g3{grid-template-columns:repeat(2,1fr)}.stats-bar{grid-template-columns:repeat(2,1fr)}}
@media(max-width:600px){.page{padding:0 var(--sp-3) var(--sp-8)}.g3,.g2{grid-template-columns:1fr}.stats-bar{grid-template-columns:1fr}.hdr-row{flex-wrap:wrap;gap:var(--sp-2)}.metrics-bar{grid-template-columns:repeat(2,1fr)}.j-form{flex-direction:column}.oi-row{grid-template-columns:50px 1fr 1fr}.oi-stp{display:none}}
</style>
</head>
<body>
<a href="#dash" class="skip-link">Skip to dashboard</a>
<header class="app-hdr">
  <div class="hdr-row">
    <div class="hdr-title">__TITLE__ <span class="mono">$__BUDGET_FMT__</span>/mo</div>
    <div class="hdr-regime" id="regime-display"></div>
    <div class="hdr-export">
      <button class="btn-sm" id="btn-fetch" style="border-color:var(--c-up);color:var(--c-up)">Fetch Live</button>
      <button class="btn-sm" id="btn-export">Export</button>
      <button class="btn-sm" id="btn-reset">Reset</button>
      <label class="btn-sm" style="cursor:pointer">Import<input type="file" accept=".json" id="btn-import" style="display:none"></label>
    </div>
  </div>
  <nav class="tab-bar" role="tablist">
    <button class="tab-btn active" data-tab="dash" role="tab">Dashboard</button>
    <button class="tab-btn" data-tab="book" role="tab">Book</button>
    <button class="tab-btn" data-tab="triggers" role="tab">Triggers</button>
    <button class="tab-btn" data-tab="journal" role="tab">Journal</button>
  </nav>
</header>
<div class="page">
<section class="tab-pane active" id="dash">
  <div class="stats-bar" id="stats-bar"></div>
  <div class="action-panel" id="action-panel"></div>
  <div class="sec-label">Market Data</div>
  <div class="metrics-bar" id="metrics-bar"></div>
  <div class="sec-label">Execution Rules</div>
  <ol class="rules" id="rules-list"></ol>
</section>
<section class="tab-pane" id="book">
  <div class="sec-label">Core Portfolio</div>
  <div class="g3" id="inst-grid"></div>
  <div class="sec-label" style="margin-top:var(--sp-8)">Triggered Overlays</div>
  <div class="g2" id="overlay-grid"></div>
</section>
<section class="tab-pane" id="triggers">
  <div class="sec-label">Escalation Dashboard</div>
  <div class="g2" id="trigger-grid"></div>
</section>
<section class="tab-pane" id="journal">
  <div class="j-form" id="j-form">
    <label>Type<select class="j-inp" id="j-type"><option value="note">Note</option><option value="trade">Trade</option><option value="review">Review</option><option value="trigger">Trigger</option></select></label>
    <label>Date<input type="date" class="j-inp" id="j-date"></label>
    <label class="j-note">Entry<input type="text" class="j-inp" id="j-note" placeholder="What happened?"></label>
    <button class="btn-add primary" id="j-add">Log</button>
  </div>
  <div class="j-filters" id="j-filters"></div>
  <div id="j-list"></div>
</section>
<footer class="prov">
  __SITUATION__
  __PROVENANCE__
</footer>
</div>
<script>
const TOTAL=__BUDGET__;
const CATS=__CATS_JS__;
const INSTS=__INSTS_JS__;
const TRIGS=__TRIGS_JS__;
const OVERLAYS=__OVERLAYS_JS__;
const RULES=__RULES_JS__;
const MKT_FIELDS=__MKT_JS__;
__FETCH_JS__
const DEFAULTS=__DEFAULTS_JS__;
""" + JS_LOGIC + """
</script>
</body>
</html>"""


# =========================================================================
# STATIC JS LOGIC (identical for every commodity book)
# =========================================================================

JS_LOGIC = r"""
let B;
function initPrices(b){INSTS.forEach(i=>{if(!b.prices[i.id])b.prices[i.id]=i.ref});OVERLAYS.forEach(o=>o.insts.forEach(i=>{if(!b.prices[i.id])b.prices[i.id]=i.ref}))}
function load(){try{const r=localStorage.getItem('acb2');if(r){B=JSON.parse(r);if(!B.v||B.v<2){B=JSON.parse(JSON.stringify(DEFAULTS))}}else{B=JSON.parse(JSON.stringify(DEFAULTS))}}catch(e){B=JSON.parse(JSON.stringify(DEFAULTS))}initPrices(B);if(!B.trigSt)B.trigSt={};if(!B.binary)B.binary=DEFAULTS.binary?JSON.parse(JSON.stringify(DEFAULTS.binary)):{};if(!B.ui)B.ui={tab:'dash',jFilt:'all',expanded:[]}}
function save(){B.modified=new Date().toISOString();try{localStorage.setItem('acb2',JSON.stringify(B))}catch(e){}}
function exportBook(){const j=JSON.stringify(B,null,2);const b=new Blob([j],{type:'application/json'});const u=URL.createObjectURL(b);const a=document.createElement('a');a.href=u;a.download=`commodity-book-${new Date().toISOString().slice(0,10)}.json`;a.click();URL.revokeObjectURL(u)}
function importBook(file){const r=new FileReader();r.onload=e=>{try{const d=JSON.parse(e.target.result);if(d.v===2){B=d;initPrices(B);save();renderAll()}}catch(err){alert('Invalid file')}};r.readAsText(file)}
function resetBook(){if(!confirm('Reset all data? This clears positions, journal, and trigger state.'))return;B=JSON.parse(JSON.stringify(DEFAULTS));initPrices(B);save();renderAll()}
function regime(b){if(b>=155)return{id:'extreme',lbl:'EXTREME',c:'#9C27B0'};if(b>=135)return{id:'escalation',lbl:'ESCALATION',c:'#ef5350'};if(b>=115)return{id:'elevated',lbl:'ELEVATED',c:'var(--c-warn)'};return{id:'base',lbl:'PRE-PERSISTENCE',c:'var(--t3)'}}
function adjLvl(inst){const c=B.prices[inst.id];const p=(c-inst.ref)/inst.ref;if(!inst.tL)return{tL:null,tH:null,stp:null,adj:false,p:0};if(Math.abs(p)>.02)return{tL:+(inst.tL*(1+p)).toFixed(2),tH:+(inst.tH*(1+p)).toFixed(2),stp:+(inst.stp*(1+p)).toFixed(2),adj:true,p};return{tL:inst.tL,tH:inst.tH,stp:inst.stp,adj:false,p:0}}
function rngPos(c,s,t){if(!s||!t)return 50;const r=t-s;return r===0?50:Math.max(0,Math.min(100,((c-s)/r)*100))}
function evalTrig(t){
  if(t.bin){return{lv:B.binary[t.bin]?'trig':'mon',lb:B.binary[t.bin]?'TRIGGERED':'MONITORING'}}
  const v=B.market[t.mk];
  if(t.rvs){const cd=closeDates(t.id);if(v<=t.th&&cd.length>=t.cls)return{lv:'trig',lb:'TRIGGERED'};if(v/t.th<1.12)return{lv:'appr',lb:'APPROACHING'};return{lv:'mon',lb:'MONITORING'}}
  if(t.cstr){return v>t.th?{lv:'cstr',lb:'ACTIVE'}:{lv:'mon',lb:'INACTIVE'}}
  if(t.alt){const gld=B.prices['GLD']||0;if(gld>t.alt.th||v>t.th)return{lv:'trig',lb:'TRIGGERED'};if(Math.max(v/t.th,gld/t.alt.th)>.95)return{lv:'appr',lb:'APPROACHING'};return{lv:'mon',lb:'MONITORING'}}
  if(t.op==='>'){const cd=closeDates(t.id);const r=v/t.th;if(v>t.th){if(t.cls&&cd.length<t.cls)return{lv:'appr',lb:`ABOVE ${cd.length}/${t.cls}`};return{lv:'trig',lb:'TRIGGERED'}}if(r>.95)return{lv:'appr',lb:'APPROACHING'};return{lv:'mon',lb:'MONITORING'}}
  return{lv:'mon',lb:'MONITORING'}
}
function closeDates(tid){return(B.trigSt[tid]&&B.trigSt[tid].closes)||[]}
function overlayUnlocked(o){return o.trig.some(tid=>{const t=TRIGS.find(x=>x.id===tid);return t&&evalTrig(t).lv==='trig'})}
function sgovAvail(){return(B.sgov?B.sgov.budget:0)-((B.sgov&&B.sgov.ledger)?B.sgov.ledger.reduce((s,d)=>s+d.amount,0):0)}
function posVal(id){const pos=B.positions[id];if(!pos||!pos.lots||!pos.lots.length)return{shares:0,cost:0,mktVal:0,pl:0,plPct:0};let sh=0,cost=0;pos.lots.forEach(l=>{if(l.type==='buy'){sh+=l.shares;cost+=l.shares*l.price}else{const avg=sh>0?cost/sh:0;sh-=l.shares;cost-=l.shares*avg}});const price=B.prices[id]||0;const mv=sh*price;return{shares:sh,cost,mktVal:mv,pl:mv-cost,plPct:cost>0?((mv-cost)/cost*100):0}}
function bookTotals(){let tv=0,tc=0;[...INSTS,...OVERLAYS.flatMap(o=>o.insts)].forEach(i=>{const p=posVal(i.id);tv+=p.mktVal;tc+=p.cost});return{val:tv,cost:tc,pl:tv-tc,plPct:tc>0?((tv-tc)/tc*100):0}}
function fmt(n,d){if(n==null)return'--';d=d!=null?d:2;return n.toLocaleString('en-US',{minimumFractionDigits:d,maximumFractionDigits:d})}
function fPct(n){return(n>=0?'+':'')+n.toFixed(1)+'%'}
function fDate(d){if(!d)return'--';return new Date(d+'T12:00:00').toLocaleDateString('en-US',{month:'short',day:'numeric'})}
function today(){return new Date().toISOString().slice(0,10)}
function addJ(type,text){B.journal.unshift({id:Date.now(),date:today(),type,text});save()}
function addPos(instId,date,shares,price,type,note){if(!B.positions[instId])B.positions[instId]={lots:[]};B.positions[instId].lots.push({date,shares:+shares,price:+price,type,note:note||''});addJ('trade',`${type==='buy'?'Bought':'Sold'} ${shares} ${instId} @ $${fmt(price)}${note?'. '+note:''}`);save();renderAll()}
function logClose(tid){const t=TRIGS.find(x=>x.id===tid);if(!t)return;if(!B.trigSt[tid])B.trigSt[tid]={closes:[]};const v=B.market[t.mk];B.trigSt[tid].closes.push({date:today(),value:v});const cd=B.trigSt[tid].closes;if(t.cls&&cd.length>=t.cls){addJ('trigger',`${t.nm} TRIGGERED after ${t.cls} closes. Value: ${v}`)}save();renderAll()}
function renderAll(){renderRegime();renderStats();renderActions();renderMetrics();renderRules();renderInsts();renderOverlays();renderTriggers();renderJournal()}
function renderRegime(){const r=regime(B.market.brent||0);document.getElementById('regime-display').innerHTML=`<span style="font-family:var(--font-mono);font-weight:700">$${fmt(B.market.brent||0)}</span><span class="regime-tag" style="background:${r.c}22;color:${r.c};border:1px solid ${r.c}44">${r.lbl}</span>`}
function renderStats(){const bt=bookTotals();const sa=sgovAvail();const plCls=bt.pl>0?'pl-up':bt.pl<0?'pl-dn':'pl-flat';document.getElementById('stats-bar').innerHTML=`<div class="stat-card"><div class="stat-val">$${fmt(bt.val,0)}</div><div class="stat-lbl">BOOK VALUE</div></div><div class="stat-card"><div class="stat-val ${plCls}">${bt.pl>=0?'+':''}$${fmt(bt.pl,0)}</div><div class="stat-lbl">UNREALIZED P&L</div></div><div class="stat-card"><div class="stat-val ${plCls}">${fPct(bt.plPct)}</div><div class="stat-lbl">RETURN</div></div><div class="stat-card"><div class="stat-val">$${fmt(sa,0)}</div><div class="stat-lbl">SGOV AVAILABLE</div></div><div class="stat-card"><div class="stat-val">$${fmt(bt.cost,0)}</div><div class="stat-lbl">TOTAL DEPLOYED</div></div>`}
function renderActions(){const items=[];const rd=[1,3,5];let nr=new Date();for(let i=1;i<=7;i++){nr=new Date(Date.now()+i*864e5);if(rd.includes(nr.getDay()))break}const ns=['Sun','Mon','Tue','Wed','Thu','Fri','Sat'][nr.getDay()]+' '+nr.toLocaleDateString('en-US',{month:'short',day:'numeric'});TRIGS.forEach(t=>{const e=evalTrig(t);if(e.lv==='trig'&&!t.cstr){items.push(`<li class="act-item"><span class="act-badge ${t.rvs?'b-block':'b-act'}">${t.rvs?'REVERSE':'ACT'}</span><span class="act-text"><strong>${t.nm}:</strong> ${t.act}</span></li>`)}else if(e.lv==='cstr'){items.push(`<li class="act-item"><span class="act-badge b-block">BLOCK</span><span class="act-text"><strong>${t.nm}:</strong> ${t.act}</span></li>`)}else if(e.lv==='appr'||e.lb.includes('ABOVE')){items.push(`<li class="act-item"><span class="act-badge b-watch">WATCH</span><span class="act-text"><strong>${t.nm}:</strong> ${t.mk?B.market[t.mk]:''} — threshold ${t.th||'binary'}</span></li>`)}});const rigsT=TRIGS.find(t=>t.id==='rigs'||t.bin==='rigsFlat');if(rigsT){const re=evalTrig(rigsT);if(re.lv!=='trig')items.push(`<li class="act-item"><span class="act-badge b-block">BLOCK</span><span class="act-text"><strong>Services locked.</strong> Rigs ${B.market.usRigs||'?'}, still falling.</span></li>`)}if(!items.length)items.push(`<li class="act-item"><span class="act-badge b-hold">HOLD</span><span class="act-text">All triggers monitoring. Continue monthly DCA.</span></li>`);document.getElementById('action-panel').innerHTML=`<div class="ap-head"><span class="ap-title">What To Do Now</span><span class="ap-date">SGOV ammo: $${sgovAvail()}</span></div><ul class="act-list">${items.join('')}</ul><div class="act-next">Next review: <strong>${ns}</strong>${nr.getDay()===5?' — Baker Hughes':''}</div>`}
function renderMetrics(){let h='';MKT_FIELDS.forEach(f=>{h+=`<div class="m-item"><label class="m-lbl" for="m-${f.k}">${f.lbl}</label><input class="m-inp" type="number" step="${f.step}" id="m-${f.k}" data-k="${f.k}" value="${B.market[f.k]||f.v}"></div>`});document.getElementById('metrics-bar').innerHTML=h}
function renderRules(){document.getElementById('rules-list').innerHTML=RULES.map((r,i)=>`<li class="rule"><span class="rule-n">${i+1}.</span><span>${r}</span></li>`).join('')}
function renderInsts(){let h='';INSTS.forEach(inst=>{const c=B.prices[inst.id];const pv=posVal(inst.id);const a=adjLvl(inst);const col=CATS[inst.cat];const pct=(inst.mo/TOTAL*100).toFixed(1);let rangeH='',posH='';if(pv.shares>0){const plc=pv.pl>=0?'pl-up':'pl-dn';posH=`<div class="pos-summary"><div class="pos-row"><span class="lbl">Shares</span><span class="val">${fmt(pv.shares,2)}</span></div><div class="pos-row"><span class="lbl">Avg Cost</span><span class="val">$${fmt(pv.cost/pv.shares)}</span></div><div class="pos-row"><span class="lbl">Mkt Value</span><span class="val">$${fmt(pv.mktVal)}</span></div><div class="pos-row"><span class="lbl">P&L</span><span class="val ${plc}">${pv.pl>=0?'+':''}$${fmt(pv.pl)} (${fPct(pv.plPct)})</span></div></div>`}else{posH='<div class="pos-empty">No position yet</div>'}if(inst.rsv){const sa=sgovAvail();const bgt=B.sgov?B.sgov.budget:0;const ap=bgt>0?(sa/bgt*100).toFixed(0):'100';rangeH=`<div class="sgov-meter"><div class="sgov-track"><div class="sgov-fill" style="width:${ap}%"></div></div><div class="sgov-labels"><span>Deployed: $${bgt-sa}</span><span>Available: $${sa}</span></div></div>`;if(B.sgov&&B.sgov.ledger&&B.sgov.ledger.length){rangeH+=`<div style="margin-top:6px;font-family:var(--font-mono);font-size:11px;color:var(--t3)">`;B.sgov.ledger.forEach(d=>{rangeH+=`<div>${fDate(d.date)} | ${d.trigger} | $${d.amount} → ${d.target}</div>`});rangeH+='</div>'}}else if(a.tL!=null){const pos=rngPos(c,a.stp,a.tL);const up=((a.tL-c)/c*100);const dn=((c-a.stp)/c*100);const rr=dn>0?(up/dn).toFixed(1):'--';const fc=pos<30?'var(--c-dn)':col;rangeH=`<div class="range-bar"><div class="r-track"><div class="r-fill" style="width:${pos}%;background:${fc};opacity:.3"></div><div class="r-mark" style="left:${pos}%;background:${col}"></div></div><div class="r-labels"><span class="stp">${fmt(a.stp)}</span><span>${fmt(c)}</span><span class="tgt">${fmt(a.tL)}-${fmt(a.tH)}</span></div><div class="r-metrics"><span class="up">${fPct(up)} target</span><span class="rr">${rr}:1</span><span class="dn">${fPct(-dn)} stop</span></div></div>`}const adjB=a.adj?`<span class="p-adj">Adj ${fPct(a.p*100)}</span>`:'';let lotsH='';const lots=(B.positions[inst.id]&&B.positions[inst.id].lots)||[];if(lots.length){lotsH='<div class="lot-list">';lots.forEach(l=>{lotsH+=`<div class="lot-row"><span class="lot-date">${fDate(l.date)}</span><span class="${l.type==='buy'?'lot-buy':'lot-sell'}">${l.type==='buy'?'+':'-'}${l.shares}</span><span>$${fmt(l.price)}</span><span style="color:var(--t4)">${l.note||''}</span></div>`});lotsH+='</div>'}h+=`<div class="i-card" data-c="${inst.cat}" data-id="${inst.id}" style="--cat-c:${col}"><style>.i-card[data-id="${inst.id}"]::before{background:${col}}</style><div class="i-head"><span class="i-ticker" style="color:${col}">${inst.id}</span><span class="i-alloc">$${inst.mo.toLocaleString()}/mo <span class="pct">${pct}%</span></span></div><div class="i-role">${inst.role}</div>${posH}<div class="price-row"><span class="p-lbl">Price</span><input type="number" step=".01" class="p-inp" value="${c}" data-inst="${inst.id}" aria-label="${inst.id} current price">${adjB}</div>${rangeH}${lotsH}<button class="btn-open-form" data-pf="${inst.id}">+ Add Position</button><div class="pos-form" id="pf-${inst.id}"><div class="pf-row"><input type="date" class="pf-inp w-date" value="${today()}" data-f="date"><input type="number" class="pf-inp w-num" placeholder="Shares" step=".01" data-f="shares"><input type="number" class="pf-inp w-num" placeholder="Price" step=".01" value="${c}" data-f="price"><select class="pf-inp" data-f="type"><option value="buy">Buy</option><option value="sell">Sell</option></select></div><div class="pf-row"><input type="text" class="pf-inp w-note" placeholder="Note (e.g. Monthly DCA)" data-f="note"><div class="pf-btns"><button class="btn-add primary" data-pf-add="${inst.id}">Add</button><button class="btn-add ghost" data-pf-cancel="${inst.id}">Cancel</button></div></div></div></div>`});document.getElementById('inst-grid').innerHTML=h}
function renderOverlays(){let h='';OVERLAYS.forEach(o=>{const ul=overlayUnlocked(o);let ih='<div class="oi-row" style="font-weight:600;color:var(--t3);font-size:11px"><span>Ticker</span><span>Current</span><span>Target</span><span>Stop</span></div>';o.insts.forEach(i=>{const c=B.prices[i.id]||i.ref;ih+=`<div class="oi-row"><span class="oi-tk">${i.id}</span><span>$${fmt(c)}</span><span class="oi-tgt">$${fmt(i.tL)}-${fmt(i.tH)}</span><span class="oi-stp">$${fmt(i.stp)}</span></div>`;if(i.note)ih+=`<div class="o-note">${i.note}</div>`});h+=`<div class="o-card ${ul?'unlocked':'locked'}"><span class="o-lock ${ul?'lk-off':'lk-on'}">${ul?'UNLOCKED':'LOCKED'}</span><div class="o-name">${o.nm}</div><div class="o-trig">Trigger: ${o.cond}</div>${ih}</div>`});document.getElementById('overlay-grid').innerHTML=h}
function renderTriggers(){let h='';TRIGS.forEach(t=>{const e=evalTrig(t);const sc=t.cstr?(e.lv==='cstr'?'st-cstr':''):(t.rvs&&e.lv==='trig'?'st-rev':e.lv==='trig'?'st-trig':e.lv==='appr'||e.lb.includes('ABOVE')?'st-appr':'');const bc=t.cstr?(e.lv==='cstr'?'bg-cstr':'bg-mon'):e.lv==='trig'?'bg-trig':(e.lv==='appr'||e.lb.includes('ABOVE'))?'bg-appr':'bg-mon';let inp='';if(t.bin){const ck=B.binary[t.bin]?'checked':'';const descs={'supplyLoss':'> 13 mbpd loss or Kharg escalation','rigsFlat':'Rigs flat/up 2 consecutive weeks','shipWorse':'Rerouting / stranding worsened'};inp=`<div class="toggle-row"><label class="tgl"><input type="checkbox" ${ck} data-bin="${t.bin}"><span class="tgl-trk"></span></label><span class="tgl-txt">${descs[t.bin]||t.det}</span></div>`}else{const v=B.market[t.mk];let prog;if(t.rvs)prog=Math.max(0,Math.min(100,(t.th/v)*100));else prog=Math.max(0,Math.min(100,(v/t.th)*100));const pc=prog>=100?'var(--c-up)':prog>=95?'var(--c-warn)':'var(--t4)';const tl=t.mk==='curveSpread'?`${t.op} ${t.th}%`:`${t.op} $${fmt(t.th,t.th<10?2:0)}`;inp=`<div class="t-metric"><span class="lbl">${t.mk}</span><span class="val">${t.mk==='curveSpread'?v+'%':'$'+fmt(v)}</span><span class="thr">${tl}</span></div><div class="prog-wrap"><div class="prog-track"><div class="prog-fill" style="width:${Math.min(prog,100)}%;background:${pc}"></div></div><span class="prog-pct">${prog.toFixed(1)}%</span></div>`;if(t.alt){const gld=B.prices['GLD']||0;const gp=Math.min(100,(gld/t.alt.th)*100);const gc=gp>=100?'var(--c-up)':gp>=95?'var(--c-warn)':'var(--t4)';inp+=`<div class="t-metric" style="margin-top:2px"><span class="lbl">GLD</span><span class="val">$${fmt(gld)}</span><span class="thr">> $${fmt(t.alt.th,0)}</span></div><div class="prog-wrap"><div class="prog-track"><div class="prog-fill" style="width:${gp}%;background:${gc}"></div></div><span class="prog-pct">${gp.toFixed(1)}%</span></div>`}}let clH='';if(t.cls){const cd=closeDates(t.id);clH=`<div class="close-log"><div class="cl-head"><span class="cl-count">${cd.length} / ${t.cls}</span><span class="cl-req">closes</span><button class="btn-log-close" data-cl="${t.id}">Log Close</button></div>`;if(cd.length)clH+=`<div class="cl-dates">${cd.map(c=>`${fDate(c.date)}: ${c.value}`).join(' · ')}</div>`;clH+=`</div>`}const vis=e.lv==='trig'||e.lv==='cstr'||e.lb.includes('ABOVE');const acls=t.cstr?'vis-c':t.rvs?'vis-r':'vis';const alcls=t.cstr?'cst':t.rvs?'rev':'act';const altxt=t.cstr?'CONSTRAINT':t.rvs?'REVERSAL':'ACTION';const exp=B.ui.expanded&&B.ui.expanded.includes(t.id);h+=`<div class="t-card ${sc}" data-tid="${t.id}"><div class="t-head"><span class="t-name">${t.nm}</span><span class="t-badge ${bc}">${e.lb}</span></div>${inp}${clH}<div class="t-action ${vis?acls:''}"><span class="ta-label ${alcls}">${altxt}</span><span class="ta-text">${t.act}</span><span class="ta-detail">${t.det}</span></div><button class="htr-btn" data-htr="${t.id}">${exp?'- Hide':'+ Context'}</button><div class="htr ${exp?'open':''}" id="htr-${t.id}">${t.htr}</div></div>`});document.getElementById('trigger-grid').innerHTML=h}
function renderJournal(){const filt=B.ui.jFilt||'all';const types=['all','trade','review','trigger','note','setup'];let fh='';types.forEach(t=>{fh+=`<button class="j-filt ${t===filt?'active':''}" data-jf="${t}">${t==='all'?'All':t.charAt(0).toUpperCase()+t.slice(1)}</button>`});document.getElementById('j-filters').innerHTML=fh;const entries=filt==='all'?B.journal:B.journal.filter(e=>e.type===filt);if(!entries.length){document.getElementById('j-list').innerHTML='<div class="j-empty">No entries yet.</div>';return}let eh='';entries.forEach(e=>{eh+=`<div class="j-entry"><span class="j-date">${fDate(e.date)}</span><span class="j-type ${e.type}">${e.type}</span><span class="j-text">${e.text}</span></div>`});document.getElementById('j-list').innerHTML=eh}
document.querySelector('.tab-bar').addEventListener('click',e=>{const b=e.target.closest('.tab-btn');if(!b)return;document.querySelectorAll('.tab-btn,.tab-pane').forEach(el=>el.classList.remove('active'));b.classList.add('active');document.getElementById(b.dataset.tab).classList.add('active');B.ui.tab=b.dataset.tab;save()});
document.getElementById('dash').addEventListener('input',e=>{if(e.target.classList.contains('m-inp')){const k=e.target.dataset.k;const v=parseFloat(e.target.value);if(!isNaN(v)){B.market[k]=v;save();renderAll()}}});
document.getElementById('book').addEventListener('input',e=>{if(e.target.classList.contains('p-inp')){const id=e.target.dataset.inst;const v=parseFloat(e.target.value);if(!isNaN(v)){B.prices[id]=v;save();renderAll()}}});
document.getElementById('book').addEventListener('click',e=>{const ob=e.target.closest('[data-pf]');if(ob&&!e.target.dataset.pfAdd&&!e.target.dataset.pfCancel){document.getElementById('pf-'+ob.dataset.pf).classList.toggle('open');return}const ab=e.target.closest('[data-pf-add]');if(ab){const id=ab.dataset.pfAdd;const f=document.getElementById('pf-'+id);const d=f.querySelector('[data-f="date"]').value;const s=f.querySelector('[data-f="shares"]').value;const p=f.querySelector('[data-f="price"]').value;const t=f.querySelector('[data-f="type"]').value;const n=f.querySelector('[data-f="note"]').value;if(s&&p){addPos(id,d||today(),s,p,t,n);f.classList.remove('open')}return}const cb=e.target.closest('[data-pf-cancel]');if(cb){document.getElementById('pf-'+cb.dataset.pfCancel).classList.remove('open')}});
document.getElementById('triggers').addEventListener('change',e=>{if(e.target.dataset.bin){B.binary[e.target.dataset.bin]=e.target.checked;const nm=TRIGS.find(t=>t.bin===e.target.dataset.bin);if(nm&&e.target.checked)addJ('trigger',`${nm.nm} toggled ON`);save();renderAll()}});
document.getElementById('triggers').addEventListener('click',e=>{const cl=e.target.closest('.btn-log-close');if(cl){logClose(cl.dataset.cl);return}const ht=e.target.closest('.htr-btn');if(ht){const id=ht.dataset.htr;if(!B.ui.expanded)B.ui.expanded=[];const idx=B.ui.expanded.indexOf(id);if(idx>=0)B.ui.expanded.splice(idx,1);else B.ui.expanded.push(id);save();renderAll()}});
document.getElementById('j-add').addEventListener('click',()=>{const t=document.getElementById('j-type').value;const d=document.getElementById('j-date').value||today();const n=document.getElementById('j-note').value.trim();if(!n)return;B.journal.unshift({id:Date.now(),date:d,type:t,text:n});save();document.getElementById('j-note').value='';renderJournal()});
document.getElementById('j-note').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();document.getElementById('j-add').click()}});
document.getElementById('journal').addEventListener('click',e=>{const f=e.target.closest('.j-filt');if(f){B.ui.jFilt=f.dataset.jf;save();renderJournal()}});
document.getElementById('btn-export').addEventListener('click',exportBook);
document.getElementById('btn-fetch').addEventListener('click',async()=>{const btn=document.getElementById('btn-fetch');btn.textContent='Fetching...';btn.disabled=true;try{const yUrl=`https://query2.finance.yahoo.com/v7/finance/spark?symbols=${encodeURIComponent(FETCH_SYMS.join(','))}&range=1d&interval=1d`;const r=await fetch(`https://api.allorigins.win/get?url=${encodeURIComponent(yUrl)}`);const d=JSON.parse((await r.json()).contents);d.spark.result.forEach(item=>{const s=item.symbol;const p=item.response[0]?.meta?.regularMarketPrice;if(!p)return;if(FETCH_MAP[s])B.market[FETCH_MAP[s]]=+p.toFixed(2);else if(B.prices[s]!==undefined)B.prices[s]=+p.toFixed(2)});B.market.lastFetch=new Date().toISOString();addJ('note',`Live fetch: Brent $${B.market.brent}, Gold $${B.market.goldSpot}`);save();renderAll();btn.textContent='Fetched';setTimeout(()=>{btn.textContent='Fetch Live';btn.disabled=false},2000)}catch(e){btn.textContent='Failed';setTimeout(()=>{btn.textContent='Fetch Live';btn.disabled=false},2000);console.error('Fetch error:',e)}});
document.getElementById('btn-import').addEventListener('change',e=>{if(e.target.files[0])importBook(e.target.files[0])});
document.getElementById('btn-reset').addEventListener('click',resetBook);
load();
document.getElementById('j-date').value=today();
if(B.ui.tab){const tb=document.querySelector(`.tab-btn[data-tab="${B.ui.tab}"]`);if(tb){document.querySelectorAll('.tab-btn,.tab-pane').forEach(el=>el.classList.remove('active'));tb.classList.add('active');document.getElementById(B.ui.tab).classList.add('active')}}
renderAll();
"""


# =========================================================================
# CLI
# =========================================================================

def print_summary(cfg: dict) -> None:
    """Print a config summary table."""
    budget = cfg.get("monthlyBudget", 0)
    insts = cfg.get("instruments", [])
    trigs = cfg.get("triggers", [])
    ovs = cfg.get("overlays", [])
    ov_count = sum(len(o.get("instruments", [])) for o in ovs)

    print(f"\n  Title:        {cfg.get('title', '?')}")
    print(f"  Budget:       ${budget:,}/mo")
    print(f"  Instruments:  {len(insts)} core + {ov_count} overlay")
    print(f"  Triggers:     {len(trigs)} ({sum(1 for t in trigs if 'binaryKey' in t)} binary, {sum(1 for t in trigs if 'metricKey' in t)} numeric)")
    print(f"  Overlays:     {len(ovs)}")
    print(f"  Rules:        {len(cfg.get('rules', []))}")

    print(f"\n  Allocation:")
    for inst in insts:
        pct = inst["monthly"] / budget * 100 if budget else 0
        print(f"    {inst['id']:6s}  ${inst['monthly']:>5,}  {pct:5.1f}%  {inst['role']}")

    mkt = {m["key"]: m["value"] for m in cfg.get("marketFields", [])}
    print(f"\n  Trigger Proximity:")
    for t in trigs:
        if "binaryKey" in t:
            print(f"    {t['name']:25s}  BINARY")
        elif "metricKey" in t and "threshold" in t:
            val = mkt.get(t["metricKey"], 0)
            th = t["threshold"]
            op = t.get("operator", ">")
            pct = (val / th * 100) if (op == ">" and th) else ((th / val * 100) if val else 0)
            print(f"    {t['name']:25s}  {val:>8} {op} {th:<8}  {pct:5.1f}%")


def main():
    parser = argparse.ArgumentParser(
        description="Generate an active commodity book from JSON config",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s walkthrough                          Show full JSON schema docs
  %(prog)s config.json --dry-run                Validate + summarize only
  %(prog)s config.json -o book.html             Generate HTML
  %(prog)s config.json -o book.html --fetch     Generate with live prices
  %(prog)s config.json --fetch --update-config  Write live prices into JSON
  %(prog)s config.json -o book.html --fetch --validate --publish --force
        """,
    )
    parser.add_argument("config", help="JSON config path, or 'walkthrough' for docs")
    parser.add_argument("-o", "--output", default="active-commodity-book.html", help="Output HTML file")
    parser.add_argument("--fetch", action="store_true", help="Fetch live prices from Yahoo Finance")
    parser.add_argument("--update-config", action="store_true", help="Write fetched prices back into JSON config")
    parser.add_argument("--dry-run", action="store_true", help="Validate and summarize only")
    parser.add_argument("--force", action="store_true", help="Overwrite output without asking")
    parser.add_argument("--validate", action="store_true", help="Run validate.py on output")
    parser.add_argument("--screenshot", action="store_true", help="Generate OG screenshot")
    parser.add_argument("--publish", action="store_true", help="Publish to Reading Room")
    parser.add_argument("--username", default="admin", help="Reading Room username")
    parser.add_argument("--slug", help="URL slug for published article")
    parser.add_argument("--category", default="ANALYSIS", help="Article category")
    parser.add_argument("--api-url", default="http://127.0.0.1:8100", help="Reading Room API URL")
    args = parser.parse_args()

    # Walkthrough mode
    if args.config == "walkthrough":
        print(WALKTHROUGH)
        return

    # Load
    print(f"Loading: {args.config}")
    cfg = load_config(args.config)

    # Validate
    errors, warnings = validate_config(cfg)
    for w in warnings:
        print(f"  WARN: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"  ERROR: {e}", file=sys.stderr)
        print(f"\n  {len(errors)} error(s). Fix and retry.", file=sys.stderr)
        sys.exit(1)
    print(f"  Valid ({len(warnings)} warning(s))")

    # Summary
    print_summary(cfg)

    # Fetch
    if args.fetch or args.update_config:
        print("\nFetching live prices...")
        cfg = fetch_prices(cfg)
        if args.update_config:
            update_config_file(args.config, cfg)

    # Dry run exits here
    if args.dry_run:
        print("\n  --dry-run: no HTML generated.")
        return

    # Overwrite check
    output = os.path.abspath(args.output)
    if os.path.isfile(output) and not args.force:
        print(f"\n  Output exists: {output}")
        print(f"  Use --force to overwrite.")
        sys.exit(1)

    # Generate
    print(f"\nGenerating HTML...")
    html = generate_html(cfg)
    Path(output).write_text(html)
    print(f"  Written: {output} ({len(html):,} bytes)")

    # Validate
    if args.validate:
        print("\nValidating...")
        run_validate(output)

    # Screenshot
    if args.screenshot:
        print("\nScreenshotting...")
        run_screenshot(output, str(Path(output).parent))

    # Publish
    if args.publish:
        print("\nPublishing...")
        run_publish(output, cfg, args)

    print("\nDone.")


if __name__ == "__main__":
    main()
