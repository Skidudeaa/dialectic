"""
Contracts for the LLM's scored track record (llm/self_model.py).

fetch_track_record reads the desk's claims-ledger calibration (and, once
Phase 4 ships, the paper book) so render_self_awareness can show the
participant its own EMPIRICAL score. The contracts that matter:

- desk down / creds unset → None → the section is omitted ENTIRELY, never
  rendered degraded;
- a missing portfolio omits only the book line (Phase 4 arrives later);
- the 15-minute TTL cache bounds prompt-path cost — one desk probe per
  window, failures cached too;
- prediction_watch (the grader) must NOT consume render_self_awareness:
  a grader that knows its aggregate score has a motive.

tradingDesk is mocked at self_model.td; no live desk.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

import llm.self_model as self_model
from llm.self_model import (
    ParticipationSnapshot,
    SelfModel,
    fetch_track_record,
    reset_track_record_cache,
)
from llm.tradingdesk_client import TradingDeskError

CALIBRATION = {
    "calibration": [
        {"bucket": "0.6-0.7", "midpoint": 0.65, "total": 4, "correct": 3, "accuracy": 0.75},
    ],
    "total_predictions": 12,
    "total_correct": 8,
    "brier_score": 0.18,
    "ref_brier": 0.25,
    "bss_vs": "market",
    "past_deadline_unscored": 2,
}


@pytest.fixture(autouse=True)
def fresh_cache():
    reset_track_record_cache()
    yield
    reset_track_record_cache()


# ── fetch_track_record ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_reads_claude_calibration_and_portfolio(monkeypatch):
    portfolio = {"books": {"iran-hormuz-graph": {
        "equity": 105000, "spy_baseline_now": 101000,
    }}}
    get = AsyncMock(side_effect=[dict(CALIBRATION), portfolio])
    monkeypatch.setattr(self_model.td, "get", get)

    record = await fetch_track_record()

    assert record["calibration"]["brier_score"] == 0.18
    assert record["portfolio"]["books"]["iran-hormuz-graph"]["equity"] == 105000
    first = get.await_args_list[0]
    assert first.args == ("/api/predictions/calibration",)
    assert first.kwargs["params"] == {"source_label": "Claude"}


@pytest.mark.asyncio
async def test_missing_portfolio_keeps_the_calibration_half(monkeypatch):
    """Phase 4 hasn't shipped: /api/portfolio errors, calibration survives."""
    get = AsyncMock(side_effect=[dict(CALIBRATION), TradingDeskError("404")])
    monkeypatch.setattr(self_model.td, "get", get)

    record = await fetch_track_record()

    assert "portfolio" not in record
    assert record["calibration"]["total_predictions"] == 12


@pytest.mark.asyncio
async def test_desk_down_is_none(monkeypatch):
    monkeypatch.setattr(
        self_model.td, "get", AsyncMock(side_effect=TradingDeskError("down")),
    )
    assert await fetch_track_record() is None


@pytest.mark.asyncio
async def test_ttl_cache_probes_the_desk_once(monkeypatch):
    get = AsyncMock(side_effect=TradingDeskError("down"))
    monkeypatch.setattr(self_model.td, "get", get)

    assert await fetch_track_record() is None
    assert await fetch_track_record() is None

    # One calibration probe total — the second call answered from cache.
    assert get.await_count == 1


# ── the rendered block ───────────────────────────────────────────────


def _snapshot(track_record=None):
    return ParticipationSnapshot(total_messages_sent=3, track_record=track_record)


def test_golden_block_with_reference_and_unscored(monkeypatch):
    text = SelfModel(db=None).render_self_awareness(
        _snapshot({"calibration": dict(CALIBRATION)})
    )
    assert "## Your Track Record (scored, not self-reported)" in text
    assert (
        "- Predictions: 12 resolved, Brier 0.18 vs 0.25 (market) — "
        "lower is better; 2 past deadline unscored." in text
    )
    # No portfolio → no book line.
    assert "Book:" not in text


def test_book_line_renders_when_the_portfolio_exists():
    # td's real shape: {books: {id: {...}}}. Two books aggregate.
    text = SelfModel(db=None).render_self_awareness(
        _snapshot({
            "calibration": dict(CALIBRATION),
            "portfolio": {"books": {
                "iran-hormuz-graph": {"equity": 105000, "spy_baseline_now": 101000},
                "trump-tariffs-graph": {"equity": 50000, "spy_baseline_now": 52000},
            }},
        })
    )
    assert ("- Book: equity $155,000 vs SPY benchmark $153,000 "
            "(price return only).") in text


def test_book_line_omitted_without_a_benchmark():
    # An unfunded book (equity but no spy units yet) must not overclaim.
    text = SelfModel(db=None).render_self_awareness(
        _snapshot({
            "calibration": dict(CALIBRATION),
            "portfolio": {"books": {
                "iran-hormuz-graph": {"equity": 0.0, "spy_baseline_now": None},
            }},
        })
    )
    assert "Book:" not in text


def test_none_track_record_omits_the_section_entirely():
    text = SelfModel(db=None).render_self_awareness(_snapshot(None))
    assert "Track Record" not in text
    assert "Brier" not in text


def test_zero_resolved_is_honest_not_invented():
    text = SelfModel(db=None).render_self_awareness(
        _snapshot({"calibration": {"total_predictions": 0, "brier_score": None}})
    )
    assert "- Predictions: 0 resolved — no scored track record yet." in text


def test_default_snapshot_renders_no_track_record():
    """Back-compat: every existing ParticipationSnapshot() constructor call
    keeps its old rendering."""
    text = SelfModel(db=None).render_self_awareness(ParticipationSnapshot())
    assert "Track Record" not in text


# ── the snapshot carries it (so orchestrator.py stays untouched) ─────


@pytest.mark.asyncio
async def test_participation_snapshot_carries_the_track_record(monkeypatch):
    async def fake_fetch():
        return {"calibration": dict(CALIBRATION)}

    monkeypatch.setattr(self_model, "fetch_track_record", fake_fetch)

    row = {
        "last_spoke_at": None, "turns_since_last_spoke": 2,
        "total_messages_sent": 5, "total_silences": 1,
        "primary_count": 5, "provoker_count": 0, "last_mode": "primary",
        "avg_confidence_last_10": 0.7, "confidence_trend": "stable",
        "llm_message_ratio": 0.3, "engaged_count": 3, "ignored_count": 1,
        "effectiveness_avg": None, "active_thread_count": 1,
        "total_fork_count": 0, "session_count": 1,
        "days_since_last_session": None, "fsm_state": None,
        "state_entered_at": None, "state_source": None,
    }
    db = AsyncMock()
    db.fetchrow = AsyncMock(return_value=row)
    db.fetch = AsyncMock(return_value=[])

    snapshot = await SelfModel(db).get_participation_snapshot(uuid4())

    assert snapshot.track_record == {"calibration": dict(CALIBRATION)}


# ── the grader stays blind ───────────────────────────────────────────


def test_prediction_watch_never_imports_the_self_model():
    """The verdict prompt must not know its aggregate score. Checked by
    IDENTITY — no object in prediction_watch's namespace originates from
    llm.self_model — not by grepping source text."""
    import llm.prediction_watch as pw

    modules = {
        getattr(value, "__module__", None) for value in vars(pw).values()
    }
    assert "llm.self_model" not in modules
    assert not hasattr(pw, "render_self_awareness")
    assert not hasattr(pw, "SelfModel")
