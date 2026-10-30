"""One room-bound ride projection shared by HTTP and Scout; observation by ride identity."""
import os
from datetime import date, datetime, time, timedelta, timezone

from . import observe, fixes
from .register import get_register


def leg_for(register, ride):
    if not ride.get("leg") or not ride.get("leg_ready"):
        return None
    try:
        return register.leg(ride["leg"])
    except (KeyError, ValueError):
        return None


async def bound_trip(db, room_id, register=None):
    slug = await db.fetchval("SELECT linked_journey FROM rooms WHERE id=$1", room_id)
    if not slug:
        raise KeyError("No ride in this room")
    trip = (register or get_register()).ride(slug)
    if not trip["rides"]:
        raise KeyError("No ride in this room")
    return trip


def state_for(ride, saved, book, run, now):
    saved = saved or {}
    state = saved.get("state", "waiting")
    departed, arrived = saved.get("departed_at"), saved.get("arrived_at")
    if book:
        return "arrived", departed, arrived
    if ride["vehicle"].get("mmsi") and not ride["vehicle"].get("amtrak"):
        origin = date.fromisoformat(ride["date"])
        today = now.astimezone(observe.CHICAGO).date()
        if today >= origin:
            state = "riding"
            departed = datetime.combine(origin, time(), observe.CHICAGO)
        if today > origin + timedelta(days=1):
            state = "arrived"
            arrived = datetime.combine(origin+timedelta(days=2), time(), observe.CHICAGO)
    elif run:
        stations = {s["code"]: s for s in run.get("stations", [])}
        board, alight = stations.get(ride["board"], {}), stations.get(ride["alight"], {})
        if board.get("status") == "Departed":
            if state == "waiting":
                state = "riding"
            departed = observe.timestamp(observe.actual(board, "dep", now)) or departed or now
        arrival = observe.actual(alight, "arr", now)
        if arrival:
            state, arrived = "arrived", observe.timestamp(arrival)
    return state, departed, arrived


async def observation(ride, now):
    vehicle = ride["vehicle"]
    if vehicle.get("amtrak"):
        run = observe.run_for(await observe.trains(vehicle["amtrak"]), ride)
        return run, observe.train_fix(run, now)
    if vehicle.get("mmsi"):
        feed = await fixes.fetch_feed(os.environ.get("LONGWAY_FIXES_URL", fixes.SHIPS_URL))
        fix = (feed.get("fixes") or {}).get(str(vehicle["mmsi"])) or {}
        sog = fix.get("sog")
        return None, fixes.position(fix.get("lat"), fix.get("lon"), fix.get("fix"), now,
            speed_mph=sog * 1.150779 if isinstance(sog, (int, float)) else None,
            heading=str(fix["heading"]) if fix.get("heading") is not None else None, source="ais")
    return None, None


async def rows_for(db, slug):
    return {r["ride_id"]: dict(r) for r in await db.fetch("SELECT * FROM longway_rides WHERE trip_slug=$1", slug)}


def summaries(trip, saved, now):
    return [dict(id=r["id"], date=r["date"], state=state_for(r, saved.get(r["id"]), r.get("logbook"), None, now)[0])
            for r in trip["rides"]]


def pick(items, ride_id=None):
    if ride_id:
        found = next((r for r in items if r["id"] == ride_id), None)
        if found is None:
            raise KeyError(ride_id)
        return found
    riding = sorted((r for r in items if r["state"] == "riding"), key=lambda r: r["date"])
    waiting = sorted((r for r in items if r["state"] == "waiting"), key=lambda r: r["date"])
    arrived = sorted((r for r in items if r["state"] == "arrived"), key=lambda r: r["date"], reverse=True)
    return (riding or waiting or arrived)[0]


async def payload(db, room_id, ride_id=None, *, now=None, with_history=True):
    now = now or datetime.now(timezone.utc)
    register = get_register()
    trip = await bound_trip(db, room_id, register)
    saved = await rows_for(db, trip["slug"])
    items = summaries(trip, saved, now)
    chosen = pick(items, ride_id)
    ride = next(r for r in trip["rides"] if r["id"] == chosen["id"])
    row = saved.get(ride["id"], {})
    leg, book = leg_for(register, ride), register.logbook(trip["slug"], ride["id"])
    run, fix = (None, None) if chosen["state"] == "arrived" else await observation(ride, now)
    state, _, _ = state_for(ride, row, book, run, now)
    chosen["state"] = state
    stations = run.get("stations", []) if run else row.get("stations", [])
    stored = await db.fetch("SELECT * FROM longway_ride_fixes WHERE trip_slug=$1 AND ride_id=$2 ORDER BY at", trip["slug"], ride["id"])
    # Retain the last broadcast during a feed outage; its age remains truthful.
    if not fix and stored and state != "arrived":
        last = stored[-1]
        fix = fixes.position(last["lat"], last["lon"], observe.iso(last["at"]), now,
                             speed_mph=last["speed_mph"], heading=last["heading"], source=last["source"])
    km = observe.project(fix["lat"], fix["lon"], leg) if fix else None
    if state == "arrived":
        fix, km = None, None
    recorded = book["stops"] if book else (observe.record_stops(ride, stations, leg, row.get("observed_at") or now) if state == "arrived" else None)
    stop_table = observe.stops(ride, recorded if recorded is not None else stations, leg, now, logbook=recorded is not None)
    track = book["track"] if book else [[observe.iso(f["at"]), f["lat"], f["lon"], f["km"]] for f in stored]
    history = await observe.history(ride["vehicle"]["amtrak"], now) if with_history and ride["vehicle"].get("amtrak") else None
    run_id = run.get("trainID") if run else row.get("run_id")
    if run_id is None and ride["vehicle"].get("amtrak"):
        run_id = f"{ride['vehicle']['amtrak']}-{date.fromisoformat(ride['date']).day}"
    return dict(trip={k: trip[k] for k in ("slug", "title")}, rides=items, ride=dict(ride, state=state),
                run=run_id, fix=fix, fix_unavailable_reason=None if fix else (
                    "ride arrived" if state == "arrived" else "run has no valid position and broadcast timestamp"),
                km=km, stops=stop_table, history=history, track=track, fetched_at=observe.iso(now))


async def riding(db, user_id):
    rooms = await db.fetch("""SELECT r.id,r.name FROM rooms r JOIN room_memberships m ON m.room_id=r.id
        WHERE m.user_id=$1 AND r.linked_journey IS NOT NULL ORDER BY r.created_at,r.id""", user_id)
    result = []
    now = datetime.now(timezone.utc)
    for room in rooms:
        try:
            trip = await bound_trip(db, room["id"])
        except (KeyError, ValueError):
            continue
        for item in summaries(trip, await rows_for(db, trip["slug"]), now):
            if item["state"] == "arrived":
                continue
            data = await payload(db, room["id"], item["id"], now=now, with_history=False)
            if data["ride"]["state"] == "arrived":
                continue
            stop = next((s for s in data["stops"] if s["status"] != "Departed"), None)
            result.append(dict(room_id=str(room["id"]), room_name=room["name"], trip=data["trip"],
                ride={"id": item["id"], "state": data["ride"]["state"], "vehicle": {"name": data["ride"]["vehicle"]["name"]}},
                fix=data["fix"], next_stop={"code": stop["code"], "name": stop["name"], "est": stop["arr"] or stop["dep"]} if stop else None,
                late_min=stop["late_min"] if stop else None))
    return {"rides": result}


def window(leg, km, side="both"):
    if side not in ("left", "right", "both"):
        raise ValueError("side must be left, right, or both")
    model, guide, found = leg["sights"], leg.get("guide") or {}, {}
    for row in model["km"]:
        if abs(row[0]-km) > 2:
            continue
        for name, c, text in (("left", row[1], row[5]), ("right", row[2], row[6])):
            if side not in (name, "both") or not text:
                continue
            # Compound row names retain the lake and peak's own guide entries.
            names = [key for key in guide if key.casefold() in text.casefold()] or [text]
            for title in names:
                entry = dict(name=title, side=name, km=row[0], distance_km=round(abs(row[0]-km), 3),
                             c=c, **{"class": model["classes"][c]["label"]},
                             guide={k: guide.get(title, {}).get(k) for k in ("title", "what", "history", "links")})
                key = (name, title)
                if key not in found or entry["distance_km"] < found[key]["distance_km"]:
                    found[key] = entry
    return {"provenance": "model", "km": km, "side": side, "check": leg.get("check"),
            "sights": sorted(found.values(), key=lambda s: (-s["c"], s["distance_km"]))}
