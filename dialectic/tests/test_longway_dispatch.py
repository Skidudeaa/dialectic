from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from scheduler import SchedulerContext
from organs.longway import dispatch, jobs
from tests.test_longway_register import longway_repo, git
from tests.test_longway_api import db, house, client


@pytest.mark.asyncio
async def test_sunday_posts_once_and_pushes_monday_does_nothing(db,house,client,longway_repo,monkeypatch):
    sunday=datetime(2026,11,1,14,tzinfo=timezone.utc)
    await db.execute("INSERT INTO messages(id,thread_id,sequence,created_at,speaker_type,user_id,message_type,content) VALUES ($1,$2,1,$3,'human',$4,'text','What about November?')",uuid4(),house.thread,sunday-timedelta(days=1),house.user.user_id)
    # Scope Home to our fixture and make a thread if the test DB lacks one.
    home=await db.fetchval("SELECT id FROM rooms WHERE is_home")
    if home:
        await db.execute("UPDATE rooms SET is_home=false WHERE id=$1",home)
    home=uuid4()
    await db.execute("INSERT INTO rooms(id,created_at,token,name,is_home) VALUES ($1,clock_timestamp(),$2,'Test Home',true)",home,str(home))
    await db.execute("INSERT INTO threads(id,room_id,created_at,title) VALUES ($1,$2,clock_timestamp(),'Main')",uuid4(),home)
    await db.execute("INSERT INTO room_memberships(room_id,user_id,joined_at) VALUES ($1,$2,clock_timestamp())",home,house.user.user_id)
    # Only fixture bound rooms qualify in this transaction.
    await db.execute("UPDATE rooms SET linked_journey=NULL WHERE id<>$1",house.room)
    model=AsyncMock(return_value="S1 remains unverified. Which month?\n\n"+dispatch.REACTION_LINE)
    monkeypatch.setattr(jobs,"draft",model)
    push=AsyncMock()
    monkeypatch.setattr("api.notifications.webpush.send_web_notifications",push)
    broadcast=AsyncMock()
    ctx=SchedulerContext(house.pool,broadcast=broadcast)
    assert await jobs.sunday_dispatch(ctx,now=sunday+timedelta(days=1)) == {"skipped":"not Sunday"}
    model.assert_not_called()
    result=await jobs.sunday_dispatch(ctx,now=sunday)
    assert set(result) == {str(home),str(house.room)},result
    assert push.await_count == 2 and broadcast.await_count == 2
    latest=(await client.get(f"/rooms/{house.room}/longway/dispatch/latest")).json()
    assert latest["speaker_type"] == "llm_primary"
    assert latest["metadata"]["longway_dispatch"] == {"journey":"ogasawara","week_of":"2026-11-01"}
    assert latest["content"].endswith(dispatch.REACTION_LINE)
    await jobs.sunday_dispatch(ctx,now=sunday)
    assert model.await_count == 2 and push.await_count == 2


@pytest.mark.asyncio
async def test_history_model_and_quiet_week(longway_repo,monkeypatch):
    movement=await dispatch.history("ogasawara")
    assert movement[0]["evidence_changes"][0]["id"] == "S1"
    assert "Which month" in movement[0]["next_decision"]
    assert "BOOKING-PRIVATE" not in str(await dispatch.history())
    request=[]
    class Provider:
        client=SimpleNamespace(aclose=AsyncMock())
        async def complete(self, value):
            request.append(value)
            return SimpleNamespace(content="S1 is unverified. Which month should we investigate?")
    monkeypatch.setattr(dispatch,"AnthropicProvider",Provider)
    monkeypatch.setenv("LONGWAY_DISPATCH_MODEL","chosen-model")
    text=await dispatch.draft("ogasawara")
    assert text.endswith(dispatch.REACTION_LINE)
    assert request[0].model == "chosen-model" and "Go far enough" in request[0].system
    later=datetime.now(timezone.utc)+timedelta(days=9)
    assert await dispatch.draft("ogasawara",later) == "Nothing moved this week\n\n"+dispatch.REACTION_LINE
    assert len(request) == 1


@pytest.mark.asyncio
async def test_dispatch_includes_confirmation_contest_and_receipt(db,house,client,longway_repo,monkeypatch):
    from organs.longway import proposals,scout
    from uuid import UUID
    monkeypatch.setattr(proposals.defuddle_client,'extract_article',AsyncMock(return_value={'content':'The ferry sails weekly.','site':'Kaiun'}))
    ids=[]
    for action in ('confirm','contest'):
        result=await proposals.propose(db,house.room,'ogasawara','https://www.ogasawarakaiun.co.jp/',
            'The ferry sails weekly','Tokyo')
        ids.append(result['id'])
        assert (await client.post(f"/rooms/{house.room}/field/marks/{result['field_mark_id']}/review",
            json={'action':action,'note':'Read the page'})).status_code==200
    await db.execute("UPDATE longway_evidence_proposals SET written_sid='S42' WHERE id=$1",UUID(ids[0]))
    monkeypatch.setenv('LONGWAY_SEARCH_PROVIDER','none')
    run=await scout.reserve(house.pool,house.room,'ogasawara')
    await scout.finish(house.pool,run['id'],'done')
    movement=await dispatch.history('ogasawara',db=db,room_id=house.room)
    activity=movement[-1]
    assert [r['action'] for r in activity['proposal_reviews']]==['confirm','contest']
    assert [str(r['id']) for r in activity['proposal_reviews']]==ids
    assert activity['proposal_reviews'][0]['written_sid']=='S42'
    assert activity['scout_runs'][0]['id']==run['id']
    class Model:
        client=SimpleNamespace(aclose=AsyncMock())
        async def complete(self,request):
            assert all(i in request.messages[0]['content'] for i in ids)
            assert str(run['id']) in request.messages[0]['content']
            return SimpleNamespace(content=f"Proposal {ids[0]} became S42; {ids[1]} was contested. Scout filed its receipt.\n\nWhich month should we investigate?")
    monkeypatch.setattr(dispatch,'AnthropicProvider',Model)
    text=await dispatch.draft('ogasawara',db=db,room_id=house.room)
    assert text.split('\n\n')[-2]=='Which month should we investigate?'
    assert text.endswith(dispatch.REACTION_LINE)
