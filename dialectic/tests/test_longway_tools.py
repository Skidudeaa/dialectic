from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from organs.longway import proposals, fixes
from organs.longway.tools import build_tools
from tests.conftest import make_room
from tests.test_longway_register import longway_repo, voyage_repo, git
from tests.test_longway_api import db, house, home_room, client


async def add_member(db, house, name):
    member = uuid4()
    await db.execute("INSERT INTO users(id,created_at,display_name) VALUES ($1,now(),$2)", member, name)
    await db.execute("INSERT INTO room_memberships(room_id,user_id,joined_at) VALUES ($1,$2,now())", house.room, member)
    return member


async def post_message(db, thread, sequence, member, content, speaker="human", deleted=False):
    message_id = uuid4()
    await db.execute("""INSERT INTO messages(id,thread_id,sequence,created_at,speaker_type,user_id,message_type,content,is_deleted)
        VALUES ($1,$2,$3,clock_timestamp(),$4,$5,'text',$6,$7)""", message_id, thread, sequence, speaker, member, content, deleted)
    return str(message_id)


async def assert_request_refused(edit, args, root):
    head = git(root, "rev-parse", "HEAD")
    assert not git(root, "status", "--porcelain")
    result = await edit(args)
    assert "Pass the message_id of the message" in result["error"]
    assert git(root, "rev-parse", "HEAD") == head
    assert not git(root, "status", "--porcelain")


@pytest.mark.asyncio
async def test_tool_source_gate_and_field_confirm(db,house,client,longway_repo,monkeypatch):
    room=make_room(id=house.room)
    tool=next(t for t in build_tools(room,db) if t.name=="propose_evidence")
    args=dict(candidate="ogasawara",url="https://www.ogasawarakaiun.co.jp/",claim="The ferry sails weekly",scope="Tokyo to Chichijima")
    fetch=AsyncMock(return_value={"content":"The ferry never sails weekly", "site":"Kaiun"})
    monkeypatch.setattr(proposals.defuddle_client,"extract_article",fetch)
    assert (await tool.execute(args))["filed"] is False
    assert await db.fetchval("SELECT count(*) FROM longway_evidence_proposals WHERE room_id=$1",house.room) == 0
    fetch.return_value={"content":"The ferry sails weekly from Tokyo.","site":"Kaiun"}
    result=await tool.execute(args)
    assert result["filed"] is True
    row=await db.fetchrow("SELECT * FROM longway_evidence_proposals WHERE id=$1",UUID(result["id"]))
    assert row["proposed_by"] == "llm" and len(row["support"].split()) < 40
    mark=result["field_mark_id"]
    response=await client.post(f"/rooms/{house.room}/field/marks/{mark}/review",json={"action":"confirm"})
    assert response.status_code == 200,response.text
    rows=(await client.get(f"/rooms/{house.room}/longway/proposals")).json()
    assert rows[0]["queued"] is True and rows[0]["review_state"] == "confirmed"
    assert len(longway_repo.evidence("ogasawara")) == 1


def test_guard_is_not_keyword_overlap():
    assert proposals.supported_passage("The ferry sails weekly", "The ferry never sails weekly") is None
    assert proposals.supported_passage("Sails from Tokyo to Chichijima", "Sails from Chichijima to Tokyo") is None
    assert proposals.supported_passage("The ferry sails weekly", "THE ferry sails\nweekly.") is not None


@pytest.mark.asyncio
async def test_read_fit_and_location_tools(longway_repo,monkeypatch):
    tools={t.name:t for t in build_tools(make_room(),None)}
    assert all(t.timeout_s < 30 for t in tools.values())
    assert len((await tools["read_register"].execute({}))["journeys"]) == 2
    assert "hypothesis" in (await tools["fit_window"].execute({"trip":"friends-2027"}))["fit"]
    async def feed(url):
        return {"fixes":{}}
    monkeypatch.setattr(fixes,"fetch_feed",feed)
    assert (await tools["where_is"].execute({"name":"Ogasawara"}))["vehicles"][0]["heard"] is False


@pytest.mark.asyncio
async def test_undated_train_is_heard_but_not_a_fabricated_fix(monkeypatch):
    from datetime import datetime, timezone
    from organs.longway import observe
    run={"trainID":"14-28", "lat":45.5, "lon":-122.5}
    async def trains(num):
        return [run]
    async def feed(url):
        return {"fixes":{},"written":"2026-10-28T00:00:00Z"}
    monkeypatch.setattr(observe,"trains",trains)
    monkeypatch.setattr(fixes,"fetch_feed",feed)
    chart={"vehicles":[{"name":"Coast Starlight","amtrak":"14"}]}
    now=datetime(2026,10,28,1,tzinfo=timezone.utc)
    result=await fixes.overlay(chart,now)
    assert result["vehicles"][0]["heard"] is True
    assert result["vehicles"][0]["fix"] is None
    run["lastValTS"]="2026-10-28T00:45:00Z"
    result=await fixes.overlay(chart,now)
    assert result["vehicles"][0]["fix"]["age_min"] == 15
    assert result["vehicles"][0]["fix"]["source"] == "amtrak"


@pytest.mark.asyncio
async def test_scout_voyage_and_member_edit(db, house, voyage_repo, monkeypatch):
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED", "1")
    tools = {t.name: t for t in build_tools(make_room(id=house.room), db)}
    read = tools["read_voyage"].execute
    stops = await read({"slug": "nile"})
    assert stops["stations"] == [{"id": "aswan", "name": "Aswan"}, {"id": "luxor", "name": "Luxor"}]
    assert {"start", "stations"} <= set(stops["keys"])
    stop = await read({"slug": "nile", "station": "aswan"})
    assert stop["km"] > 0 and stop["moment"]["cite"] == ["S1"]
    assert "No station" in (await read({"slug": "nile", "station": "absent"}))["error"]

    edit = tools["edit_journey"].execute
    assert "message_id" in tools["edit_journey"].input_schema["required"]
    root = voyage_repo.root
    args = {"slug": "nile", "document": "voyage", "message_id": str(uuid4()),
            "ops": [{"op": "set", "path": "stations/aswan/kicker", "value": "A late sail"}]}
    assert "linked journey" in (await edit(args))["error"]
    await db.execute("UPDATE rooms SET linked_journey='nile' WHERE id=$1", house.room)
    await assert_request_refused(edit, args, root)

    bob = await add_member(db, house, "Bob")
    args["message_id"] = await post_message(db, house.thread, 1, bob, "@Scout change the Aswan kicker to A late sail")
    # A real member and message, but no account email yet.
    await assert_request_refused(edit, args, root)
    email = f"{bob}@example.org"
    await db.execute("INSERT INTO user_credentials(user_id,email,password_hash) VALUES ($1,$2,'unused')", bob, email)
    result = await edit(args)
    assert result["commit"] == git(root, "rev-parse", "HEAD") and result["changed"] == ["stations/aswan/kicker"]
    assert (await read({"slug": "nile", "station": "aswan"}))["kicker"] == "A late sail"
    assert git(root, "log", "-1", "--format=%an <%ae>") == f"Bob <{email}>"
    refused = await edit(dict(args, document="record", ops=[{"op": "set", "path": "status", "value": "shortlisted"}]))
    assert "status is not changed here" in refused["error"]
    assert git(root, "rev-parse", "HEAD") == result["commit"]


@pytest.mark.asyncio
async def test_scout_keeps_the_asking_member_when_bob_speaks_later(db, house, voyage_repo, monkeypatch):
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED", "1")
    bob = await add_member(db, house, "Bob")
    await db.execute("INSERT INTO user_credentials(user_id,email,password_hash) VALUES ($1,$2,'unused')", bob, f"{bob}@example.org")
    alice = house.user.user_id
    alice_id = await post_message(db, house.thread, 1, alice, "@Scout change our dossier to Ocean crossing in autumn")
    # The recency window spans threads. Alice is exactly the twelfth visible human message.
    thread = uuid4()
    await db.execute("INSERT INTO threads(id,room_id,created_at,title) VALUES ($1,$2,now(),'Planning')", thread, house.room)
    for seq in range(1, 11):
        await post_message(db, thread, seq, bob, "I can meet on Sunday")
    bob_id = await post_message(db, thread, 11, bob, "@Scout change the record title to Autumn crossing")
    await post_message(db, thread, 12, bob, "Withdrawn", deleted=True)
    await post_message(db, thread, 13, None, "Reading", speaker="llm_primary")

    root = voyage_repo.root
    edit = next(t.execute for t in build_tools(make_room(id=house.room), db) if t.name == "edit_journey")
    args = dict(slug="ogasawara", document="dossier", text="Ocean crossing in autumn", message_id=alice_id)
    requests = [
        (args, "Alice", house.user.email),
        (dict(slug="ogasawara", document="record", message_id=bob_id,
              ops=[{"op": "set", "path": "title", "value": "Autumn crossing"}]), "Bob", f"{bob}@example.org"),
    ]
    for request, name, email in requests:
        result = await edit(request)
        sha = git(root, "rev-parse", "HEAD")
        assert result["commit"] == sha
        assert git(root, "show", "-s", "--format=%an <%ae>", sha) == f"{name} <{email}>"
        assert git(root, "show", "-s", "--format=%(trailers:only)", sha).splitlines() == [
            "Edited-In: The Long Way house", f"Asked-In: {request['message_id']}"]

    # Even a new message from Alice cannot extend the life of her previous request.
    await post_message(db, thread, 14, alice, "Afternoon works")
    await assert_request_refused(edit, dict(args, text="Another change"), root)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["other-room", "scout", "deleted", "removed-member", "blank-name",
                                  "malformed", "noncanonical", "missing"])
async def test_scout_refuses_ineligible_request_ids(db, house, home_room, voyage_repo, monkeypatch, case):
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED", "1")
    alice = house.user.user_id
    thread = house.thread
    if case == "other-room":
        thread = uuid4()
        await db.execute("INSERT INTO room_memberships(room_id,user_id,joined_at) VALUES ($1,$2,now())",
                         home_room["id"], alice)
        await db.execute("INSERT INTO threads(id,room_id,created_at,title) VALUES ($1,$2,now(),'Main')",
                         thread, home_room["id"])
    request_id = await post_message(db, thread, 1, alice, "@Scout change the dossier to New plan",
                                    speaker="llm_primary" if case == "scout" else "human", deleted=case == "deleted")
    if case == "removed-member":
        await db.execute("DELETE FROM room_memberships WHERE room_id=$1 AND user_id=$2", house.room, alice)
    elif case == "blank-name":
        await db.execute("UPDATE users SET display_name=' ' WHERE id=$1", alice)
    args = dict(slug="ogasawara", document="dossier", text="New plan", message_id=request_id)
    if case == "malformed":
        args["message_id"] = "Alice"
    elif case == "noncanonical":
        args["message_id"] = request_id.replace("-", "")
    elif case == "missing":
        del args["message_id"]
    edit = next(t.execute for t in build_tools(make_room(id=house.room), db) if t.name == "edit_journey")
    await assert_request_refused(edit, args, voyage_repo.root)


@pytest.mark.asyncio
async def test_house_scout_can_edit_an_unbound_candidate(db, house, home_room, voyage_repo, monkeypatch):
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED", "1")
    home = home_room["id"]
    await db.execute("INSERT INTO room_memberships(room_id,user_id,joined_at) VALUES ($1,$2,now())", home, house.user.user_id)
    thread = uuid4()
    await db.execute("INSERT INTO threads(id,room_id,created_at,title) VALUES ($1,$2,now(),'Main')", thread, home)
    request_id = await post_message(db, thread, 1, house.user.user_id, "@Scout rename the Nile record to River fixture")
    edit = next(t for t in build_tools(make_room(id=home), db) if t.name == "edit_journey")
    result = await edit.execute({"slug": "nile", "document": "record", "message_id": request_id,
                                 "ops": [{"op": "set", "path": "title", "value": "River fixture"}]})
    assert result["changed"] == ["title"]
    assert voyage_repo.document("nile", "record")["value"]["title"] == "River fixture"


@pytest.mark.asyncio
async def test_scout_can_read_whole_editable_documents_within_tool_limit(voyage_repo):
    import json
    from llm.tools import serialize_tool_result
    read = next(t.execute for t in build_tools(make_room(), None) if t.name == "read_register")
    markdown = "舟🌊" * 3000
    (voyage_repo.root / "candidates/nile/dossier.md").write_text(markdown)
    args = {"slug": "nile", "document": "dossier"}
    parts = []
    while True:
        window = json.loads(serialize_tool_result(await read(args)))
        parts.append(window["content"])
        if window["next_start_char"] is None:
            break
        args["start_char"] = window["next_start_char"]
    assert len(parts) > 1 and "".join(parts) == markdown
    record = await read({"slug": "nile", "document": "record"})
    assert "status" in record["protected"]
    assert json.loads(record["content"]) == voyage_repo.document("nile", "record")["value"]
