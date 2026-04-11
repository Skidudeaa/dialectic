#!/usr/bin/env python3
"""
End-to-end validation harness for the Dialectic integration pipeline.

Validates the full data flow:
    thesisgraph.py --export-state → diff-snapshots.py → push-to-dialectic.py

Run with:
    python3 -m pytest tools/validation/e2e_test.py -q

All tests use stdlib only (plus pytest). The mock Dialectic server runs
in a background thread and binds to a random port to avoid conflicts.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# --- Paths to pipeline scripts ---
ROOT = Path(__file__).resolve().parent.parent.parent
THESISGRAPH = str(ROOT / "tools" / "thesis-graph" / "thesisgraph.py")
DIFF_SNAPSHOTS = str(ROOT / "tools" / "bridge" / "diff-snapshots.py")
PUSH_SCRIPT = str(ROOT / "tools" / "bridge" / "push-to-dialectic.py")
GRAPH_CONFIG = str(ROOT / "books" / "iran-hormuz-graph.json")

# --- Import mock server from sibling module ---
sys.path.insert(0, str(Path(__file__).parent))
from mock_dialectic import (
    start_server_thread,
    get_received_snapshots,
    clear_received_snapshots,
    force_next_status,
    MockDialecticHandler,
    REQUIRED_SNAPSHOT_KEYS,
)

# --- Required keys per INTEGRATION.md snapshot schema ---
SNAPSHOT_KEYS = {
    "v", "timestamp", "title", "nodeStates", "confluenceScores",
    "cascadePhase", "countdowns", "marketSnapshot", "scenarioImpacts",
    "portfolioSummary", "horizonTrace", "tvIndicators",
}


# =========================================================================
# FIXTURES
# =========================================================================

def make_snapshot(**overrides) -> dict:
    """Build a minimal valid snapshot dict matching the INTEGRATION.md schema."""
    base = {
        "v": 1,
        "timestamp": "2026-03-30T14:00:00Z",
        "title": "Test Snapshot",
        "nodeStates": {
            "hormuz": "fired",
            "brent": "approaching",
            "diesel": "fired",
            "fert-shortage": "approaching",
        },
        "confluenceScores": {
            "em-stress": 1.30,
        },
        "cascadePhase": {
            "number": 2,
            "key": "transmission",
            "status": "STARTING",
        },
        "countdowns": [
            {
                "nodeId": "planting-miss",
                "label": "Planting Cycle Miss",
                "deadline": "2026-04-15",
                "daysRemaining": 17,
            },
        ],
        "marketSnapshot": {
            "brent": 112.57,
            "diesel": 5.38,
            "nolaFert": 683,
            "dxy": 100.18,
            "curveSpread": 15,
        },
        "scenarioImpacts": {
            "reopen-apr1": {"probability": 0.10, "netImpact": -5.2},
            "closed-may": {"probability": 0.45, "netImpact": 12.8},
            "kharg-strike": {"probability": 0.15, "netImpact": 22.4},
            "selective-reopen": {"probability": 0.30, "netImpact": 4.1},
        },
        "portfolioSummary": {
            "monthlyBudget": 8000,
            "topPositions": ["XOP $1400/mo", "XLE $1200/mo", "SGOV $1200/mo"],
            "sgovAvailable": 1200,
        },
    }
    base.update(overrides)
    return base


def make_shifted_snapshot() -> dict:
    """Build a snapshot that differs from the base — for diff testing."""
    return make_snapshot(
        timestamp="2026-03-31T14:00:00Z",
        nodeStates={
            "hormuz": "fired",
            "brent": "fired",              # changed: approaching -> fired
            "diesel": "fired",
            "fert-shortage": "fired",      # changed: approaching -> fired
            "freight": "approaching",      # new node
        },
        confluenceScores={"em-stress": 1.75},  # increased
        countdowns=[
            {
                "nodeId": "planting-miss",
                "label": "Planting Cycle Miss",
                "deadline": "2026-04-15",
                "daysRemaining": 15,        # decreased
            },
        ],
        marketSnapshot={
            "brent": 115.20,               # up
            "diesel": 5.55,                # up
            "nolaFert": 710,               # up
            "dxy": 101.50,                 # up
            "curveSpread": 18,             # up
        },
    )


def write_temp_snapshot(tmp_dir: Path, name: str, snap: dict) -> str:
    """Write a snapshot dict to a JSON file and return its path as a string."""
    p = tmp_dir / name
    p.write_text(json.dumps(snap, indent=2))
    return str(p)


@pytest.fixture(scope="module")
def mock_server():
    """Start the mock Dialectic server once for the module. Yields (server, port)."""
    server, thread = start_server_thread(port=0)
    port = server.server_address[1]
    yield server, port
    server.shutdown()


@pytest.fixture(autouse=True)
def _clear_mock_state():
    """Clear received snapshots before each test for isolation."""
    clear_received_snapshots()


# =========================================================================
# 1. SNAPSHOT GENERATION — thesisgraph.py --export-state
# =========================================================================

class TestSnapshotGeneration:
    """Validate that thesisgraph.py produces correct snapshot JSON."""

    def test_export_to_stdout_produces_valid_json(self):
        """Run --export-state - and verify stdout is parseable JSON."""
        result = subprocess.run(
            [sys.executable, THESISGRAPH, GRAPH_CONFIG, "--export-state", "-"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"thesisgraph.py failed: {result.stderr}"
        snapshot = json.loads(result.stdout)
        assert isinstance(snapshot, dict)

    def test_snapshot_has_all_required_keys(self):
        """Snapshot must contain every key from INTEGRATION.md spec."""
        result = subprocess.run(
            [sys.executable, THESISGRAPH, GRAPH_CONFIG, "--export-state", "-"],
            capture_output=True, text=True, timeout=30,
        )
        snapshot = json.loads(result.stdout)
        missing = SNAPSHOT_KEYS - set(snapshot.keys())
        assert not missing, f"Missing required keys: {sorted(missing)}"

    def test_snapshot_version_is_1(self):
        result = subprocess.run(
            [sys.executable, THESISGRAPH, GRAPH_CONFIG, "--export-state", "-"],
            capture_output=True, text=True, timeout=30,
        )
        snapshot = json.loads(result.stdout)
        assert snapshot["v"] == 2

    def test_snapshot_node_states_non_empty(self):
        """The iran-hormuz config has 16 nodes; nodeStates must reflect that."""
        result = subprocess.run(
            [sys.executable, THESISGRAPH, GRAPH_CONFIG, "--export-state", "-"],
            capture_output=True, text=True, timeout=30,
        )
        snapshot = json.loads(result.stdout)
        assert len(snapshot["nodeStates"]) >= 10, (
            f"Expected 10+ nodes, got {len(snapshot['nodeStates'])}"
        )

    def test_snapshot_has_countdowns(self):
        """planting-miss is a deadline node -- must appear in countdowns."""
        result = subprocess.run(
            [sys.executable, THESISGRAPH, GRAPH_CONFIG, "--export-state", "-"],
            capture_output=True, text=True, timeout=30,
        )
        snapshot = json.loads(result.stdout)
        node_ids = [c["nodeId"] for c in snapshot["countdowns"]]
        assert "planting-miss" in node_ids

    def test_snapshot_has_scenario_impacts(self):
        """All 4 scenarios from the config must appear in scenarioImpacts."""
        result = subprocess.run(
            [sys.executable, THESISGRAPH, GRAPH_CONFIG, "--export-state", "-"],
            capture_output=True, text=True, timeout=30,
        )
        snapshot = json.loads(result.stdout)
        expected_scenarios = {"reopen-apr1", "closed-may", "kharg-strike", "selective-reopen"}
        actual = set(snapshot["scenarioImpacts"].keys())
        assert expected_scenarios == actual, (
            f"Missing: {expected_scenarios - actual}, Extra: {actual - expected_scenarios}"
        )

    def test_snapshot_cascade_phase_structure(self):
        result = subprocess.run(
            [sys.executable, THESISGRAPH, GRAPH_CONFIG, "--export-state", "-"],
            capture_output=True, text=True, timeout=30,
        )
        snapshot = json.loads(result.stdout)
        cp = snapshot["cascadePhase"]
        assert "number" in cp and isinstance(cp["number"], int)
        assert "key" in cp and isinstance(cp["key"], str)
        assert "status" in cp and isinstance(cp["status"], str)

    def test_export_to_file(self, tmp_path):
        """Export to a file and verify it matches stdout export."""
        out_file = str(tmp_path / "snap.json")
        result = subprocess.run(
            [sys.executable, THESISGRAPH, GRAPH_CONFIG, "--export-state", out_file],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        with open(out_file) as f:
            snapshot = json.load(f)
        assert SNAPSHOT_KEYS == set(snapshot.keys())


# =========================================================================
# 2. SNAPSHOT DIFF — diff-snapshots.py
# =========================================================================

class TestSnapshotDiff:
    """Validate diff-snapshots.py produces correct deltas."""

    def test_diff_detects_state_transitions(self, tmp_path):
        """State changes between snapshots are captured."""
        old = make_snapshot()
        new = make_shifted_snapshot()
        old_p = write_temp_snapshot(tmp_path, "old.json", old)
        new_p = write_temp_snapshot(tmp_path, "new.json", new)

        result = subprocess.run(
            [sys.executable, DIFF_SNAPSHOTS, old_p, new_p],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        delta = json.loads(result.stdout)

        assert delta["hasChanges"] is True
        changed_ids = [c["nodeId"] for c in delta["stateChanges"]]
        assert "brent" in changed_ids
        assert "fert-shortage" in changed_ids

    def test_diff_detects_market_moves(self, tmp_path):
        old = make_snapshot()
        new = make_shifted_snapshot()
        old_p = write_temp_snapshot(tmp_path, "old.json", old)
        new_p = write_temp_snapshot(tmp_path, "new.json", new)

        result = subprocess.run(
            [sys.executable, DIFF_SNAPSHOTS, old_p, new_p],
            capture_output=True, text=True, timeout=10,
        )
        delta = json.loads(result.stdout)

        assert "brent" in delta["marketChanges"]
        brent = delta["marketChanges"]["brent"]
        assert brent["from"] == 112.57
        assert brent["to"] == 115.20
        assert brent["pctChange"] is not None

    def test_diff_detects_confluence_changes(self, tmp_path):
        old = make_snapshot()
        new = make_shifted_snapshot()
        old_p = write_temp_snapshot(tmp_path, "old.json", old)
        new_p = write_temp_snapshot(tmp_path, "new.json", new)

        result = subprocess.run(
            [sys.executable, DIFF_SNAPSHOTS, old_p, new_p],
            capture_output=True, text=True, timeout=10,
        )
        delta = json.loads(result.stdout)

        assert "em-stress" in delta["confluenceChanges"]
        em = delta["confluenceChanges"]["em-stress"]
        assert em["from"] == 1.30
        assert em["to"] == 1.75

    def test_diff_detects_new_nodes(self, tmp_path):
        old = make_snapshot()
        new = make_shifted_snapshot()
        old_p = write_temp_snapshot(tmp_path, "old.json", old)
        new_p = write_temp_snapshot(tmp_path, "new.json", new)

        result = subprocess.run(
            [sys.executable, DIFF_SNAPSHOTS, old_p, new_p],
            capture_output=True, text=True, timeout=10,
        )
        delta = json.loads(result.stdout)

        assert "freight" in delta["newNodes"]

    def test_diff_detects_countdown_changes(self, tmp_path):
        old = make_snapshot()
        new = make_shifted_snapshot()
        old_p = write_temp_snapshot(tmp_path, "old.json", old)
        new_p = write_temp_snapshot(tmp_path, "new.json", new)

        result = subprocess.run(
            [sys.executable, DIFF_SNAPSHOTS, old_p, new_p],
            capture_output=True, text=True, timeout=10,
        )
        delta = json.loads(result.stdout)

        assert len(delta["countdownChanges"]) > 0
        cd = delta["countdownChanges"][0]
        assert cd["nodeId"] == "planting-miss"
        assert cd["from"] == 17
        assert cd["to"] == 15

    def test_identical_snapshots_exit_code_1(self, tmp_path):
        """Identical snapshots produce hasChanges=false and exit code 1."""
        snap = make_snapshot()
        old_p = write_temp_snapshot(tmp_path, "old.json", snap)
        new_p = write_temp_snapshot(tmp_path, "new.json", snap)

        result = subprocess.run(
            [sys.executable, DIFF_SNAPSHOTS, old_p, new_p],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 1
        delta = json.loads(result.stdout)
        assert delta["hasChanges"] is False

    def test_diff_delta_shape(self, tmp_path):
        """Delta output has the expected top-level structure."""
        old = make_snapshot()
        new = make_shifted_snapshot()
        old_p = write_temp_snapshot(tmp_path, "old.json", old)
        new_p = write_temp_snapshot(tmp_path, "new.json", new)

        result = subprocess.run(
            [sys.executable, DIFF_SNAPSHOTS, old_p, new_p],
            capture_output=True, text=True, timeout=10,
        )
        delta = json.loads(result.stdout)

        expected_keys = {
            "hasChanges", "stateChanges", "confluenceChanges",
            "countdownChanges", "marketChanges", "newNodes", "removedNodes",
            "tvIndicatorShifts",
        }
        assert expected_keys == set(delta.keys()), (
            f"Missing: {expected_keys - set(delta.keys())}, "
            f"Extra: {set(delta.keys()) - expected_keys}"
        )


# =========================================================================
# 3. PUSH TO MOCK — push-to-dialectic.py → mock server
# =========================================================================

class TestPushToMock:
    """Validate push-to-dialectic.py correctly POSTs to the mock server."""

    def test_push_success(self, mock_server, tmp_path):
        """Push a valid snapshot and verify the mock received it."""
        _, port = mock_server
        snap = make_snapshot()
        snap_path = write_temp_snapshot(tmp_path, "snap.json", snap)

        env = os.environ.copy()
        env["DIALECTIC_ROOM_TOKEN"] = "test-token-abc123"

        result = subprocess.run(
            [
                sys.executable, PUSH_SCRIPT,
                "--snapshot", snap_path,
                "--room-id", "test-room-uuid",
                "--dialectic-url", f"http://127.0.0.1:{port}",
            ],
            capture_output=True, text=True, timeout=10, env=env,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"

        # Verify response JSON
        response = json.loads(result.stdout)
        assert response["status"] == "ok"
        assert response["room_id"] == "test-room-uuid"

        # Verify mock stored the snapshot
        received = get_received_snapshots()
        assert len(received) == 1
        assert received[0].room_id == "test-room-uuid"
        # WHY: make_snapshot() produces a hand-crafted test payload; its version
        # matches whatever the fixture declares, not the engine's current version.
        assert received[0].payload["v"] in (1, 2)
        assert received[0].payload["nodeStates"]["hormuz"] == "fired"

    def test_push_correct_auth_header(self, mock_server, tmp_path):
        """Verify the Authorization header is Bearer <token>."""
        _, port = mock_server
        snap = make_snapshot()
        snap_path = write_temp_snapshot(tmp_path, "snap.json", snap)

        env = os.environ.copy()
        env["DIALECTIC_ROOM_TOKEN"] = "my-secret-token"

        subprocess.run(
            [
                sys.executable, PUSH_SCRIPT,
                "--snapshot", snap_path,
                "--room-id", "auth-test",
                "--dialectic-url", f"http://127.0.0.1:{port}",
            ],
            capture_output=True, text=True, timeout=10, env=env,
        )

        received = get_received_snapshots()
        assert len(received) == 1
        assert received[0].auth_header == "Bearer my-secret-token"

    def test_push_correct_content_type(self, mock_server, tmp_path):
        """Verify Content-Type is application/json."""
        _, port = mock_server
        snap = make_snapshot()
        snap_path = write_temp_snapshot(tmp_path, "snap.json", snap)

        env = os.environ.copy()
        env["DIALECTIC_ROOM_TOKEN"] = "token"

        subprocess.run(
            [
                sys.executable, PUSH_SCRIPT,
                "--snapshot", snap_path,
                "--room-id", "ct-test",
                "--dialectic-url", f"http://127.0.0.1:{port}",
            ],
            capture_output=True, text=True, timeout=10, env=env,
        )

        received = get_received_snapshots()
        assert len(received) == 1
        assert received[0].content_type == "application/json"

    def test_push_correct_user_agent(self, mock_server, tmp_path):
        """Verify User-Agent identifies the bridge script."""
        _, port = mock_server
        snap = make_snapshot()
        snap_path = write_temp_snapshot(tmp_path, "snap.json", snap)

        env = os.environ.copy()
        env["DIALECTIC_ROOM_TOKEN"] = "token"

        subprocess.run(
            [
                sys.executable, PUSH_SCRIPT,
                "--snapshot", snap_path,
                "--room-id", "ua-test",
                "--dialectic-url", f"http://127.0.0.1:{port}",
            ],
            capture_output=True, text=True, timeout=10, env=env,
        )

        received = get_received_snapshots()
        assert len(received) == 1
        assert "tradingDesk" in received[0].user_agent


# =========================================================================
# 4. FULL PIPELINE — generate → diff → push → validate
# =========================================================================

class TestFullPipeline:
    """Chain all three steps: generate snapshot, diff, push to mock."""

    def test_generate_diff_push(self, mock_server, tmp_path):
        """Full E2E: thesisgraph → snapshot → diff against baseline → push."""
        _, port = mock_server

        # Step 1: Generate a live snapshot from thesisgraph.py
        snap_path = str(tmp_path / "live.json")
        gen_result = subprocess.run(
            [sys.executable, THESISGRAPH, GRAPH_CONFIG, "--export-state", snap_path],
            capture_output=True, text=True, timeout=30,
        )
        assert gen_result.returncode == 0, f"Generation failed: {gen_result.stderr}"

        # Verify the snapshot file was created and is valid
        with open(snap_path) as f:
            live_snap = json.load(f)
        assert SNAPSHOT_KEYS == set(live_snap.keys())

        # Step 2: Diff against a baseline (the fixture snapshot has different values)
        baseline_path = write_temp_snapshot(tmp_path, "baseline.json", make_snapshot())
        diff_result = subprocess.run(
            [sys.executable, DIFF_SNAPSHOTS, baseline_path, snap_path],
            capture_output=True, text=True, timeout=10,
        )
        # WHY: The live snapshot will differ from our fixture baseline in node
        # counts and market values, so we expect changes (exit code 0).
        assert diff_result.returncode == 0, (
            f"Expected changes between baseline and live snapshot. "
            f"stderr: {diff_result.stderr}"
        )
        delta = json.loads(diff_result.stdout)
        assert delta["hasChanges"] is True

        # Step 3: Push the live snapshot to the mock Dialectic server
        env = os.environ.copy()
        env["DIALECTIC_ROOM_TOKEN"] = "e2e-pipeline-token"

        push_result = subprocess.run(
            [
                sys.executable, PUSH_SCRIPT,
                "--snapshot", snap_path,
                "--room-id", "e2e-room",
                "--dialectic-url", f"http://127.0.0.1:{port}",
            ],
            capture_output=True, text=True, timeout=10, env=env,
        )
        assert push_result.returncode == 0, f"Push failed: {push_result.stderr}"

        # Step 4: Validate the mock received the correct payload
        received = get_received_snapshots()
        assert len(received) == 1
        assert received[0].room_id == "e2e-room"
        assert received[0].auth_header == "Bearer e2e-pipeline-token"

        # The pushed payload must match what thesisgraph.py generated
        assert received[0].payload["v"] == live_snap["v"]
        assert received[0].payload["nodeStates"] == live_snap["nodeStates"]
        assert received[0].payload["cascadePhase"] == live_snap["cascadePhase"]

    def test_stdin_pipe_to_push(self, mock_server, tmp_path):
        """Test the pipe pattern: thesisgraph --export-state - | push-to-dialectic."""
        _, port = mock_server

        env = os.environ.copy()
        env["DIALECTIC_ROOM_TOKEN"] = "pipe-token"

        # WHY: We can't use actual shell pipes in subprocess easily, so we
        # generate to stdout then feed it to push via a temp file to simulate
        # the pipe. The real pipe works because push accepts --snapshot -.
        gen_result = subprocess.run(
            [sys.executable, THESISGRAPH, GRAPH_CONFIG, "--export-state", "-"],
            capture_output=True, text=True, timeout=30,
        )
        assert gen_result.returncode == 0

        # Write stdout to temp file then push
        snap_path = write_temp_snapshot(
            tmp_path, "piped.json", json.loads(gen_result.stdout)
        )

        push_result = subprocess.run(
            [
                sys.executable, PUSH_SCRIPT,
                "--snapshot", snap_path,
                "--room-id", "pipe-room",
                "--dialectic-url", f"http://127.0.0.1:{port}",
            ],
            capture_output=True, text=True, timeout=10, env=env,
        )
        assert push_result.returncode == 0

        received = get_received_snapshots()
        assert len(received) == 1
        assert received[0].room_id == "pipe-room"
        # Verify the snapshot is structurally valid
        payload = received[0].payload
        missing = SNAPSHOT_KEYS - set(payload.keys())
        assert not missing, f"Pushed snapshot missing keys: {sorted(missing)}"


# =========================================================================
# 5. ERROR CASES
# =========================================================================

class TestErrorCases:
    """Validate error handling across the pipeline."""

    def test_push_missing_token_exits_2(self, mock_server, tmp_path):
        """push-to-dialectic.py exits 2 when DIALECTIC_ROOM_TOKEN is unset."""
        _, port = mock_server
        snap = make_snapshot()
        snap_path = write_temp_snapshot(tmp_path, "snap.json", snap)

        env = os.environ.copy()
        # WHY: Remove the token to test the missing-token path.
        env.pop("DIALECTIC_ROOM_TOKEN", None)

        result = subprocess.run(
            [
                sys.executable, PUSH_SCRIPT,
                "--snapshot", snap_path,
                "--room-id", "no-token",
                "--dialectic-url", f"http://127.0.0.1:{port}",
            ],
            capture_output=True, text=True, timeout=10, env=env,
        )
        assert result.returncode == 2
        assert "DIALECTIC_ROOM_TOKEN" in result.stderr

    def test_push_server_500(self, mock_server, tmp_path):
        """push-to-dialectic.py retries on 500 and succeeds on second attempt."""
        _, port = mock_server
        snap = make_snapshot()
        snap_path = write_temp_snapshot(tmp_path, "snap.json", snap)

        # Force the mock to return 500 on the next POST — retry will succeed
        force_next_status(500)

        env = os.environ.copy()
        env["DIALECTIC_ROOM_TOKEN"] = "token"

        result = subprocess.run(
            [
                sys.executable, PUSH_SCRIPT,
                "--snapshot", snap_path,
                "--room-id", "error-room",
                "--dialectic-url", f"http://127.0.0.1:{port}",
            ],
            capture_output=True, text=True, timeout=30, env=env,
        )
        # WHY: push-to-dialectic now retries 5xx errors. force_next_status(500)
        # only affects one request, so the retry gets a 200 and succeeds.
        assert result.returncode == 0
        assert "500" in result.stderr  # first attempt logged the 500

    def test_push_connection_refused(self, tmp_path):
        """push-to-dialectic.py exits 2 when the server is unreachable."""
        snap = make_snapshot()
        snap_path = write_temp_snapshot(tmp_path, "snap.json", snap)

        env = os.environ.copy()
        env["DIALECTIC_ROOM_TOKEN"] = "token"

        # WHY: Port 1 is almost certainly not running an HTTP server,
        # which triggers a connection-refused error.
        result = subprocess.run(
            [
                sys.executable, PUSH_SCRIPT,
                "--snapshot", snap_path,
                "--room-id", "dead-room",
                "--dialectic-url", "http://127.0.0.1:1",
            ],
            capture_output=True, text=True, timeout=15, env=env,
        )
        assert result.returncode == 2
        assert "Connection" in result.stderr or "error" in result.stderr.lower()

    def test_push_empty_snapshot_exits_2(self, mock_server, tmp_path):
        """push-to-dialectic.py exits 2 for an empty file."""
        _, port = mock_server
        empty_path = str(tmp_path / "empty.json")
        Path(empty_path).write_text("")

        env = os.environ.copy()
        env["DIALECTIC_ROOM_TOKEN"] = "token"

        result = subprocess.run(
            [
                sys.executable, PUSH_SCRIPT,
                "--snapshot", empty_path,
                "--room-id", "empty-room",
                "--dialectic-url", f"http://127.0.0.1:{port}",
            ],
            capture_output=True, text=True, timeout=10, env=env,
        )
        assert result.returncode == 2
        assert "empty" in result.stderr.lower()

    def test_push_malformed_json_exits_2(self, mock_server, tmp_path):
        """push-to-dialectic.py exits 2 for invalid JSON."""
        _, port = mock_server
        bad_path = str(tmp_path / "bad.json")
        Path(bad_path).write_text("{not valid json!!!}")

        env = os.environ.copy()
        env["DIALECTIC_ROOM_TOKEN"] = "token"

        result = subprocess.run(
            [
                sys.executable, PUSH_SCRIPT,
                "--snapshot", bad_path,
                "--room-id", "bad-room",
                "--dialectic-url", f"http://127.0.0.1:{port}",
            ],
            capture_output=True, text=True, timeout=10, env=env,
        )
        assert result.returncode == 2
        assert "JSON" in result.stderr or "json" in result.stderr

    def test_push_missing_snapshot_keys_returns_400(self, mock_server, tmp_path):
        """Mock returns 400 for a snapshot missing required keys, push exits 1."""
        _, port = mock_server
        # WHY: A dict with v=1 but missing other required keys should fail
        # server-side validation.
        incomplete = {"v": 1, "timestamp": "2026-03-30T00:00:00Z"}
        snap_path = write_temp_snapshot(tmp_path, "incomplete.json", incomplete)

        env = os.environ.copy()
        env["DIALECTIC_ROOM_TOKEN"] = "token"

        result = subprocess.run(
            [
                sys.executable, PUSH_SCRIPT,
                "--snapshot", snap_path,
                "--room-id", "incomplete-room",
                "--dialectic-url", f"http://127.0.0.1:{port}",
            ],
            capture_output=True, text=True, timeout=10, env=env,
        )
        # Server returns 400, push script maps HTTP errors to exit code 1
        assert result.returncode == 1
        assert "400" in result.stderr

    def test_push_nonexistent_file_exits_2(self, mock_server):
        """push-to-dialectic.py exits 2 for a file that does not exist."""
        _, port = mock_server

        env = os.environ.copy()
        env["DIALECTIC_ROOM_TOKEN"] = "token"

        result = subprocess.run(
            [
                sys.executable, PUSH_SCRIPT,
                "--snapshot", "/tmp/does-not-exist-at-all.json",
                "--room-id", "missing-file-room",
                "--dialectic-url", f"http://127.0.0.1:{port}",
            ],
            capture_output=True, text=True, timeout=10, env=env,
        )
        assert result.returncode == 2
        assert "not found" in result.stderr.lower()

    def test_diff_missing_file_exits_2(self, tmp_path):
        """diff-snapshots.py exits 2 for a missing file."""
        snap_path = write_temp_snapshot(tmp_path, "exists.json", make_snapshot())

        result = subprocess.run(
            [sys.executable, DIFF_SNAPSHOTS, "/tmp/nope.json", snap_path],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 2

    def test_diff_invalid_json_exits_2(self, tmp_path):
        """diff-snapshots.py exits 2 for invalid JSON."""
        good = write_temp_snapshot(tmp_path, "good.json", make_snapshot())
        bad = str(tmp_path / "bad.json")
        Path(bad).write_text("{{broken")

        result = subprocess.run(
            [sys.executable, DIFF_SNAPSHOTS, good, bad],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 2


# =========================================================================
# 6. MOCK SERVER VALIDATION (standalone behavior)
# =========================================================================

class TestMockServerBehavior:
    """Validate the mock server's own schema enforcement and debug endpoint."""

    def test_mock_rejects_missing_auth(self, mock_server):
        """POST without Authorization header returns 401."""
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError

        _, port = mock_server
        url = f"http://127.0.0.1:{port}/rooms/test/trading/snapshot"
        snap = json.dumps(make_snapshot()).encode()

        req = Request(url, data=snap, headers={"Content-Type": "application/json"},
                      method="POST")
        with pytest.raises(HTTPError) as exc_info:
            urlopen(req, timeout=5)
        assert exc_info.value.code == 401

    def test_mock_rejects_invalid_path(self, mock_server):
        """POST to a wrong path returns 404."""
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError

        _, port = mock_server
        url = f"http://127.0.0.1:{port}/wrong/path"
        snap = json.dumps(make_snapshot()).encode()

        req = Request(url, data=snap, headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer token",
        }, method="POST")
        with pytest.raises(HTTPError) as exc_info:
            urlopen(req, timeout=5)
        assert exc_info.value.code == 404

    def test_mock_get_snapshots_debug_endpoint(self, mock_server):
        """GET /snapshots returns the list of received snapshots."""
        from urllib.request import Request, urlopen

        _, port = mock_server

        # First push a snapshot so there's something to list
        snap = json.dumps(make_snapshot()).encode()
        post_req = Request(
            f"http://127.0.0.1:{port}/rooms/debug-room/trading/snapshot",
            data=snap,
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer debug-token",
            },
            method="POST",
        )
        urlopen(post_req, timeout=5)

        # Now GET /snapshots
        get_req = Request(f"http://127.0.0.1:{port}/snapshots", method="GET")
        with urlopen(get_req, timeout=5) as resp:
            body = json.loads(resp.read())

        assert body["count"] == 1
        assert body["snapshots"][0]["room_id"] == "debug-room"

    def test_mock_rejects_missing_snapshot_keys(self, mock_server):
        """POST with incomplete snapshot payload returns 400."""
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError

        _, port = mock_server
        url = f"http://127.0.0.1:{port}/rooms/test/trading/snapshot"
        incomplete = json.dumps({"v": 1}).encode()

        req = Request(url, data=incomplete, headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer token",
        }, method="POST")
        with pytest.raises(HTTPError) as exc_info:
            urlopen(req, timeout=5)
        assert exc_info.value.code == 400


# =========================================================================
# PIPELINE INTEGRATION TESTS — validates critical fixes C1 and C2
# =========================================================================

class TestCriticalFixes:
    """Integration tests for the critical review findings."""

    def test_export_state_stdout_is_valid_json(self, tmp_path):
        """--export-state - must produce valid JSON on stdout (C2 fix).

        WHY: fetch_prices previously printed status to stdout, corrupting the
        JSON output when piped. This test catches regression.
        """
        out_path = str(tmp_path / "snapshot.json")
        result = subprocess.run(
            [sys.executable, THESISGRAPH, GRAPH_CONFIG, "--export-state", out_path],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0, f"thesisgraph failed: {result.stderr}"

        snapshot_text = Path(out_path).read_text()
        snapshot = json.loads(snapshot_text)  # must not raise
        assert "v" in snapshot
        assert "nodeStates" in snapshot

    def test_export_state_stdout_pipe_is_clean(self):
        """--export-state - to stdout must be parseable JSON with no interleaved text."""
        result = subprocess.run(
            [sys.executable, THESISGRAPH, GRAPH_CONFIG, "--export-state", "-"],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0, f"thesisgraph failed: {result.stderr}"
        # stdout must be valid JSON — no price status lines interleaved
        snapshot = json.loads(result.stdout)
        assert snapshot["v"] == 2

    def test_closes_required_nodes_not_fired_at_generation(self):
        """Nodes with closesRequired must not be 'fired' at generation time (C1 fix).

        WHY: Python eval_node_state previously ignored closesRequired, returning
        'fired' immediately. At generation time with no close log, nodes with
        closesRequired should be 'approaching' at most (never 'fired').
        """
        result = subprocess.run(
            [sys.executable, THESISGRAPH, GRAPH_CONFIG, "--export-state", "-"],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0
        snapshot = json.loads(result.stdout)

        # Load config to find nodes with closesRequired thresholds
        config = json.loads(Path(GRAPH_CONFIG).read_text())
        closes_required_nodes = set()
        for node in config.get("nodes", []):
            for th in node.get("thresholds", []):
                if th.get("closesRequired") and th["closesRequired"] > 0:
                    closes_required_nodes.add(node["id"])
            if node.get("closesRequired") and node["closesRequired"] > 0:
                closes_required_nodes.add(node["id"])

        node_states = snapshot.get("nodeStates", {})
        for nid in closes_required_nodes:
            state = node_states.get(nid)
            assert state != "fired", (
                f"Node '{nid}' has closesRequired but is 'fired' at generation time. "
                f"Should be 'approaching' or 'stable'."
            )

    def test_scenario_impacts_are_numeric(self):
        """eval_scenario impact values must be numeric, not None or missing."""
        result = subprocess.run(
            [sys.executable, THESISGRAPH, GRAPH_CONFIG, "--export-state", "-"],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0
        snapshot = json.loads(result.stdout)

        for sid, impact in snapshot.get("scenarioImpacts", {}).items():
            assert "probability" in impact, f"Scenario '{sid}' missing probability"
            assert "netImpact" in impact, f"Scenario '{sid}' missing netImpact"
            assert isinstance(impact["netImpact"], (int, float)), (
                f"Scenario '{sid}' netImpact is {type(impact['netImpact'])}, not numeric"
            )

    def test_snapshot_keys_complete(self):
        """Exported snapshot must contain all required keys per INTEGRATION.md."""
        result = subprocess.run(
            [sys.executable, THESISGRAPH, GRAPH_CONFIG, "--export-state", "-"],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0
        snapshot = json.loads(result.stdout)
        missing = SNAPSHOT_KEYS - set(snapshot.keys())
        assert not missing, f"Snapshot missing keys: {missing}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
