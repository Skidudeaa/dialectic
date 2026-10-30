from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from organs.longway import proposals, fixes
from organs.longway.tools import build_tools
from tests.conftest import make_room
from tests.test_longway_register import longway_repo
from tests.test_longway_api import db, house, client


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
