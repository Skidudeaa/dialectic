"""
Tests for the audit_log + confirm_tokens migration (Unit 12).

WHY: These tables back every destructive action in the cockpit (trade
kill, scenario apply, builder delete). The invariants we test:
  - the migration creates both tables idempotently,
  - audit rows round-trip cleanly with payload JSON,
  - list_audit honors all three filters and the limit cap,
  - confirm tokens are 16-byte hex (32 chars) and cryptographically random,
  - tokens consume exactly once and are bound to (actor, action, target),
  - expired tokens are rejected and can be purged in bulk,
  - concurrent issuance never collides on the PK.
"""

import re
import threading
from datetime import datetime, timedelta, timezone

import pytest

from web.persistence.repository import Repository


@pytest.fixture
def repo():
    """Fresh in-memory SQLite database per test."""
    r = Repository(":memory:")
    r.initialize()
    return r


# ═══════════════════════════════════════════════════════════════════════
# MIGRATION
# ═══════════════════════════════════════════════════════════════════════

class TestMigration:
    def test_creates_audit_and_confirm_tables(self, repo):
        conn = repo._conn()
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        assert "audit_log" in tables
        assert "confirm_tokens" in tables
        conn.close()

    def test_idempotent(self, repo):
        """Running migrations a second time applies nothing new and does
        not raise — IF NOT EXISTS guards every CREATE."""
        # First call already happened in the fixture.
        applied = repo.initialize()
        assert applied == 0


# ═══════════════════════════════════════════════════════════════════════
# AUDIT LOG
# ═══════════════════════════════════════════════════════════════════════

class TestAuditLog:
    def test_add_audit_row_returns_id(self, repo):
        row_id = repo.add_audit_row(
            actor="amo", action="trade.kill", target="TRD-XOP-HORMUZ",
            reason="thesis broke", confirm_token="abc",
            payload={"trade_id": "TRD-XOP-HORMUZ", "reason": "thesis broke"},
        )
        assert isinstance(row_id, int) and row_id > 0

    def test_round_trip_payload(self, repo):
        repo.add_audit_row(
            actor="amo", action="trade.kill", target="TRD-A",
            reason="r", payload={"k": "v", "n": 7},
        )
        rows = repo.list_audit()
        assert len(rows) == 1
        assert rows[0]["actor"] == "amo"
        assert rows[0]["action"] == "trade.kill"
        assert rows[0]["target"] == "TRD-A"
        assert rows[0]["reason"] == "r"
        assert rows[0]["payload"] == {"k": "v", "n": 7}

    def test_null_payload_returns_none(self, repo):
        repo.add_audit_row(actor="dan", action="x.y", target="t1")
        rows = repo.list_audit()
        assert rows[0]["payload"] is None
        assert rows[0]["reason"] is None
        assert rows[0]["confirm_token"] is None

    def test_filter_by_actor(self, repo):
        repo.add_audit_row(actor="amo", action="trade.kill", target="t1")
        repo.add_audit_row(actor="dan", action="trade.kill", target="t2")
        repo.add_audit_row(actor="amo", action="trade.kill", target="t3")
        rows = repo.list_audit(actor="amo")
        assert len(rows) == 2
        assert {r["target"] for r in rows} == {"t1", "t3"}

    def test_filter_by_action(self, repo):
        repo.add_audit_row(actor="amo", action="trade.kill", target="t1")
        repo.add_audit_row(actor="amo", action="scenario.apply", target="s1")
        rows = repo.list_audit(action="scenario.apply")
        assert len(rows) == 1
        assert rows[0]["target"] == "s1"

    def test_filter_by_since(self, repo):
        # Insert a row, then capture a timestamp AFTER it, then insert two more.
        repo.add_audit_row(actor="amo", action="x.y", target="t1")
        # Sleep-free cutoff: use the inserted ts as the boundary.
        cutoff = repo.list_audit()[0]["ts"]
        # Fabricate a later timestamp by adding 1 second.
        later = (
            datetime.fromisoformat(cutoff) + timedelta(seconds=1)
        ).isoformat()
        # We can't easily insert with a custom ts via the public API, so
        # instead: query "since cutoff" — should return at least the row
        # we just inserted (ts >= cutoff).
        rows = repo.list_audit(since_iso=cutoff)
        assert len(rows) == 1
        # Far-future cutoff returns nothing.
        rows = repo.list_audit(since_iso=later)
        assert rows == []

    def test_limit_caps_rowcount(self, repo):
        for i in range(10):
            repo.add_audit_row(actor="amo", action="x.y", target=f"t{i}")
        rows = repo.list_audit(limit=3)
        assert len(rows) == 3
        # Newest-first: the last-inserted target ("t9") comes first.
        assert rows[0]["target"] == "t9"

    def test_combined_filters(self, repo):
        repo.add_audit_row(actor="amo", action="trade.kill", target="t1")
        repo.add_audit_row(actor="amo", action="scenario.apply", target="s1")
        repo.add_audit_row(actor="dan", action="trade.kill", target="t2")
        rows = repo.list_audit(actor="amo", action="trade.kill")
        assert len(rows) == 1
        assert rows[0]["target"] == "t1"


# ═══════════════════════════════════════════════════════════════════════
# CONFIRM TOKENS
# ═══════════════════════════════════════════════════════════════════════

class TestConfirmTokens:
    def test_issue_returns_hex_token(self, repo):
        rec = repo.issue_confirm_token("amo", "trade.kill", "TRD-A")
        assert "token" in rec and "expires_at" in rec
        # 16 random bytes hex-encoded → 32 chars, lowercase hex only.
        assert re.fullmatch(r"[0-9a-f]{32}", rec["token"])

    def test_issue_persists_actor_action_target(self, repo):
        rec = repo.issue_confirm_token("amo", "trade.kill", "TRD-A")
        # Inspect the stored row directly.
        conn = repo._conn()
        row = conn.execute(
            "SELECT * FROM confirm_tokens WHERE token = ?", (rec["token"],),
        ).fetchone()
        conn.close()
        assert row["actor"] == "amo"
        assert row["action"] == "trade.kill"
        assert row["target"] == "TRD-A"
        assert row["consumed_at"] is None

    def test_consume_returns_true_once(self, repo):
        rec = repo.issue_confirm_token("amo", "trade.kill", "TRD-A")
        ok = repo.consume_confirm_token(rec["token"], "amo", "trade.kill", "TRD-A")
        assert ok is True

    def test_consume_returns_false_second_time(self, repo):
        rec = repo.issue_confirm_token("amo", "trade.kill", "TRD-A")
        repo.consume_confirm_token(rec["token"], "amo", "trade.kill", "TRD-A")
        ok = repo.consume_confirm_token(rec["token"], "amo", "trade.kill", "TRD-A")
        assert ok is False

    def test_consume_unknown_token_returns_false(self, repo):
        ok = repo.consume_confirm_token("0" * 32, "amo", "trade.kill", "TRD-A")
        assert ok is False

    def test_consume_mismatched_actor_returns_false(self, repo):
        rec = repo.issue_confirm_token("amo", "trade.kill", "TRD-A")
        ok = repo.consume_confirm_token(rec["token"], "dan", "trade.kill", "TRD-A")
        assert ok is False

    def test_consume_mismatched_action_returns_false(self, repo):
        rec = repo.issue_confirm_token("amo", "trade.kill", "TRD-A")
        ok = repo.consume_confirm_token(rec["token"], "amo", "scenario.apply", "TRD-A")
        assert ok is False

    def test_consume_mismatched_target_returns_false(self, repo):
        rec = repo.issue_confirm_token("amo", "trade.kill", "TRD-A")
        ok = repo.consume_confirm_token(rec["token"], "amo", "trade.kill", "TRD-B")
        assert ok is False

    def test_expired_token_consume_returns_false(self, repo):
        rec = repo.issue_confirm_token("amo", "trade.kill", "TRD-A", ttl_seconds=30)
        # Rewind expires_at to the distant past.
        conn = repo._conn()
        conn.execute(
            "UPDATE confirm_tokens SET expires_at = '1970-01-01T00:00:00+00:00' WHERE token = ?",
            (rec["token"],),
        )
        conn.commit()
        conn.close()
        ok = repo.consume_confirm_token(rec["token"], "amo", "trade.kill", "TRD-A")
        assert ok is False

    def test_purge_drops_only_expired(self, repo):
        # One expired, one fresh.
        a = repo.issue_confirm_token("amo", "trade.kill", "TRD-A")
        b = repo.issue_confirm_token("amo", "trade.kill", "TRD-B")
        conn = repo._conn()
        conn.execute(
            "UPDATE confirm_tokens SET expires_at = '1970-01-01T00:00:00+00:00' WHERE token = ?",
            (a["token"],),
        )
        conn.commit()
        conn.close()
        purged = repo.purge_expired_confirm_tokens()
        assert purged == 1
        # The fresh token still works.
        ok = repo.consume_confirm_token(b["token"], "amo", "trade.kill", "TRD-B")
        assert ok is True

    def test_concurrent_issue_unique_tokens(self, tmp_path):
        """50 threads issuing tokens — every one must be distinct.

        WHY: secrets.token_hex(16) collisions are astronomically
        unlikely, but the PK constraint would surface a collision as a
        loud IntegrityError. This test would catch a regression where
        someone swapped in a non-secure (e.g. time-seeded) generator.

        WHY a file-backed DB here: the in-memory shared-cache DB has a
        single writer-lock across all threads with very tight
        contention; WAL mode on a real file lets the 50 writes
        serialize cleanly without "database table is locked" errors.
        """
        repo = Repository(tmp_path / "concurrent.db")
        repo.initialize()

        tokens: list = []
        errors: list = []
        lock = threading.Lock()

        def worker(idx):
            try:
                rec = repo.issue_confirm_token("amo", "trade.kill", f"TRD-{idx}")
                with lock:
                    tokens.append(rec["token"])
            except Exception as e:
                with lock:
                    errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert len(tokens) == 50
        assert len(set(tokens)) == 50  # all unique
