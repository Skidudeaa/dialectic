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
        self.counter_prompt=None
        self.client=SimpleNamespace(aclose=AsyncMock())

    async def complete(self, request):
        self.requests.append(request)
        assert request.model=='fake-scout-model' and request.effort=='high'
        assert 'You are the Scout' in request.system and 'untrusted evidence' in request.system
        assert {t['name'] for t in request.tools}=={'known_sources','read_page','propose','read_register'}
        counter=len(request.messages)>1 and isinstance(request.messages[1]['content'],str)
        phase='counter' if counter else 'research'
        if counter and request.messages[1]['content']!=self.counter_prompt:
            # Each load-bearing proposal gets its own counter phase; the script restarts per prompt.
            self.counter_prompt=request.messages[1]['content']
            self.turns['counter']=0
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
            # The live model named the candidate by its title; the run files under its own journey regardless.
            return response('propose',{'candidate':'Banda Islands','url':URL,'claim':CLAIM,
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
    # pages_read counts distinct pages: propose and the counter phase re-read from the run's cache.
    assert receipt['pages_read']==2 and receipt['proposals']==1 and receipt['searches']==0
    assert receipt['input_tokens']==17*7 and receipt['output_tokens']==11*7
    assert [call.args[0] for call in fetcher.await_args_list].count(URL)==1
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
    assert message['metadata']['longway_scout_run']==dict(run_id=str(receipt['id']),journey='banda-islands',pages_read=2,proposals=1,counter_proposals=0)
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
@pytest.mark.parametrize('budget,value,reason,filed',[('PAGES','1','pages',1),('OUTPUT_TOKENS','11','output_tokens',0)])
async def test_budgets_end_with_receipts(budget,value,reason,filed,db,house,banda,monkeypatch):
    monkeypatch.setenv('LONGWAY_SCOUT_BUDGET_'+budget,value)
    receipt=await scout.run(house.pool,house.room,'banda-islands',provider=ScriptedProvider(),fetcher=captured_page)
    assert receipt['status']=='done' and receipt['error']==reason+' budget exhausted',receipt
    # One page's budget still files the proposal from that page: proposing re-reads the cache, not the budget.
    assert receipt['proposals']==filed
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


@pytest.mark.asyncio
async def test_run_counter_searches_a_stranded_load_bearing_proposal(db,house,banda):
    """A load-bearing proposal filed by hand (or left by a budget-starved run) has no contrary search and
    cannot be confirmed; the next run performs it. Without the pickup its counter_searched_at stays null."""
    await proposals.propose(db,house.room,candidate='banda-islands',url=URL,scope='schedule, by hand',
        claim='Pelnis are the slowest, cheapest and most reliable option',
        load_bearing=True,proposed_by='human',user_id=house.user.user_id,fetcher=captured_page)
    stranded=await db.fetchrow('SELECT * FROM longway_evidence_proposals WHERE room_id=$1 AND run_id IS NULL',house.room)
    assert stranded['load_bearing'] and stranded['counter_searched_at'] is None
    receipt=await scout.run(house.pool,house.room,'banda-islands',provider=ScriptedProvider(),fetcher=captured_page)
    assert receipt['status']=='done' and receipt['error'] is None,receipt
    stamped=await db.fetch('SELECT id,run_id,counter_searched_at FROM longway_evidence_proposals WHERE room_id=$1 ORDER BY created_at',house.room)
    assert len(stamped)==2 and all(r['counter_searched_at'] for r in stamped)
    assert receipt['pages_read']==2  # the counter phases re-read from the run's cache


@pytest.mark.asyncio
async def test_confirming_the_answer_closes_the_question(db,house,client,banda):
    await scout.run(house.pool,house.room,'banda-islands',provider=ScriptedProvider(),fetcher=captured_page)
    base=f'/rooms/{house.room}/longway'
    row=(await client.get(base+'/proposals')).json()[0]
    assert row['question_id']==str(banda['id']) and not row['requires_counter']
    assert (await client.post(f"/rooms/{house.room}/field/marks/{row['field_mark_id']}/review",json={'action':'confirm'})).status_code==200
    assert await db.fetchval('SELECT closed_at FROM longway_questions WHERE id=$1',banda['id']) is not None
    assert (await client.get(base+'/questions')).json()==[]
    assert await questions.select_open(db,'banda-islands')==[]


class RefusingProvider(ScriptedProvider):
    """Proposes a claim the page does not contain before giving up."""
    async def complete(self, request):
        research=not (len(request.messages)>1 and isinstance(request.messages[1]['content'],str))
        if research and self.turns['research']==2:
            self.turns['research']+=1
            return response('propose',{'url':URL,'claim':'A ferry sails every Tuesday at dawn','scope':'schedule','load_bearing':True})
        return await super().complete(request)


@pytest.mark.asyncio
async def test_refused_proposals_are_logged_and_counted_in_the_receipt(db,house,banda):
    receipt=await scout.run(house.pool,house.room,'banda-islands',provider=RefusingProvider(),fetcher=captured_page)
    assert receipt['status']=='done' and receipt['proposals']==0,receipt
    refused=[e for e in receipt['log'] if e['tool']=='propose_refused']
    assert len(refused)==1 and refused[0]['claim']=='A ferry sails every Tuesday at dawn' and refused[0]['reason']
    content=await db.fetchval("SELECT content FROM messages WHERE thread_id=$1 AND metadata ? 'longway_scout_run'",house.thread)
    assert 'filed 0 proposals (1 refused by the passage gate)' in content


@pytest.mark.asyncio
async def test_propose_accepts_periods_names_bad_ids_and_refuses_duplicates(db,house,banda):
    """What the fourth live run sent: month and year dates, S-numbers as ids, and the same line six times."""
    first=await proposals.propose(db,house.room,candidate='banda-islands',url=URL,claim=CLAIM,scope='schedule',
        applies_from='2024-02',applies_to='2024',fetcher=captured_page)
    assert first['filed']
    row=await db.fetchrow('SELECT applies_from,applies_to FROM longway_evidence_proposals WHERE id=$1',UUID(first['id']))
    assert row['applies_from'].isoformat()=='2024-02-01' and row['applies_to'].isoformat()=='2024-12-31'
    again=await proposals.propose(db,house.room,candidate='banda-islands',url=URL,claim=CLAIM.upper()+'.',scope='schedule',fetcher=captured_page)
    assert not again['filed'] and again['id']==first['id'] and 'contradicts='+first['id'] in again['why']
    assert await db.fetchval('SELECT count(*) FROM longway_evidence_proposals WHERE room_id=$1',house.room)==1
    with pytest.raises(ValueError,match='contradicts must be the id'):
        await proposals.propose(db,house.room,candidate='banda-islands',url=URL,claim=CLAIM,scope='x',contradicts='S14',fetcher=captured_page)


def test_context_trim_keeps_fresh_and_recent_pages(monkeypatch):
    """Old page bodies shrink in place before the next model call; unseen and recent ones stay whole."""
    monkeypatch.setenv('LONGWAY_SEARCH_PROVIDER','none')
    research=scout.Research(None,{'id':None,'journey':'banda-islands','room_id':None})
    blocks=[{'type':'tool_result','tool_use_id':str(i),'content':json.dumps({'text':'x'*100})} for i in range(7)]
    for i,block in enumerate(blocks[:6]):
        research.remember('read_page',f'https://p/{i}',block)
    research.trim()                      # all six unseen: untouched
    assert all('trimmed' not in b['content'] for b in blocks[:6])
    research.remember('read_page','https://p/6',blocks[6])
    research.trim()                      # six seen pages: the oldest two shrink, the fresh seventh stays
    assert ['trimmed' in b['content'] for b in blocks]==[True,True,False,False,False,False,False]
    assert 'https://p/0' in json.loads(blocks[0]['content'])['trimmed']
    research.remember('propose',None,{'content':'kept'})
    assert len(research.context)==7      # only the tools in CONTEXT_KEEP are remembered


@pytest.mark.asyncio
async def test_thin_pages_are_rendered_when_firecrawl_is_configured(db,house,banda,monkeypatch):
    PELNI='https://www.pelni.co.id/reservasi-tiket'
    row=await scout.reserve(house.pool,house.room,'banda-islands')
    rendered=AsyncMock(return_value={'content':'Jadwal kapal: KM Pangrango Ambon - Banda Neira. '*40,'site':'www.pelni.co.id','published':None,'reader':'firecrawl'})
    monkeypatch.delenv('LONGWAY_FIRECRAWL_KEY',raising=False)
    page=await scout.Research(house.pool,row,fetcher=captured_page,renderer=rendered).read_page({'url':PELNI})
    assert page['thin'] and rendered.await_count==0
    monkeypatch.setenv('LONGWAY_FIRECRAWL_KEY','fc-test')
    page=await scout.Research(house.pool,row,fetcher=captured_page,renderer=rendered).read_page({'url':PELNI})
    assert not page['thin'] and 'Pangrango' in page['text'] and page['site']=='www.pelni.co.id'
    assert rendered.await_args.args==(PELNI,'fc-test')
    failing=AsyncMock(side_effect=RuntimeError('boom'))
    page=await scout.Research(house.pool,row,fetcher=captured_page,renderer=failing).read_page({'url':PELNI})
    assert page['thin'] and 'booking application' in page['text']
    log=await db.fetchval('SELECT log FROM longway_scout_runs WHERE id=$1',row['id'])
    readers=[e.get('reader') for e in log if e['tool']=='read_page']
    assert readers==['defuddle','firecrawl','defuddle'] and any(e['tool']=='render' and e['error']=='RuntimeError' for e in log)
    assert not any('fc-test' in json.dumps(e) for e in log)
