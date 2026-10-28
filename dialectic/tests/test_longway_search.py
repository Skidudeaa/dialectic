"""Canned provider protocols, with real stored provenance before tool return."""
import json

import httpx
import pytest
from organs.longway import search, scout
from tests.test_longway_api import db,house
from tests.test_longway_register import longway_repo


@pytest.mark.asyncio
@pytest.mark.parametrize('provider',['brave','exa'])
async def test_search_protocol_and_durable_results(provider,db,house,longway_repo,monkeypatch):
    monkeypatch.setenv('LONGWAY_SEARCH_PROVIDER',provider)
    monkeypatch.setenv('LONGWAY_SEARCH_KEY','test-secret')
    row=await scout.reserve(house.pool,house.room,'ogasawara')
    def transport(request):
        if provider=='brave':
            assert request.method=='GET' and request.headers['X-Subscription-Token']=='test-secret'
            assert request.url.params['q']=='pelni ambon banda schedule' and request.url.params['count']=='8'
            return httpx.Response(200,json={'web':{'results':[{'url':'https://example.org/timetable','title':'Timetable','description':'A snippet'}]}})
        assert request.method=='POST' and request.headers['x-api-key']=='test-secret'
        body=json.loads(request.content)
        assert body['query']=='pelni ambon banda schedule' and body['numResults']==8 and body['type']=='auto'
        return httpx.Response(200,json={'results':[{'url':'https://example.org/timetable','title':'Timetable','highlights':['A snippet']}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        result=await search.search(db,row['id'],'pelni ambon banda schedule',client=client)
    stored=await db.fetch('SELECT * FROM longway_search_results WHERE run_id=$1',row['id'])
    assert len(stored)==len(result)==1
    assert str(stored[0]['id'])==result[0]['id'] and stored[0]['snippet']=='A snippet'
    assert stored[0]['rank']==1 and stored[0]['provider']==provider
    assert await db.fetchval('SELECT searches FROM longway_scout_runs WHERE id=$1',row['id'])==1
    assert 'test-secret' not in str(dict(stored[0]))


def test_startup_configuration_and_tool_absence(monkeypatch):
    monkeypatch.delenv('LONGWAY_SEARCH_KEY',raising=False)
    monkeypatch.setenv('LONGWAY_SEARCH_PROVIDER','brave')
    from organs.longway import startup
    with pytest.raises(RuntimeError,match='LONGWAY_SEARCH_KEY'):
        startup(None)
    monkeypatch.setenv('LONGWAY_SEARCH_PROVIDER','none')
    registry=scout.Research(None,{}).registry()
    assert set(registry.names())=={'known_sources','read_page','propose','read_register'}
    monkeypatch.setenv('LONGWAY_SEARCH_PROVIDER','exa')
    monkeypatch.setenv('LONGWAY_SEARCH_KEY','secret')
    assert 'search' in scout.Research(None,{}).registry().names()
