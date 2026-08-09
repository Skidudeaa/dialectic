"""
Tests for the per-source feed-freshness contract (cockpit Unit 5).

WHY: The UI paints amber staleness badges off the snapshot's `feedFreshness`
block. If the shape drifts or the Pydantic model rejects a valid stamp, badges
go silent and the operator loses the "is my data fresh?" signal. These tests
lock the contract both directions — accept well-formed stamps, reject bad ones.
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from web.schemas.snapshots import FeedFreshness, ThesisSnapshot, snapshot_from_export


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class TestFeedFreshnessModel:
    """FeedFreshness: source + fetchedAt + ttlSeconds (+ optional detail)."""

    def test_minimal_fields_accepted(self):
        f = FeedFreshness(source="yahoo", fetchedAt=_iso_now(), ttlSeconds=300)
        assert f.source == "yahoo"
        assert f.ttlSeconds == 300
        assert f.detail is None

    def test_detail_round_trip(self):
        f = FeedFreshness(
            source="polymarket",
            fetchedAt=_iso_now(),
            ttlSeconds=900,
            detail="3/5 markets matched",
        )
        assert f.detail == "3/5 markets matched"

    def test_ttl_must_be_positive(self):
        with pytest.raises(ValidationError):
            FeedFreshness(source="yahoo", fetchedAt=_iso_now(), ttlSeconds=0)
        with pytest.raises(ValidationError):
            FeedFreshness(source="yahoo", fetchedAt=_iso_now(), ttlSeconds=-1)

    def test_required_fields_missing_rejects(self):
        with pytest.raises(ValidationError):
            FeedFreshness(source="yahoo", ttlSeconds=300)  # no fetchedAt
        with pytest.raises(ValidationError):
            FeedFreshness(fetchedAt=_iso_now(), ttlSeconds=300)  # no source


class TestSnapshotFeedFreshnessBlock:
    """ThesisSnapshot accepts a Dict[source,FeedFreshness] and defaults to {}."""

    def _minimal_export(self, freshness: dict | None = None) -> dict:
        """Smallest valid export payload for snapshot_from_export()."""
        export = {
            "v": 2,
            "timestamp": _iso_now(),
            "title": "Test Thesis",
            "nodeStates": {},
            "confluenceScores": {},
            "cascadePhase": {"number": 1, "key": "shock", "status": "STARTING"},
            "countdowns": [],
            "marketSnapshot": {},
            "scenarioImpacts": {},
            "portfolioSummary": {"monthlyBudget": 0, "topPositions": []},
            "horizonTrace": {},
            "tvIndicators": {},
        }
        if freshness is not None:
            export["feedFreshness"] = freshness
        return export

    def test_missing_block_defaults_empty(self):
        """Legacy snapshot without feedFreshness still validates."""
        snap = snapshot_from_export(self._minimal_export())
        assert snap.feedFreshness == {}

    def test_single_source_stamped(self):
        freshness = {
            "yahoo": {
                "source": "yahoo",
                "fetchedAt": _iso_now(),
                "ttlSeconds": 300,
            }
        }
        snap = snapshot_from_export(self._minimal_export(freshness))
        assert "yahoo" in snap.feedFreshness
        assert snap.feedFreshness["yahoo"].ttlSeconds == 300

    def test_multi_source_coexists(self):
        """Several providers can stamp independently in one snapshot."""
        freshness = {
            "yahoo": {"source": "yahoo", "fetchedAt": _iso_now(), "ttlSeconds": 300},
            "polymarket": {
                "source": "polymarket",
                "fetchedAt": _iso_now(),
                "ttlSeconds": 900,
                "detail": "12/15 markets",
            },
            "derived": {
                "source": "derived",
                "fetchedAt": _iso_now(),
                "ttlSeconds": 86400,
            },
        }
        snap = snapshot_from_export(self._minimal_export(freshness))
        assert set(snap.feedFreshness.keys()) == {"yahoo", "polymarket", "derived"}
        assert snap.feedFreshness["polymarket"].detail == "12/15 markets"

    def test_malformed_entry_rejects(self):
        """A stamp with ttl <= 0 should fail the whole snapshot."""
        bad = {
            "yahoo": {
                "source": "yahoo",
                "fetchedAt": _iso_now(),
                "ttlSeconds": 0,  # invalid
            }
        }
        with pytest.raises(ValidationError):
            snapshot_from_export(self._minimal_export(bad))

    def test_direct_model_instantiation(self):
        """Building ThesisSnapshot directly from kwargs also works."""
        snap = ThesisSnapshot(
            v=2,
            thesisId="test",
            timestamp=_iso_now(),
            title="Test",
            nodeStates={},
            confluenceScores={},
            cascadePhase={"number": 1, "key": "shock", "status": "STARTING"},
            countdowns=[],
            marketSnapshot={},
            scenarioImpacts={},
            portfolioSummary={"monthlyBudget": 0, "topPositions": []},
            feedFreshness={
                "fred": FeedFreshness(
                    source="fred",
                    fetchedAt=_iso_now(),
                    ttlSeconds=3600,
                    detail="DGS10, DTWEXBGS",
                )
            },
        )
        assert snap.feedFreshness["fred"].ttlSeconds == 3600


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
