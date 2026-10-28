from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from scheduler import SchedulerContext
from organs.longway import proposals, jobs
from tests.test_longway_register import longway_repo, git
from tests.test_longway_api import db, house, client


async def filed(db,house,monkeypatch):
    monkeypatch.setattr(proposals.defuddle_client,"extract_article",AsyncMock(return_value={"content":"The ferry sails weekly", "site":"Kaiun"}))
    return await proposals.propose(db,house.room,"ogasawara","https://www.ogasawarakaiun.co.jp/","The ferry sails weekly","Tokyo")


@pytest.mark.asyncio
async def test_writer_confirmation_toggle_author_and_retry(db,house,client,longway_repo,monkeypatch):
    result=await filed(db,house,monkeypatch)
    ctx=SchedulerContext(house.pool)
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED","1")
    await jobs.evidence_writer(ctx)
    assert len(longway_repo.evidence("ogasawara")) == 1
    response=await client.post(f"/rooms/{house.room}/field/marks/{result['field_mark_id']}/review",json={"action":"confirm"})
    assert response.status_code == 200,response.text
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED","0")
    await jobs.evidence_writer(ctx)
    assert len(longway_repo.evidence("ogasawara")) == 1
    assert await db.fetchval("SELECT written_at FROM longway_evidence_proposals WHERE id=$1",UUID(result["id"])) is None
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED","1")
    written=await jobs.evidence_writer(ctx)
    assert written[result["id"]]["sid"] == "S2",written
    row=await db.fetchrow("SELECT * FROM longway_evidence_proposals WHERE id=$1",UUID(result["id"]))
    assert row["written_sid"] == "S2" and row["written_at"] and row["written_commit"]
    assert row["written_by"] == house.user.user_id
    entries=longway_repo.evidence("ogasawara")
    assert entries[-1]["status"] == "verified"
    assert entries[-1]["checked_at"] == response.json()["review"]["created_at"][:10]
    assert git(longway_repo.root,"log","-1","--format=%an <%ae>") == f"Alice <{house.user.email}>"
    assert git(longway_repo.root,"rev-list","--count","HEAD") == "2"
    await jobs.evidence_writer(ctx)
    assert len(longway_repo.evidence("ogasawara")) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("action",["contest","correct"])
async def test_contested_or_corrected_never_written(action,db,house,client,longway_repo,monkeypatch):
    result=await filed(db,house,monkeypatch)
    endpoint=f"/rooms/{house.room}/field/marks/{result['field_mark_id']}/review"
    assert (await client.post(endpoint,json={"action":"confirm"})).status_code == 200
    body={"action":action,"note":"Wrong frequency"}
    if action=="correct":
        # Field replacements name a new source-backed proposal. The existing
        # Field dedup key intentionally rejects merely retitling the same ref.
        monkeypatch.setattr(proposals.defuddle_client,"extract_article",AsyncMock(return_value={"content":"The ferry sails every six days", "site":"Kaiun"}))
        replacement=await proposals.propose(db,house.room,"ogasawara","https://www.ogasawarakaiun.co.jp/","The ferry sails every six days","Tokyo")
        body["replacement"]={"relation":"context","subjects":[{"entity":"longway_evidence_proposals","id":replacement["id"]}],"title":"Actually every six days"}
    response=await client.post(endpoint,json=body)
    assert response.status_code == 200,response.text
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED","1")
    await jobs.evidence_writer(SchedulerContext(house.pool))
    assert len(longway_repo.evidence("ogasawara")) == 1


@pytest.mark.asyncio
async def test_confirmed_context_cannot_authorize_evidence(db,house,client,longway_repo,monkeypatch):
    result=await filed(db,house,monkeypatch)
    context=await client.post(f"/rooms/{house.room}/field/marks",json={
        "relation":"context", "subjects":[{"entity":"longway_evidence_proposals","id":result["id"]}],
        "title":"This claim needs investigation"})
    assert context.status_code == 201,context.text
    context_id=context.json()["id"].removeprefix("field_mark:")
    response=await client.post(f"/rooms/{house.room}/field/marks/{context_id}/review",json={"action":"confirm"})
    assert response.status_code == 200,response.text
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED","1")
    await jobs.evidence_writer(SchedulerContext(house.pool))
    assert len(longway_repo.evidence("ogasawara")) == 1
