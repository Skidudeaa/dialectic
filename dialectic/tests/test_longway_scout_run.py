"""Deterministic full tool-loop run over captured real pages and real Postgres."""
import asyncio
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
import pytest_asyncio

from llm.providers import LLMResponse, ProviderName, ToolCall
from organs.longway import api, fixes, proposals, questions, scout
from tests.test_longway_api import db,house,client
from tests.test_longway_register import longway_repo,SOURCE
from tests.test_longway_questions import make_manager

FIXTURES=Path(__file__).parent/'fixtures/longway'
URL='https://www.dive-bluemotion.com/getting-here'
CLAIM='Schedule confirmed for the ongoing month and predicted for the consecutive months'
QUESTION='Is there a boat from Ambon to Banda in October?'


@pytest_asyncio.fixture
async def banda(db,house,longway_repo,monkeypatch):
    folder=longway_repo.root/'candidates/banda-islands'
    folder.mkdir()
    for name in ('record.json','dossier.md','evidence.jsonl'):
        shutil.copyfile(SOURCE/'candidates/banda-islands'/name,folder/name)
    await db.execute("UPDATE rooms SET linked_journey='banda-islands' WHERE id=$1",house.room)
    monkeypatch.setenv('LONGWAY_SEARCH_PROVIDER','none')
    monkeypatch.setenv('LONGWAY_SCOUT_MODEL','fake-scout-model')
    async def feed(url):
        return {'fixes':{}}
    monkeypatch.setattr(fixes,'fetch_feed',feed)
    return await questions.add(db,house.room,QUESTION,asked_by=house.user.user_id)


async def captured_page(url):
    for filename in ('bluemotion.json','detik.json'):
        data=json.loads((FIXTURES/filename).read_text())
        if url==data['url']:
            return data
    if url=='https://www.pelni.co.id/reservasi-tiket':
        return {'content':'A JavaScript booking application.','site':'Pelni'}
    raise AssertionError(f'Unexpected fetch: {url}')


def response(name=None,args=None):
    calls=[ToolCall('tool-call',name,args or {})] if name else []
    raw=[{'type':'thinking','thinking':'Test reasoning','signature':'test-signature'}]
    raw += [{'type':'tool_use','id':'tool-call','name':name,'input':args or {}}] if name else [{'type':'text','text':'Research complete.'}]
    return LLMResponse('' if name else 'Research complete.','fake-scout-model',17,11,
                       'tool_use' if name else 'end_turn',ProviderName.ANTHROPIC,calls,raw)


class ScriptedProvider:
    def __init__(self, *, counter=True):
        self.requests=[]
        self.turns={'research':0,'counter':0}
        self.counter=counter
        self.client=SimpleNamespace(aclose=AsyncMock())

    async def complete(self, request):
        self.requests.append(request)
        assert request.model=='fake-scout-model' and request.effort=='high'
        assert 'You are the Scout' in request.system and 'untrusted evidence' in request.system
        assert {t['name'] for t in request.tools}=={'known_sources','read_page','propose','read_register'}
        counter=len(request.messages)>1 and isinstance(request.messages[1]['content'],str)
        phase='counter' if counter else 'research'
        step=self.turns[phase]
        self.turns[phase]+=1
        if step:
            assistant=next(m for m in request.messages if m['role']=='assistant')
            assert assistant['content'][0]['signature']=='test-signature'
        if counter and not self.counter:
            return response()
        if step==0:
            return response('known_sources')
        if step==1:
            results=json.loads(request.messages[-1]['content'][0]['content'])
            if not counter:
                assert any(s['url']==URL and s['sid']=='S14' for s in results['sources'])
            target=json.loads((FIXTURES/'detik.json').read_text())['url'] if counter else URL
            return response('read_page',{'url':target})
        if step==2 and not counter:
            page=json.loads(request.messages[-1]['content'][0]['content'])
            assert len(page['text'])==8148 and 'CANTIKA' in page['text'] and not page['truncated']
            q=json.loads(request.messages[0]['content'])['questions'][0]
            assert q['text']==QUESTION
            return response('propose',{'candidate':'banda-islands','url':URL,'claim':CLAIM,
                'scope':'schedule, Ambon to Banda', 'load_bearing':True, 'question_id':q['id'],
                'leg_from':'Ambon','leg_to':'Banda Neira','vehicle':'Pelni'})
        return response()


@pytest.mark.asyncio
async def test_banda_full_run_receipt_question_and_chart(db,house,client,banda,monkeypatch):
    provider=ScriptedProvider()
    fetcher=AsyncMock(side_effect=captured_page)
    broadcast=AsyncMock()
    receipt=await scout.run(house.pool,house.room,'banda-islands',provider=provider,fetcher=fetcher,
                            ctx=SimpleNamespace(broadcast=broadcast))
    assert receipt['status']=='done' and receipt['error'] is None,receipt
    assert receipt['pages_read']==3 and receipt['proposals']==1 and receipt['searches']==0
    assert receipt['input_tokens']==17*7 and receipt['output_tokens']==11*7
    assert [call.args[0] for call in fetcher.await_args_list].count(URL)==2
    base=f'/rooms/{house.room}/longway'
    rows=(await client.get(base+'/proposals')).json()
    assert len(rows)==1
    row=rows[0]
    assert row['support']==CLAIM+'.' and row['leg_from']=='Ambon' and row['leg_to']=='Banda Neira'
    assert row['question_id']==str(banda['id']) and row['question_text']==QUESTION
    assert row['run_id']==str(receipt['id']) and row['load_bearing'] and row['counter_searched_at']
    assert row['publisher_count']==1 and not row['requires_counter']
    queued=(await client.get(base+'/questions')).json()[0]
    assert queued['answered_by_proposal']==row['id'] and queued['answer_review']=='proposed'
    chart=(await client.get(base+'/chart')).json()
    assert chart['proposals']['banda-islands'][0]['id']==row['id']
    legs=next(j['segments'] for j in chart['journeys'] if j['slug']=='banda-islands')
    assert next(l for l in legs if l['from']=='Ambon' and l['to']=='Banda Neira')['proposed']
    message=await db.fetchrow("SELECT * FROM messages WHERE thread_id=$1 AND metadata ? 'longway_scout_run'",house.thread)
    assert message['speaker_type']=='llm_primary'
    assert message['metadata']['longway_scout_run']==dict(run_id=str(receipt['id']),journey='banda-islands',pages_read=3,proposals=1,counter_proposals=0)
    assert QUESTION in message['content'] and 'Status: done' in message['content']
    assert broadcast.await_count==1
    assert (await client.get(base+'/scout/runs')).json()[0]['id']==str(receipt['id'])
    assert 'log' not in (await client.get(base+'/scout/runs')).json()[0]
    assert [q['id'] for q in await questions.select_open(db,'banda-islands')]==[banda['id']]
    detail=(await client.get(base+f"/scout/runs/{receipt['id']}")).json()
    assert any(entry['tool']=='counter_complete' for entry in detail['log'])
    assert (await client.post(f"/rooms/{house.room}/field/marks/{row['field_mark_id']}/review",json={'action':'contest','note':'No October departure established'})).status_code==200
    chart=(await client.get(base+'/chart')).json()
    assert 'banda-islands' not in chart['proposals']
    assert not next(j for j in chart['journeys'] if j['slug']=='banda-islands')['segments'][0]['proposed']


@pytest.mark.asyncio
async def test_counter_phase_without_tool_activity_cannot_unlock(db,house,banda):
    receipt=await scout.run(house.pool,house.room,'banda-islands',provider=ScriptedProvider(counter=False),fetcher=captured_page)
    assert receipt['status']=='failed' and 'Counter-search did not use known_sources' in receipt['error']
    proposal=await db.fetchrow('SELECT * FROM longway_evidence_proposals WHERE run_id=$1',receipt['id'])
    assert proposal['counter_searched_at'] is None


@pytest.mark.asyncio
@pytest.mark.parametrize('budget,value,reason',[('PAGES','1','pages'),('OUTPUT_TOKENS','11','output_tokens')])
async def test_budgets_end_with_receipts(budget,value,reason,db,house,banda,monkeypatch):
    monkeypatch.setenv('LONGWAY_SCOUT_BUDGET_'+budget,value)
    receipt=await scout.run(house.pool,house.room,'banda-islands',provider=ScriptedProvider(),fetcher=captured_page)
    assert receipt['status']=='done' and receipt['error']==reason+' budget exhausted',receipt
    assert receipt['proposals']==0
    assert await db.fetchval("SELECT count(*) FROM messages WHERE thread_id=$1 AND metadata ? 'longway_scout_run'",house.thread)==1


@pytest.mark.asyncio
async def test_manual_start_conflict_kill_and_room_fence(db,house,client,banda,monkeypatch):
    await make_manager(db,house)
    monkeypatch.setattr(api,'_pool',house.pool)
    monkeypatch.setattr(api,'scout_context',lambda:SimpleNamespace(broadcast=None))
    entered=asyncio.Event()
    class Blocked:
        client=SimpleNamespace(aclose=AsyncMock())
        async def complete(self,request):
            entered.set()
            await asyncio.Event().wait()
    monkeypatch.setattr(scout,'AnthropicProvider',Blocked)
    base=f'/rooms/{house.room}/longway'
    response_=await client.post(base+'/scout',json={})
    assert response_.status_code==200,response_.text
    run_id=response_.json()['run_id']
    await asyncio.wait_for(entered.wait(),2)
    assert (await client.post(base+'/scout',json={})).status_code==409
    killed=await client.post(base+f'/scout/runs/{run_id}/kill')
    assert killed.status_code==200 and killed.json()['status']=='killed',killed.text
    assert (await client.post(base+f'/scout/runs/{run_id}/kill')).json()['status']=='killed'
    rows=await db.fetch("SELECT content FROM messages WHERE thread_id=$1 AND metadata ? 'longway_scout_run'",house.thread)
    assert len(rows)==1 and 'killed' in rows[0]['content']
    from uuid import uuid4
    assert (await client.get(base+f'/scout/runs/{uuid4()}')).status_code==404


@pytest.mark.asyncio
async def test_configured_search_is_metered_through_loop(db,house,banda,monkeypatch):
    import httpx
    from organs.longway import search
    monkeypatch.setenv('LONGWAY_SEARCH_PROVIDER','brave')
    monkeypatch.setenv('LONGWAY_SEARCH_KEY','not-logged')
    def transport(request):
        return httpx.Response(200,json={'web':{'results':[{'url':URL,'title':'Getting here','description':'Search snippet'}]}})
    http=httpx.AsyncClient(transport=httpx.MockTransport(transport))
    original=search.search
    async def canned(*args,**kwargs):
        return await original(*args,**kwargs,client=http)
    monkeypatch.setattr(search,'search',canned)
    class SearchProvider:
        count=0
        async def complete(self,request):
            assert 'search' in [t['name'] for t in request.tools]
            self.count+=1
            if self.count==1:
                return response('known_sources')
            if self.count==2:
                return response('search',{'query':'pelni ambon banda schedule','count':8})
            result=json.loads(request.messages[-1]['content'][0]['content'])['results'][0]
            assert await db.fetchval('SELECT url FROM longway_search_results WHERE id=$1',UUID(result['id']))==URL
            return response()
    try:
        receipt=await scout.run(house.pool,house.room,'banda-islands',provider=SearchProvider(),fetcher=captured_page)
    finally:
        await http.aclose()
    assert receipt['status']=='done' and receipt['searches']==1,receipt
    assert 'not-logged' not in str(receipt)
    assert any(e['tool']=='search' for e in receipt['log'])


@pytest.mark.asyncio
async def test_seconds_budget_and_provider_failure_post_receipts(db,house,banda,monkeypatch):
    monkeypatch.setenv('LONGWAY_SCOUT_BUDGET_SECONDS','1')
    class Slow:
        async def complete(self,request):
            await asyncio.Event().wait()
    receipt=await scout.run(house.pool,house.room,'banda-islands',provider=Slow())
    assert receipt['status']=='done' and receipt['error']=='seconds budget exhausted'
    class Failed:
        async def complete(self,request):
            raise RuntimeError('upstream test-secret unavailable')
    monkeypatch.setenv('ANTHROPIC_API_KEY','test-secret')
    failed=await scout.run(house.pool,house.room,'banda-islands',provider=Failed())
    assert failed['status']=='failed' and 'test-secret' not in failed['error']
    assert await db.fetchval("SELECT count(*) FROM messages WHERE thread_id=$1 AND metadata ? 'longway_scout_run'",house.thread)==2


@pytest.mark.asyncio
async def test_read_limit_and_thin_page_are_visible_to_model(db,house,banda):
    row=await scout.reserve(house.pool,house.room,'banda-islands')
    async def page(url):
        return {'content':'X'*13000,'site':'Operator','published':None}
    research=scout.Research(house.pool,row,page)
    result=await research.read_page({'url':URL})
    assert len(result['text'])==12000 and result['truncated'] and not result['thin']
    research.fetcher=captured_page
    thin=await research.read_page({'url':'https://www.pelni.co.id/reservasi-tiket'})
    assert thin['thin'] and 'timetable' not in thin['text']
    receipt=await scout.finish(house.pool,row['id'],'done')
    assert receipt['log'][0]['truncated'] and receipt['log'][1]['thin']


@pytest.mark.asyncio
async def test_manual_http_run_completes_with_fake_provider(db,house,client,banda,monkeypatch):
    await make_manager(db,house)
    monkeypatch.setattr(api,'_pool',house.pool)
    monkeypatch.setattr(api,'scout_context',lambda:SimpleNamespace(broadcast=None))
    model=ScriptedProvider()
    monkeypatch.setattr(scout,'AnthropicProvider',lambda:model)
    monkeypatch.setattr(scout.defuddle_client,'extract_article',captured_page)
    base=f'/rooms/{house.room}/longway'
    posted=await client.post(base+'/scout',json={'question_ids':[str(banda['id'])]})
    assert posted.status_code==200,posted.text
    run_id=UUID(posted.json()['run_id'])
    task=scout._TASKS.get(run_id)
    if task:
        await task
    receipt=(await client.get(base+f'/scout/runs/{run_id}')).json()
    assert receipt['status']=='done' and receipt['proposals']==1,receipt
    assert receipt['started_by']==str(house.user.user_id) and receipt['trigger']=='manual'
    model.client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_counter_findings_are_separate_proposals(db,house,banda):
    class Contrary(ScriptedProvider):
        async def complete(self,request):
            counter=len(request.messages)>1 and isinstance(request.messages[1]['content'],str)
            if counter and self.turns['counter']==2:
                self.turns['counter']+=1
                original=json.loads(request.messages[1]['content'].split('\n')[-1])
                return response('propose',dict(candidate='banda-islands',url=URL,
                    claim='schedules may change spontaneously',scope='schedule exceptions',load_bearing=True,
                    question_id=str(banda['id']),contradicts=original['id']))
            return await super().complete(request)
    receipt=await scout.run(house.pool,house.room,'banda-islands',provider=Contrary(),fetcher=captured_page)
    assert receipt['status']=='done' and receipt['proposals']==2 and receipt['counter_proposals']==1,receipt
    rows=await db.fetch('SELECT * FROM longway_evidence_proposals WHERE run_id=$1 ORDER BY created_at',receipt['id'])
    assert rows[1]['contradicts']==rows[0]['id'] and rows[0]['counter_searched_at']
    assert rows[1]['support']=='Around Christmas, New Year and Idul Fitri, schedules may change spontaneously.'


@pytest.mark.asyncio
async def test_nightly_run_can_be_killed_while_provider_is_pending(db,house,banda):
    entered=asyncio.Event()
    class Pending:
        async def complete(self,request):
            entered.set()
            await asyncio.Event().wait()
    task=asyncio.create_task(scout.run(house.pool,house.room,'banda-islands',trigger='nightly',provider=Pending()))
    await asyncio.wait_for(entered.wait(),2)
    run_id=await db.fetchval("SELECT id FROM longway_scout_runs WHERE room_id=$1 AND status='running'",house.room)
    receipt=await scout.kill(house.pool,house.room,run_id)
    assert receipt['status']=='killed'
    assert (await asyncio.wait_for(task,2))['status']=='killed'
