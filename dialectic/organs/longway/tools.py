"""Scout conversation tools for reading the house and committing member-requested candidate edits."""
import asyncio
import json
from uuid import UUID

from .register import CommitsDisabled, DirtyDocument, UnknownCandidate, get_register
from .fixes import overlay
from .proposals import propose, PROPOSAL_FIELDS


def build_tools(room, db):
    from llm.tools import TOOL_RESULT_CHAR_CAP, Tool

    async def read_register(args):
        register = get_register()
        if args.get("document"):
            if not args.get("slug"):
                return {"error": "Choose a candidate slug to read its document."}
            try:
                doc = await asyncio.to_thread(register.document, args["slug"], args["document"])
            except (KeyError, UnknownCandidate):
                return {"error": "Unknown document"}
            content = doc["value"] if doc["format"] == "text" else json.dumps(doc["value"], ensure_ascii=False, indent=2)
            start = args.get("start_char", 0)
            if type(start) is not int or not 0 <= start <= len(content):
                return {"error": "Choose a character offset within this document."}
            end = min(len(content), start + TOOL_RESULT_CHAR_CAP)
            # The conversation loop caps serialized JSON, including escaping.
            while True:
                result = {"name": doc["name"], "format": doc["format"], "protected": doc["protected"],
                          "content": content[start:end], "next_start_char": end if end < len(content) else None}
                if len(json.dumps(result)) <= TOOL_RESULT_CHAR_CAP:
                    return result
                end = start + (end - start) // 2
        if not args.get("slug"):
            return await asyncio.to_thread(register.chart)
        item = await asyncio.to_thread(register.journey, args["slug"])
        if item["kind"] == "candidate":
            notes = await asyncio.to_thread(register.notebook, args["slug"])
            friends = [{k: n[k] for k in ("id", "kind", "place", "about", "by", "text", "state", "steer") if k in n}
                       for n in notes if n["state"] != "set aside"]
            if friends:
                return {"notebook": friends, **item}
        return item

    async def read_voyage(args):
        try:
            data = await asyncio.to_thread(get_register().voyage, args["slug"])
        except (FileNotFoundError, UnknownCandidate):
            return {"error": "Unknown journey or no voyage"}
        except ValueError as exc:
            return {"error": str(exc)}
        voyage = data["voyage"]
        stations = voyage["stations"]
        station = args.get("station")
        if station is None:
            return {"stations": [{"id": s["id"], "name": s["name"]} for s in stations], "keys": list(voyage)}
        return next((s for s in stations if s["id"] == station), {"error": f"No station {station!r} in this voyage"})

    async def member_write(args, *, notebook):
        binding = await db.fetchrow("SELECT linked_journey, is_home FROM rooms WHERE id=$1", room.id)
        if not binding or not (binding["is_home"] or binding["linked_journey"] == args["slug"]):
            return {"error": "This room can only change its linked journey."}
        refusal = {"error": "Pass the message_id of the message in which a member of this room asked you for this change."}
        raw_id = args.get("message_id")
        if not isinstance(raw_id, str):
            return refusal
        try:
            message_id = UUID(raw_id)
        except ValueError:
            return refusal
        if str(message_id) != raw_id:
            return refusal

        actor = await db.fetchrow("""
            WITH recent AS (
                SELECT m.id, m.user_id FROM messages m JOIN threads t ON t.id=m.thread_id
                WHERE t.room_id=$1 AND m.speaker_type='human' AND NOT m.is_deleted
                ORDER BY m.created_at DESC, m.id DESC LIMIT 12
            )
            SELECT u.display_name, c.email, EXISTS(
                SELECT 1 FROM rooms h JOIN room_memberships hm ON hm.room_id=h.id
                WHERE h.is_home AND hm.user_id=u.id AND hm.can_manage_home) AS manager FROM recent
            JOIN users u ON u.id=recent.user_id
            JOIN room_memberships rm ON rm.user_id=u.id AND rm.room_id=$1
            JOIN user_credentials c ON c.user_id=u.id
            WHERE recent.id=$2""", room.id, message_id)
        if not actor or not (actor["display_name"] or "").strip() or not (actor["email"] or "").strip():
            return refusal
        if not notebook and not actor["manager"]:
            return {"error": "Only a house manager can ask for a change to the voyage, dossier or record."}
        try:
            if notebook:
                return await asyncio.to_thread(get_register().add_note, args["slug"], args["kind"], args["text"],
                                              args.get("place"), args.get("about"), actor["display_name"], actor["email"],
                                              extra_trailers=(f"Asked-In: {message_id}",))
            return await asyncio.to_thread(get_register().edit_document, args["slug"], args["document"],
                                           args.get("ops"), args.get("text"), actor["display_name"], actor["email"],
                                           extra_trailers=(f"Asked-In: {message_id}",))
        except KeyError:
            return {"error": "Unknown document"}
        except (ValueError, CommitsDisabled, DirtyDocument) as exc:
            return {"error": str(exc)}

    async def add_note(args):
        return await member_write(args, notebook=True)

    async def edit_journey(args):
        return await member_write(args, notebook=False)

    async def fit_window(args):
        return {"fit": get_register().fit_window(args["trip"])}

    async def where_is(args):
        chart = await overlay(get_register().chart())
        query = args["name"].casefold()
        return {"vehicles": [v for v in chart["vehicles"] if query in v["name"].casefold() or query == v["journey"].casefold()],
                "fixes_state": chart["fixes_state"], "note": "A position is not a timetable or availability."}

    async def propose_evidence(args):
        allowed = ('candidate', 'url', 'claim', 'scope') + tuple(k for k in PROPOSAL_FIELDS if k != 'run_id')
        return await propose(db, room.id, **{key: args[key] for key in allowed if key in args})

    async def draft_dispatch(args):
        from .dispatch import draft
        binding = await db.fetchrow("SELECT linked_journey, is_home FROM rooms WHERE id=$1", room.id)
        if not binding or not (binding["is_home"] or binding["linked_journey"]):
            raise ValueError("Bind this room to a journey before drafting its dispatch")
        return {"draft": await draft(binding["linked_journey"], db=db, room_id=room.id), "posted": False}

    async def ride_status(args):
        from .rides import payload
        try:
            return await payload(db, room.id, args.get("ride"))
        except (KeyError, ValueError):
            return {"error": "No such ride in this room"}

    async def out_the_window(args):
        from .rides import payload, leg_for, window
        try:
            data = await payload(db, room.id, with_history=False)
        except (KeyError, ValueError):
            return {"error": "No ride in this room", "provenance": "model"}
        km = args.get("km")
        if km is None:
            if data["ride"]["state"] != "riding":
                return {"error": f"Ride is {data['ride']['state']}; supply km to explore its model", "provenance": "model"}
            km = data["km"]
        if km is None:
            return {"error": "No observed km; supply km to explore the model", "provenance": "model"}
        leg = leg_for(get_register(), data["ride"])
        if not leg:
            return {"error": "This ride has no leg model", "provenance": "model"}
        return window(leg, km, args.get("side", "both"))

    def tool(name, description, fn, properties, required=(), timeout=14):
        return Tool(name, description, {"type": "object", "properties": properties,
                    "required": list(required), "additionalProperties": False}, fn,
                    name.replace("_", " "), timeout_s=timeout)

    string = {"type": "string"}
    document_name = {"type": "string", "enum": ["voyage", "record", "dossier"]}
    proposal_properties = {key: string for key in ('candidate', 'url', 'claim', 'scope')}
    proposal_properties.update({key: {'type': ['string', 'null']} for key in PROPOSAL_FIELDS if key not in ('run_id', 'load_bearing')})
    proposal_properties['load_bearing'] = {'type': 'boolean'}
    return [
        tool("read_register", "Read the public register, or a journey, its evidence and its friends’ notes. For an entire editable candidate document, "
             "supply slug and document and continue at next_start_char until null. Shared trips expose only Established and Undecided.",
             read_register, {"slug": string, "document": document_name, "start_char": {"type": "integer", "minimum": 0}}),
        tool("fit_window", "Compare recorded candidate seasons with a shared trip's window; hypotheses remain hypotheses.", fit_window, {"trip": string}, ("trip",)),
        tool("where_is", "Read last observed ship/train positions by vehicle name or journey slug, with unknown fixes explicit.", where_is, {"name": string}, ("name",)),
        tool("propose_evidence", "Fetch a page and file a bounded claim for human Field confirmation. Use a 3–35 word phrase occurring in the extracted page. Never writes the repo.", propose_evidence, proposal_properties, ("candidate", "url", "claim", "scope"), 26),
        tool("draft_dispatch", "Draft this room's weekly dispatch from git evidence. Does not post or push.", draft_dispatch, {}, timeout=28),
        tool("ride_status", "Read only this room's ride, broadcast fix and age, stops, lateness and history.", ride_status, {"ride": string}),
        tool("out_the_window", "Read sights within 2 km on this ride's leg, with guide text and links. These are model predictions, not observations. Omit km only while riding.", out_the_window,
             {"side": {"type": "string", "enum": ["left", "right", "both"]}, "km": {"type": "number"}}),
        tool("read_voyage", "Read one river stop by station ID, or list the stops and the voyage's top-level keys.",
             read_voyage, {"slug": string, "station": string}, ("slug",)),
        tool("add_note", "Put a friend's place or thought in the notebook in their words. Pass the id of their asking message.",
             add_note, {"slug": string, "kind": {"type": "string", "enum": ["place", "thought"]},
                        "text": string, "place": string, "about": string, "message_id": {"type": "string", "format": "uuid"}},
             ("slug", "kind", "text", "message_id"), timeout=28),
        tool("edit_journey", "Change the journey's voyage, record or dossier in the repository in the asking member's name. "
             "Use only when a member's message addressed to you in this room asks for that specific change. "
             "Pass that message's UUID in message_id. Keep every fact's S-number citations. "
             "Status and review fields cannot be changed. Supply ops for voyage or record, or the whole markdown text for dossier.",
             edit_journey, {"slug": string, "document": document_name, "message_id": {"type": "string", "format": "uuid"},
                            "ops": {"type": "array", "maxItems": 200, "items": {"type": "object", "properties": {
                                "op": {"type": "string", "enum": ["set", "remove", "move"]},
                                "path": {"type": "string", "description": "Slash-separated keys, item IDs or positions, e.g. stations/aswan/kicker"},
                                "value": {"description": "New JSON value for set"},
                                "before": {"type": ["string", "null"], "description": "Move before this item, or null for the end"}},
                                "required": ["op", "path"]}},
                            "text": {"type": "string", "maxLength": 200_000}}, ("slug", "document", "message_id"), timeout=28),
    ]
