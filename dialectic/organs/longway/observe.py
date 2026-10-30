"""Broadcast observations and actual-only history; never substitute fetch time."""
import asyncio
import math
import re
from datetime import datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo

import httpx

from .fixes import fetch_feed, position, timestamp

AMTRAK = "https://api-v3.amtraker.com/v3/trains"
HISTORY = "https://asm-backend.transitdocs.com/train"
USER_AGENT = "Mozilla/5.0"
CHICAGO = ZoneInfo("America/Chicago")
_history_cache = {}
_history_tasks = {}


def iso(value):
    at = value if isinstance(value, datetime) else timestamp(value)
    return at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if at else None


def number(value):
    value = str(value)
    if not re.fullmatch(r"\d{1,4}", value):
        raise ValueError("Invalid Amtrak number")
    return value


async def trains(num):
    num = number(num)
    data = await fetch_feed(f"{AMTRAK}/{num}")
    return [r for r in data.get(num, []) if isinstance(r, dict)]


def latest(runs):
    return max(runs, key=lambda r: timestamp(r.get("lastValTS")) or datetime.min.replace(tzinfo=timezone.utc), default=None)


def run_for(runs, ride):
    day = datetime.fromisoformat(ride["date"]).date()
    run_id = f"{ride['vehicle']['amtrak']}-{day.day}"
    for run in runs:
        if run.get("trainID") != run_id:
            continue
        # The id repeats monthly. The origin's local scheduled date disambiguates it.
        origin = next((timestamp(s.get("schDep")) for s in run.get("stations", []) if timestamp(s.get("schDep"))), None)
        if origin and origin.date() != day:
            continue
        return run
    return None


def train_fix(run, now):
    if not run:
        return None
    speed = run.get("velocity")
    speed = speed if isinstance(speed, (int, float)) and math.isfinite(speed) and speed >= 0 else None
    return position(run.get("lat"), run.get("lon"), run.get("lastValTS"), now,
                    speed_mph=speed, heading=str(run["heading"]) if run.get("heading") is not None else None, source="amtrak")


def actual(station, field, now):
    status = station.get("status")
    at = timestamp(station.get(field))
    permitted = status == "Departed" or (field == "arr" and status == "Station")
    return iso(at) if permitted and at and at <= now else None


def late(actual_at, scheduled):
    a, s = timestamp(actual_at), timestamp(scheduled)
    return math.floor((a - s).total_seconds() / 60 + .5) if a and s else None


def stations_for(ride, stations):
    codes = [s.get("code") for s in stations]
    if ride["board"] not in codes or ride["alight"] not in codes:
        return []
    return stations[codes.index(ride["board"]):codes.index(ride["alight"]) + 1]


def stops(ride, stations, leg, now, *, logbook=False):
    model = {s["code"]: s for s in (leg or {}).get("sights", {}).get("stations", [])}
    result = []
    for s in stations_for(ride, stations):
        m = model.get(s["code"], {})
        if logbook:
            arr, dep = iso(s.get("arr")), iso(s.get("dep"))
            sa, sd = iso(s.get("sched_arr")), iso(s.get("sched_dep"))
            lateness = s.get("late_dep") if s.get("late_dep") is not None else s.get("late_arr")
            estimated, status = False, None
        else:
            arr, dep = iso(s.get("arr")), iso(s.get("dep"))
            sa, sd = iso(s.get("schArr")), iso(s.get("schDep"))
            lateness = late(dep, sd) if dep and sd else late(arr, sa)
            estimated = bool((arr and not actual(s, "arr", now)) or (dep and not actual(s, "dep", now)))
            status = s.get("status")
        result.append(dict(code=s["code"], name=s.get("name") or m.get("name") or s["code"],
                           km=s.get("km", m.get("km")), sched_arr=sa, sched_dep=sd,
                           arr=arr, dep=dep, estimated=estimated, status=status, late_min=lateness))
    return result


def record_stops(ride, stations, leg, observed_at):
    """Logbook-shaped stops: estimates are excluded even after their clock time passes."""
    station_km = {s["code"]: s["km"] for s in (leg or {}).get("sights", {}).get("stations", [])}
    result = []
    for s in stations_for(ride, stations):
        arr, dep = actual(s, "arr", observed_at), actual(s, "dep", observed_at)
        result.append(dict(code=s["code"], km=station_km.get(s["code"]),
                           sched_arr=iso(s.get("schArr")), arr=arr, late_arr=late(arr, s.get("schArr")),
                           sched_dep=iso(s.get("schDep")), dep=dep, late_dep=late(dep, s.get("schDep"))))
    return result


def project(lat, lon, leg):
    """Nearest segment in a local equirectangular plane, interpolated in model km."""
    rows = (leg or {}).get("sights", {}).get("km", [])
    best = None
    scale = math.cos(math.radians(lat))
    for a, b in zip(rows, rows[1:]):
        ax, ay = (a[4]-lon)*scale, a[3]-lat
        bx, by = (b[4]-lon)*scale, b[3]-lat
        dx, dy = bx-ax, by-ay
        t = max(0, min(1, -(ax*dx+ay*dy)/(dx*dx+dy*dy))) if dx or dy else 0
        distance = (ax+t*dx)**2 + (ay+t*dy)**2
        if best is None or distance < best[0]:
            best = distance, a[0]+t*(b[0]-a[0])
    return round(best[1], 3) if best else (rows[0][0] if rows else None)


async def _history(num, day):
    values, observed, failures = {}, 0, 0
    async with httpx.AsyncClient(timeout=5, headers={"User-Agent": USER_AGENT}) as client:
        async def one(date):
            response = await client.get(f"{HISTORY}/{date:%Y/%m/%d}/A/{num}")
            if response.status_code == 404:
                return {}
            response.raise_for_status()
            return response.json()
        for offset in range(1, 46, 5):
            batch = await asyncio.gather(*(one(day-timedelta(days=i)) for i in range(offset, offset+5)), return_exceptions=True)
            for data in batch:
                if isinstance(data, Exception):
                    failures += 1
                    continue
                seen = False
                for stop in data.get("stops", []):
                    arrival = stop.get("arrive") or {}
                    variance = arrival.get("variance")
                    if arrival.get("type") == "ACTUAL" and isinstance(variance, (int, float)) and math.isfinite(variance):
                        values.setdefault(stop["code"], []).append(math.floor(-variance/60+.5))
                        seen = True
                observed += seen
    return None if not observed and failures else {"days": observed, "at": {
        code: {"median": math.floor(median(v)+.5), "worst": max(v), "n": len(v)} for code, v in values.items()}}


async def history(num, now):
    num = number(num)
    day = now.astimezone(CHICAGO).date()
    key = (num, day)
    if key not in _history_cache:
        if key not in _history_tasks:
            async def fill():
                try:
                    result = await _history(num, day)
                    # Bound cache growth to the latest Chicago day for each train.
                    for old in list(_history_cache):
                        if old[0] == num:
                            del _history_cache[old]
                    _history_cache[key] = result
                finally:
                    _history_tasks.pop(key, None)
            _history_tasks[key] = asyncio.create_task(fill())
        # Cold history must not delay a live position or Scout response by 45 requests.
        try:
            await asyncio.wait_for(asyncio.shield(_history_tasks[key]), timeout=1)
        except asyncio.TimeoutError:
            return None
    return _history_cache.get(key)
