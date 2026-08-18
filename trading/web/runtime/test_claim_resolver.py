"""
Tests for ClaimResolver — deterministic auto-resolution of spec-carrying claims.

WHY every fixture hand-computes its own verdict: the resolver is the one
component allowed to close ledger rows with no human tap, so each test names
the exact bars/spot/state/deadline combination and the exact verdict it must
produce — a resolver that resolves the right NUMBER of claims with the wrong
verdicts must fail loudly here.

ORACLE CONTRACT UNDER TEST: daily bars decide price_cross claims; the spot
quote only short-circuits a cross that is true right now. The review's
founding scenario — a stock touches the threshold intraday and falls back
before the next 300s tick — is pinned below in
test_bars_catch_intraday_cross_spot_missed.
"""

import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from web.persistence.repository import Repository
from web.runtime import claim_resolver as cr_module
from web.runtime.claim_resolver import (
    AUTO_RESOLVE_ACTION,
    LATE_CROSS_ACTION,
    ClaimResolver,
    fetch_daily_bars,
    fetch_polymarket_market_state,
    polymarket_verdict,
)
from web.runtime.coordinator import RuntimeCoordinator

TODAY = datetime.now(timezone.utc).date()
FUTURE = (TODAY + timedelta(days=7)).isoformat()
PAST = (TODAY - timedelta(days=2)).isoformat()
CREATED_PAST = (TODAY - timedelta(days=12)).isoformat() + "T00:00:00+00:00"


@pytest.fixture
def repo():
    r = Repository(":memory:")
    r.initialize()
    return r


class FakeWS:
    """Records broadcast_all calls; the resolver treats it as the manager."""

    def __init__(self):
        self.broadcasts = []

    async def broadcast_all(self, msg_type, payload, user="system"):
        self.broadcasts.append((msg_type, payload, user))


def quotes(**symbol_prices):
    """Spot fetcher returning a fixed symbol→price book (fetch_quotes shape)."""
    book = [{"symbol": s, "price": p, "source": "yahoo"}
            for s, p in symbol_prices.items()]
    return lambda: book


def quote_spy():
    """Recording fetcher: assert on .calls AFTER the run — an in-resolver
    raise would be swallowed by its own quote-failure guard, making a
    raising sentinel vacuously green."""
    def fetch():
        fetch.calls += 1
        return []
    fetch.calls = 0
    return fetch


def bars(*rows):
    """bar_fetcher from (iso_date, high, low) tuples. Filters to the
    requested window exactly as the real fetcher does — so one fixture can
    serve both the resolution window and the late-cross watch window — and
    records the windows on .windows so tests can assert what the resolver
    actually asked for."""
    def fetch(symbol, start, end):
        fetch.windows.append((symbol, start, end))
        return [
            {"date": date.fromisoformat(d), "high": h, "low": l}
            for (d, h, l) in rows
            if start <= date.fromisoformat(d) <= end
        ]
    fetch.windows = []
    return fetch


def bars_unavailable(symbol, start, end):
    return None  # transport/parse failure


def set_created_at(repo, prediction_id, iso):
    """WHY raw SQL: save_prediction_once stamps created_at with _now_iso(),
    so there is no supported way to build a claim whose window started in
    the past — and the bar oracle's window is defined off that column."""
    conn = repo._conn()
    try:
        conn.execute("UPDATE predictions SET created_at = ? WHERE id = ?",
                     (iso, prediction_id))
        conn.commit()
    finally:
        conn.close()


def price_claim(repo, *, symbol="XOP", comparator="above", threshold=115.0,
                deadline=FUTURE, created_at=None, statement="XOP crosses 115"):
    record, created = repo.save_prediction_once("amo", {
        "statement": statement,
        "confidence": 0.7,
        "deadline": deadline,
        "resolution_spec": {"kind": "price_cross", "symbol": symbol,
                            "comparator": comparator, "threshold": threshold},
    })
    assert created
    if created_at is not None:
        set_created_at(repo, record["id"], created_at)
    return record


def poly_claim(repo, *, market_id="us-strike-2026", deadline=FUTURE):
    record, created = repo.save_prediction_once("amo", {
        "statement": "Market resolves Yes",
        "confidence": 0.6,
        "deadline": deadline,
        "resolution_spec": {"kind": "polymarket", "market_id": market_id},
    })
    assert created
    return record


def get_prediction(repo, prediction_id):
    return next(p for p in repo.list_predictions() if p["id"] == prediction_id)


def evidence(repo, prediction_id) -> dict:
    return json.loads(get_prediction(repo, prediction_id)["resolution_notes"])


def resolver_for(repo, ws=None, quote_fetcher=None, bar_fetcher=None,
                 market_state_fetcher=None):
    return ClaimResolver(
        repo,
        ws_manager=ws,
        quote_fetcher=quote_fetcher or (lambda: []),
        bar_fetcher=bar_fetcher or bars_unavailable,
        market_state_fetcher=market_state_fetcher or (lambda market_id: None),
    )


# ════════════════════════════════════════════════════════════════════
# price_cross — spot short-circuit
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_spot_short_circuit_resolves_correct_without_bars(repo):
    claim = price_claim(repo, comparator="above", threshold=115.0)
    ws = FakeWS()
    bar_fetch = bars()
    summary = await resolver_for(
        repo, ws, quotes(XOP=150.0), bar_fetcher=bar_fetch
    ).run_once()

    assert summary["resolved"] == 1
    assert bar_fetch.windows == []  # spot proved it; no chart call
    row = get_prediction(repo, claim["id"])
    assert row["resolution"] == "correct"
    ev = evidence(repo, claim["id"])
    assert ev["provider"] == "yahoo_spot"
    assert ev["observed"] == {"date": TODAY.isoformat(), "price": 150.0,
                              "threshold": 115.0, "comparator": "above"}
    audits = repo.list_audit(action=AUTO_RESOLVE_ACTION)
    assert len(audits) == 1 and audits[0]["target"] == claim["id"]
    assert audits[0]["payload"]["resolution"] == "correct"
    assert len(ws.broadcasts) == 1
    assert "Auto-resolved correct" in ws.broadcasts[0][1]["detail"]


@pytest.mark.asyncio
async def test_spot_short_circuit_below(repo):
    claim = price_claim(repo, comparator="below", threshold=100.0)
    summary = await resolver_for(
        repo, quote_fetcher=quotes(XOP=90.0), bar_fetcher=bars()
    ).run_once()
    assert summary["resolved"] == 1
    assert get_prediction(repo, claim["id"])["resolution"] == "correct"


# ════════════════════════════════════════════════════════════════════
# price_cross — the bar oracle
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_bars_catch_intraday_cross_spot_missed(repo):
    """THE REVIEW SCENARIO: stock touched 100.2 intraday, fell back to 98
    before the next tick. Spot says no cross; the daily bar's high is the
    oracle and resolves correct."""
    claim = price_claim(repo, threshold=100.0, created_at=CREATED_PAST)
    hit_day = (TODAY - timedelta(days=3)).isoformat()
    summary = await resolver_for(
        repo,
        quote_fetcher=quotes(XOP=98.0),
        bar_fetcher=bars((hit_day, 100.2, 96.0)),
    ).run_once()

    assert summary["resolved"] == 1
    row = get_prediction(repo, claim["id"])
    assert row["resolution"] == "correct"
    ev = evidence(repo, claim["id"])
    assert ev["provider"] == "yahoo_v8_daily"
    assert ev["observed"] == {"date": hit_day, "high": 100.2,
                              "threshold": 100.0, "comparator": "above"}


@pytest.mark.asyncio
async def test_bars_below_crosses_on_low(repo):
    claim = price_claim(repo, comparator="below", threshold=90.0,
                        created_at=CREATED_PAST)
    hit_day = (TODAY - timedelta(days=1)).isoformat()
    await resolver_for(
        repo,
        quote_fetcher=quotes(XOP=95.0),
        bar_fetcher=bars((hit_day, 99.0, 89.5)),
    ).run_once()
    row = get_prediction(repo, claim["id"])
    assert row["resolution"] == "correct"
    assert evidence(repo, claim["id"])["observed"]["low"] == 89.5


@pytest.mark.asyncio
async def test_bars_window_is_created_to_min_today_deadline(repo):
    price_claim(repo, created_at=CREATED_PAST)          # open window
    expired = price_claim(repo, deadline=PAST, created_at=CREATED_PAST,
                          statement="expired claim")
    bar_fetch = bars(((TODAY - timedelta(days=5)).isoformat(), 100.0, 95.0))
    await resolver_for(
        repo, quote_fetcher=quotes(XOP=100.0), bar_fetcher=bar_fetch
    ).run_once()

    created = date.fromisoformat(CREATED_PAST[:10])
    assert (
        ("XOP", created, TODAY) in bar_fetch.windows       # open: capped today
        and ("XOP", created, TODAY - timedelta(days=2)) in bar_fetch.windows
    )  # expired: capped at its deadline
    # Neither bar crossed 115, so the expired one resolved incorrect.
    assert get_prediction(repo, expired["id"])["resolution"] == "incorrect"


@pytest.mark.asyncio
async def test_uncrossed_open_window_stays_open(repo):
    claim = price_claim(repo, created_at=CREATED_PAST)
    summary = await resolver_for(
        repo,
        quote_fetcher=quotes(XOP=100.0),
        bar_fetcher=bars(((TODAY - timedelta(days=2)).isoformat(), 110.0, 99.0)),
    ).run_once()
    assert summary["resolved"] == 0 and summary["skipped"] == 1
    assert get_prediction(repo, claim["id"])["resolution"] is None


@pytest.mark.asyncio
async def test_past_deadline_uncrossed_bars_resolve_incorrect_with_evidence(repo):
    """THE MANDATED FIXTURE: the incorrect verdict's evidence JSON records
    the exact window checked and the max high that never reached threshold."""
    claim = price_claim(repo, deadline=PAST, created_at=CREATED_PAST)
    d1 = (TODAY - timedelta(days=10)).isoformat()
    d2 = (TODAY - timedelta(days=5)).isoformat()
    summary = await resolver_for(
        repo,
        quote_fetcher=quotes(XOP=100.0),
        bar_fetcher=bars((d1, 108.0, 101.0), (d2, 112.5, 99.0)),
    ).run_once()

    assert summary["resolved"] == 1
    row = get_prediction(repo, claim["id"])
    assert row["resolution"] == "incorrect"
    ev = evidence(repo, claim["id"])
    assert ev == {
        "auto": "price_cross",
        "provider": "yahoo_v8_daily",
        "observed": {
            "window": {"start": CREATED_PAST[:10], "end": PAST},
            "bars": 2,
            "max_high": 112.5,
            "threshold": 115.0,
            "comparator": "above",
        },
    }


@pytest.mark.asyncio
async def test_past_deadline_bar_cross_resolves_correct_retroactively(repo):
    """Bars prove the cross happened inside the window even though the
    resolver only looked after expiry — no false incorrect."""
    claim = price_claim(repo, deadline=PAST, created_at=CREATED_PAST)
    hit_day = (TODAY - timedelta(days=6)).isoformat()
    await resolver_for(
        repo,
        quote_fetcher=quotes(XOP=100.0),
        bar_fetcher=bars((hit_day, 116.0, 108.0)),
    ).run_once()
    row = get_prediction(repo, claim["id"])
    assert row["resolution"] == "correct"
    assert evidence(repo, claim["id"])["observed"]["date"] == hit_day


@pytest.mark.asyncio
async def test_past_deadline_spot_cross_is_not_the_oracle(repo):
    """Spot sits across the threshold NOW, but the pre-deadline bars show no
    cross → incorrect; the NEXT sweep flags the post-deadline crossing BAR
    as a late cross, stamped with the bar's own date (the right-but-early
    laboratory hook)."""
    claim = price_claim(repo, deadline=PAST, created_at=CREATED_PAST)
    hit_day = (TODAY - timedelta(days=1)).isoformat()  # one day past deadline+0
    resolver = resolver_for(
        repo,
        quote_fetcher=quotes(XOP=150.0),
        bar_fetcher=bars(
            ((TODAY - timedelta(days=8)).isoformat(), 110.0, 100.0),  # in-window, no cross
            (hit_day, 150.0, 140.0),                                   # post-deadline cross
        ),
    )

    first = await resolver.run_once()
    assert first["resolved"] == 1 and first["late_crosses"] == 0
    assert get_prediction(repo, claim["id"])["resolution"] == "incorrect"

    second = await resolver.run_once()
    assert second["resolved"] == 0 and second["late_crosses"] == 1
    flags = repo.list_audit(action=LATE_CROSS_ACTION)
    assert len(flags) == 1 and flags[0]["target"] == claim["id"]
    stamp = json.loads(flags[0]["reason"])
    # delay_days dates from the crossing BAR, not from today.
    assert stamp == {"late_cross": {"date": hit_day, "delay_days": 1}}
    # The resolution itself stands untouched.
    assert get_prediction(repo, claim["id"])["resolution"] == "incorrect"
    # And the queryable notes field carries the same structured stamp,
    # merged into the auto-resolve evidence JSON without destroying it.
    notes = json.loads(get_prediction(repo, claim["id"])["resolution_notes"])
    assert notes["late_cross"] == {"date": hit_day, "delay_days": 1}
    assert notes.get("auto") == "price_cross"  # evidence survived the merge


@pytest.mark.asyncio
async def test_bars_unavailable_never_resolves_even_past_deadline(repo):
    claim = price_claim(repo, deadline=PAST, created_at=CREATED_PAST)
    summary = await resolver_for(
        repo, quote_fetcher=quotes(XOP=100.0), bar_fetcher=bars_unavailable
    ).run_once()
    assert summary == {"resolved": 0, "skipped": 1, "late_crosses": 0}
    assert get_prediction(repo, claim["id"])["resolution"] is None


@pytest.mark.asyncio
async def test_empty_bar_window_past_deadline_skips(repo):
    """Zero bars is indistinguishable from missing data — skip, don't guess."""
    claim = price_claim(repo, deadline=PAST, created_at=CREATED_PAST)
    summary = await resolver_for(
        repo, quote_fetcher=quotes(XOP=100.0), bar_fetcher=bars()
    ).run_once()
    assert summary["skipped"] == 1
    assert get_prediction(repo, claim["id"])["resolution"] is None


@pytest.mark.asyncio
async def test_spot_missing_bars_still_decide(repo):
    """Absence of a spot quote proves nothing — the bars are consulted."""
    claim = price_claim(repo, created_at=CREATED_PAST)
    hit_day = (TODAY - timedelta(days=2)).isoformat()
    summary = await resolver_for(
        repo, quote_fetcher=quotes(), bar_fetcher=bars((hit_day, 120.0, 110.0))
    ).run_once()
    assert summary["resolved"] == 1
    assert get_prediction(repo, claim["id"])["resolution"] == "correct"


@pytest.mark.asyncio
async def test_unparseable_deadline_skips(repo):
    claim = price_claim(repo, deadline="whenever")
    summary = await resolver_for(
        repo, quote_fetcher=quotes(XOP=150.0), bar_fetcher=bars()
    ).run_once()
    # Unparseable window skips even though the spot would have crossed —
    # the spot short-circuit needs a valid window to assert "before deadline".
    assert summary["skipped"] == 1
    assert get_prediction(repo, claim["id"])["resolution"] is None


def test_fetch_daily_bars_parses_and_windows(monkeypatch):
    """Yahoo v8 parse: null bars dropped, timestamps → UTC dates, and only
    bars inside [start .. end] survive."""
    def ts(d: date) -> int:
        return int(datetime(d.year, d.month, d.day, 15, 30,
                            tzinfo=timezone.utc).timestamp())

    inside = TODAY - timedelta(days=3)
    before = TODAY - timedelta(days=30)
    payload = {"chart": {"result": [{
        "timestamp": [ts(before), ts(inside), None, ts(TODAY)],
        "indicators": {"quote": [{
            "high": [90.0, 100.2, 50.0, None],
            "low": [85.0, 96.0, 40.0, 97.0],
        }]},
    }]}}

    class FakeResp:
        def read(self):
            return json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    seen_urls = []

    def fake_urlopen(req, timeout=20):
        seen_urls.append(req.full_url)
        return FakeResp()

    monkeypatch.setattr(cr_module, "urlopen", fake_urlopen)

    result = fetch_daily_bars("XOP", TODAY - timedelta(days=10), TODAY)
    assert result == [
        {"date": inside, "high": 100.2, "low": 96.0},
        {"date": TODAY, "high": None, "low": 97.0},
    ]
    assert "interval=1d" in seen_urls[0] and "range=1mo" in seen_urls[0]


# ════════════════════════════════════════════════════════════════════
# polymarket
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_polymarket_closed_yes_resolves_correct(repo):
    claim = poly_claim(repo)
    fetcher = lambda mid: {"closed": True, "yes_probability": 1.0}  # noqa: E731
    spy = quote_spy()
    summary = await resolver_for(
        repo, quote_fetcher=spy, market_state_fetcher=fetcher
    ).run_once()
    assert summary["resolved"] == 1
    assert spy.calls == 0
    row = get_prediction(repo, claim["id"])
    assert row["resolution"] == "correct"
    assert evidence(repo, claim["id"]) == {
        "auto": "polymarket", "provider": "gamma",
        "market_id": "us-strike-2026", "outcome": "Yes",
    }


@pytest.mark.asyncio
async def test_polymarket_closed_no_resolves_incorrect(repo):
    claim = poly_claim(repo)
    fetcher = lambda mid: {"closed": True, "yes_probability": 0.0}  # noqa: E731
    await resolver_for(repo, market_state_fetcher=fetcher).run_once()
    row = get_prediction(repo, claim["id"])
    assert row["resolution"] == "incorrect"
    assert evidence(repo, claim["id"])["outcome"] == "No"


@pytest.mark.asyncio
async def test_polymarket_open_market_skips_even_past_deadline(repo):
    claim = poly_claim(repo, deadline=PAST)
    fetcher = lambda mid: {"closed": False, "yes_probability": 0.62}  # noqa: E731
    summary = await resolver_for(repo, market_state_fetcher=fetcher).run_once()
    assert summary["skipped"] == 1
    assert get_prediction(repo, claim["id"])["resolution"] is None


@pytest.mark.asyncio
async def test_polymarket_fetch_failure_skips(repo):
    claim = poly_claim(repo)
    summary = await resolver_for(
        repo, market_state_fetcher=lambda mid: None
    ).run_once()
    assert summary["skipped"] == 1
    assert get_prediction(repo, claim["id"])["resolution"] is None


def test_polymarket_verdict_mapping():
    """The YES-side contract, as a pure table."""
    assert polymarket_verdict({"closed": True, "yes_probability": 1.0}) == "correct"
    assert polymarket_verdict({"closed": True, "yes_probability": 0.995}) == "correct"
    assert polymarket_verdict({"closed": True, "yes_probability": 0.0}) == "incorrect"
    assert polymarket_verdict({"closed": True, "yes_probability": 0.005}) == "incorrect"
    # Closed but unsettled prices are ambiguous — no verdict.
    assert polymarket_verdict({"closed": True, "yes_probability": 0.5}) is None
    assert polymarket_verdict({"closed": True, "yes_probability": None}) is None
    assert polymarket_verdict({"closed": False, "yes_probability": 1.0}) is None
    assert polymarket_verdict(None) is None


def test_fetch_polymarket_market_state_sees_closed_markets(monkeypatch):
    """The lookup must NOT inherit the shared client's closed=false filter."""
    from tools.data_fetch import polymarket as polymarket_mod

    seen_urls = []

    def fake_request(url, timeout=15):
        seen_urls.append(url)
        return json.dumps([{
            "slug": "us-strike-2026",
            "closed": True,
            "outcomePrices": '["1", "0"]',
            "outcomes": '["Yes", "No"]',
        }]).encode()

    monkeypatch.setattr(polymarket_mod, "_search_events", lambda q, timeout=15: [])
    monkeypatch.setattr(polymarket_mod, "_make_request", fake_request)

    state = fetch_polymarket_market_state("us-strike-2026")
    assert state == {"closed": True, "yes_probability": 1.0}
    assert seen_urls and "closed=false" not in seen_urls[0]


# ════════════════════════════════════════════════════════════════════
# idempotency + human precedence
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_idempotent_rerun_is_noop(repo):
    claim = price_claim(repo)
    ws = FakeWS()
    resolver = resolver_for(repo, ws, quotes(XOP=150.0), bar_fetcher=bars())

    assert (await resolver.run_once())["resolved"] == 1
    assert (await resolver.run_once())["resolved"] == 0

    assert get_prediction(repo, claim["id"])["resolution"] == "correct"
    assert len(repo.list_audit(action=AUTO_RESOLVE_ACTION)) == 1
    assert len(ws.broadcasts) == 1


@pytest.mark.asyncio
async def test_human_resolution_wins_conflict_stands_down(repo):
    """Race shape: the sweep read the row unresolved, a human resolved it
    incorrect before _apply ran. The auto verdict must withdraw silently."""
    claim = price_claim(repo)
    ws = FakeWS()
    resolver = resolver_for(repo, ws, quotes(XOP=150.0))
    row_snapshot = get_prediction(repo, claim["id"])

    repo.resolve_prediction_once(claim["id"], "incorrect", None, "human call")

    applied = await resolver._apply(row_snapshot, "correct", "auto: cross observed")
    assert applied is False
    assert get_prediction(repo, claim["id"])["resolution"] == "incorrect"
    assert repo.list_audit(action=AUTO_RESOLVE_ACTION) == []
    assert ws.broadcasts == []


@pytest.mark.asyncio
async def test_apply_same_verdict_replay_is_silent(repo):
    claim = price_claim(repo)
    ws = FakeWS()
    resolver = resolver_for(repo, ws, quotes(XOP=150.0))
    row_snapshot = get_prediction(repo, claim["id"])

    repo.resolve_prediction_once(claim["id"], "correct", None, "human call")

    assert await resolver._apply(row_snapshot, "correct", "auto") is False
    assert ws.broadcasts == []
    assert repo.list_audit(action=AUTO_RESOLVE_ACTION) == []


@pytest.mark.asyncio
async def test_human_resolved_rows_never_reach_apply(repo):
    claim = price_claim(repo)
    repo.resolve_prediction_once(claim["id"], "partial", None, None)
    summary = await resolver_for(repo, quote_fetcher=quotes(XOP=150.0)).run_once()
    assert summary == {"resolved": 0, "skipped": 0, "late_crosses": 0}
    assert get_prediction(repo, claim["id"])["resolution"] == "partial"


# ════════════════════════════════════════════════════════════════════
# late-cross watch
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_late_cross_bar_catches_spike_spot_missed(repo):
    """MANDATED FIXTURE: the post-deadline spike fell back before any spot
    tick saw it. The daily bar's high is the watch's oracle, and the stamp
    carries the BAR's date — today's date would overstate the delay."""
    claim = price_claim(repo, deadline=PAST, created_at=CREATED_PAST)
    repo.resolve_prediction_once(claim["id"], "incorrect", None, "expired")
    hit_day = (TODAY - timedelta(days=1)).isoformat()
    summary = await resolver_for(
        repo,
        quote_fetcher=quotes(XOP=98.0),  # spot sits back below threshold
        bar_fetcher=bars((hit_day, 115.5, 97.0)),
    ).run_once()

    assert summary["late_crosses"] == 1
    flags = repo.list_audit(action=LATE_CROSS_ACTION)
    assert len(flags) == 1 and flags[0]["target"] == claim["id"]
    assert json.loads(flags[0]["reason"]) == {
        "late_cross": {"date": hit_day, "delay_days": 1}
    }
    assert flags[0]["payload"]["bar"] == {"date": hit_day, "high": 115.5}
    row = get_prediction(repo, claim["id"])
    assert row["resolution"] == "incorrect"  # the verdict stands
    # Prose human notes get the stamp appended, never rewritten.
    assert row["resolution_notes"].startswith("expired")
    assert '"late_cross"' in row["resolution_notes"]


@pytest.mark.asyncio
async def test_late_cross_watch_window_is_post_deadline_only(repo):
    """The watch asks for (deadline, min(today, deadline+30d)] — an
    at-or-before-deadline bar belongs to resolution, not the watch."""
    claim = price_claim(repo, deadline=PAST, created_at=CREATED_PAST)
    repo.resolve_prediction_once(claim["id"], "incorrect", None, "expired")
    bar_fetch = bars()
    await resolver_for(repo, bar_fetcher=bar_fetch).run_once()
    deadline = TODAY - timedelta(days=2)
    assert bar_fetch.windows == [("XOP", deadline + timedelta(days=1), TODAY)]


@pytest.mark.asyncio
async def test_late_cross_flagged_once_across_restarts(repo):
    claim = price_claim(repo, deadline=PAST, created_at=CREATED_PAST)
    repo.resolve_prediction_once(claim["id"], "incorrect", None, "expired")
    hit_day = (TODAY - timedelta(days=1)).isoformat()

    first = resolver_for(repo, bar_fetcher=bars((hit_day, 150.0, 140.0)))
    assert (await first.run_once())["late_crosses"] == 1
    assert (await first.run_once())["late_crosses"] == 0

    # A fresh resolver (process restart) hydrates the flag set from audit.
    second = resolver_for(repo, bar_fetcher=bars((hit_day, 150.0, 140.0)))
    assert (await second.run_once())["late_crosses"] == 0
    flags = repo.list_audit(action=LATE_CROSS_ACTION)
    assert len(flags) == 1
    assert json.loads(flags[0]["reason"])["late_cross"]["delay_days"] == 1


@pytest.mark.asyncio
async def test_late_cross_uncrossed_bars_not_flagged(repo):
    claim = price_claim(repo, deadline=PAST, created_at=CREATED_PAST)
    repo.resolve_prediction_once(claim["id"], "incorrect", None, "expired")
    uncrossed = ((TODAY - timedelta(days=1)).isoformat(), 110.0, 100.0)
    summary = await resolver_for(repo, bar_fetcher=bars(uncrossed)).run_once()
    assert summary["late_crosses"] == 0
    assert repo.list_audit(action=LATE_CROSS_ACTION) == []


@pytest.mark.asyncio
async def test_late_cross_bars_unavailable_not_flagged(repo):
    claim = price_claim(repo, deadline=PAST, created_at=CREATED_PAST)
    repo.resolve_prediction_once(claim["id"], "incorrect", None, "expired")
    summary = await resolver_for(repo, bar_fetcher=bars_unavailable).run_once()
    assert summary["late_crosses"] == 0
    assert repo.list_audit(action=LATE_CROSS_ACTION) == []


@pytest.mark.asyncio
async def test_late_cross_existing_notes_stamp_respected(repo):
    """A row whose notes already carry a late_cross object (a backfill, or
    the stamp seam itself) must not be double-flagged."""
    claim = price_claim(repo, deadline=PAST, created_at=CREATED_PAST)
    repo.resolve_prediction_once(
        claim["id"], "incorrect", None,
        json.dumps({"late_cross": {"date": "2026-08-10", "delay_days": 5}}),
    )
    hit = ((TODAY - timedelta(days=1)).isoformat(), 150.0, 140.0)
    summary = await resolver_for(repo, bar_fetcher=bars(hit)).run_once()
    assert summary["late_crosses"] == 0
    assert repo.list_audit(action=LATE_CROSS_ACTION) == []


@pytest.mark.asyncio
async def test_late_cross_window_expires(repo):
    old_deadline = (TODAY - timedelta(days=45)).isoformat()
    claim = price_claim(repo, deadline=old_deadline, created_at=CREATED_PAST)
    repo.resolve_prediction_once(claim["id"], "incorrect", None, "expired")
    hit = ((TODAY - timedelta(days=1)).isoformat(), 150.0, 140.0)
    summary = await resolver_for(repo, bar_fetcher=bars(hit)).run_once()
    assert summary["late_crosses"] == 0


# ════════════════════════════════════════════════════════════════════
# efficiency + wiring
# ════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_empty_ledger_is_free(repo):
    spy = quote_spy()
    summary = await resolver_for(repo, quote_fetcher=spy).run_once()
    assert summary == {"resolved": 0, "skipped": 0, "late_crosses": 0}
    assert spy.calls == 0


@pytest.mark.asyncio
async def test_specless_predictions_ignored(repo):
    record, _ = repo.save_prediction_once("amo", {
        "statement": "free-text call, human flow only",
        "confidence": 0.8,
        "deadline": PAST,
    })
    spy = quote_spy()
    summary = await resolver_for(repo, quote_fetcher=spy).run_once()
    assert summary == {"resolved": 0, "skipped": 0, "late_crosses": 0}
    assert spy.calls == 0
    assert get_prediction(repo, record["id"])["resolution"] is None


@pytest.mark.asyncio
async def test_coordinator_tick_survives_resolver_fault():
    """The tick sweep must complete even when claim resolution explodes."""
    coordinator = RuntimeCoordinator(repo=MagicMock(), ws_manager=None)
    coordinator._claim_resolver.run_once = AsyncMock(
        side_effect=RuntimeError("boom")
    )
    await coordinator._run_all_ticks()  # must not raise
    coordinator._claim_resolver.run_once.assert_awaited_once()


@pytest.mark.asyncio
async def test_coordinator_tick_invokes_resolver():
    coordinator = RuntimeCoordinator(repo=MagicMock(), ws_manager=None)
    coordinator._claim_resolver.run_once = AsyncMock(
        return_value={"resolved": 0, "skipped": 0, "late_crosses": 0}
    )
    await coordinator._run_all_ticks()
    coordinator._claim_resolver.run_once.assert_awaited_once()
