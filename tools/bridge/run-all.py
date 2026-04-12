#!/usr/bin/env python3
"""
Run All -- orchestrate the full thesis pipeline for all active thesis graphs.

Discovers all thesis-graph books in the books/ directory, then for each book
(in alphabetical order):
  1. Copies the previous snapshot (if any) to {book-id}-prev.json
  2. Runs thesisgraph.py --fetch --export-state to generate a fresh snapshot
  3. Runs diff-snapshots.py to detect changes vs. the previous snapshot
  4. If changes were found, pushes the snapshot to Dialectic

Books without a meta.dialecticRoomId are exported but not pushed (export-only
mode). Books with a missing or malformed JSON are reported as failures but do
not abort the run; remaining books are processed and the runner exits 1 at end.

Usage:
    # Run all thesis books
    python3 tools/bridge/run-all.py

    # Preview what would run (no network calls)
    python3 tools/bridge/run-all.py --dry-run

    # Use a custom books directory (e.g. for testing)
    python3 tools/bridge/run-all.py --books path/to/books/

    # Cron (Mon/Wed/Fri at 08:00):
    #   0 8 * * 1,3,5 cd /path/to/tradingDesk && \\
    #       DIALECTIC_ROOM_TOKEN=<token> python3 tools/bridge/run-all.py \\
    #       >> logs/run-all.log 2>&1
    #
    # NOTE: push-to-dialectic.py defaults to http://localhost:8002 (the mock
    # server port). Production pushes require the Dialectic URL to be supplied
    # when invoking push-to-dialectic.py directly (--dialectic-url flag).

Exit codes:
    0 -- all books succeeded (or no thesis-graph books discovered)
    1 -- one or more books failed
    2 -- configuration error (snapshots/ directory missing, books/ not found)

Environment variables:
    DIALECTIC_ROOM_TOKEN  -- shared room token for all Dialectic pushes.
                             Required for push steps; if absent,
                             push-to-dialectic.py exits 2 (book marked failed).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional


# =========================================================================
# SCRIPT PATHS
# WHY: Resolved at import time so tests can monkeypatch these module-level
#      constants to point at stub scripts without touching the filesystem
#      layout. All three subprocess calls reference these names at call time,
#      so a post-import monkeypatch takes effect immediately.
# =========================================================================

ROOT: Path = Path(__file__).resolve().parent.parent.parent
THESISGRAPH: str = str(ROOT / "tools" / "thesis_graph" / "thesisgraph.py")
DIFF_SNAPSHOTS: str = str(ROOT / "tools" / "bridge" / "diff_snapshots.py")
PUSH_SCRIPT: str = str(ROOT / "tools" / "bridge" / "push_to_dialectic.py")


# =========================================================================
# BOOK LOADING
# =========================================================================

def load_book(path: Path) -> Optional[dict]:
    """
    Load a book JSON and return it if it is a thesis-graph book.

    Returns:
        dict with book data if meta.type == "thesis-graph"
        {"_error": str} if the file cannot be loaded or parsed
        None if the file is valid JSON but not a thesis-graph book (silently skip)
    """
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        return {"_error": str(exc)}

    if not isinstance(data, dict):
        return None

    if data.get("meta", {}).get("type") != "thesis-graph":
        return None  # legacy format or other type — silently skip

    return data


def discover_books(books_dir: Path) -> list:
    """
    Discover all thesis-graph books in books_dir, sorted alphabetically.

    Returns a list of (book_id, book_path, book_data) tuples.
    Non-thesis-graph books are silently excluded.
    Malformed JSON files are included as error entries.
    """
    entries = []
    for path in sorted(books_dir.glob("*.json")):
        data = load_book(path)
        if data is None:
            continue
        entries.append((path.stem, path, data))
    return entries


# =========================================================================
# PIPELINE STEPS
# WHY: Each step is a thin wrapper so tests can replace the module-level
#      script constants (THESISGRAPH, DIFF_SNAPSHOTS, PUSH_SCRIPT) and
#      call these functions directly without subprocess overhead.
# =========================================================================

def run_export(book_path: Path, latest: Path) -> int:
    """
    Run thesisgraph.py --fetch --export-state.

    Stderr and stdout both pass through so progress messages and errors appear
    immediately in the terminal and cron log.
    """
    result = subprocess.run(
        [sys.executable, THESISGRAPH, str(book_path), "--fetch",
         "--export-state", str(latest)],
        check=False,
    )
    return result.returncode


def run_diff(prev: Path, latest: Path) -> int:
    """
    Run diff-snapshots.py. Returns 0 (changes), 1 (no changes), 2 (error).

    WHY: Stdout is captured to suppress the diff's JSON delta from run-all's
    stdout, which is reserved for the per-book summary lines. Stderr is left
    to pass through so error messages remain visible.
    """
    result = subprocess.run(
        [sys.executable, DIFF_SNAPSHOTS, str(prev), str(latest)],
        stdout=subprocess.PIPE,
        check=False,
    )
    return result.returncode


def run_push(latest: Path, room_id: str, room_token: str) -> int:
    """
    Run push-to-dialectic.py. Returns 0 (success), 1 (HTTP error),
    2 (config/connection error).

    WHY: Stdout is captured to suppress the verbose push response JSON.
    Stderr passes through so auth/network errors are visible immediately.
    Per-book token is injected into the subprocess environment as
    DIALECTIC_ROOM_TOKEN so push-to-dialectic.py picks it up without
    changing its CLI interface. Shell-level DIALECTIC_ROOM_TOKEN is
    overridden when a book-level token is present.
    """
    env = {**os.environ, "DIALECTIC_ROOM_TOKEN": room_token}
    result = subprocess.run(
        [sys.executable, PUSH_SCRIPT, "--snapshot", str(latest),
         "--room-id", room_id],
        stdout=subprocess.PIPE,
        env=env,
        check=False,
    )
    return result.returncode


# =========================================================================
# PER-BOOK PIPELINE
# =========================================================================

def run_book(
    book_id: str,
    book_path: Path,
    book_data: dict,
    snapshots_dir: Path,
    dry_run: bool,
) -> dict:
    """
    Execute the full pipeline for one book and return a result dict:

        {"export": "OK"|"FAIL"|"-",
         "changed": "yes"|"no"|"ERR"|"-",
         "pushed":  "OK"|"FAIL"|"-",
         "status":  "OK"|"FAIL"}

    The result dict drives both the summary line printer and the any_failed
    accumulator in main(). "-" signals a step that was skipped intentionally.
    """
    result: dict[str, str] = {
        "export": "-", "changed": "-", "pushed": "-", "status": "OK"
    }

    # Handle books that failed to load
    if "_error" in book_data:
        print(
            f"[error] {book_id}: invalid JSON — {book_data['_error']}",
            file=sys.stderr,
        )
        result["status"] = "FAIL"
        return result

    meta = book_data.get("meta", {})
    # WHY: treat falsy values ("", None) as absent — Unit 1 inserts "" as a
    # placeholder until the real room UUID is available from Dialectic admin.
    room_id: str = meta.get("dialecticRoomId") or ""
    # Per-book token takes precedence over DIALECTIC_ROOM_TOKEN env var.
    # WHY: Each Dialectic room has its own token; storing it alongside the
    # room ID in the book JSON avoids per-book env var proliferation.
    # Falls back to the env var so single-room setups need no JSON change.
    room_token: str = meta.get("dialecticRoomToken") or os.environ.get("DIALECTIC_ROOM_TOKEN", "")

    latest: Path = snapshots_dir / f"{book_id}-latest.json"
    prev: Path = snapshots_dir / f"{book_id}-prev.json"

    if dry_run:
        print(
            f"[dry-run] {book_id}: "
            f"room={room_id or 'NONE'}  "
            f"snapshot={latest}  "
            f"prev={prev}"
        )
        return result

    # Step 1: rotate previous snapshot before export
    if latest.exists():
        shutil.copy2(latest, prev)

    # Step 2: export
    export_rc = run_export(book_path, latest)
    if export_rc != 0:
        print(
            f"[error] {book_id}: thesisgraph failed (exit {export_rc})",
            file=sys.stderr,
        )
        result["export"] = "FAIL"
        result["status"] = "FAIL"
        return result
    result["export"] = "OK"

    # Step 3: first-run detection
    # WHY: prev is absent iff latest was absent before this run. The copy step
    # only runs when latest exists, so if prev doesn't exist after the copy,
    # this is the book's first export — skip diff and push.
    if not prev.exists():
        print(
            f"[info] {book_id}: first run — snapshot saved, no diff",
            file=sys.stderr,
        )
        return result

    # Step 4: no-room-id check
    if not room_id:
        print(
            f"[warn] {book_id}: no dialecticRoomId — export only",
            file=sys.stderr,
        )
        return result

    # Step 5: diff
    diff_rc = run_diff(prev, latest)
    if diff_rc == 2:
        print(f"[error] {book_id}: diff failed (exit 2)", file=sys.stderr)
        result["changed"] = "ERR"
        result["status"] = "FAIL"
        return result
    elif diff_rc == 1:
        result["changed"] = "no"
        return result
    else:  # diff_rc == 0 — changes found
        result["changed"] = "yes"

    # Step 6: push
    push_rc = run_push(latest, room_id, room_token)
    if push_rc != 0:
        print(
            f"[error] {book_id}: push failed (exit {push_rc})",
            file=sys.stderr,
        )
        result["pushed"] = "FAIL"
        result["status"] = "FAIL"
        return result

    result["pushed"] = "OK"

    # Step 7: evaluate open trades against the fresh snapshot (lifecycle monitor)
    # WHY: After push, the snapshot is the latest pipeline output. Evaluate all
    # open trades' predicate gates against it. This is the CAPTURE layer of the
    # REPAIR → TAG → CAPTURE architecture.
    open_trades_path: Path = ROOT / "outcomes" / "open_trades.json"
    if open_trades_path.exists():
        try:
            # WHY: Dynamic import avoids adding a hard dependency at module level.
            # Tests can monkeypatch or skip this path by not providing open_trades.json.
            lifecycle_mod = ROOT / "tools" / "outcomes" / "lifecycle_monitor.py"
            if lifecycle_mod.exists():
                import importlib.util
                spec = importlib.util.spec_from_file_location("lifecycle_monitor", str(lifecycle_mod))
                lm = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(lm)
                trade_results = lm.step7_evaluate_open_trades(
                    snapshot_path=latest,
                    open_trades_path=open_trades_path,
                    book_id=book_id,
                    book_path=book_path,
                    ledger_dir=str(ROOT / "outcomes" / "trades"),
                )
                result["trades"] = json.dumps(trade_results)
        except Exception as exc:
            # WHY: Step 7 failures should not abort the pipeline. Log and continue.
            print(f"[warn] {book_id}: lifecycle monitor failed — {exc}", file=sys.stderr)
            result["trades"] = "ERR"

    return result


# =========================================================================
# CLI
# =========================================================================

def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser. Separated for testability."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the full thesis pipeline (fetch → export → diff → push) "
            "for all active thesis-graph books in one command."
        ),
        epilog=(
            "Exit codes: 0 = all books succeeded, 1 = one or more books failed,\n"
            "            2 = configuration error.\n\n"
            "Auth: set DIALECTIC_ROOM_TOKEN in the environment.\n"
            "Room IDs: set meta.dialecticRoomId in each book JSON.\n"
            "Books without dialecticRoomId are exported but not pushed."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print what would run for each book (book ID, room ID, snapshot "
            "paths) without executing any fetches, exports, diffs, or pushes."
        ),
    )
    parser.add_argument(
        "--books",
        default=None,
        metavar="DIR",
        help=(
            "Directory containing book JSON files "
            "(default: books/ relative to repo root). "
            "Useful for testing with a subset of configs."
        ),
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Resolve books directory
    books_dir: Path = Path(args.books).resolve() if args.books else ROOT / "books"
    if not books_dir.is_dir():
        print(f"Error: books directory not found: {books_dir}", file=sys.stderr)
        sys.exit(2)

    # Validate snapshots directory
    # WHY: ROOT is a module-level constant that tests can monkeypatch, so
    # ROOT / "snapshots" resolves to the test's tmp_path when monkeypatched.
    snapshots_dir: Path = ROOT / "snapshots"
    if not snapshots_dir.is_dir():
        print(
            f"Error: snapshots/ directory not found at {snapshots_dir}.\n"
            "Create it first: mkdir snapshots",
            file=sys.stderr,
        )
        sys.exit(2)

    # Discover and process books
    books = discover_books(books_dir)
    if not books:
        print("[info] No thesis-graph books found.", file=sys.stderr)
        sys.exit(0)

    any_failed = False
    summary: list[tuple[str, dict]] = []

    for book_id, book_path, book_data in books:
        book_result = run_book(
            book_id, book_path, book_data, snapshots_dir, dry_run=args.dry_run
        )
        summary.append((book_id, book_result))
        if book_result["status"] == "FAIL":
            any_failed = True

    # Print per-book summary after all subprocess output
    if not args.dry_run and summary:
        max_id_len = max(len(bid) for bid, _ in summary)
        print()  # blank line separator from subprocess output
        for book_id, r in summary:
            pad = " " * (max_id_len - len(book_id))
            print(
                f"[{book_id}]{pad}  "
                f"export={r['export']}  "
                f"changed={r['changed']}  "
                f"pushed={r['pushed']}"
            )

    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
