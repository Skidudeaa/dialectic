# world_adapters.py — the live provider adapters the World Lens reserved.
#
# ARCHITECTURE: one scheduler job (`world_signals`) polls a fixed set of
# KEYLESS public feeds, converts each response into ONE complete, bounded
# `WorldSignalSnapshot`, and replaces exactly that provider in the
# process-local `world_signal_store`. Nothing here writes the database,
# nothing here creates geographic authority, and nothing here is reachable
# from an HTTP writer. A signal becomes durable only when a person places it
# through `api/geo.py` — the authority ladder is untouched.
#
# WHY the fence is the room's own confirmed geography: God's Eye View shows
# the whole planet because it has no rooms. Dialectic has rooms, and a room's
# accepted GeoScopes already say which patch of world it argues about. So a
# room's area of interest IS the bounding box of its live scopes, and a
# provider observation is offered to a room only when it falls inside that
# box. A room that has placed nothing gets no signals and no noise.
#
# WHY every adapter reports state instead of raising: absence is never
# silently converted into zero (fusion design §4.3). A timeout is
# `unavailable`, an HTTP 429 is `rate_limited`, a missing key is
# `not_configured`, an empty-but-successful poll is `ok` with zero signals,
# and each is a distinct row in the source list the UI renders.
#
# TRADEOFF: coordinates come from the provider verbatim; we never smooth,
# interpolate or reproject them server-side. The client may interpolate for
# motion, but the evidence value stays the reported fix.

import asyncio
import csv
import io
import logging
import math
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional
from uuid import UUID

import httpx

from geo_scopes import GeoProvenance, LIVE_PREDICATE
from scheduler import Job, SchedulerContext
from world_signals import (
    WorldSignal,
    WorldSignalSnapshot,
    world_signal_store,
)

logger = logging.getLogger(__name__)

# One poll per interval per provider; the job itself runs on the scheduler's
# 30s tick through the usual interval bucket.
WORLD_SIGNALS_INTERVAL_S = 300  # was 120; see ADSB_FENCE_PAUSE_S
HTTP_TIMEOUT_S = 20.0
# A room's area of interest is its live scopes' bbox, padded so a contact
# approaching the place is visible before it arrives.
ROOM_BBOX_PAD_DEG = 1.5
MAX_ROOMS = 24
MAX_SIGNALS_PER_PROVIDER = 400
# Aircraft move; a fix older than this is not evidence about "now".
AIRCRAFT_TTL_S = 180
QUAKE_TTL_S = 3600
SATELLITE_TTL_S = 120
LAUNCH_TTL_S = 3600
FIRE_TTL_S = 7200

_ROOM_SCOPES_SQL = f"""
SELECT g.room_id, g.geometry
FROM geo_scopes g
WHERE g.authority IN ('human_confirmed', 'source_reported')
  AND {LIVE_PREDICATE}
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _enabled(name: str) -> bool:
    return os.environ.get(name, "1").strip().lower() not in ("0", "false", "no", "off")


def _coords(geometry: Any) -> list[tuple[float, float]]:
    """Every [lon, lat] position in a GeoJSON geometry, at any nesting depth."""
    def walk(node: Any) -> Iterable[tuple[float, float]]:
        if (isinstance(node, (list, tuple)) and len(node) >= 2
                and all(isinstance(v, (int, float)) for v in node[:2])):
            yield float(node[0]), float(node[1])
            return
        if isinstance(node, (list, tuple)):
            for child in node:
                yield from walk(child)

    if not isinstance(geometry, dict):
        return []
    return list(walk(geometry.get("coordinates")))


class RoomFence:
    """One room's area of interest, derived from its accepted geography."""

    __slots__ = ("room_id", "west", "south", "east", "north")

    def __init__(self, room_id: UUID, west: float, south: float,
                 east: float, north: float) -> None:
        self.room_id = room_id
        self.west, self.south, self.east, self.north = west, south, east, north

    @property
    def centroid(self) -> tuple[float, float]:
        return ((self.west + self.east) / 2.0, (self.south + self.north) / 2.0)

    @property
    def radius_nm(self) -> float:
        """Great-circle-ish radius covering the box, in nautical miles."""
        lat_span_nm = (self.north - self.south) / 2.0 * 60.0
        mid_lat = math.radians((self.north + self.south) / 2.0)
        lon_span_nm = (self.east - self.west) / 2.0 * 60.0 * max(math.cos(mid_lat), 0.05)
        return math.hypot(lat_span_nm, lon_span_nm)

    def contains(self, lon: float, lat: float) -> bool:
        return self.west <= lon <= self.east and self.south <= lat <= self.north


def _merge_boxes(boxes: list[list[float]]) -> list[list[float]]:
    """Union boxes that touch; leave far-apart ones separate. Repeats until
    stable because a merge can bridge two boxes that were disjoint before."""
    merged = [list(b) for b in boxes]
    changed = True
    while changed:
        changed = False
        out: list[list[float]] = []
        for b in merged:
            for m in out:
                if not (b[2] < m[0] or b[0] > m[2] or b[3] < m[1] or b[1] > m[3]):
                    m[0], m[1] = min(m[0], b[0]), min(m[1], b[1])
                    m[2], m[3] = max(m[2], b[2]), max(m[3], b[3])
                    changed = True
                    break
            else:
                out.append(b)
        merged = out
    return merged


async def room_fences(conn) -> list[RoomFence]:
    """Fences for rooms that own confirmed geography: one padded box PER
    SCOPE, merged with its neighbours when they touch.

    WHY not one box per room (the 2026-08-26 shape): a room whose scopes are
    far apart -- AI Capex holds Northern Virginia AND Taiwan -- got a single
    box spanning half the globe whose centroid fell in Libya, so the 250 nm
    adsb poll covered nothing the room cared about. Per-scope boxes keep each
    poll on the geography that asked for it; a room may own several fences.
    """
    rows = await conn.fetch(_ROOM_SCOPES_SQL)
    per_room: dict[UUID, list[list[float]]] = {}
    for row in rows:
        geometry = row["geometry"]
        if isinstance(geometry, str):
            import json
            try:
                geometry = json.loads(geometry)
            except ValueError:
                continue
        positions = _coords(geometry)
        if not positions:
            continue
        lons = [p[0] for p in positions]
        lats = [p[1] for p in positions]
        per_room.setdefault(row["room_id"], []).append([
            max(-180.0, min(lons) - ROOM_BBOX_PAD_DEG),
            max(-90.0, min(lats) - ROOM_BBOX_PAD_DEG),
            min(180.0, max(lons) + ROOM_BBOX_PAD_DEG),
            min(90.0, max(lats) + ROOM_BBOX_PAD_DEG),
        ])

    fences: list[RoomFence] = []
    for room_id, boxes in per_room.items():
        for w, s, e, n in _merge_boxes(boxes):
            fences.append(RoomFence(room_id, w, s, e, n))
    # ponytail: MAX_ROOMS now caps FENCES (a room may own several); raise it or
    # rank by room activity if the house ever places more geography than this.
    return fences[:MAX_ROOMS]


class AdapterResult:
    """What one provider poll produced, including how it failed."""

    __slots__ = ("source_state", "freshness", "coverage", "observations", "observed_at")

    def __init__(self, source_state: str, freshness: str, coverage: str,
                 observations: Optional[list[dict]] = None,
                 observed_at: Optional[datetime] = None) -> None:
        self.source_state = source_state
        self.freshness = freshness
        self.coverage = coverage
        self.observations = observations or []
        self.observed_at = observed_at


def _unavailable(reason: str) -> AdapterResult:
    return AdapterResult("unavailable", "unknown", reason[:500])


async def _get(client: httpx.AsyncClient, url: str, **kwargs) -> httpx.Response:
    response = await client.get(url, **kwargs)
    response.raise_for_status()
    return response


def _newer(candidate: dict, incumbent: dict) -> bool:
    """Is `candidate` a fresher report of the same object than `incumbent`?

    Provider clocks first: an explicit ``observed_at`` on both sides settles it.
    Failing that, ``age_s`` is the provider's own "seconds since this fix"
    (adsb.lol's ``seen``), where SMALLER is newer. With neither, the two
    payloads are the same fix seen through two room queries, and the first is
    kept so the choice stays deterministic rather than iteration-order luck.
    """
    mine, theirs = candidate.get("observed_at"), incumbent.get("observed_at")
    if mine is not None and theirs is not None:
        return mine > theirs
    if mine is not None or theirs is not None:
        return mine is not None
    mine_age, theirs_age = candidate.get("age_s"), incumbent.get("age_s")
    if isinstance(mine_age, (int, float)) and isinstance(theirs_age, (int, float)):
        return mine_age < theirs_age
    return False


def _dedupe_by_source(observations: list[dict]) -> list[dict]:
    """Collapse one object reported through more than one room query.

    WHY THIS EXISTS: the per-fence adapters ask each placed room's area
    separately, and those queries overlap — adsb.lol is asked for a CIRCLE
    around each room's centroid, so two rooms a few hundred nautical miles
    apart both hear the same aircraft even when their boxes do not intersect.
    A ``WorldSignal`` id is ``world_signal:<provider>:<source_id>`` and carries
    no room, deliberately: one real aircraft is one object, not one per room.
    Two copies of it therefore collide inside ``WorldSignalSnapshot``, which
    rejects duplicate ids by raising — and that raise escapes the job, so
    every adapter after this one is skipped. Collapsing here keeps the
    identity global and leaves room containment to ``build_snapshot``.

    Insertion order is preserved so a snapshot is stable between runs.
    """
    best: dict[str, dict] = {}
    for observation in observations:
        source_id = observation["source_id"]
        incumbent = best.get(source_id)
        if incumbent is None or _newer(observation, incumbent):
            best[source_id] = observation
    return list(best.values())


def _guarded(coverage_when_down: str):
    """Turn transport failures into evidence states rather than exceptions."""
    def wrap(fn):
        async def run(client, fences):
            try:
                return await fn(client, fences)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in (429, 503):
                    return AdapterResult("rate_limited", "unknown", f"{coverage_when_down} — provider throttled")
                return _unavailable(f"{coverage_when_down} — HTTP {exc.response.status_code}")
            except (httpx.HTTPError, asyncio.TimeoutError) as exc:
                return _unavailable(f"{coverage_when_down} — {type(exc).__name__}")
            except (ValueError, KeyError, TypeError) as exc:
                return _unavailable(f"{coverage_when_down} — malformed response ({type(exc).__name__})")
        return run
    return wrap


# ── USGS earthquakes ─────────────────────────────────────────────────────
USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"


@_guarded("USGS M1.0+ worldwide, last 24 hours")
async def poll_earthquakes(client: httpx.AsyncClient, fences: list[RoomFence]) -> AdapterResult:
    payload = (await _get(client, USGS_URL)).json()
    observations: list[dict] = []
    for feature in payload.get("features", []):
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        if len(coordinates) < 2:
            continue
        lon, lat = float(coordinates[0]), float(coordinates[1])
        depth_km = float(coordinates[2]) if len(coordinates) > 2 else None
        source_id = str(feature.get("id") or "").strip()
        if not source_id:
            continue
        magnitude = props.get("mag")
        observed_ms = props.get("time")
        observations.append({
            "source_id": source_id,
            "lon": lon,
            "lat": lat,
            "layer": "earthquakes",
            "label": props.get("title") or f"M{magnitude} earthquake",
            "url": props.get("url"),
            "observed_at": (
                datetime.fromtimestamp(observed_ms / 1000.0, tz=timezone.utc)
                if isinstance(observed_ms, (int, float)) else None
            ),
            "ttl_s": QUAKE_TTL_S,
            "details": {
                "magnitude": magnitude,
                "depth_km": depth_km,
                "place": props.get("place"),
                "felt_reports": props.get("felt"),
                "tsunami": bool(props.get("tsunami")),
            },
        })
    return AdapterResult(
        "ok", "current",
        f"USGS M1.0+ worldwide, last 24 hours ({len(observations)} events)",
        observations,
    )


# ── adsb.lol live aircraft ───────────────────────────────────────────────
ADSB_URL = "https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{dist}"
ADSB_MAX_NM = 250
# WHY: adsb.lol answers roughly one request per five seconds from one IP
# (measured 2026-08-30: at 2s spacing, three fences passed and the next
# three got 429 -- the Pearl River, Yangtze and Bo Hai fences were starved on
# every tick). Ten fences at 5s is ~50s per poll, which is why the job runs
# every 300s rather than 120s: the scheduler tick is serial.
ADSB_FENCE_PAUSE_S = 5.0


@_guarded("adsb.lol ADS-B receivers within 250 NM of each placed room")
async def poll_aircraft(client: httpx.AsyncClient, fences: list[RoomFence]) -> AdapterResult:
    observations: list[dict] = []
    # One aircraft can sit inside two fences (a room's neighbouring scopes, or
    # two rooms sharing the Strait). Keep the first report per hex; the fence
    # fan-out in build_snapshot assigns it to every room that contains it.
    seen_hex: set[str] = set()
    partial = False
    for index, fence in enumerate(fences):
        if index and ADSB_FENCE_PAUSE_S:
            await asyncio.sleep(ADSB_FENCE_PAUSE_S)
        lon, lat = fence.centroid
        dist = int(max(25.0, min(ADSB_MAX_NM, fence.radius_nm + 50.0)))
        try:
            payload = (await _get(client, ADSB_URL.format(
                lat=round(lat, 4), lon=round(lon, 4), dist=dist,
            ))).json()
        except (httpx.HTTPError, ValueError):
            partial = True
            continue
        for contact in payload.get("ac", []) or []:
            hexid = str(contact.get("hex") or "").strip()
            c_lat, c_lon = contact.get("lat"), contact.get("lon")
            if not hexid or c_lat is None or c_lon is None or hexid in seen_hex:
                continue
            seen_hex.add(hexid)
            callsign = str(contact.get("flight") or "").strip()
            observations.append({
                "source_id": hexid,
                "lon": float(c_lon),
                "lat": float(c_lat),
                "layer": "aircraft",
                "label": callsign or hexid.upper(),
                "url": f"https://globe.adsb.lol/?icao={hexid}",
                "observed_at": None,
                # The provider's own recency, used only to pick between two
                # reports of the SAME aircraft; never rendered as a time.
                "age_s": contact.get("seen"),
                "ttl_s": AIRCRAFT_TTL_S,
                "details": {
                    "callsign": callsign or None,
                    "registration": contact.get("r"),
                    "type": contact.get("t"),
                    "altitude_ft": contact.get("alt_baro"),
                    "ground_speed_kt": contact.get("gs"),
                    "track_deg": contact.get("track"),
                    "vertical_rate_fpm": contact.get("baro_rate"),
                    "squawk": contact.get("squawk"),
                    "emergency": contact.get("emergency"),
                    "seen_s": contact.get("seen"),
                },
            })
    contacts = _dedupe_by_source(observations)
    return AdapterResult(
        "partial" if partial else "ok",
        "current",
        f"adsb.lol ADS-B within {ADSB_MAX_NM} NM of each placed room "
        f"({len(contacts)} contacts)",
        contacts,
    )


# ── ISS ──────────────────────────────────────────────────────────────────
ISS_URL = "https://api.wheretheiss.at/v1/satellites/25544"


@_guarded("wheretheiss.at — ISS (NORAD 25544) sub-satellite point")
async def poll_satellites(client: httpx.AsyncClient, fences: list[RoomFence]) -> AdapterResult:
    payload = (await _get(client, ISS_URL)).json()
    lat, lon = payload.get("latitude"), payload.get("longitude")
    if lat is None or lon is None:
        return _unavailable("wheretheiss.at — no position in response")
    timestamp = payload.get("timestamp")
    return AdapterResult(
        "ok", "current",
        "wheretheiss.at — ISS (NORAD 25544) sub-satellite point, global",
        [{
            "source_id": "25544",
            "lon": float(lon),
            "lat": float(lat),
            "layer": "satellites",
            "label": "ISS (ZARYA)",
            "url": "https://wheretheiss.at/w/satellite/25544",
            "observed_at": (
                datetime.fromtimestamp(timestamp, tz=timezone.utc)
                if isinstance(timestamp, (int, float)) else None
            ),
            "ttl_s": SATELLITE_TTL_S,
            "global": True,
            "details": {
                "norad_id": 25544,
                "altitude_km": payload.get("altitude"),
                "velocity_kmh": payload.get("velocity"),
                "visibility": payload.get("visibility"),
                "footprint_km": payload.get("footprint"),
            },
        }],
    )


# ── Launch Library 2 — upcoming launches ─────────────────────────────────
# `mode=list` omits the pad entirely -- and a launch with no pad has no
# geography, so the list mode silently produced zero signals. Normal mode is
# the one that carries pad.latitude/longitude.
LAUNCH_URL = "https://ll.thespacedevs.com/2.3.0/launches/upcoming/?limit=20"


@_guarded("Launch Library 2 — next 30 scheduled orbital launches")
async def poll_launches(client: httpx.AsyncClient, fences: list[RoomFence]) -> AdapterResult:
    payload = (await _get(client, LAUNCH_URL)).json()
    observations: list[dict] = []
    for launch in payload.get("results", []) or []:
        pad = launch.get("pad") or {}
        lat, lon = pad.get("latitude"), pad.get("longitude")
        source_id = str(launch.get("id") or "").strip()
        if lat is None or lon is None or not source_id:
            continue
        status = (launch.get("status") or {}).get("abbrev")
        observations.append({
            # Launch Library ids are UUIDs; the signal grammar allows them.
            "source_id": source_id,
            "lon": float(lon),
            "lat": float(lat),
            "layer": "launches",
            "label": str(launch.get("name") or "Scheduled launch")[:240],
            "url": launch.get("url"),
            "observed_at": None,
            "ttl_s": LAUNCH_TTL_S,
            "details": {
                "window_start": launch.get("net"),
                "status": status,
                "pad": pad.get("name"),
                "provider": (launch.get("launch_service_provider") or {}).get("name"),
            },
        })
    return AdapterResult(
        "ok", "current",
        f"Launch Library 2 — next scheduled orbital launches ({len(observations)} pads)",
        observations,
    )


# ── NASA FIRMS active fires (free key) ───────────────────────────────────
FIRMS_URL = (
    "https://firms.modaps.eosdis.nasa.gov/api/area/csv/"
    "{key}/VIIRS_NOAA20_NRT/{west},{south},{east},{north}/1"
)


@_guarded("NASA FIRMS VIIRS active fire detections, last 24 hours")
async def poll_fires(client: httpx.AsyncClient, fences: list[RoomFence]) -> AdapterResult:
    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if not key:
        return AdapterResult(
            "not_configured", "not_applicable",
            "NASA FIRMS active fires — set FIRMS_MAP_KEY to enable",
        )
    observations: list[dict] = []
    partial = False
    for fence in fences:
        try:
            body = (await _get(client, FIRMS_URL.format(
                key=key,
                west=round(fence.west, 3), south=round(fence.south, 3),
                east=round(fence.east, 3), north=round(fence.north, 3),
            ))).text
        except (httpx.HTTPError, ValueError):
            partial = True
            continue
        for row in csv.DictReader(io.StringIO(body)):
            try:
                lat, lon = float(row["latitude"]), float(row["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            acq_date, acq_time = row.get("acq_date", ""), str(row.get("acq_time", "")).zfill(4)
            observations.append({
                "source_id": f"{acq_date}.{acq_time}.{lat:.5f}.{lon:.5f}".replace("-", "~"),
                "lon": lon,
                "lat": lat,
                "layer": "fires",
                "label": f"Fire detection {row.get('confidence', '')}".strip(),
                "url": "https://firms.modaps.eosdis.nasa.gov/",
                "observed_at": None,
                "ttl_s": FIRE_TTL_S,
                "details": {
                    "brightness_k": row.get("bright_ti4"),
                    "frp_mw": row.get("frp"),
                    "confidence": row.get("confidence"),
                    "satellite": row.get("satellite"),
                    "acquired": f"{acq_date} {acq_time}Z",
                },
            })
    detections = _dedupe_by_source(observations)
    return AdapterResult(
        "partial" if partial else "ok",
        "current",
        f"NASA FIRMS VIIRS active fires over each placed room "
        f"({len(detections)} detections)",
        detections,
    )


class Adapter:
    """One provider, its attribution, its kill switch, and its own floor rate.

    WHY a per-adapter `min_interval_s` rather than one job interval: the job's
    120s cadence is right for aircraft, which move, and rude to Launch Library,
    whose anonymous tier documents roughly fifteen requests an hour. Polling a
    provider faster than its published allowance is how a free feed becomes a
    `rate_limited` row for everyone.
    """

    __slots__ = ("provider", "credit", "enabled_env", "poll", "min_interval_s")

    def __init__(self, provider: str, credit: str, enabled_env: str,
                 poll: Callable, min_interval_s: int = 0) -> None:
        self.provider = provider
        self.credit = credit
        self.enabled_env = enabled_env
        self.poll = poll
        self.min_interval_s = min_interval_s


ADAPTERS: tuple[Adapter, ...] = (
    Adapter("usgs", "USGS Earthquake Hazards Program (public domain)",
            "WORLD_SIGNALS_USGS_ENABLED", poll_earthquakes,
            # The feed itself is regenerated every minute; a quake stays news
            # for an hour, so five minutes is generous in both directions.
            min_interval_s=300),
    Adapter("adsb", "Data from adsb.lol (ODbL)",
            "WORLD_SIGNALS_ADSB_ENABLED", poll_aircraft),
    Adapter("iss", "Position from wheretheiss.at",
            "WORLD_SIGNALS_ISS_ENABLED", poll_satellites),
    Adapter("launch", "Launch Library 2 by The Space Devs (CC BY 4.0)",
            "WORLD_SIGNALS_LAUNCH_ENABLED", poll_launches,
            # The anonymous tier is documented at ~15 requests/hour. A launch
            # manifest does not change on a two-minute timescale anyway.
            min_interval_s=1800),
    Adapter("firms", "NASA FIRMS — we acknowledge the use of data from NASA FIRMS",
            "WORLD_SIGNALS_FIRMS_ENABLED", poll_fires,
            # 5,000 transactions / 10 minutes is the documented ceiling, but a
            # fire detection is a 24-hour product: ten minutes is plenty.
            min_interval_s=600),
)


# When each provider was last polled, so a slow feed is not asked again on the
# next tick. Process-local, exactly like the snapshots it guards.
_last_polled: dict[str, float] = {}


def due(adapter: Adapter, *, now: Optional[float] = None) -> bool:
    """Has this adapter's own floor elapsed? A provider never polled is due."""
    current = time.monotonic() if now is None else now
    last = _last_polled.get(adapter.provider)
    return last is None or (current - last) >= adapter.min_interval_s


def build_snapshot(adapter: Adapter, result: AdapterResult,
                   fences: list[RoomFence], *,
                   retrieved_at: Optional[datetime] = None) -> Optional[WorldSignalSnapshot]:
    """Fan one provider's observations across every room that contains them.

    Returns None when no room is configured — the store holds no source rather
    than an empty one, so the UI can say "not configured" truthfully.
    """
    if not fences:
        return None
    retrieved = retrieved_at or _now()
    signals: list[WorldSignal] = []
    for observation in result.observations:
        if len(signals) >= MAX_SIGNALS_PER_PROVIDER:
            break
        lon, lat = observation["lon"], observation["lat"]
        is_global = bool(observation.get("global"))
        for fence in fences:
            if not is_global and not fence.contains(lon, lat):
                continue
            source_id = observation["source_id"]
            signal_id = f"world_signal:{adapter.provider}:{source_id}"
            observed_at = observation.get("observed_at")
            if observed_at is not None and observed_at > retrieved:
                observed_at = retrieved
            try:
                signals.append(WorldSignal(
                    id=signal_id,
                    provider=adapter.provider,
                    source_id=source_id,
                    room_id=fence.room_id,
                    layer=observation["layer"],
                    kind="point",
                    geometry={"type": "Point", "coordinates": [lon, lat]},
                    provenance=GeoProvenance(
                        provider=adapter.provider,
                        acquisition=f"adapter:{adapter.provider}",
                        source_id=source_id,
                        url=observation.get("url"),
                        credit=adapter.credit,
                    ),
                    source_state=result.source_state,
                    freshness=result.freshness,
                    coverage=result.coverage,
                    observed_at=observed_at,
                    retrieved_at=retrieved,
                    expires_at=retrieved + timedelta(seconds=observation["ttl_s"]),
                    label=str(observation.get("label") or "")[:240],
                    details={k: v for k, v in (observation.get("details") or {}).items()
                             if v is not None},
                ))
            except ValueError as exc:
                logger.debug("world_signals: dropped %s (%s)", signal_id, exc)
            # One observation belongs to at most one room's signal id: the id
            # grammar is provider+source, and the snapshot forbids duplicates.
            break
    return WorldSignalSnapshot(
        provider=adapter.provider,
        configured_room_ids=frozenset(fence.room_id for fence in fences),
        source_state=result.source_state,
        freshness=result.freshness,
        coverage=result.coverage,
        observed_at=result.observed_at,
        retrieved_at=retrieved,
        signals=tuple(signals),
    )


async def refresh_world_signals(ctx: SchedulerContext) -> dict:
    """Poll every enabled adapter and replace its snapshot in the store."""
    if not _enabled("WORLD_SIGNALS_ENABLED"):
        return {"skipped": "disabled"}
    async with ctx.pool.acquire() as conn:
        fences = await room_fences(conn)
    if not fences:
        return {"rooms": 0, "note": "no room owns confirmed geography"}

    detail: dict[str, Any] = {"rooms": len(fences)}
    async with httpx.AsyncClient(
        timeout=HTTP_TIMEOUT_S,
        headers={"User-Agent": "Dialectic World Lens (+https://github.com/)"},
        follow_redirects=True,
    ) as client:
        for adapter in ADAPTERS:
            if not _enabled(adapter.enabled_env):
                continue
            if not due(adapter):
                continue
            _last_polled[adapter.provider] = time.monotonic()
            result = await adapter.poll(client, fences)
            snapshot = build_snapshot(adapter, result, fences)
            if snapshot is None:
                continue
            try:
                world_signal_store.replace(snapshot)
            except ValueError as exc:
                logger.warning("world_signals: %s snapshot rejected (%s)", adapter.provider, exc)
                detail[adapter.provider] = f"rejected: {exc}"
                continue
            detail[adapter.provider] = {
                "state": result.source_state,
                "signals": len(snapshot.signals),
            }
    return detail


def register_world_signal_jobs(scheduler) -> None:
    scheduler.register(Job(
        "world_signals", WORLD_SIGNALS_INTERVAL_S, refresh_world_signals,
        enabled_env="WORLD_SIGNALS_ENABLED",
        # On by default again (World Lens plan, 2026-08-30): the audit's
        # "2,000 polls a week discarded unseen" is no longer true — it has a
        # reader now. `llm/world_watch.py`'s `world_watch` job (registered
        # right after this one) polls this same store every 300s, persists
        # terms-cleared contacts into `world_observations`, and can interject
        # on a bound scope. The Atlas `?signals=true` flag remains a second,
        # optional reader.
        enabled_default=True,
    ))
