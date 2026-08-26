"""The live World Lens adapters: fencing, evidence states, and bounds.

Every test drives the REAL adapter function with a stubbed transport, so a
change to the parsing, the fence, or the failure vocabulary fails here.
"""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest

import world_adapters as wa
from world_signals import WorldSignalStore


ROOM_A = uuid4()
ROOM_B = uuid4()


def fence(room_id=ROOM_A, w=55.0, s=25.0, e=57.0, n=27.0):
    return wa.RoomFence(room_id, w, s, e, n)


def client_returning(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ── the fence ────────────────────────────────────────────────────────────

def test_fence_contains_and_geometry_bbox():
    positions = wa._coords({
        "type": "Polygon",
        "coordinates": [[[55.0, 25.0], [57.0, 25.0], [57.0, 27.0], [55.0, 25.0]]],
    })
    assert (57.0, 27.0) in positions
    f = fence()
    assert f.contains(56.0, 26.0)
    assert not f.contains(0.0, 0.0)
    assert f.radius_nm > 0


def test_centroid_is_the_box_centre():
    assert fence().centroid == (56.0, 26.0)


# ── USGS ─────────────────────────────────────────────────────────────────

USGS_BODY = {
    "features": [
        {
            "id": "us7000abcd",
            "geometry": {"type": "Point", "coordinates": [56.0, 26.0, 10.0]},
            "properties": {
                "mag": 5.4, "title": "M 5.4 - near the Strait",
                "time": 1_700_000_000_000, "url": "https://example.test/quake",
                "place": "Strait", "tsunami": 0,
            },
        },
        {
            "id": "us7000zzzz",
            "geometry": {"type": "Point", "coordinates": [-120.0, 38.0, 3.0]},
            "properties": {"mag": 2.1, "title": "M 2.1 - California", "time": 1_700_000_000_000},
        },
    ],
}


@pytest.mark.asyncio
async def test_earthquakes_parse_and_fence_to_the_room():
    async with client_returning(lambda r: httpx.Response(200, json=USGS_BODY)) as client:
        result = await wa.poll_earthquakes(client, [fence()])
    assert result.source_state == "ok"
    assert len(result.observations) == 2  # the adapter reports the world...

    snapshot = wa.build_snapshot(wa.ADAPTERS[0], result, [fence()])
    # ...and the FENCE is what drops the Californian quake.
    assert [s.source_id for s in snapshot.signals] == ["us7000abcd"]
    signal = snapshot.signals[0]
    assert signal.room_id == ROOM_A
    assert signal.layer == "earthquakes"
    assert signal.details["magnitude"] == 5.4
    assert signal.provenance.acquisition == "adapter:usgs"
    assert signal.expires_at > signal.retrieved_at


@pytest.mark.asyncio
async def test_a_timeout_is_unavailable_not_an_exception():
    def boom(request):
        raise httpx.ConnectTimeout("timed out", request=request)

    async with client_returning(boom) as client:
        result = await wa.poll_earthquakes(client, [fence()])
    assert result.source_state == "unavailable"
    assert result.observations == []
    assert "ConnectTimeout" in result.coverage


@pytest.mark.asyncio
async def test_throttling_is_rate_limited():
    async with client_returning(lambda r: httpx.Response(429)) as client:
        result = await wa.poll_earthquakes(client, [fence()])
    assert result.source_state == "rate_limited"


@pytest.mark.asyncio
async def test_a_successful_empty_poll_is_ok_with_zero_signals():
    async with client_returning(lambda r: httpx.Response(200, json={"features": []})) as client:
        result = await wa.poll_earthquakes(client, [fence()])
    assert result.source_state == "ok"
    snapshot = wa.build_snapshot(wa.ADAPTERS[0], result, [fence()])
    assert snapshot.signals == ()
    assert snapshot.source_state == "ok"  # absence is not unavailable


# ── aircraft ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_aircraft_carry_their_telemetry():
    body = {"ac": [{
        "hex": "a1b2c3", "flight": "UAE201  ", "lat": 26.1, "lon": 56.2,
        "alt_baro": 37000, "gs": 470, "track": 118.4, "t": "B77W", "r": "A6-EGA",
    }]}
    async with client_returning(lambda r: httpx.Response(200, json=body)) as client:
        result = await wa.poll_aircraft(client, [fence()])
    assert result.source_state == "ok"
    snapshot = wa.build_snapshot(wa.ADAPTERS[1], result, [fence()])
    signal = snapshot.signals[0]
    assert signal.label == "UAE201"
    assert signal.details["track_deg"] == 118.4
    assert signal.details["altitude_ft"] == 37000
    # An aircraft fix expires fast — it is not evidence about "now" for long.
    assert signal.expires_at - signal.retrieved_at == timedelta(seconds=wa.AIRCRAFT_TTL_S)


@pytest.mark.asyncio
async def test_one_dead_room_makes_the_source_partial_not_dead():
    seen = {"n": 0}

    def handler(request):
        seen["n"] += 1
        if seen["n"] == 1:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"ac": []})

    async with client_returning(handler) as client:
        result = await wa.poll_aircraft(client, [fence(ROOM_A), fence(ROOM_B, 0, 0, 1, 1)])
    assert result.source_state == "partial"


# ── the ISS is global, not fenced ────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_iss_reaches_every_configured_room_wherever_it_is():
    body = {"latitude": -33.9, "longitude": 151.2, "timestamp": 1_700_000_000,
            "altitude": 420.5, "velocity": 27600.0}
    async with client_returning(lambda r: httpx.Response(200, json=body)) as client:
        result = await wa.poll_satellites(client, [fence()])
    snapshot = wa.build_snapshot(wa.ADAPTERS[2], result, [fence()])
    # Sydney is nowhere near the Strait box, and the signal still lands.
    assert len(snapshot.signals) == 1
    assert snapshot.signals[0].details["norad_id"] == 25544


# ── FIRMS: a missing key is not_configured, never a silent zero ──────────

@pytest.mark.asyncio
async def test_a_missing_firms_key_is_not_configured(monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)

    def never(request):  # the adapter must not reach the network at all
        raise AssertionError("FIRMS was polled without a key")

    async with client_returning(never) as client:
        result = await wa.poll_fires(client, [fence()])
    assert result.source_state == "not_configured"
    assert result.freshness == "not_applicable"


@pytest.mark.asyncio
async def test_firms_csv_rows_become_point_signals(monkeypatch):
    monkeypatch.setenv("FIRMS_MAP_KEY", "test-key")
    csv_body = (
        "latitude,longitude,bright_ti4,acq_date,acq_time,satellite,confidence,frp\n"
        "26.20,56.30,330.1,2026-08-26,0412,N20,n,12.4\n"
    )
    async with client_returning(lambda r: httpx.Response(200, text=csv_body)) as client:
        result = await wa.poll_fires(client, [fence()])
    assert result.source_state == "ok"
    snapshot = wa.build_snapshot(wa.ADAPTERS[4], result, [fence()])
    assert len(snapshot.signals) == 1
    assert snapshot.signals[0].details["frp_mw"] == "12.4"


# ── the store contract the projection depends on ─────────────────────────

def test_a_replaced_snapshot_projects_only_into_eligible_rooms():
    store = WorldSignalStore()
    result = wa.AdapterResult("ok", "current", "test coverage", [{
        "source_id": "us1", "lon": 56.0, "lat": 26.0, "layer": "earthquakes",
        "label": "M5", "url": None, "observed_at": None, "ttl_s": 600,
        "details": {"magnitude": 5.0},
    }])
    snapshot = wa.build_snapshot(wa.ADAPTERS[0], result, [fence(ROOM_A)])
    store.replace(snapshot)

    mine = store.project([ROOM_A])
    assert mine.signal_sources.status == "configured"
    assert len(mine.signals) == 1

    theirs = store.project([ROOM_B])
    assert theirs.signal_sources.status == "not_configured"
    assert theirs.signals == []


def test_an_expired_signal_leaves_the_projection_but_the_source_remains():
    store = WorldSignalStore()
    result = wa.AdapterResult("ok", "current", "test coverage", [{
        "source_id": "us1", "lon": 56.0, "lat": 26.0, "layer": "earthquakes",
        "label": "M5", "url": None, "observed_at": None, "ttl_s": 60,
        "details": {},
    }])
    store.replace(wa.build_snapshot(wa.ADAPTERS[0], result, [fence(ROOM_A)]))
    later = datetime.now(timezone.utc) + timedelta(seconds=120)
    projection = store.project([ROOM_A], now=later)
    assert projection.signals == []
    assert projection.signal_sources.sources[0].signal_count == 0


def test_no_configured_room_means_no_snapshot_at_all():
    result = wa.AdapterResult("ok", "current", "test coverage", [])
    assert wa.build_snapshot(wa.ADAPTERS[0], result, []) is None


def test_the_provider_bound_holds():
    many = [{
        "source_id": f"us{i}", "lon": 56.0, "lat": 26.0, "layer": "earthquakes",
        "label": "M5", "url": None, "observed_at": None, "ttl_s": 600, "details": {},
    } for i in range(wa.MAX_SIGNALS_PER_PROVIDER + 50)]
    snapshot = wa.build_snapshot(
        wa.ADAPTERS[0], wa.AdapterResult("ok", "current", "c", many), [fence()],
    )
    assert len(snapshot.signals) == wa.MAX_SIGNALS_PER_PROVIDER


# ── launches: the pad IS the geography ───────────────────────────────────

@pytest.mark.asyncio
async def test_launches_read_the_pad_coordinates():
    """Regression: `mode=list` omits `pad` entirely, so every launch was
    silently dropped for having no geography and the layer looked merely
    empty. The URL must ask for the mode that carries the pad."""
    assert "mode=list" not in wa.LAUNCH_URL

    body = {"results": [{
        "id": "95653d52-bb77-4860-a815-dd7141778d17",
        "name": "Falcon 9 Block 5 | Starlink Group 15-22",
        "net": "2026-08-27T09:35:11Z",
        "status": {"abbrev": "Go"},
        "pad": {"name": "Space Launch Complex 4E", "latitude": 34.632, "longitude": -120.611},
        "launch_service_provider": {"name": "SpaceX"},
    }]}
    async with client_returning(lambda r: httpx.Response(200, json=body)) as client:
        result = await wa.poll_launches(client, [fence()])
    assert result.source_state == "ok"
    assert len(result.observations) == 1

    world = wa.RoomFence(ROOM_A, -180.0, -90.0, 180.0, 90.0)
    snapshot = wa.build_snapshot(wa.ADAPTERS[3], result, [world])
    signal = snapshot.signals[0]
    assert signal.geometry["coordinates"] == [-120.611, 34.632]
    assert signal.details["pad"] == "Space Launch Complex 4E"
    assert signal.details["status"] == "Go"


@pytest.mark.asyncio
async def test_a_launch_with_no_pad_is_dropped_not_placed_at_null_island():
    body = {"results": [
        {"id": "no-pad", "name": "Undisclosed", "pad": {}},
        {"id": "", "name": "Nameless", "pad": {"latitude": 1.0, "longitude": 1.0}},
    ]}
    async with client_returning(lambda r: httpx.Response(200, json=body)) as client:
        result = await wa.poll_launches(client, [fence()])
    assert result.observations == []


# ── each provider's own floor rate ───────────────────────────────────────

def test_a_slow_provider_is_not_polled_on_every_tick():
    launch = next(a for a in wa.ADAPTERS if a.provider == "launch")
    aircraft = next(a for a in wa.ADAPTERS if a.provider == "adsb")
    # Aircraft move; the manifest of next month's launches does not.
    assert launch.min_interval_s >= 1800
    assert aircraft.min_interval_s == 0

    wa._last_polled.pop("launch", None)
    assert wa.due(launch)                      # never polled -> due
    wa._last_polled["launch"] = 1_000.0
    assert not wa.due(launch, now=1_060.0)     # one minute later -> not yet
    assert wa.due(launch, now=1_000.0 + launch.min_interval_s)
    wa._last_polled.pop("launch", None)


def test_a_no_floor_provider_is_always_due():
    aircraft = next(a for a in wa.ADAPTERS if a.provider == "adsb")
    wa._last_polled["adsb"] = 1_000.0
    assert wa.due(aircraft, now=1_000.1)
    wa._last_polled.pop("adsb", None)
