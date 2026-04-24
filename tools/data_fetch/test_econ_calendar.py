#!/usr/bin/env python3
"""
Tests for the econ calendar connector.

Run with: python3 -m pytest tools/data_fetch/test_econ_calendar.py -q

WHY mock HTTP: tests must work offline. We monkeypatch _fred_get to drive the
FRED success and failure paths without network. The static fallback runs
unmocked because it is, by design, deterministic and offline-safe.
"""

import json
import os
import sys
from datetime import date, timedelta
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from econ_calendar import (  # noqa: E402
    _STATIC_EVENTS,
    _filter_static,
    _parse_iso_date,
    _score_match,
    _tokenize,
    fetch_upcoming_events,
    match_event,
)


# Anchor "today" to match the curated static window. The plan asks the static
# table to span the next 90 days from 2026-04-24, so we test against that
# anchor across the suite.
TODAY = date(2026, 4, 24)


# =============================================================================
# Static fallback path
# =============================================================================

class TestStaticFallback:
    def test_static_fallback_returns_events(self):
        """Static fallback must always return events for the curated window."""
        events = fetch_upcoming_events(lookahead_days=90, today=TODAY, api_key=None)
        assert isinstance(events, list)
        assert len(events) >= 6
        for ev in events:
            assert ev["source"] == "static"

    def test_static_lookahead_window_honored(self):
        """A 7-day lookahead trims the result set."""
        narrow = fetch_upcoming_events(lookahead_days=7, today=TODAY, api_key=None)
        wide = fetch_upcoming_events(lookahead_days=90, today=TODAY, api_key=None)
        # Narrow window must be a strict subset of the wider one.
        assert len(narrow) < len(wide)
        for ev in narrow:
            assert 0 <= ev["days_remaining"] <= 7

    def test_zero_lookahead_returns_only_today(self):
        """lookahead_days=0 is a degenerate but legal request."""
        events = fetch_upcoming_events(lookahead_days=0, today=TODAY, api_key=None)
        for ev in events:
            assert ev["days_remaining"] == 0

    def test_negative_lookahead_raises(self):
        with pytest.raises(ValueError):
            fetch_upcoming_events(lookahead_days=-1, today=TODAY, api_key=None)

    def test_static_dataset_size_meets_minimum(self):
        """Plan requires >=6 events covering the next 90 days from 2026-04-24."""
        events = _filter_static(today=TODAY, lookahead_days=90)
        assert len(events) >= 6


# =============================================================================
# FRED primary path
# =============================================================================

def _fred_response_with(release_dates):
    """Build a FRED-shaped JSON response."""
    return {
        "realtime_start": TODAY.isoformat(),
        "realtime_end": (TODAY + timedelta(days=90)).isoformat(),
        "release_dates": release_dates,
    }


class TestFredPath:
    def test_fred_success_returns_fred_events(self, monkeypatch):
        """When FRED succeeds, events from FRED are returned and tagged."""
        payload = _fred_response_with([
            {"release_id": 10, "release_name": "Consumer Price Index",
             "date": (TODAY + timedelta(days=14)).isoformat()},
            {"release_id": 11, "release_name": "Employment Situation",
             "date": (TODAY + timedelta(days=8)).isoformat()},
        ])
        monkeypatch.setattr(
            "econ_calendar._fred_get", lambda path, params, timeout=10: payload
        )
        events = fetch_upcoming_events(
            lookahead_days=90, today=TODAY, api_key="fake-key"
        )
        assert events, "expected at least one FRED event"
        for ev in events:
            assert ev["source"] == "fred"
        # Should be sorted by days_remaining ascending.
        days = [e["days_remaining"] for e in events]
        assert days == sorted(days)

    def test_fred_5xx_falls_back_to_static(self, monkeypatch):
        """FRED HTTPError must transparently fall back to static."""
        def boom(path, params, timeout=10):
            raise HTTPError(
                url="x", code=503, msg="Service Unavailable", hdrs=None, fp=None
            )

        monkeypatch.setattr("econ_calendar._fred_get", boom)
        events = fetch_upcoming_events(
            lookahead_days=90, today=TODAY, api_key="fake-key"
        )
        assert events, "fallback must return non-empty"
        for ev in events:
            assert ev["source"] == "static"

    def test_fred_url_error_falls_back_to_static(self, monkeypatch):
        """Network errors on the FRED path must fall back."""
        def boom(path, params, timeout=10):
            raise URLError("connection refused")

        monkeypatch.setattr("econ_calendar._fred_get", boom)
        events = fetch_upcoming_events(
            lookahead_days=90, today=TODAY, api_key="fake-key"
        )
        assert events
        assert all(ev["source"] == "static" for ev in events)

    def test_fred_empty_falls_back_to_static(self, monkeypatch):
        """If FRED returns no events in window, fallback fills the gap."""
        monkeypatch.setattr(
            "econ_calendar._fred_get",
            lambda path, params, timeout=10: _fred_response_with([]),
        )
        events = fetch_upcoming_events(
            lookahead_days=90, today=TODAY, api_key="fake-key"
        )
        assert events
        assert all(ev["source"] == "static" for ev in events)

    def test_fred_filters_outside_window(self, monkeypatch):
        """Releases outside the lookahead window are dropped."""
        payload = _fred_response_with([
            {"release_id": 1, "release_name": "Within",
             "date": (TODAY + timedelta(days=10)).isoformat()},
            {"release_id": 2, "release_name": "Past",
             "date": (TODAY - timedelta(days=5)).isoformat()},
            {"release_id": 3, "release_name": "Beyond",
             "date": (TODAY + timedelta(days=200)).isoformat()},
        ])
        monkeypatch.setattr(
            "econ_calendar._fred_get", lambda path, params, timeout=10: payload
        )
        events = fetch_upcoming_events(
            lookahead_days=90, today=TODAY, api_key="fake-key"
        )
        assert len(events) == 1
        assert events[0]["label"] == "Within"

    def test_no_api_key_uses_static(self, monkeypatch):
        """Without an API key, the FRED path is skipped entirely."""
        called = {"hits": 0}

        def boom(path, params, timeout=10):
            called["hits"] += 1
            raise AssertionError("FRED must not be called without a key")

        monkeypatch.setattr("econ_calendar._fred_get", boom)
        monkeypatch.delenv("FRED_API_KEY", raising=False)
        events = fetch_upcoming_events(lookahead_days=90, today=TODAY, api_key=None)
        assert called["hits"] == 0
        assert all(ev["source"] == "static" for ev in events)


# =============================================================================
# match_event
# =============================================================================

class TestMatchEvent:
    def test_match_by_exact_slug(self):
        events = fetch_upcoming_events(lookahead_days=90, today=TODAY, api_key=None)
        hit = match_event("boj-2026-05", events)
        assert hit is not None
        assert hit["event_id"] == "boj-2026-05"

    def test_match_by_keyword(self):
        events = fetch_upcoming_events(lookahead_days=90, today=TODAY, api_key=None)
        hit = match_event("boj-decision", events)
        assert hit is not None
        # Keyword "boj" must steer us to a BoJ event, not FOMC/CPI.
        assert hit["event_id"].startswith("boj-")

    def test_match_by_description_freetext(self):
        events = fetch_upcoming_events(lookahead_days=90, today=TODAY, api_key=None)
        hit = match_event("Next FOMC rate decision", events)
        assert hit is not None
        assert hit["event_id"].startswith("fomc-")

    def test_no_match_returns_none(self):
        events = fetch_upcoming_events(lookahead_days=90, today=TODAY, api_key=None)
        assert match_event("xyzzy-no-match-anywhere", events) is None

    def test_empty_query_returns_none(self):
        events = fetch_upcoming_events(lookahead_days=90, today=TODAY, api_key=None)
        assert match_event("", events) is None
        assert match_event("   ", events) is None

    def test_empty_events_list_returns_none(self):
        assert match_event("fomc", []) is None

    def test_match_prefers_earliest_when_tied(self):
        """When two events tie on score, the soonest one wins."""
        events = fetch_upcoming_events(lookahead_days=90, today=TODAY, api_key=None)
        hit = match_event("fomc", events)
        assert hit is not None
        assert hit["event_id"].startswith("fomc-")
        # All FOMC events should have the same score; earliest must win.
        fomc_events = [e for e in events if e["event_id"].startswith("fomc-")]
        earliest = min(fomc_events, key=lambda e: e["date"])
        assert hit["event_id"] == earliest["event_id"]


# =============================================================================
# Schema / shape invariants
# =============================================================================

class TestEventShape:
    def test_iso8601_date_shape(self):
        events = fetch_upcoming_events(lookahead_days=90, today=TODAY, api_key=None)
        for ev in events:
            # ISO date YYYY-MM-DD — exactly 10 chars, parseable
            assert isinstance(ev["date"], str)
            assert len(ev["date"]) == 10
            assert _parse_iso_date(ev["date"]) is not None

    def test_required_keys_present(self):
        events = fetch_upcoming_events(lookahead_days=90, today=TODAY, api_key=None)
        required = {"event_id", "label", "source", "date", "days_remaining"}
        for ev in events:
            assert required.issubset(ev.keys()), ev

    def test_days_remaining_math(self):
        events = fetch_upcoming_events(lookahead_days=90, today=TODAY, api_key=None)
        for ev in events:
            d = _parse_iso_date(ev["date"])
            assert d is not None
            assert ev["days_remaining"] == (d - TODAY).days

    def test_expired_events_filtered(self):
        """Events strictly before `today` must not appear in the result."""
        # Push "today" forward so most static entries become expired.
        future = date(2026, 8, 1)
        events = fetch_upcoming_events(lookahead_days=90, today=future, api_key=None)
        for ev in events:
            assert ev["days_remaining"] >= 0

    def test_results_sorted_ascending(self):
        events = fetch_upcoming_events(lookahead_days=90, today=TODAY, api_key=None)
        days = [e["days_remaining"] for e in events]
        assert days == sorted(days)

    def test_event_ids_unique(self):
        events = fetch_upcoming_events(lookahead_days=90, today=TODAY, api_key=None)
        ids = [e["event_id"] for e in events]
        assert len(ids) == len(set(ids)), "event_ids must be unique"

    def test_serializable_to_json(self):
        """Event dicts must be plain JSON (no datetime objects, no sets)."""
        events = fetch_upcoming_events(lookahead_days=90, today=TODAY, api_key=None)
        # Round-trip through json to prove serializability.
        encoded = json.dumps(events)
        decoded = json.loads(encoded)
        assert decoded == events


# =============================================================================
# Tokenizer + scorer (kept tight; just enough to lock semantics)
# =============================================================================

class TestScoring:
    def test_tokenize_kebab_case(self):
        assert _tokenize("boj-decision") == ["boj", "decision"]

    def test_tokenize_freetext(self):
        toks = _tokenize("Next FOMC — rate decision (May)")
        assert "fomc" in toks
        assert "rate" in toks
        assert "may" in toks

    def test_score_exact_id_dominates(self):
        ev = _STATIC_EVENTS[0]
        score = _score_match(_tokenize(ev["event_id"]), {**ev, "label": ev["label"]})
        # Exact id match returns the sentinel high score.
        assert score >= 10_000
