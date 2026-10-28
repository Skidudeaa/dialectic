"""Cached observations, never inferred timetables or vessel availability."""
import asyncio
import copy
import math
import os
import time
from datetime import datetime, timezone

import httpx

SHIPS_URL = "https://js6zejddjuvin9wi.public.blob.vercel-storage.com/ships.json"
TRAINS_URL = "https://amtrak-live.vercel.app/api/trains?format=geojson"
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
        async with httpx.AsyncClient(timeout=5) as client:
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
    return dict(lat=lat, lon=lon, at=at,
                age_min=max(0, round((now-date).total_seconds()/60)), **fields)


async def overlay(chart, now=None):
    now = now or datetime.now(timezone.utc)
    result = copy.deepcopy(chart)
    ships, trains = await asyncio.gather(
        fetch_feed(os.environ.get("LONGWAY_FIXES_URL", SHIPS_URL)),
        fetch_feed(os.environ.get("LONGWAY_TRAINS_URL", TRAINS_URL)) if any(v.get("amtrak") for v in chart["vehicles"]) else asyncio.sleep(0, result={}),
    )
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
            feature = next((f for f in trains.get("features", []) if str(f.get("properties", {}).get("num")) == str(vehicle["amtrak"])), None)
            if feature:
                vehicle["heard"] = True
                props = feature.get("properties", {})
                coords = feature.get("geometry", {}).get("coordinates", [])
                if len(coords) >= 2:
                    # This feed currently omits GPS time. A heard vehicle can
                    # have no drawable Fix until upstream exposes lastValTS;
                    # fetch time must not impersonate the broadcast timestamp.
                    vehicle["fix"] = position(coords[1], coords[0], props.get("at"), now,
                                              sog=None, status=None, place=None, source="amtrak")
        if vehicle["heard"] and vehicle["fix"] is None:
            vehicle["fix_unavailable_reason"] = "feed lacks a valid position or broadcast timestamp"
    return result
