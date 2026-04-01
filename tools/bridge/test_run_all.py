"""
Tests for tools/bridge/run-all.py multi-book runner.

Run:
    python3 -m pytest tools/bridge/test_run_all.py -v

Test approach: import run-all via importlib (handles the hyphen in filename),
then monkeypatch the module-level THESISGRAPH / DIFF_SNAPSHOTS / PUSH_SCRIPT
constants and ROOT to stub scripts written in tmp_path. This avoids real
network calls while exercising the full pipeline logic including snapshot
rotation and per-book result tracking.
"""

import importlib
import json
import os
import sys
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest

# =========================================================================
# MODULE IMPORT
# WHY: run-all.py contains a hyphen which is invalid as a Python identifier,
# so `import run-all` fails. importlib handles it the same way test_push.py
# handles push-to-dialectic.
# =========================================================================

sys.path.insert(0, str(Path(__file__).parent))
run_all = importlib.import_module("run-all")


# =========================================================================
# HELPERS
# =========================================================================

def make_book_json(room_id: str = "test-room-uuid", book_type: str = "thesis-graph") -> dict:
    """Minimal valid thesis-graph book JSON fixture."""
    meta: dict = {
        "title": "Test Thesis",
        "type": book_type,
        "monthlyBudget": 1000,
    }
    if room_id is not None:
        meta["dialecticRoomId"] = room_id
    return {"meta": meta, "nodes": [], "edges": []}


def write_book(books_dir: Path, name: str, data: dict) -> Path:
    """Write a book JSON to books_dir/{name}.json and return the path."""
    p = books_dir / f"{name}.json"
    p.write_text(json.dumps(data))
    return p


def write_stub(path: Path, content: str) -> None:
    """Write a Python stub script to path and make it executable."""
    path.write_text(dedent(content))
    path.chmod(0o755)


def make_thesisgraph_stub(tmp_path: Path, exit_code: int = 0) -> Path:
    """
    Stub for thesisgraph.py that writes a minimal snapshot JSON to the
    --export-state path and exits with the given code.
    """
    stub = tmp_path / "fake_thesisgraph.py"
    write_stub(stub, f"""
        import json, sys
        from pathlib import Path
        exit_code = {exit_code}
        # Find --export-state argument
        for i, arg in enumerate(sys.argv):
            if arg == "--export-state" and i + 1 < len(sys.argv):
                out = sys.argv[i + 1]
                snap = {{"v": 1, "timestamp": "2026-01-01T00:00:00Z", "nodeStates": {{}}}}
                Path(out).write_text(json.dumps(snap))
                break
        sys.exit(exit_code)
    """)
    return stub


def make_diff_stub(tmp_path: Path, exit_code: int) -> Path:
    """Stub for diff-snapshots.py that exits with the given code."""
    stub = tmp_path / f"fake_diff_{exit_code}.py"
    write_stub(stub, f"""
        import sys
        sys.exit({exit_code})
    """)
    return stub


def make_push_stub(tmp_path: Path, exit_code: int = 0) -> Path:
    """Stub for push-to-dialectic.py that exits with the given code."""
    stub = tmp_path / f"fake_push_{exit_code}.py"
    write_stub(stub, f"""
        import sys
        sys.exit({exit_code})
    """)
    return stub


def run_main(argv: list, tmp_snapshots: Path, thesisgraph_stub: Path,
             diff_stub: Path, push_stub: Path) -> int:
    """
    Call run_all.main() with monkeypatched constants and return the exit code.

    Monkeypatches:
      - ROOT: points to tmp dir so snapshots_dir = ROOT/"snapshots" resolves correctly
      - THESISGRAPH, DIFF_SNAPSHOTS, PUSH_SCRIPT: stub scripts

    Returns the SystemExit code (or 0 if main() returns normally).
    """
    # Make snapshots dir accessible by pointing ROOT to its parent
    snapshots_parent = tmp_snapshots.parent

    with (
        patch.object(run_all, "ROOT", snapshots_parent),
        patch.object(run_all, "THESISGRAPH", str(thesisgraph_stub)),
        patch.object(run_all, "DIFF_SNAPSHOTS", str(diff_stub)),
        patch.object(run_all, "PUSH_SCRIPT", str(push_stub)),
        patch("sys.argv", ["run-all.py"] + argv),
    ):
        try:
            run_all.main()
            return 0
        except SystemExit as e:
            return int(e.code) if e.code is not None else 0


# =========================================================================
# FIXTURES
# =========================================================================

@pytest.fixture()
def books_dir(tmp_path: Path) -> Path:
    d = tmp_path / "books"
    d.mkdir()
    return d


@pytest.fixture()
def snapshots_dir(tmp_path: Path) -> Path:
    d = tmp_path / "snapshots"
    d.mkdir()
    return d


# =========================================================================
# DISCOVERY TESTS
# =========================================================================

class TestBookDiscovery:
    def test_thesis_books_discovered(self, tmp_path, books_dir, snapshots_dir):
        """Two thesis-graph books are discovered; legacy book is silently skipped."""
        write_book(books_dir, "a-thesis", make_book_json())
        write_book(books_dir, "b-thesis", make_book_json())
        write_book(books_dir, "legacy", {"title": "old", "categories": {}})  # no meta.type

        tg = make_thesisgraph_stub(tmp_path)
        diff = make_diff_stub(tmp_path, 1)  # no changes
        push = make_push_stub(tmp_path)

        rc = run_main(
            ["--books", str(books_dir)],
            snapshots_dir, tg, diff, push,
        )
        assert rc == 0

    def test_alphabetical_order_enforced(self, tmp_path, books_dir, snapshots_dir, capsys):
        """Books are processed in alphabetical order regardless of filesystem order."""
        write_book(books_dir, "z-thesis", make_book_json())
        write_book(books_dir, "a-thesis", make_book_json())

        tg = make_thesisgraph_stub(tmp_path)
        diff = make_diff_stub(tmp_path, 1)
        push = make_push_stub(tmp_path)

        rc = run_main(
            ["--books", str(books_dir)],
            snapshots_dir, tg, diff, push,
        )
        captured = capsys.readouterr()
        a_pos = captured.out.index("a-thesis")
        z_pos = captured.out.index("z-thesis")
        assert a_pos < z_pos
        assert rc == 0

    def test_empty_books_dir_exits_zero(self, tmp_path, books_dir, snapshots_dir):
        """Empty books directory exits 0 with no errors."""
        tg = make_thesisgraph_stub(tmp_path)
        diff = make_diff_stub(tmp_path, 1)
        push = make_push_stub(tmp_path)

        rc = run_main(["--books", str(books_dir)], snapshots_dir, tg, diff, push)
        assert rc == 0

    def test_malformed_json_marked_failed(self, tmp_path, books_dir, snapshots_dir, capsys):
        """A book with malformed JSON is marked as failed; run exits 1."""
        p = books_dir / "bad.json"
        p.write_text("{not valid json}")

        # Also add a valid book to confirm the run continues
        write_book(books_dir, "good-thesis", make_book_json())
        tg = make_thesisgraph_stub(tmp_path)
        diff = make_diff_stub(tmp_path, 1)
        push = make_push_stub(tmp_path)

        rc = run_main(["--books", str(books_dir)], snapshots_dir, tg, diff, push)
        captured = capsys.readouterr()
        assert "[error]" in captured.err
        assert rc == 1


# =========================================================================
# HAPPY PATH PIPELINE TESTS
# =========================================================================

class TestHappyPath:
    def test_changes_found_push_succeeds(self, tmp_path, books_dir, snapshots_dir, capsys):
        """Changes found → push runs → summary shows export=OK changed=yes pushed=OK."""
        write_book(books_dir, "my-thesis", make_book_json(room_id="room-uuid"))

        # Pre-create prev so first-run detection passes
        prev = snapshots_dir / "my-thesis-prev.json"
        prev.write_text(json.dumps({"v": 1}))
        # Pre-create latest so the copy step runs
        latest = snapshots_dir / "my-thesis-latest.json"
        latest.write_text(json.dumps({"v": 1}))

        tg = make_thesisgraph_stub(tmp_path, exit_code=0)
        diff = make_diff_stub(tmp_path, 0)   # changes found
        push = make_push_stub(tmp_path, 0)   # success

        rc = run_main(["--books", str(books_dir)], snapshots_dir, tg, diff, push)
        captured = capsys.readouterr()
        assert rc == 0
        assert "export=OK" in captured.out
        assert "changed=yes" in captured.out
        assert "pushed=OK" in captured.out

    def test_no_changes_push_skipped(self, tmp_path, books_dir, snapshots_dir, capsys):
        """No changes found → push not run → summary shows changed=no pushed=-."""
        write_book(books_dir, "my-thesis", make_book_json(room_id="room-uuid"))

        prev = snapshots_dir / "my-thesis-prev.json"
        prev.write_text(json.dumps({"v": 1}))
        latest = snapshots_dir / "my-thesis-latest.json"
        latest.write_text(json.dumps({"v": 1}))

        tg = make_thesisgraph_stub(tmp_path)
        diff = make_diff_stub(tmp_path, 1)   # no changes

        # Use an always-fail push stub to prove push is never called
        push = make_push_stub(tmp_path, exit_code=99)

        rc = run_main(["--books", str(books_dir)], snapshots_dir, tg, diff, push)
        captured = capsys.readouterr()
        assert rc == 0
        assert "changed=no" in captured.out
        assert "pushed=-" in captured.out

    def test_first_run_no_diff(self, tmp_path, books_dir, snapshots_dir, capsys):
        """First run (no prev snapshot) → diff and push skipped → [info] logged."""
        write_book(books_dir, "new-thesis", make_book_json(room_id="room-uuid"))
        # No pre-existing snapshot files

        tg = make_thesisgraph_stub(tmp_path)
        diff = make_diff_stub(tmp_path, exit_code=99)   # never reached
        push = make_push_stub(tmp_path, exit_code=99)   # never reached

        rc = run_main(["--books", str(books_dir)], snapshots_dir, tg, diff, push)
        captured = capsys.readouterr()
        assert rc == 0
        assert "[info]" in captured.err
        assert "first run" in captured.err


# =========================================================================
# CONFIGURATION / EDGE CASES
# =========================================================================

class TestConfiguration:
    def test_no_room_id_export_only(self, tmp_path, books_dir, snapshots_dir, capsys):
        """Book without dialecticRoomId exports but diff+push are skipped."""
        write_book(books_dir, "local-thesis", make_book_json(room_id=None))

        # Pre-create prev so first-run detection does not intercept first
        prev = snapshots_dir / "local-thesis-prev.json"
        prev.write_text(json.dumps({"v": 1}))
        latest = snapshots_dir / "local-thesis-latest.json"
        latest.write_text(json.dumps({"v": 1}))

        tg = make_thesisgraph_stub(tmp_path)
        diff = make_diff_stub(tmp_path, exit_code=99)
        push = make_push_stub(tmp_path, exit_code=99)

        rc = run_main(["--books", str(books_dir)], snapshots_dir, tg, diff, push)
        captured = capsys.readouterr()
        assert rc == 0
        assert "[warn]" in captured.err
        assert "no dialecticRoomId" in captured.err

    def test_empty_room_id_treated_as_absent(self, tmp_path, books_dir, snapshots_dir, capsys):
        """Empty-string dialecticRoomId is treated the same as absent."""
        write_book(books_dir, "local-thesis", make_book_json(room_id=""))

        prev = snapshots_dir / "local-thesis-prev.json"
        prev.write_text(json.dumps({"v": 1}))
        latest = snapshots_dir / "local-thesis-latest.json"
        latest.write_text(json.dumps({"v": 1}))

        tg = make_thesisgraph_stub(tmp_path)
        diff = make_diff_stub(tmp_path, exit_code=99)
        push = make_push_stub(tmp_path, exit_code=99)

        rc = run_main(["--books", str(books_dir)], snapshots_dir, tg, diff, push)
        captured = capsys.readouterr()
        assert rc == 0
        assert "no dialecticRoomId" in captured.err

    def test_books_dir_flag_overrides_default(self, tmp_path, snapshots_dir):
        """--books DIR flag is respected; only books in that directory are processed."""
        custom_books = tmp_path / "custom_books"
        custom_books.mkdir()
        write_book(custom_books, "custom-thesis", make_book_json())

        tg = make_thesisgraph_stub(tmp_path)
        diff = make_diff_stub(tmp_path, 1)
        push = make_push_stub(tmp_path)

        rc = run_main(
            ["--books", str(custom_books)],
            snapshots_dir, tg, diff, push,
        )
        assert rc == 0

    def test_missing_snapshots_dir_exits_two(self, tmp_path, books_dir):
        """Missing snapshots/ directory exits 2 with a clear error message."""
        write_book(books_dir, "my-thesis", make_book_json())
        bad_snapshots = tmp_path / "nonexistent-snapshots"
        # Do not create bad_snapshots

        tg = make_thesisgraph_stub(tmp_path)
        diff = make_diff_stub(tmp_path, 1)
        push = make_push_stub(tmp_path)

        rc = run_main(["--books", str(books_dir)], bad_snapshots, tg, diff, push)
        assert rc == 2


# =========================================================================
# FAILURE HANDLING
# =========================================================================

class TestFailureHandling:
    def test_thesisgraph_failure_marks_book_failed(
        self, tmp_path, books_dir, snapshots_dir, capsys
    ):
        """thesisgraph failure marks book as failed and runner exits 1."""
        write_book(books_dir, "fail-thesis", make_book_json())

        tg = make_thesisgraph_stub(tmp_path, exit_code=1)
        diff = make_diff_stub(tmp_path, 0)
        push = make_push_stub(tmp_path)

        rc = run_main(["--books", str(books_dir)], snapshots_dir, tg, diff, push)
        captured = capsys.readouterr()
        assert rc == 1
        assert "[error]" in captured.err

    def test_diff_error_exit2_marks_failed(
        self, tmp_path, books_dir, snapshots_dir, capsys
    ):
        """diff exit 2 marks book as failed; push is not called."""
        write_book(books_dir, "my-thesis", make_book_json(room_id="room-uuid"))
        prev = snapshots_dir / "my-thesis-prev.json"
        prev.write_text(json.dumps({"v": 1}))
        latest = snapshots_dir / "my-thesis-latest.json"
        latest.write_text(json.dumps({"v": 1}))

        tg = make_thesisgraph_stub(tmp_path)
        diff = make_diff_stub(tmp_path, 2)       # diff error
        push = make_push_stub(tmp_path, exit_code=99)  # never reached

        rc = run_main(["--books", str(books_dir)], snapshots_dir, tg, diff, push)
        captured = capsys.readouterr()
        assert rc == 1
        assert "[error]" in captured.err

    def test_push_failure_marks_book_failed(
        self, tmp_path, books_dir, snapshots_dir, capsys
    ):
        """Push failure marks book as failed; runner exits 1."""
        write_book(books_dir, "my-thesis", make_book_json(room_id="room-uuid"))
        prev = snapshots_dir / "my-thesis-prev.json"
        prev.write_text(json.dumps({"v": 1}))
        latest = snapshots_dir / "my-thesis-latest.json"
        latest.write_text(json.dumps({"v": 1}))

        tg = make_thesisgraph_stub(tmp_path)
        diff = make_diff_stub(tmp_path, 0)    # changes
        push = make_push_stub(tmp_path, exit_code=1)  # push fails

        rc = run_main(["--books", str(books_dir)], snapshots_dir, tg, diff, push)
        captured = capsys.readouterr()
        assert rc == 1
        assert "[error]" in captured.err
        assert "push failed" in captured.err

    def test_one_failure_others_continue(
        self, tmp_path, books_dir, snapshots_dir, capsys
    ):
        """One book failing does not abort other books; runner exits 1."""
        write_book(books_dir, "a-fail", make_book_json())
        write_book(books_dir, "b-ok", make_book_json())

        # Thesisgraph stub that fails for a-fail, succeeds for b-ok
        stub = tmp_path / "selective_tg.py"
        write_stub(stub, """
            import json, sys
            from pathlib import Path
            book_path = sys.argv[1]
            for i, arg in enumerate(sys.argv):
                if arg == "--export-state" and i + 1 < len(sys.argv):
                    out = sys.argv[i + 1]
                    snap = {"v": 1, "timestamp": "2026-01-01T00:00:00Z", "nodeStates": {}}
                    Path(out).write_text(json.dumps(snap))
                    break
            # Fail only for 'a-fail' book
            sys.exit(1 if "a-fail" in book_path else 0)
        """)

        diff = make_diff_stub(tmp_path, 1)   # no changes
        push = make_push_stub(tmp_path)

        rc = run_main(["--books", str(books_dir)], snapshots_dir, stub, diff, push)
        captured = capsys.readouterr()
        assert rc == 1
        # b-ok should appear in summary as OK
        assert "b-ok" in captured.out
        assert "export=OK" in captured.out

    def test_all_succeed_exits_zero(self, tmp_path, books_dir, snapshots_dir):
        """All books succeeding exits 0."""
        write_book(books_dir, "thesis-a", make_book_json())
        write_book(books_dir, "thesis-b", make_book_json())

        tg = make_thesisgraph_stub(tmp_path)
        diff = make_diff_stub(tmp_path, 1)   # no changes
        push = make_push_stub(tmp_path)

        rc = run_main(["--books", str(books_dir)], snapshots_dir, tg, diff, push)
        assert rc == 0


# =========================================================================
# DRY RUN
# =========================================================================

class TestDryRun:
    def test_dry_run_prints_book_info(self, tmp_path, books_dir, snapshots_dir, capsys):
        """--dry-run prints book ID, room ID, and snapshot paths without running anything."""
        write_book(books_dir, "iran-hormuz", make_book_json(room_id="abc-uuid"))
        write_book(books_dir, "trump-tariffs", make_book_json(room_id="def-uuid"))

        tg = make_thesisgraph_stub(tmp_path, exit_code=99)  # never called
        diff = make_diff_stub(tmp_path, exit_code=99)
        push = make_push_stub(tmp_path, exit_code=99)

        rc = run_main(
            ["--books", str(books_dir), "--dry-run"],
            snapshots_dir, tg, diff, push,
        )
        captured = capsys.readouterr()
        assert rc == 0
        assert "iran-hormuz" in captured.out
        assert "abc-uuid" in captured.out
        assert "trump-tariffs" in captured.out
        # No snapshot files should have been created
        assert not list(snapshots_dir.iterdir())

    def test_dry_run_no_subprocess_calls(self, tmp_path, books_dir, snapshots_dir):
        """--dry-run exits 0 even when stub scripts would fail."""
        write_book(books_dir, "my-thesis", make_book_json())

        tg = make_thesisgraph_stub(tmp_path, exit_code=1)
        diff = make_diff_stub(tmp_path, exit_code=2)
        push = make_push_stub(tmp_path, exit_code=1)

        rc = run_main(
            ["--books", str(books_dir), "--dry-run"],
            snapshots_dir, tg, diff, push,
        )
        assert rc == 0


# =========================================================================
# SNAPSHOT ROTATION
# =========================================================================

class TestSnapshotRotation:
    def test_prev_replaced_on_run(self, tmp_path, books_dir, snapshots_dir):
        """Pre-existing latest.json is copied to prev.json before export."""
        write_book(books_dir, "my-thesis", make_book_json())

        old_content = json.dumps({"v": 1, "timestamp": "old"})
        latest = snapshots_dir / "my-thesis-latest.json"
        latest.write_text(old_content)

        tg = make_thesisgraph_stub(tmp_path)   # writes new content to latest
        diff = make_diff_stub(tmp_path, 1)      # no changes
        push = make_push_stub(tmp_path)

        rc = run_main(["--books", str(books_dir)], snapshots_dir, tg, diff, push)
        assert rc == 0

        prev = snapshots_dir / "my-thesis-prev.json"
        assert prev.exists(), "prev.json should have been created from old latest"
        assert json.loads(prev.read_text()) == json.loads(old_content)

    def test_no_prev_on_first_run(self, tmp_path, books_dir, snapshots_dir):
        """If no latest.json exists, prev.json is not created (first-run path)."""
        write_book(books_dir, "new-thesis", make_book_json())

        tg = make_thesisgraph_stub(tmp_path)
        diff = make_diff_stub(tmp_path, exit_code=99)
        push = make_push_stub(tmp_path, exit_code=99)

        rc = run_main(["--books", str(books_dir)], snapshots_dir, tg, diff, push)
        assert rc == 0

        prev = snapshots_dir / "new-thesis-prev.json"
        assert not prev.exists(), "prev.json should not exist on first run"
        latest = snapshots_dir / "new-thesis-latest.json"
        assert latest.exists(), "latest.json should exist after export"
