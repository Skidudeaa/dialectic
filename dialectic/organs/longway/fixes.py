"""Cached observations, never inferred timetables or vessel availability."""
import asyncio
import copy
import math
import os
import time
from datetime import datetime, timezone

import httpx

SHIPS_URL = "https://js6zejddjuvin9wi.public.blob.vercel-storage.com/ships.json"
_cache = {}


def timestamp(value):
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return at if at.tzinfo else None
    except (TypeError, ValueError, AttributeError):
        return None


async def fetch_feed(url):
    cached = _cache.get(url)
    if cached and time.monotonic() - cached[0] < 60:
        return cached[1]
    try:
        async with httpx.AsyncClient(timeout=5, headers={"User-Agent": "Mozilla/5.0"}) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("feed must be an object")
    except (httpx.HTTPError, ValueError) as exc:
        data = {"error": f"feed unavailable: {type(exc).__name__}"}
    _cache[url] = (time.monotonic(), data)
    return data


def position(lat, lon, at, now, **fields):
    if not all(isinstance(n, (int, float)) and math.isfinite(n) for n in (lat, lon)):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    date = timestamp(at)
    if date is None:
        return None
    return dict(lat=lat, lon=lon, at=date.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                age_min=max(0, round((now-date).total_seconds()/60)), **fields)


async def overlay(chart, now=None):
    now = now or datetime.now(timezone.utc)
    result = copy.deepcopy(chart)
    from . import observe
    numbers = sorted({str(v["amtrak"]) for v in chart["vehicles"] if v.get("amtrak")})
    feeds = await asyncio.gather(fetch_feed(os.environ.get("LONGWAY_FIXES_URL", SHIPS_URL)),
                                 *(observe.trains(n) for n in numbers))
    ships, trains = feeds[0], dict(zip(numbers, feeds[1:]))
    written = timestamp(ships.get("written"))
    age = (now - written).total_seconds()/60 if written else None
    stale = age is None or age > 75
    why = ships.get("error") or ("listener has no written timestamp" if age is None else f"listener silent {round(age/60, 1)} h" if stale else None)
    result["fixes_state"] = dict(written=ships.get("written") if written else None, stale=stale, why=why)
    result["fetched_at"] = now.isoformat().replace("+00:00", "Z")
    for vehicle in result["vehicles"]:
        vehicle.update(fix=None, heard=False)
        fix = (ships.get("fixes") or {}).get(str(vehicle.get("mmsi")))
        if isinstance(fix, dict):
            vehicle["heard"] = True
            vehicle["fix"] = position(fix.get("lat"), fix.get("lon"), fix.get("fix"), now,
                                      sog=fix.get("sog"), status=fix.get("status"), place=None, source="ais")
        if vehicle.get("amtrak"):
            run = observe.latest(trains.get(str(vehicle["amtrak"]), []))
            if run:
                vehicle["heard"] = True
                fix = observe.train_fix(run, now)
                if fix:
                    vehicle["fix"] = dict(lat=fix["lat"], lon=fix["lon"], at=fix["at"],
                                          age_min=fix["age_min"], sog=fix["speed_mph"] / 1.150779 if fix["speed_mph"] is not None else None,
                                          status=None, place=None, source="amtrak")
        if vehicle["heard"] and vehicle["fix"] is None:
            vehicle["fix_unavailable_reason"] = "feed lacks a valid position or broadcast timestamp"
    return result
