"""
Tests for the nightly retention task.

WHY the exact-survivor assertions matter more than the counts: this is the
only code in the desk that deletes committed history. A prune that keeps the
right NUMBER of rows while keeping the wrong ones is indistinguishable from a
correct one until someone scrolls back six weeks and finds a hole — by which
time the rows are gone. Every prune test here names the surviving revisions.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from web.persistence.repository import Repository
from web.runtime.maintenance import (
    DEFAULT_KEEP_RECENT,
    LAST_VACUUM_KEY,
    MaintenanceTask,
    next_run_at,
    should_vacuum,
)

UTC = timezone.utc


@pytest.fixture
def repo():
    r = Repository(":memory:")
    r.initialize()
    return r


def seed_snapshots(repo: Repository, thesis_id: str,
                   revisions_by_day: dict) -> None:
    """Insert snapshots with controlled generated_at.

    WHY raw SQL: save_snapshot() stamps generated_at with _now_iso(), so
    there is no supported way to build a fixture that spans days. The
    retention rule is defined in terms of that column, so the fixture has to
    own it.
    """
    conn = repo._conn()
    try:
        for day, revisions in revisions_by_day.items():
            for i, rev in enumerate(revisions):
                conn.execute(
                    """INSERT INTO thesis_snapshots
                       (thesis_id, revision, generated_at, snapshot_json)
                       VALUES (?, ?, ?, ?)""",
                    (thesis_id, rev, f"{day}T{i % 24:02d}:15:00+00:00", "{}"),
                )
        conn.commit()
    finally:
        conn.close()


def surviving(repo: Repository, thesis_id: str) -> list:
    conn = repo._conn()
    try:
        return [
            r[0] for r in conn.execute(
                "SELECT revision FROM thesis_snapshots WHERE thesis_id = ? "
                "ORDER BY revision", (thesis_id,),
            )
        ]
    finally:
        conn.close()


# =========================================================================
# SCHEDULE
# =========================================================================

class TestNextRunAt:
    def test_later_today_when_before_the_window(self):
        now = datetime(2026, 8, 9, 3, 0, tzinfo=UTC)
        assert next_run_at(now) == datetime(2026, 8, 9, 4, 30, tzinfo=UTC)

    def test_tomorrow_when_after_the_window(self):
        now = datetime(2026, 8, 9, 5, 0, tzinfo=UTC)
        assert next_run_at(now) == datetime(2026, 8, 10, 4, 30, tzinfo=UTC)

    def test_exactly_on_the_window_goes_to_tomorrow(self):
        """Strictly-after, or a run finishing inside its own minute reschedules
        itself immediately and hot-loops the prune."""
        now = datetime(2026, 8, 9, 4, 30, 0, tzinfo=UTC)
        assert next_run_at(now) == datetime(2026, 8, 10, 4, 30, tzinfo=UTC)

    def test_one_second_past_the_window(self):
        now = datetime(2026, 8, 9, 4, 30, 1, tzinfo=UTC)
        assert next_run_at(now) == datetime(2026, 8, 10, 4, 30, tzinfo=UTC)

    def test_crosses_month_and_year_boundaries(self):
        assert next_run_at(datetime(2026, 8, 31, 12, 0, tzinfo=UTC)) == \
            datetime(2026, 9, 1, 4, 30, tzinfo=UTC)
        assert next_run_at(datetime(2026, 12, 31, 23, 59, tzinfo=UTC)) == \
            datetime(2027, 1, 1, 4, 30, tzinfo=UTC)

    def test_non_utc_input_is_converted_not_reinterpreted(self):
        """23:00 in UTC-5 is 04:00 UTC — the SAME night's window, not the next."""
        eastern = timezone(timedelta(hours=-5))
        now = datetime(2026, 8, 8, 23, 0, tzinfo=eastern)
        assert next_run_at(now) == datetime(2026, 8, 9, 4, 30, tzinfo=UTC)

    def test_naive_datetime_is_refused(self):
        """A naive datetime would silently schedule against local time — the
        one thing pinning the window to UTC exists to prevent."""
        with pytest.raises(ValueError):
            next_run_at(datetime(2026, 8, 9, 3, 0))

    def test_every_run_is_exactly_a_day_apart(self):
        """The UTC window has no DST discontinuity — walk a year and prove it."""
        cursor = datetime(2026, 1, 1, 5, 0, tzinfo=UTC)
        previous = None
        for _ in range(365):
            run = next_run_at(cursor)
            if previous is not None:
                assert run - previous == timedelta(days=1)
            previous = run
            cursor = run + timedelta(seconds=1)

    def test_task_reports_seconds_until_next_run(self, repo):
        task = MaintenanceTask(repo)
        now = datetime(2026, 8, 9, 4, 0, tzinfo=UTC)
        assert task.seconds_until_next_run(now) == 30 * 60


# =========================================================================
# VACUUM GUARD
# =========================================================================

class TestShouldVacuum:
    NOW = datetime(2026, 8, 9, 4, 30, tzinfo=UTC)
    LONG_AGO = datetime(2026, 1, 1, tzinfo=UTC).isoformat()

    def stats(self, free, total=1000):
        return {"freelist_count": free, "page_count": total, "page_size": 4096}

    def test_fires_above_the_ratio(self):
        assert should_vacuum(self.stats(250), self.LONG_AGO, self.NOW) is True

    def test_holds_below_the_ratio(self):
        assert should_vacuum(self.stats(150), self.LONG_AGO, self.NOW) is False

    def test_ratio_threshold_is_exclusive(self):
        """Exactly 20% is not 'more than 20%'."""
        assert should_vacuum(self.stats(200), self.LONG_AGO, self.NOW) is False
        assert should_vacuum(self.stats(201), self.LONG_AGO, self.NOW) is True

    def test_never_vacuumed_passes_the_age_gate(self):
        assert should_vacuum(self.stats(250), None, self.NOW) is True
        assert should_vacuum(self.stats(250), "", self.NOW) is True

    def test_recent_vacuum_blocks_even_at_high_free_ratio(self):
        recent = (self.NOW - timedelta(days=27)).isoformat()
        assert should_vacuum(self.stats(900), recent, self.NOW) is False

    def test_age_gate_boundary(self):
        assert should_vacuum(
            self.stats(250), (self.NOW - timedelta(days=28)).isoformat(), self.NOW
        ) is True
        assert should_vacuum(
            self.stats(250),
            (self.NOW - timedelta(days=28) + timedelta(seconds=1)).isoformat(),
            self.NOW,
        ) is False

    def test_empty_database_never_vacuums(self):
        assert should_vacuum(self.stats(0, total=0), None, self.NOW) is False
        assert should_vacuum({}, None, self.NOW) is False

    def test_unparseable_timestamp_is_treated_as_never(self):
        """A stamp we cannot read must not be able to suppress a rewrite."""
        assert should_vacuum(self.stats(250), "last tuesday", self.NOW) is True

    def test_naive_stored_timestamp_is_read_as_utc(self):
        naive = (self.NOW - timedelta(days=27)).replace(tzinfo=None).isoformat()
        assert should_vacuum(self.stats(900), naive, self.NOW) is False

    def test_thresholds_are_overridable(self):
        assert should_vacuum(self.stats(150), self.LONG_AGO, self.NOW,
                             free_ratio_threshold=0.10) is True


# =========================================================================
# SNAPSHOT RETENTION
# =========================================================================

class TestPruneThesisSnapshots:
    def test_keeps_newest_n_plus_first_of_each_older_day(self, repo):
        seed_snapshots(repo, "book-a", {
            "2026-08-01": list(range(1, 21)),
            "2026-08-02": list(range(21, 41)),
            "2026-08-03": list(range(41, 61)),
            "2026-08-04": list(range(61, 81)),
            "2026-08-05": list(range(81, 101)),
        })

        deleted = repo.prune_thesis_snapshots(keep_recent=10)

        # Newest 10 = 91..100. First-of-day among the older 90 = 1, 21, 41,
        # 61, 81 (81 is the first revision of 08-05 that falls outside the
        # newest-10 window — the boundary day keeps its opener too).
        assert surviving(repo, "book-a") == [1, 21, 41, 61, 81] + list(range(91, 101))
        assert deleted == 85

    def test_is_idempotent(self, repo):
        seed_snapshots(repo, "book-a", {
            "2026-08-01": list(range(1, 21)),
            "2026-08-02": list(range(21, 41)),
        })
        repo.prune_thesis_snapshots(keep_recent=5)
        before = surviving(repo, "book-a")
        assert repo.prune_thesis_snapshots(keep_recent=5) == 0
        assert surviving(repo, "book-a") == before

    def test_keeps_everything_below_the_threshold(self, repo):
        seed_snapshots(repo, "book-a", {"2026-08-01": [1, 2, 3]})
        assert repo.prune_thesis_snapshots(keep_recent=2016) == 0
        assert surviving(repo, "book-a") == [1, 2, 3]

    def test_theses_are_pruned_independently(self, repo):
        """'Newest 2016' is per thesis. A global LIMIT would wipe a quiet
        book entirely while a busy one kept everything."""
        seed_snapshots(repo, "busy", {"2026-08-01": list(range(1, 51))})
        seed_snapshots(repo, "quiet", {"2026-08-01": [1, 2]})

        repo.prune_thesis_snapshots(keep_recent=10)

        assert surviving(repo, "quiet") == [1, 2]
        assert surviving(repo, "busy") == [1] + list(range(41, 51))

    def test_daily_survivor_is_the_first_of_the_day_not_the_last(self, repo):
        seed_snapshots(repo, "book-a", {
            "2026-08-01": [5, 6, 7],
            "2026-08-02": [8, 9, 10],
        })
        repo.prune_thesis_snapshots(keep_recent=1)
        assert surviving(repo, "book-a") == [5, 8, 10]

    def test_day_bucketing_uses_the_utc_date(self, repo):
        """Two snapshots either side of midnight UTC are two days, and both
        openers survive."""
        conn = repo._conn()
        try:
            conn.execute(
                """INSERT INTO thesis_snapshots (thesis_id, revision, generated_at,
                   snapshot_json) VALUES ('b', 1, '2026-08-01T23:59:00+00:00', '{}')""")
            conn.execute(
                """INSERT INTO thesis_snapshots (thesis_id, revision, generated_at,
                   snapshot_json) VALUES ('b', 2, '2026-08-02T00:01:00+00:00', '{}')""")
            conn.execute(
                """INSERT INTO thesis_snapshots (thesis_id, revision, generated_at,
                   snapshot_json) VALUES ('b', 3, '2026-08-02T00:06:00+00:00', '{}')""")
            conn.commit()
        finally:
            conn.close()

        repo.prune_thesis_snapshots(keep_recent=0)
        assert surviving(repo, "b") == [1, 2]

    def test_empty_table_is_a_no_op(self, repo):
        assert repo.prune_thesis_snapshots(keep_recent=10) == 0

    def test_negative_keep_is_refused(self, repo):
        with pytest.raises(ValueError):
            repo.prune_thesis_snapshots(keep_recent=-1)

    def test_default_keeps_seven_days_at_a_300s_tick(self):
        assert DEFAULT_KEEP_RECENT == 7 * 24 * 3600 // 300


# =========================================================================
# FETCH RUN RETENTION
# =========================================================================

def seed_fetch_runs(repo: Repository, ages_in_days: list) -> None:
    conn = repo._conn()
    try:
        now = datetime.now(UTC)
        for i, age in enumerate(ages_in_days):
            conn.execute(
                """INSERT INTO fetch_runs (run_id, thesis_id, started_at, status)
                   VALUES (?, 'book-a', ?, 'success')""",
                (i + 1, (now - timedelta(days=age)).isoformat()),
            )
        conn.commit()
    finally:
        conn.close()


def surviving_runs(repo: Repository) -> list:
    conn = repo._conn()
    try:
        return [r[0] for r in conn.execute(
            "SELECT run_id FROM fetch_runs ORDER BY run_id")]
    finally:
        conn.close()


class TestPruneFetchRuns:
    def test_deletes_beyond_the_cutoff(self, repo):
        seed_fetch_runs(repo, [0, 1, 13, 13.9, 14.1, 30, 120])
        deleted = repo.prune_fetch_runs(days=14)
        assert deleted == 3
        assert surviving_runs(repo) == [1, 2, 3, 4]

    def test_cutoff_compares_like_for_like(self, repo):
        """started_at is ISO with a 'T'; SQLite's own datetime() uses a space,
        which sorts BELOW 'T' and mis-buckets every row in the boundary day."""
        conn = repo._conn()
        try:
            now = datetime.now(UTC)
            # 3 hours INSIDE the window, same calendar day as the cutoff.
            conn.execute(
                """INSERT INTO fetch_runs (run_id, thesis_id, started_at, status)
                   VALUES (1, 'a', ?, 'success')""",
                ((now - timedelta(days=14) + timedelta(hours=3)).isoformat(),),
            )
            conn.commit()
        finally:
            conn.close()
        assert repo.prune_fetch_runs(days=14) == 0
        assert surviving_runs(repo) == [1]

    def test_zero_days_deletes_everything_older_than_now(self, repo):
        seed_fetch_runs(repo, [0.001, 1])
        assert repo.prune_fetch_runs(days=0) == 2

    def test_negative_days_is_refused(self, repo):
        with pytest.raises(ValueError):
            repo.prune_fetch_runs(days=-1)


# =========================================================================
# MAINTENANCE STATE
# =========================================================================

class TestMaintenanceState:
    def test_round_trips(self, repo):
        assert repo.get_maintenance_state(LAST_VACUUM_KEY) is None
        repo.set_maintenance_state(LAST_VACUUM_KEY, "2026-08-09T04:30:00+00:00")
        assert repo.get_maintenance_state(LAST_VACUUM_KEY) == \
            "2026-08-09T04:30:00+00:00"

    def test_upserts_rather_than_duplicating(self, repo):
        repo.set_maintenance_state("k", "one")
        repo.set_maintenance_state("k", "two")
        assert repo.get_maintenance_state("k") == "two"
        conn = repo._conn()
        try:
            assert conn.execute(
                "SELECT COUNT(*) FROM maintenance_state WHERE key='k'"
            ).fetchone()[0] == 1
        finally:
            conn.close()

    def test_page_stats_are_real_numbers(self, repo):
        stats = repo.get_page_stats()
        assert stats["page_count"] > 0
        assert stats["page_size"] > 0
        assert stats["freelist_count"] >= 0


# =========================================================================
# THE TASK
# =========================================================================

def fake_repo(*, free=0, pages=1000, last_vacuum=None,
              snapshots_deleted=7, runs_deleted=3):
    repo = MagicMock()
    repo.prune_thesis_snapshots.return_value = snapshots_deleted
    repo.prune_fetch_runs.return_value = runs_deleted
    repo.get_page_stats.return_value = {
        "freelist_count": free, "page_count": pages, "page_size": 4096,
    }
    repo.get_maintenance_state.return_value = last_vacuum
    # No paper books unless a test seeds them — keeps the equity step (and
    # its Yahoo fetches) out of every pre-existing run_once assertion.
    repo.list_fill_books.return_value = []
    return repo


class TestRunOnce:
    @pytest.mark.asyncio
    async def test_prunes_both_tables_with_the_configured_bounds(self):
        repo = fake_repo()
        task = MaintenanceTask(repo, keep_recent=2016, fetch_run_days=14)

        summary = await task.run_once()

        repo.prune_thesis_snapshots.assert_called_once_with(2016)
        repo.prune_fetch_runs.assert_called_once_with(14)
        assert summary["snapshots_deleted"] == 7
        assert summary["fetch_runs_deleted"] == 3

    @pytest.mark.asyncio
    async def test_skips_vacuum_below_the_ratio(self):
        repo = fake_repo(free=100, pages=1000, last_vacuum=None)
        summary = await MaintenanceTask(repo).run_once()
        repo.vacuum.assert_not_called()
        assert summary["vacuumed"] is False

    @pytest.mark.asyncio
    async def test_vacuums_when_both_gates_pass(self):
        repo = fake_repo(free=400, pages=1000, last_vacuum=None)
        summary = await MaintenanceTask(repo).run_once()
        repo.vacuum.assert_called_once()
        assert summary["vacuumed"] is True
        assert "vacuum_seconds" in summary

    @pytest.mark.asyncio
    async def test_records_the_vacuum_timestamp(self):
        repo = fake_repo(free=400, pages=1000, last_vacuum=None)
        await MaintenanceTask(repo).run_once()
        key, value = repo.set_maintenance_state.call_args[0]
        assert key == LAST_VACUUM_KEY
        assert datetime.fromisoformat(value).tzinfo is not None

    @pytest.mark.asyncio
    async def test_recent_vacuum_suppresses_a_second_one(self):
        recent = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        repo = fake_repo(free=900, pages=1000, last_vacuum=recent)
        await MaintenanceTask(repo).run_once()
        repo.vacuum.assert_not_called()
        repo.set_maintenance_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_prune_runs_before_the_vacuum_decision(self):
        """The prune is what creates the free pages the guard measures."""
        repo = fake_repo(free=400, pages=1000)
        order = []
        repo.prune_thesis_snapshots.side_effect = lambda *_: order.append("prune") or 1
        repo.get_page_stats.side_effect = lambda: order.append("stats") or {
            "freelist_count": 400, "page_count": 1000, "page_size": 4096}
        await MaintenanceTask(repo).run_once()
        assert order[0] == "prune"
        assert "stats" in order


# =========================================================================
# EQUITY SNAPSHOT
# =========================================================================

def seed_book(repo, book_id, *, deposit=10_000.0, symbol="XOP",
              qty=20.0, price=100.0):
    """A funded book with one long position, via the real fill door."""
    repo.record_fill_once("amo", {
        "book_id": book_id, "kind": "deposit", "symbol": "CASH",
        "side": "buy", "quantity": deposit, "price": 1.0,
    })
    repo.record_fill_once("amo", {
        "book_id": book_id, "kind": "trade", "symbol": symbol,
        "side": "buy", "quantity": qty, "price": price,
    })


def fake_closes(monkeypatch, closes: dict) -> list:
    """Route fetch_daily_close through a table; record what was asked for."""
    import web.adapters.market as market
    asked = []

    def fetch(symbol):
        asked.append(symbol)
        return closes.get(symbol)

    monkeypatch.setattr(market, "fetch_daily_close", fetch)
    return asked


class TestSnapshotEquity:
    @pytest.mark.asyncio
    async def test_writes_one_mark_per_book_with_spy(self, repo, monkeypatch):
        seed_book(repo, "book-a", deposit=10_000, qty=20, price=100)
        seed_book(repo, "book-b", deposit=5_000, qty=10, price=100)
        fake_closes(monkeypatch, {"SPY": 500.0, "XOP": 150.0})

        summary = await MaintenanceTask(repo).run_once()

        assert summary["equity_marks_written"] == 2
        today = datetime.now(UTC).date().isoformat()
        [mark_a] = repo.list_equity_marks("book-a")
        # cash 8,000 + 20 x 150 = 11,000, hand-computed.
        assert mark_a["mark_date"] == today
        assert mark_a["equity"] == 11_000.0
        assert mark_a["cash"] == 8_000.0
        assert mark_a["spy_close"] == 500.0
        assert mark_a["positions"] == {"XOP": {"qty": 20.0, "close": 150.0}}
        [mark_b] = repo.list_equity_marks("book-b")
        assert mark_b["equity"] == 4_000 + 10 * 150.0

    @pytest.mark.asyncio
    async def test_spy_is_fetched_once_and_symbols_memoized(self, repo, monkeypatch):
        seed_book(repo, "book-a")
        seed_book(repo, "book-b")  # same symbol in both books
        asked = fake_closes(monkeypatch, {"SPY": 500.0, "XOP": 150.0})
        await MaintenanceTask(repo).run_once()
        assert asked.count("SPY") == 1
        assert asked.count("XOP") == 1

    @pytest.mark.asyncio
    async def test_failed_symbol_falls_back_to_previous_marks_close(
            self, repo, monkeypatch):
        seed_book(repo, "book-a", deposit=10_000, qty=20, price=100)
        repo.save_equity_mark(
            "book-a", "2026-08-01", equity=10_800, cash=8_000,
            spy_close=490.0, positions={"XOP": {"qty": 20.0, "close": 140.0}},
        )
        fake_closes(monkeypatch, {"SPY": 500.0})  # XOP fetch returns None

        summary = await MaintenanceTask(repo).run_once()

        assert summary["equity_marks_written"] == 1
        marks = repo.list_equity_marks("book-a")
        assert marks[-1]["equity"] == 8_000 + 20 * 140.0  # yesterday's close
        assert marks[-1]["positions"]["XOP"]["close"] == 140.0

    @pytest.mark.asyncio
    async def test_no_close_anywhere_skips_the_book_not_the_run(
            self, repo, monkeypatch):
        seed_book(repo, "book-a", symbol="DEAD")   # no close, no prior mark
        seed_book(repo, "book-b", symbol="XOP")
        fake_closes(monkeypatch, {"SPY": 500.0, "XOP": 150.0})

        summary = await MaintenanceTask(repo).run_once()

        assert summary["equity_marks_written"] == 1
        assert repo.list_equity_marks("book-a") == []
        assert len(repo.list_equity_marks("book-b")) == 1

    @pytest.mark.asyncio
    async def test_missing_spy_writes_nothing_and_does_not_raise(
            self, repo, monkeypatch):
        seed_book(repo, "book-a")
        fake_closes(monkeypatch, {"XOP": 150.0})  # SPY unavailable
        summary = await MaintenanceTask(repo).run_once()
        assert summary["equity_marks_written"] == 0
        assert repo.list_equity_marks("book-a") == []
        # The rest of the night still happened.
        assert "snapshots_deleted" in summary

    @pytest.mark.asyncio
    async def test_step_failure_never_breaks_the_other_steps(self):
        repo = fake_repo()
        repo.list_fill_books.side_effect = RuntimeError("table missing")
        summary = await MaintenanceTask(repo).run_once()
        assert summary["equity_snapshot_error"] is True
        assert summary["snapshots_deleted"] == 7  # prune already done

    @pytest.mark.asyncio
    async def test_rerun_same_day_replaces_not_duplicates(self, repo, monkeypatch):
        seed_book(repo, "book-a")
        fake_closes(monkeypatch, {"SPY": 500.0, "XOP": 150.0})
        task = MaintenanceTask(repo)
        await task.run_once()
        fake_closes(monkeypatch, {"SPY": 510.0, "XOP": 155.0})
        await task.run_once()
        marks = repo.list_equity_marks("book-a")
        assert len(marks) == 1  # PK (book, date) — REPLACE, not append
        assert marks[0]["spy_close"] == 510.0

    @pytest.mark.asyncio
    async def test_no_books_means_no_yahoo_calls(self, repo, monkeypatch):
        asked = fake_closes(monkeypatch, {"SPY": 500.0})
        summary = await MaintenanceTask(repo).run_once()
        assert summary["equity_marks_written"] == 0
        assert asked == []


class TestRealVacuum:
    def test_vacuum_shrinks_a_file_database(self, tmp_path):
        """Exercises the real VACUUM against a throwaway file — the sqlite3
        module opens an implicit transaction around DML, and VACUUM inside
        one raises."""
        db = tmp_path / "t.db"
        repo = Repository(db)
        repo.initialize()
        seed_snapshots(repo, "book-a", {
            f"2026-08-{d:02d}": list(range(d * 100, d * 100 + 100))
            for d in range(1, 10)
        })
        conn = repo._conn()
        try:
            conn.execute(
                "UPDATE thesis_snapshots SET snapshot_json = ?", ("x" * 4000,))
            conn.commit()
        finally:
            conn.close()

        repo.prune_thesis_snapshots(keep_recent=5)
        before = repo.get_page_stats()
        assert before["freelist_count"] > 0

        repo.vacuum()

        after = repo.get_page_stats()
        assert after["freelist_count"] == 0
        assert after["page_count"] < before["page_count"]

    @pytest.mark.asyncio
    async def test_end_to_end_against_a_real_database(self, tmp_path):
        """Drives the real task against a real file DB — no mocks anywhere."""
        db = tmp_path / "t.db"
        repo = Repository(db)
        repo.initialize()
        seed_snapshots(repo, "book-a", {
            "2026-08-01": list(range(1, 51)),
            "2026-08-02": list(range(51, 101)),
        })
        seed_fetch_runs(repo, [1, 20, 40])

        task = MaintenanceTask(repo, keep_recent=10, fetch_run_days=14,
                               vacuum_free_ratio=0.0, vacuum_min_days=0)
        summary = await task.run_once()

        assert surviving(repo, "book-a") == [1, 51] + list(range(91, 101))
        assert summary["snapshots_deleted"] == 88
        assert summary["fetch_runs_deleted"] == 2
        assert summary["vacuumed"] is True
        assert repo.get_maintenance_state(LAST_VACUUM_KEY) is not None


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_stop_is_clean(self, repo):
        task = MaintenanceTask(repo)
        await task.start()
        await asyncio.sleep(0)
        assert task._task is not None
        await task.stop()
        assert task._task is None

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self, repo):
        task = MaintenanceTask(repo)
        await task.start()
        first = task._task
        await task.start()
        assert task._task is first
        await task.stop()

    @pytest.mark.asyncio
    async def test_stop_before_start_does_not_raise(self, repo):
        await MaintenanceTask(repo).stop()

    @pytest.mark.asyncio
    async def test_loop_sleeps_until_the_window_then_runs(self, repo):
        """The loop must not run on startup — 04:30 is chosen precisely so the
        blocking work never lands during a trading session."""
        task = MaintenanceTask(repo)
        task.run_once = AsyncMock(return_value={})
        slept = []

        async def fake_sleep(delay):
            slept.append(delay)
            if len(slept) >= 2:
                task._running = False

        with patch("web.runtime.maintenance.asyncio.sleep", fake_sleep):
            task._running = True
            await task._loop()

        assert slept[0] > 0
        assert task.run_once.await_count == 1

    @pytest.mark.asyncio
    async def test_a_failing_run_does_not_end_the_loop(self, repo):
        task = MaintenanceTask(repo)
        task.run_once = AsyncMock(side_effect=RuntimeError("disk full"))
        calls = []

        async def fake_sleep(delay):
            calls.append(delay)
            if len(calls) >= 4:
                task._running = False

        with patch("web.runtime.maintenance.asyncio.sleep", fake_sleep):
            task._running = True
            await task._loop()

        assert task.run_once.await_count >= 2, "loop died on the first failure"
