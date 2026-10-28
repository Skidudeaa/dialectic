"""Five participant tools; repository mutation belongs exclusively to the writer."""
from .register import get_register
from .fixes import overlay
from .proposals import propose


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
        return await propose(db, room.id, **{key: args[key] for key in ("candidate", "url", "claim", "scope")})

    async def draft_dispatch(args):
        from .dispatch import draft
        binding = await db.fetchrow("SELECT linked_journey, is_home FROM rooms WHERE id=$1", room.id)
        if not binding or not (binding["is_home"] or binding["linked_journey"]):
            raise ValueError("Bind this room to a journey before drafting its dispatch")
        return {"draft": await draft(binding["linked_journey"]), "posted": False}

    def tool(name, description, fn, properties, required=(), timeout=14):
        return Tool(name, description, {"type": "object", "properties": properties,
                    "required": list(required), "additionalProperties": False}, fn,
                    name.replace("_", " "), timeout_s=timeout)

    string = {"type": "string"}
    return [
        tool("read_register", "Read the public journey register, or a candidate dossier and its S-number evidence. Shared trips expose only Established and Undecided.", read_register, {"slug": string}),
        tool("fit_window", "Compare recorded candidate seasons with a shared trip's window; hypotheses remain hypotheses.", fit_window, {"trip": string}, ("trip",)),
        tool("where_is", "Read last observed ship/train positions by vehicle name or journey slug, with unknown fixes explicit.", where_is, {"name": string}, ("name",)),
        tool("propose_evidence", "Fetch a page and file a bounded claim for human Field confirmation. Use a 3–35 word phrase occurring in the extracted page. Never writes the repo.", propose_evidence, {k: string for k in ("candidate", "url", "claim", "scope")}, ("candidate", "url", "claim", "scope"), 26),
        tool("draft_dispatch", "Draft this room's weekly dispatch from git evidence. Does not post or push.", draft_dispatch, {}, timeout=28),
    ]
