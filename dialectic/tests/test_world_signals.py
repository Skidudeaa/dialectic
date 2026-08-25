"""Pure contracts for the ephemeral, process-local WorldSignal owner."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from world_signals import (
    WorldSignal,
    WorldSignalExpired,
    WorldSignalMalformedId,
    WorldSignalNotFound,
    WorldSignalSnapshot,
    WorldSignalStore,
    WorldSignalWrongRoom,
)


ROOM_A = UUID("00000000-0000-4000-c000-000000000001")
ROOM_B = UUID("00000000-0000-4000-c000-000000000002")
NOW = datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc)


def _signal(
    source_id: str = "contact-1", *, room_id: UUID = ROOM_A,
    expires_at: datetime | None = None, freshness: str = "current",
) -> WorldSignal:
    return WorldSignal(
        id=f"world_signal:ais:{source_id}",
        provider="ais",
        source_id=source_id,
        room_id=room_id,
        layer="vessels",
        kind="point",
        geometry={"type": "Point", "coordinates": [56.3, 26.5]},
        provenance={
            "provider": "ais",
            "acquisition": "adapter:ais",
            "source_id": source_id,
            "url": "https://provider.test/contact-1",
            "credit": "AIS provider credit",
        },
        source_state="partial",
        freshness=freshness,
        coverage="Strait of Hormuz receiver footprint",
        observed_at=NOW - timedelta(minutes=2),
        retrieved_at=NOW - timedelta(minutes=1),
        expires_at=expires_at or NOW + timedelta(minutes=10),
        label=f"Contact {source_id}",
        details={"speed_knots": 12.4, "course": 91},
    )


def _snapshot(*signals: WorldSignal, source_state: str = "partial") -> WorldSignalSnapshot:
    return WorldSignalSnapshot(
        provider="ais",
        source_state=source_state,
        freshness="current",
        coverage="Strait of Hormuz receiver footprint",
        observed_at=NOW - timedelta(minutes=2),
        retrieved_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=10),
        signals=signals,
    )


def test_world_signal_validates_identity_geometry_and_server_provenance() -> None:
    signal = _signal()
    assert signal.id == "world_signal:ais:contact-1"
    assert signal.geometry == {"type": "Point", "coordinates": [56.3, 26.5]}

    with pytest.raises(ValidationError, match="canonical"):
        WorldSignal(**{
            **_signal().model_dump(),
            "id": "world_signal:ais:someone-else",
        })

    with pytest.raises(ValidationError, match="adapter:ais"):
        WorldSignal(**{
            **_signal().model_dump(),
            "provenance": {
                **_signal().provenance.model_dump(),
                "acquisition": "human",
            },
        })

    with pytest.raises(ValidationError, match="out of range"):
        WorldSignal(**{
            **_signal().model_dump(),
            "geometry": {"type": "Point", "coordinates": [400, 0]},
        })


def test_world_signal_is_frozen_and_store_reads_cannot_mutate_the_snapshot() -> None:
    store = WorldSignalStore()
    store.replace(_snapshot(_signal()))

    with pytest.raises(ValidationError, match="frozen"):
        store.project({ROOM_A}, now=NOW).signals[0].label = "rewritten"

    first = store.project({ROOM_A}, now=NOW)
    first.signals[0].geometry["coordinates"][0] = 0
    assert store.project({ROOM_A}, now=NOW).signals[0].geometry["coordinates"] == [56.3, 26.5]


def test_snapshot_replacement_is_bounded_atomic_and_replaces_one_provider_whole() -> None:
    store = WorldSignalStore(max_signals_per_source=2, max_total_signals=2)
    store.replace(_snapshot(_signal("old-1"), _signal("old-2")))

    too_large = _snapshot(_signal("new-1"), _signal("new-2"), _signal("new-3"))
    with pytest.raises(ValueError, match="at most 2 signals"):
        store.replace(too_large)
    assert [s.source_id for s in store.project({ROOM_A}, now=NOW).signals] == ["old-1", "old-2"]

    store.replace(_snapshot(_signal("new-only")))
    assert [s.source_id for s in store.project({ROOM_A}, now=NOW).signals] == ["new-only"]


def test_snapshot_rejects_duplicate_ids_and_provider_mismatch_without_partial_change() -> None:
    store = WorldSignalStore()
    store.replace(_snapshot(_signal("kept")))

    with pytest.raises(ValidationError, match="duplicate"):
        store.replace(_snapshot(_signal("dup"), _signal("dup")))

    other = _signal("wrong-provider").model_dump()
    other["id"] = "world_signal:firms:wrong-provider"
    other["provider"] = "firms"
    other["provenance"] = {
        **other["provenance"], "provider": "firms", "acquisition": "adapter:firms",
    }
    with pytest.raises(ValidationError, match="snapshot provider"):
        store.replace(_snapshot(WorldSignal(**other)))

    assert [s.source_id for s in store.project({ROOM_A}, now=NOW).signals] == ["kept"]


def test_projection_fences_rooms_and_keeps_source_condition_freshness_coverage_separate() -> None:
    store = WorldSignalStore()
    store.replace(_snapshot(_signal("mine", room_id=ROOM_A), _signal("theirs", room_id=ROOM_B)))

    projection = store.project({ROOM_A}, now=NOW)
    assert [s.source_id for s in projection.signals] == ["mine"]
    assert projection.signal_sources.status == "configured"
    assert len(projection.signal_sources.sources) == 1
    source = projection.signal_sources.sources[0]
    assert source.source_state == "partial"
    assert source.freshness == "current"
    assert source.coverage == "Strait of Hormuz receiver footprint"
    assert source.signal_count == 1


def test_no_configured_snapshot_is_explicit_and_not_inferred_from_an_empty_list() -> None:
    projection = WorldSignalStore().project({ROOM_A}, now=NOW)
    assert projection.signals == []
    assert projection.signal_sources.status == "not_configured"
    assert projection.signal_sources.sources == []

    configured_empty = WorldSignalStore()
    configured_empty.replace(_snapshot())
    projection = configured_empty.project({ROOM_A}, now=NOW)
    assert projection.signals == []
    assert projection.signal_sources.status == "configured"
    assert projection.signal_sources.sources[0].signal_count == 0


def test_expired_signals_are_not_projected_and_source_expiry_is_reported_separately() -> None:
    store = WorldSignalStore()
    expired = _signal("expired", expires_at=NOW - timedelta(seconds=1))
    store.replace(WorldSignalSnapshot(
        **{
            **_snapshot(expired).model_dump(),
            "expires_at": NOW - timedelta(seconds=1),
        },
    ))

    projection = store.project({ROOM_A}, now=NOW)
    assert projection.signals == []
    assert projection.signal_sources.sources[0].source_state == "partial"
    assert projection.signal_sources.sources[0].freshness == "expired"


def test_resolve_distinguishes_malformed_missing_cross_room_and_expired() -> None:
    store = WorldSignalStore()
    store.replace(_snapshot(
        _signal("live", room_id=ROOM_A),
        _signal("other-room", room_id=ROOM_B),
        _signal("expired", expires_at=NOW - timedelta(seconds=1)),
    ))

    assert store.resolve(ROOM_A, "world_signal:ais:live", now=NOW).source_id == "live"
    with pytest.raises(WorldSignalMalformedId):
        store.resolve(ROOM_A, "not-a-signal", now=NOW)
    with pytest.raises(WorldSignalNotFound):
        store.resolve(ROOM_A, "world_signal:ais:missing", now=NOW)
    with pytest.raises(WorldSignalWrongRoom):
        store.resolve(ROOM_A, "world_signal:ais:other-room", now=NOW)
    with pytest.raises(WorldSignalExpired):
        store.resolve(ROOM_A, "world_signal:ais:expired", now=NOW)
