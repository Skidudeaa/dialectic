"""Five participant tools; repository mutation belongs exclusively to the writer."""
from .register import get_register
from .fixes import overlay
from .proposals import propose, PROPOSAL_FIELDS


def build_tools(room, db):
    from llm.tools import Tool

    async def read_register(args):
        register = get_register()
        return register.journey(args["slug"]) if args.get("slug") else register.chart()

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
    proposal_properties = {key: string for key in ('candidate', 'url', 'claim', 'scope')}
    proposal_properties.update({key: {'type': ['string', 'null']} for key in PROPOSAL_FIELDS if key not in ('run_id', 'load_bearing')})
    proposal_properties['load_bearing'] = {'type': 'boolean'}
    return [
        tool("ride_status", "Read only this room's ride, broadcast fix and age, stops, lateness and history.", ride_status, {"ride": string}),
        tool("out_the_window", "Read sights within 2 km on this ride's leg, with guide text and links. These are model predictions, not observations. Omit km only while riding.", out_the_window,
             {"side": {"type": "string", "enum": ["left", "right", "both"]}, "km": {"type": "number"}}),
        tool("read_register", "Read the public journey register, or a candidate dossier and its S-number evidence. Shared trips expose only Established and Undecided.", read_register, {"slug": string}),
        tool("fit_window", "Compare recorded candidate seasons with a shared trip's window; hypotheses remain hypotheses.", fit_window, {"trip": string}, ("trip",)),
        tool("where_is", "Read last observed ship/train positions by vehicle name or journey slug, with unknown fixes explicit.", where_is, {"name": string}, ("name",)),
        tool("propose_evidence", "Fetch a page and file a bounded claim for human Field confirmation. Use a 3–35 word phrase occurring in the extracted page. Never writes the repo.", propose_evidence, proposal_properties, ("candidate", "url", "claim", "scope"), 26),
        tool("draft_dispatch", "Draft this room's weekly dispatch from git evidence. Does not post or push.", draft_dispatch, {}, timeout=28),
    ]
