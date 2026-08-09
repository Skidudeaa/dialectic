"""
Shared pytest fixtures for tools/bridge/ tests.

WHY: push_to_dialectic.py spools failed pushes to a module-level OUTBOX_DIR
(snapshots/outbox/ in the repo root). Without isolation, every test that
exercises the failure path leaks files into the real outbox, which then
get replayed by the *next* test's first push call -- breaking request-count
assertions and creating cross-test order coupling.

The autouse fixture below points OUTBOX_DIR at a per-test tmp directory.
Tests that want to inspect the outbox directly can still monkeypatch it.
"""

import importlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

push_mod = importlib.import_module("push_to_dialectic")


@pytest.fixture(autouse=True)
def _isolate_outbox(tmp_path, monkeypatch):
    """Redirect OUTBOX_DIR to a per-test tmp directory."""
    outbox = tmp_path / "_outbox"
    monkeypatch.setattr(push_mod, "OUTBOX_DIR", outbox)
    yield outbox
