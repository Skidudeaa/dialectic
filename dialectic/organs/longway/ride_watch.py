"""Durable ride observations, transition notifications, and delayed logbook writing."""
import asyncio
import logging
import math
import os
from datetime import date, datetime, timedelta, timezone

from . import observe, rides
from .register import get_register

logger = logging.getLogger(__name__)


def track_points(rows):
    """One actual broadcast per km bin; unknown km never becomes an invented path."""
    bins, points, distance, previous = set(), [], 0, None
    for row in rows:
        if previous is not None:
            lat1, lat2 = math.radians(previous["lat"]), math.radians(row["lat"])
            dlat, dlon = lat2-lat1, math.radians(row["lon"]-previous["lon"])
            chord = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
            distance += 6371 * 2 * math.asin(min(1, math.sqrt(chord)))
        previous = row
        # A ship without a leg still has a real geographic track. Thin by
        # distance travelled, leaving its model km null in the published book.
        key = ("model", math.floor(row["km"])) if row["km"] is not None else ("distance", math.floor(distance))
        if key not in bins:
            bins.add(key)
            points.append([observe.iso(row["at"]), row["lat"], row["lon"], row["km"]])
    return points


def interpolate(at, track):
    for a, b in zip(track, track[1:]):
        start, end = observe.timestamp(a[0]), observe.timestamp(b[0])
        if start <= at <= end and a[3] is not None and b[3] is not None:
            fraction = (at-start).total_seconds() / (end-start).total_seconds() if end > start else 0
            return round(a[3] + fraction*(b[3]-a[3]), 3)
    return next((p[3] for p in track if observe.timestamp(p[0]) == at), None)


async def write_book(db, register, slug, ride, row, leg, now):
    if (os.environ.get("LONGWAY_COMMIT_ENABLED") != "1" or row["state"] != "arrived"
            or not row["arrived_at"] or now < row["arrived_at"] + timedelta(hours=6)
            or row["logbook_written_at"]):
        return
    if register.logbook(slug, ride["id"]):
        await db.execute("UPDATE longway_rides SET logbook_written_at=$3 WHERE trip_slug=$1 AND ride_id=$2", slug, ride["id"], now)
        return
    people = await db.fetch("""SELECT u.id,u.display_name,c.email FROM users u
        JOIN user_credentials c ON c.user_id=u.id WHERE EXISTS
        (SELECT 1 FROM room_memberships m JOIN rooms r ON r.id=m.room_id WHERE m.user_id=u.id AND r.is_home)
        ORDER BY u.created_at,u.id""")
    author = next((p for name in ride["riders"] for p in people if p["display_name"].casefold() == name.casefold()), None)
    if not author:
        return
    rows = await db.fetch("SELECT * FROM longway_ride_fixes WHERE trip_slug=$1 AND ride_id=$2 ORDER BY at", slug, ride["id"])
    track = track_points(rows)
    full_track = [[observe.iso(r["at"]), r["lat"], r["lon"], r["km"]] for r in rows]
    notes = []
    if row["departed_at"]:
        messages = await db.fetch("""SELECT m.created_at,m.content,u.display_name FROM messages m
            JOIN threads t ON t.id=m.thread_id JOIN rooms r ON r.id=t.room_id JOIN users u ON u.id=m.user_id
            WHERE r.linked_journey=$1 AND m.speaker_type='human' AND NOT m.is_deleted
            AND m.created_at >= $2 AND m.created_at <= $3 ORDER BY m.created_at,m.id""",
            slug, row["departed_at"]-timedelta(minutes=30), row["arrived_at"])
        rider_names = {n.casefold() for n in ride["riders"]}
        notes = [dict(at=observe.iso(m["created_at"]), km=interpolate(m["created_at"], full_track),
                      member=m["display_name"], text=m["content"])
                 for m in messages if m["display_name"].casefold() in rider_names]
    stops = observe.record_stops(ride, row["stations"], leg, row["observed_at"] or now)
    vehicle = ride["vehicle"]
    book = dict(ride=ride["id"], trip=slug, vehicle=vehicle["name"], date=ride["date"],
                board=ride["board"], alight=ride["alight"], leg=ride["leg"],
                written_at=now.date().isoformat(), written_by="house", stops=stops, track=track,
                track_basis=("broadcast positions projected onto the leg model; at most one point per km" if leg
                             else "broadcast positions thinned by distance travelled; model km unavailable"),
                notes=notes)
    if vehicle.get("amtrak"):
        book["train"] = str(vehicle["amtrak"])
        publisher, url = "Amtraker (Amtrak status)", f"{observe.AMTRAK}/{vehicle['amtrak']}"
    else:
        from .fixes import SHIPS_URL
        book["mmsi"] = str(vehicle["mmsi"])
        publisher, url = "AIS listener", os.environ.get("LONGWAY_FIXES_URL", SHIPS_URL)
    book["sources"] = [dict(publisher=publisher, url=url, checked_at=observe.iso(row["observed_at"] or now),
                            note="Broadcast positions; station arrival/departure times are actual only")]
    task = asyncio.create_task(asyncio.to_thread(register.write_logbook, slug, ride["id"], book, author["display_name"], author["email"]))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise
    await db.execute("UPDATE longway_rides SET logbook_written_at=$3 WHERE trip_slug=$1 AND ride_id=$2", slug, ride["id"], now)


async def push(db, slug, ride, event, body, *, riders_only=False):
    from api.notifications.webpush import send_web_notifications
    members = await db.fetch("""SELECT r.id,r.name,m.user_id,u.display_name FROM rooms r
        JOIN room_memberships m ON m.room_id=r.id JOIN users u ON u.id=m.user_id
        WHERE r.linked_journey=$1 ORDER BY r.created_at,r.id,m.user_id""", slug)
    rider_names, seen, groups = {n.casefold() for n in ride["riders"]}, set(), {}
    for m in members:
        if m["user_id"] in seen or (riders_only and m["display_name"].casefold() not in rider_names):
            continue
        seen.add(m["user_id"])
        groups.setdefault((m["id"], m["name"]), []).append(str(m["user_id"]))
    success = True
    for (room_id, name), recipients in groups.items():
        result = await send_web_notifications(db=db, recipient_user_ids=recipients,
            title=f"{name}: {ride['vehicle']['name']}", body=body,
            data={"room_id": str(room_id), "type": "longway_ride", "ride": ride["id"]},
            tag=f"longway_ride_{slug}_{ride['id']}_{event}")
        success = success and not result.get("errors")
    return success


async def notifications(db, slug, ride, row, leg, fix, km):
    for event, station in (("departed", ride["board"]), ("arrived", ride["alight"])):
        if not row[f"{event}_at"] or row[f"{event}_pushed"]:
            continue
        if await push(db, slug, ride, event, f"{event} {station}"):
            await db.execute(f"UPDATE longway_rides SET {event}_pushed=true WHERE trip_slug=$1 AND ride_id=$2", slug, ride["id"])
    if row["state"] != "riding" or km is None or not fix or fix["age_min"] > 10 or not fix.get("speed_mph"):
        return
    for gap in ((leg or {}).get("coverage") or {}).get("gaps", []):
        minutes = (gap["km0"]-km) / (fix["speed_mph"]*1.609344) * 60
        key = f"{ride['leg']}:{gap['km0']}:{gap['km1']}"
        if not 0 <= minutes <= 10 or key in row["warned_gaps"]:
            continue
        if await push(db, slug, ride, key, f"Signal gap near {gap.get('near') or gap['km0']}: starts in {round(minutes)} min, about {gap.get('minutes', '?')} min without signal (model)", riders_only=True):
            await db.execute("UPDATE longway_rides SET warned_gaps=array_append(warned_gaps,$3) WHERE trip_slug=$1 AND ride_id=$2", slug, ride["id"], key)


async def watch(ctx, *, now=None):
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(observe.CHICAGO).date()
    register, result = get_register(), {}
    async with ctx.pool.acquire() as db:
        for journey in register.chart()["journeys"]:
            if journey["kind"] != "trip":
                continue
            trip = register.ride(journey["slug"])
            for ride in trip["rides"]:
                slug, rid = trip["slug"], ride["id"]
                try:
                    async with db.transaction():
                        await db.execute("INSERT INTO longway_rides(trip_slug,ride_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", slug, rid)
                        row = await db.fetchrow("SELECT * FROM longway_rides WHERE trip_slug=$1 AND ride_id=$2 FOR UPDATE SKIP LOCKED", slug, rid)
                        if not row:
                            continue
                        row = dict(row)
                        leg = rides.leg_for(register, ride)
                        book = register.logbook(slug, rid)
                        if book:
                            await db.execute("UPDATE longway_rides SET state='arrived',logbook_written_at=COALESCE(logbook_written_at,$3) WHERE trip_slug=$1 AND ride_id=$2", slug, rid, now)
                            row['state'] = 'arrived'
                            await notifications(db, slug, ride, row, leg, None, None)
                            continue
                        days = (date.fromisoformat(ride["date"])-today).days
                        if row["state"] == "arrived":
                            await notifications(db, slug, ride, row, leg, None, None)
                            await write_book(db, register, slug, ride, row, leg, now)
                            continue
                        if not -1 <= days <= 3 and row["state"] != "riding":
                            continue
                        run, fix = await rides.observation(ride, now)
                        state, departed, arrived = rides.state_for(ride, row, None, run, now)
                        stations = run.get("stations", []) if run else row["stations"]
                        run_id = run.get("trainID") if run else row["run_id"]
                        observed_at = now if run or fix else row["observed_at"]
                        await db.execute("""UPDATE longway_rides SET state=$3,run_id=$4,departed_at=$5,arrived_at=$6,
                            stations=$7,observed_at=$8 WHERE trip_slug=$1 AND ride_id=$2""",
                            slug, rid, state, run_id, departed, arrived, stations, observed_at)
                        row.update(state=state, run_id=run_id, departed_at=departed, arrived_at=arrived, stations=stations, observed_at=observed_at)
                        km = observe.project(fix["lat"], fix["lon"], leg) if fix else None
                        if fix:
                            stops = observe.stops(ride, stations, leg, now)
                            upcoming = next((s for s in stops if s["status"] != "Departed"), None)
                            await db.execute("""INSERT INTO longway_ride_fixes
                                (trip_slug,ride_id,at,lat,lon,speed_mph,heading,km,late_min,source)
                                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) ON CONFLICT DO NOTHING""",
                                slug, rid, observe.timestamp(fix["at"]), fix["lat"], fix["lon"], fix["speed_mph"],
                                fix["heading"], km, upcoming["late_min"] if upcoming else None, fix["source"])
                        await notifications(db, slug, ride, row, leg, fix, km)
                        await write_book(db, register, slug, ride, row, leg, now)
                        result[f"{slug}/{rid}"] = state
                except Exception as exc:
                    logger.exception("Ride %s/%s remains queued", slug, rid)
                    result[f"{slug}/{rid}"] = {"error": type(exc).__name__}
    return result
