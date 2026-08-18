"""
Tests for llm/congress_watch.py — politician disclosures become readings.

The expensive mistakes: firing while the flag is dark (the dataset URLs are
a documented ASSUMPTION nobody has verified live — the job must not fetch
until armed), filing a disclosure into a room whose book does not trade the
ticker, re-filing the same disclosure every hour (dedup is the synthetic
URL vs seen_urls), a dead mirror sinking the run, and — the standing
discipline — ANY interjection: this producer files readings only, and the
absence of an orchestrator anywhere in the module is asserted, not assumed.
All network + td calls mocked; dataset rows are canned fixtures in both
chambers' real column shapes.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from scheduler import Scheduler, SchedulerContext
from llm import congress_watch


HORMUZ_ROOM = uuid4()
JAPAN_ROOM = uuid4()

SENATE_ROWS = [
    {
        "transaction_date": "08/10/2026",
        "disclosure_date": "08/15/2026",
        "owner": "Self",
        "ticker": "XOP",
        "asset_description": "SPDR S&P Oil & Gas E&P ETF",
        "type": "Purchase",
        "amount": "$15,001 - $50,000",
        "senator": "Jane Example",
        "ptr_link": "https://efdsearch.senate.gov/search/view/ptr/abc/",
    },
    {
        # Junk ticker — the house/senate files carry "--" and stray HTML.
        "transaction_date": "08/09/2026",
        "disclosure_date": "08/14/2026",
        "ticker": "--",
        "type": "Sale (Full)",
        "amount": "$1,001 - $15,000",
        "senator": "Jane Example",
    },
    {
        # Ticker nobody's book trades.
        "transaction_date": "08/08/2026",
        "disclosure_date": "08/13/2026",
        "ticker": "ZZZZ",
        "type": "Purchase",
        "amount": "$1,001 - $15,000",
        "senator": "Sam Sample",
    },
]

HOUSE_ROWS = [
    {
        "disclosure_year": 2026,
        "disclosure_date": "2026-08-16",
        "transaction_date": "2026-08-11",
        "owner": "joint",
        "ticker": "GLD",
        "asset_description": "SPDR Gold Shares",
        "type": "sale_partial",
        "amount": "$1,001 - $15,000",
        "representative": "Hon. Rep Example",
        "district": "XX00",
        "ptr_link": "",
    },
    {
        # No member name → dropped.
        "disclosure_date": "2026-08-12",
        "ticker": "GLD",
        "type": "purchase",
        "amount": "$1,001 - $15,000",
    },
]


# =========================================================================
# Normalization — defensive against the community datasets' real junk
# =========================================================================


class TestNormalize:
    def test_senate_rows(self):
        out = congress_watch.normalize_disclosures(SENATE_ROWS, "Senate")
        assert [d["ticker"] for d in out] == ["XOP", "ZZZZ"]
        first = out[0]
        assert first["member"] == "Jane Example"
        assert first["direction"] == "buy"
        assert first["amount"] == "$15,001 - $50,000"
        assert first["url"].startswith("congress://jane-example/")
        assert len(first["url"].split("/")[-1]) == 16

    def test_house_rows(self):
        out = congress_watch.normalize_disclosures(HOUSE_ROWS, "House")
        [d] = out
        assert d["member"] == "Hon. Rep Example"
        assert d["ticker"] == "GLD"
        assert d["direction"] == "sell"
        assert d["chamber"] == "House"

    def test_identity_hash_is_stable(self):
        a = congress_watch.normalize_disclosures(SENATE_ROWS, "Senate")
        b = congress_watch.normalize_disclosures(SENATE_ROWS, "Senate")
        assert [d["url"] for d in a] == [d["url"] for d in b]

    def test_non_list_payload_is_empty(self):
        assert congress_watch.normalize_disclosures({"error": "x"}, "Senate") == []
        assert congress_watch.normalize_disclosures(None, "Senate") == []
        assert congress_watch.normalize_disclosures(["str", 42], "Senate") == []

    def test_ticker_hygiene(self):
        assert congress_watch._clean_ticker("BRK.B") == "BRK.B"
        assert congress_watch._clean_ticker(" nvda ") == "NVDA"
        assert congress_watch._clean_ticker("--") is None
        assert congress_watch._clean_ticker("N/A") is None
        assert congress_watch._clean_ticker("<div>junk</div>") is None
        assert congress_watch._clean_ticker(None) is None

    def test_unreadable_dates_sort_oldest(self):
        rows = [{"senator": "A B", "ticker": "XOP", "type": "Purchase",
                 "amount": "$1", "transaction_date": "soon",
                 "disclosure_date": "not a date"}]
        [d] = congress_watch.normalize_disclosures(rows, "Senate")
        assert d["_filed_at"] == congress_watch.datetime.min


class TestArticleBody:
    def test_reading_carries_the_facts(self):
        [d] = congress_watch.normalize_disclosures(SENATE_ROWS[:1], "Senate")
        article = congress_watch._disclosure_article(d)
        assert article["url"] == d["url"]
        assert "Jane Example" in article["title"]
        assert "XOP" in article["title"]
        for fact in ("Purchase", "buy", "$15,001 - $50,000",
                     "08/10/2026", "08/15/2026", "efdsearch.senate.gov"):
            assert fact in article["content"], fact
        assert article["site"] == "congress"


class TestBookSymbols:
    def test_extracts_instrument_ids(self):
        structure = {"instruments": {
            "brent": [{"id": "XOP"}, {"id": "XLE"}],
            "dxy-stress": [{"id": "GLD"}],
        }}
        assert congress_watch._book_symbols(structure) == {"XOP", "XLE", "GLD"}

    def test_garbage_shapes_are_empty(self):
        assert congress_watch._book_symbols(None) == set()
        assert congress_watch._book_symbols({"instruments": "nope"}) == set()
        assert congress_watch._book_symbols(
            {"instruments": {"n": [{"noid": 1}, "str"]}}) == set()


# =========================================================================
# The job
# =========================================================================


class FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


def make_db(*, rooms, seen=()):
    db = AsyncMock()

    async def _fetch(sql, *args):
        if "FROM rooms" in sql:
            return list(rooms)
        if "SELECT url FROM reading_items" in sql:
            return [{"url": u} for u in seen]
        return []

    db.fetch = AsyncMock(side_effect=_fetch)
    db.fetchval = AsyncMock(return_value=0)
    db.fetchrow = AsyncMock(return_value=None)
    db.execute = AsyncMock()
    return db


def _rooms():
    return [
        {"id": HORMUZ_ROOM, "name": "Hormuz", "linked_book_id": "iran-hormuz-graph"},
        {"id": JAPAN_ROOM, "name": "Japan", "linked_book_id": "japan-rate-shock-graph"},
    ]


STRUCTURES = {
    "iran-hormuz-graph": {"instruments": {
        "brent": [{"id": "XOP"}, {"id": "XLE"}],
        "dxy-stress": [{"id": "GLD"}],
    }},
    "japan-rate-shock-graph": {"instruments": {
        "jgb": [{"id": "EWJ"}],
    }},
}


@pytest.fixture
def mocks(monkeypatch):
    import json as _json

    m = SimpleNamespace(
        datasets={
            congress_watch.SENATE_DATASET_URL:
                _json.dumps(SENATE_ROWS).encode(),
            congress_watch.HOUSE_DATASET_URL:
                _json.dumps(HOUSE_ROWS).encode(),
        },
        fetch_errors={},
        fetch_calls=[], structure_calls=[], saved=[],
    )

    def _fetch(url):
        m.fetch_calls.append(url)
        if url in m.fetch_errors:
            raise m.fetch_errors[url]
        return m.datasets[url]

    async def _service_get(path, **kwargs):
        m.structure_calls.append(path)
        book = path.rsplit("/", 1)[-1]
        return STRUCTURES[book]

    async def _save(db, room_id, article, summary, key_claims, source, **kw):
        m.saved.append({"room_id": room_id, "url": article["url"],
                        "ticker_title": article["title"], "source": source,
                        "summary": summary})
        return {"url": article["url"], "title": article["title"]}

    monkeypatch.setattr(congress_watch, "_fetch_dataset_bytes", _fetch)
    monkeypatch.setattr(congress_watch.td, "service_get", _service_get)
    monkeypatch.setattr(congress_watch, "save_reading", _save)
    return m


def _ctx(db):
    return SchedulerContext(pool=FakePool(db), broadcast=AsyncMock())


@pytest.mark.asyncio
class TestCongressWatch:
    @pytest.fixture(autouse=True)
    def armed(self, monkeypatch):
        monkeypatch.setenv(congress_watch.ENABLED_ENV, "1")

    async def test_files_only_where_the_book_holds_the_symbol(self, mocks):
        db = make_db(rooms=_rooms())
        detail = await congress_watch.congress_watch(_ctx(db))

        # XOP (senate buy) and GLD (house sale) both live in the Hormuz
        # book; the Japan book (EWJ only) matches nothing. ZZZZ matches
        # nowhere. Readings only — no orchestrator, no broadcast.
        hormuz = detail[str(HORMUZ_ROOM)]["filed"]
        assert {f["ticker"] for f in hormuz} == {"XOP", "GLD"}
        assert detail[str(JAPAN_ROOM)] == {"filed": []}
        assert all(s["source"] == "congress" for s in mocks.saved)
        assert all(s["room_id"] == HORMUZ_ROOM for s in mocks.saved)
        assert detail["fetch_senate"] == "2 rows"
        assert detail["fetch_house"] == "1 rows"

    async def test_newest_disclosures_win_the_scan(self, mocks):
        db = make_db(rooms=_rooms()[:1])
        await congress_watch.congress_watch(_ctx(db))
        # House GLD filed 2026-08-16 sorts ahead of senate XOP (08/15).
        assert [s["url"].split("//")[1].split("/")[0]
                for s in mocks.saved] == ["hon-rep-example", "jane-example"]

    async def test_seen_disclosures_are_not_refiled(self, mocks):
        [xop] = congress_watch.normalize_disclosures(SENATE_ROWS[:1], "Senate")
        db = make_db(rooms=_rooms()[:1], seen=(xop["url"],))
        detail = await congress_watch.congress_watch(_ctx(db))
        tickers = {f["ticker"] for f in detail[str(HORMUZ_ROOM)]["filed"]}
        assert tickers == {"GLD"}

    async def test_per_room_cap_holds(self, mocks, monkeypatch):
        monkeypatch.setattr(congress_watch, "PER_ROOM_CAP", 1)
        db = make_db(rooms=_rooms()[:1])
        detail = await congress_watch.congress_watch(_ctx(db))
        assert len(detail[str(HORMUZ_ROOM)]["filed"]) == 1

    async def test_dark_by_default(self, mocks, monkeypatch):
        """THE shipping gate: with the env var UNSET the job does nothing —
        no dataset fetch, no td call, no reading. The URLs are an assumption
        until someone verifies them live and arms the flag."""
        monkeypatch.delenv(congress_watch.ENABLED_ENV, raising=False)
        db = make_db(rooms=_rooms())
        detail = await congress_watch.congress_watch(_ctx(db))
        assert detail == {"skipped": "disabled"}
        assert mocks.fetch_calls == []
        assert mocks.structure_calls == []
        assert mocks.saved == []

    async def test_explicit_zero_is_dark_too(self, mocks, monkeypatch):
        monkeypatch.setenv(congress_watch.ENABLED_ENV, "0")
        detail = await congress_watch.congress_watch(_ctx(make_db(rooms=[])))
        assert detail == {"skipped": "disabled"}
        assert mocks.fetch_calls == []

    async def test_one_dead_mirror_does_not_silence_the_other(self, mocks):
        mocks.fetch_errors[congress_watch.SENATE_DATASET_URL] = OSError("503")
        db = make_db(rooms=_rooms()[:1])
        detail = await congress_watch.congress_watch(_ctx(db))
        assert detail["fetch_senate"].startswith("failed:")
        # The house GLD row still lands.
        assert {s["url"].split("//")[1].split("/")[0]
                for s in mocks.saved} == {"hon-rep-example"}

    async def test_both_mirrors_dead_is_harmless(self, mocks):
        mocks.fetch_errors[congress_watch.SENATE_DATASET_URL] = OSError("503")
        mocks.fetch_errors[congress_watch.HOUSE_DATASET_URL] = OSError("503")
        db = make_db(rooms=_rooms())
        detail = await congress_watch.congress_watch(_ctx(db))
        assert mocks.saved == []
        assert mocks.structure_calls == []
        assert detail["fetch_senate"].startswith("failed:")
        assert detail["fetch_house"].startswith("failed:")

    async def test_td_down_skips_the_room_not_the_run(self, mocks, monkeypatch):
        async def _boom(path, **kwargs):
            if "iran" in path:
                raise congress_watch.td.TradingDeskError("bridge down")
            return STRUCTURES["japan-rate-shock-graph"]

        monkeypatch.setattr(congress_watch.td, "service_get", _boom)
        db = make_db(rooms=_rooms())
        detail = await congress_watch.congress_watch(_ctx(db))
        assert str(detail[str(HORMUZ_ROOM)]).startswith("structure_unavailable")
        assert detail[str(JAPAN_ROOM)] == {"filed": []}

    async def test_never_interjects(self):
        """Readings only, structurally: the module must not import the
        orchestrator or the interjection machinery — reading_echo and the
        morning brief are this producer's only voice. A runtime attribute
        fence, not a source grep — comments cannot satisfy or break it."""
        assert not hasattr(congress_watch, "LLMOrchestrator")
        assert not hasattr(congress_watch, "force_response")
        assert not hasattr(congress_watch, "_interject")
        assert not hasattr(congress_watch, "_broadcast_follow_up")


# =========================================================================
# Job registration
# =========================================================================


class TestRegistration:
    def test_registers_hourly_job(self):
        sched = Scheduler(SchedulerContext(pool=None))
        congress_watch.register_congress_watch_jobs(sched)
        assert len(sched.jobs) == 1
        job = sched.jobs[0]
        assert job.name == "congress_watch"
        assert job.interval_s == 3600
        assert job.enabled_env == congress_watch.ENABLED_ENV

    def test_explicit_zero_stops_the_tick(self, monkeypatch):
        monkeypatch.setenv(congress_watch.ENABLED_ENV, "0")
        sched = Scheduler(SchedulerContext(pool=None))
        congress_watch.register_congress_watch_jobs(sched)
        assert not sched.jobs[0].enabled()
