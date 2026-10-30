"""Ride contract: recorded upstream shape, real leg + backfill, HTTP, Postgres and git.

The Amtraker fixture is synthetic from the supplied 29 Oct feed schema, not a
claim of a live capture. All repository writes occur in the temporary fixture.
"""
import copy
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

from organs.longway import observe, fixes, rides, jobs, ride_watch
from organs.longway.register import CommitsDisabled
from organs.longway.tools import build_tools
from scheduler import SchedulerContext
from tests.conftest import make_room
from tests.test_longway_register import longway_repo, SOURCE, git
from tests.test_longway_api import db as base_db, house, client

NOW = datetime(2026, 10, 30, 3, tzinfo=timezone.utc)
SLUG = 'coast-starlight-2026'
REAL_HISTORY, REAL_TRAINS, REAL_FETCH = observe.history, observe.trains, fixes.fetch_feed


async def own_home(db):
    """This test's own Home room. A shared dialectic_test may already hold one and the schema allows a single Home, so
    any other is demoted inside the test's transaction, which the db fixture rolls back."""
    await db.execute("UPDATE rooms SET is_home=false WHERE is_home")
    home = uuid4()
    await db.execute("INSERT INTO rooms(id,created_at,token,name,is_home) VALUES ($1,now(),$2,'Home',true)", home, str(home))
    return home


@pytest.fixture
def sample():
    return json.loads((Path(__file__).parent/'fixtures/longway_amtraker.json').read_text())


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(observe, 'history', AsyncMock(return_value={'days': 0, 'at': {}}))
    monkeypatch.setattr(observe, 'trains', AsyncMock(return_value=[]))
    monkeypatch.setattr(fixes, 'fetch_feed', AsyncMock(return_value={'fixes': {}}))
    from api.notifications import webpush
    recorder = AsyncMock(return_value={'sent': 1, 'errors': []})
    monkeypatch.setattr(webpush, 'send_web_notifications', recorder)
    return recorder


@pytest_asyncio.fixture
async def db(base_db):
    await base_db.execute((Path(__file__).resolve().parents[1]/'migrations/032_longway_rides.sql').read_text())
    return base_db


@pytest.fixture
def real_repo(longway_repo):
    for relative in (f'trips/{SLUG}', 'legs/amtrak-313-14'):
        shutil.copytree(SOURCE/relative, longway_repo.root/relative)
    git(longway_repo.root, 'add', '.')
    git(longway_repo.root, 'commit', '-qm', 'Real ride fixture')
    return longway_repo


@pytest.fixture
def live_repo(real_repo):
    path = real_repo.root/f'trips/{SLUG}/record.json'
    data = json.loads(path.read_text())
    data['rides'][0].update(id='14-29', date='2026-10-29', riders=['aLiCe'])
    path.write_text(json.dumps(data))
    return real_repo


async def bind(db, house):
    await db.execute('UPDATE rooms SET linked_journey=$2 WHERE id=$1', house.room, SLUG)


@pytest.mark.asyncio
async def test_broadcast_parsing_and_chart_privacy(sample, monkeypatch):
    monkeypatch.setattr(observe, 'trains', AsyncMock(return_value=sample['14']))
    run = sample['14'][0]
    fix = observe.train_fix(run, NOW)
    assert fix == dict(lat=42.4946, lon=-121.8795, at='2026-10-30T02:55:00Z', age_min=5, speed_mph=40, heading='N', source='amtrak')
    newer = dict(run, trainID='14-30', lastValTS='2026-10-30T02:59:00Z', lat=43)
    monkeypatch.setattr(observe, 'trains', AsyncMock(return_value=[newer, run]))
    chart = await fixes.overlay({'vehicles': [{'name': 'Coast Starlight 14', 'amtrak': '14'}]}, NOW)
    vehicle = chart['vehicles'][0]
    assert vehicle['heard'] and vehicle['fix']['lat'] == 43
    assert vehicle['fix']['at'] == '2026-10-30T02:59:00Z'
    assert not {'run', 'riders', 'ride'} & vehicle.keys()
    for bad in (None, 'not-a-time', '2026-10-30T02:55:00'):
        assert observe.train_fix(dict(run, lastValTS=bad), NOW) is None
    assert observe.train_fix(dict(run, lat=float('nan')), NOW) is None


def test_matching_projection_and_actual_guards(sample, real_repo):
    ride = dict(real_repo.ride(SLUG)['rides'][0], date='2026-10-29')
    run = sample['14'][0]
    assert observe.run_for(sample['14'], ride) is run
    assert observe.run_for(sample['14'], dict(ride, date='2026-09-29')) is None
    assert observe.run_for([dict(run, trainID='14-28')], ride) is None
    leg = {'sights': {'km': [[0,0,0,40,-120,'',''], [10,0,0,40,-119,'','']]}}
    assert observe.project(40, -119.5, leg) == 5
    assert observe.project(40, -121, leg) == 0
    assert observe.project(40, -118, leg) == 10
    assert observe.project(40, -119, None) is None
    station = dict(status='Enroute', arr='2026-10-30T02:00:00Z', dep='2026-10-30T02:05:00Z')
    assert observe.actual(station, 'arr', NOW) is None
    station['status'] = 'Station'
    assert observe.actual(station, 'arr', NOW) == station['arr']
    assert observe.actual(station, 'dep', NOW) is None
    assert observe.actual(dict(station, arr='2026-11-01T00:00:00Z'), 'arr', NOW) is None


@pytest.mark.asyncio
async def test_real_book_api_tools_and_fences(db, house, client, real_repo, sample, monkeypatch):
    await bind(db, house)
    url = f'/rooms/{house.room}/longway'
    response = await client.get(url+'/ride')
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['ride']['id'] == '14-22' and data['ride']['state'] == 'arrived'
    assert data['run'] == '14-22' and data['ride']['leg_ready']
    assert data['fix'] is None and data['track'] == []
    assert len(data['stops']) == 18
    assert (data['stops'][0]['code'], data['stops'][0]['km']) == ('MTZ', 0)
    assert (data['stops'][-1]['code'], data['stops'][-1]['km']) == ('SEA', 1412.4)
    assert next(s for s in data['stops'] if s['code']=='KFS')['late_min'] == 101
    assert all(s['estimated'] is False and s['status'] is None for s in data['stops'])
    assert (await client.get(url+'/ride?ride=absent')).status_code == 404
    model = await client.get(url+'/ride/leg?leg=amtrak-313-14')
    assert model.status_code == 200
    assert model.headers['cache-control'] == 'private, max-age=86400' and model.headers['etag']
    assert 'strips' not in model.json()['coverage']
    shutil.copytree(real_repo.root/'legs/amtrak-313-14', real_repo.root/'legs/amtrak-313-99')
    assert (await client.get(url+'/ride/leg?leg=amtrak-313-99')).status_code == 404
    assert (await client.get(url+'/ride/leg?leg=other')).status_code == 404
    assert (await client.get(url+'/riding')).json() == {'rides': []}
    tools = {t.name: t for t in build_tools(make_room(id=house.room), db)}
    result = await tools['out_the_window'].execute({'km':635, 'side':'left'})
    lake = next(s for s in result['sights'] if s['name']=='Upper Klamath Lake')
    assert result['provenance']=='model' and "Don't miss" in lake['class']
    assert lake['guide']['what'] and lake['guide']['history'] and lake['guide']['links']
    assert 'arrived' in (await tools['out_the_window'].execute({}))['error']
    assert (await tools['ride_status'].execute({}))['ride']['id']=='14-22'
    home = await own_home(db)
    await db.execute('INSERT INTO room_memberships(room_id,user_id,joined_at) VALUES ($1,$2,now())',home,house.user.user_id)
    monkeypatch.setattr(observe,'trains',AsyncMock(return_value=sample['14']))
    chart=(await client.get(f'/rooms/{home}/longway/chart',headers={'X-Room-Token':str(home)})).json()
    vehicle=next(v for v in chart['vehicles'] if v['name']=='Coast Starlight 14')
    assert vehicle['heard'] and vehicle['fix']['at']=='2026-10-30T02:55:00Z'
    serialized=json.dumps(chart)
    assert '"riders"' not in serialized and '"ride"' not in serialized and '"run"' not in serialized
    assert '14-22' not in serialized
    assert next(j for j in chart['journeys'] if j['slug']==SLUG)['rides']==1
    for slug in ('ogasawara','private-trip','friends-2027'):
        await db.execute('UPDATE rooms SET linked_journey=$2 WHERE id=$1', house.room, slug)
        assert (await client.get(url+'/ride')).status_code == 404
    await bind(db, house)
    await db.execute('DELETE FROM room_memberships WHERE room_id=$1', house.room)
    assert (await client.get(url+'/ride')).status_code == 404
    assert (await client.get(url+'/ride/leg?leg=amtrak-313-14')).status_code == 404


@pytest.mark.asyncio
async def test_watch_transitions_broadcast_dedupe_and_riding_fence(db, house, client, live_repo, sample, monkeypatch, offline):
    await bind(db, house)
    ctx = SchedulerContext(house.pool)
    feed = AsyncMock(return_value=[])
    monkeypatch.setattr(observe, 'trains', feed)
    await jobs.ride_watch(ctx, now=NOW)
    assert await db.fetchval('SELECT state FROM longway_rides WHERE ride_id=$1','14-29') == 'waiting'
    feed.return_value = sample['14']
    sample['14'][0]['stations'][1]['status'] = 'Station'
    await jobs.ride_watch(ctx, now=NOW)
    assert await db.fetchval('SELECT state FROM longway_rides WHERE ride_id=$1','14-29') == 'waiting'
    assert not any(c.kwargs['body']=='departed MTZ' for c in offline.call_args_list)
    sample['14'][0]['stations'][1]['status'] = 'Departed'
    for _ in range(2):
        await jobs.ride_watch(ctx, now=NOW)
    assert await db.fetchval('SELECT state FROM longway_rides WHERE ride_id=$1','14-29') == 'riding'
    assert await db.fetchval('SELECT count(*) FROM longway_ride_fixes') == 1
    assert [c.kwargs['body'] for c in offline.call_args_list].count('departed MTZ') == 1
    response = await client.get(f'/rooms/{house.room}/longway/riding')
    assert response.status_code == 200
    assert response.json()['rides'][0]['ride']['state'] == 'riding'
    other = uuid4()
    await db.execute("INSERT INTO rooms(id,created_at,token,name,linked_journey) VALUES ($1,now(),$2,'Private ride',$3)", other,str(other),SLUG)
    outsider=uuid4()
    await db.execute("INSERT INTO users(id,created_at,display_name) VALUES ($1,now(),'Outside rider')",outsider)
    await db.execute('INSERT INTO room_memberships(room_id,user_id,joined_at) VALUES ($1,$2,now())',other,outsider)
    assert all(r['room_id']!=str(other) for r in (await client.get(f'/rooms/{house.room}/longway/riding')).json()['rides'])
    # Estimates in the past cannot arrive a ride; the station status is required.
    sample['14'][0]['stations'][-1]['arr'] = '2026-10-30T02:58:00Z'
    await jobs.ride_watch(ctx, now=NOW)
    assert await db.fetchval('SELECT state FROM longway_rides WHERE ride_id=$1','14-29') == 'riding'
    sample['14'][0]['stations'][-1]['status'] = 'Station'
    sample['14'][0]['lastValTS'] = '2026-10-30T02:59:00Z'
    await jobs.ride_watch(ctx, now=NOW)
    await jobs.ride_watch(ctx, now=NOW)
    assert await db.fetchval('SELECT state FROM longway_rides WHERE ride_id=$1','14-29') == 'arrived'
    assert await db.fetchval('SELECT count(*) FROM longway_ride_fixes') == 2
    for recipient in (house.user.user_id, outsider):
        assert sum(c.kwargs['body']=='arrived SEA' and str(recipient) in c.kwargs['recipient_user_ids']
                   for c in offline.call_args_list)==1
    assert (await client.get(f'/rooms/{house.room}/longway/riding')).json() == {'rides': []}
    arrived = (await client.get(f'/rooms/{house.room}/longway/ride')).json()
    assert arrived['fix'] is None
    assert all(not s['estimated'] and s['status'] is None for s in arrived['stops'])


@pytest.mark.asyncio
async def test_gap_riders_only_and_once(db, house, live_repo, sample, monkeypatch, offline):
    await bind(db, house)
    follower = uuid4()
    await db.execute("INSERT INTO users(id,created_at,display_name) VALUES ($1,now(),'Follower')", follower)
    await db.execute('INSERT INTO room_memberships(room_id,user_id,joined_at) VALUES ($1,$2,now())',house.room,follower)
    monkeypatch.setattr(observe, 'trains', AsyncMock(return_value=sample['14']))
    original = live_repo.leg
    def leg(name):
        data = original(name)
        data['coverage']={'gaps':[{'km0':637,'km1':642,'minutes':8,'near':'Lake'}]}
        return data
    monkeypatch.setattr(live_repo, 'leg', leg)
    from organs.longway import register
    monkeypatch.setattr(register, 'get_register', lambda:live_repo)
    monkeypatch.setattr(ride_watch, 'get_register', lambda:live_repo)
    for _ in range(2):
        await jobs.ride_watch(SchedulerContext(house.pool), now=NOW)
    gaps = [c.kwargs for c in offline.call_args_list if 'Signal gap' in c.kwargs['body']]
    assert len(gaps) == 1
    assert gaps[0]['recipient_user_ids'] == [str(house.user.user_id)]
    departed = next(c.kwargs for c in offline.call_args_list if c.kwargs['body']=='departed MTZ')
    assert set(departed['recipient_user_ids']) == {str(house.user.user_id),str(follower)}


@pytest.mark.asyncio
async def test_logbook_delay_author_actuals_notes_and_git(db, house, live_repo, sample, monkeypatch, offline):
    await bind(db, house)
    home = await own_home(db)
    await db.execute('INSERT INTO room_memberships(room_id,user_id,joined_at) VALUES ($1,$2,now())',home,house.user.user_id)
    follower = uuid4()
    await db.execute("INSERT INTO users(id,created_at,display_name) VALUES ($1,now(),'Follower')", follower)
    for i,(uid,speaker,at,deleted,text) in enumerate([
        (house.user.user_id,'human',NOW-timedelta(hours=1),False,'lake note'),
        (follower,'human',NOW-timedelta(hours=1),False,'follower private'),
        (house.user.user_id,'llm_primary',NOW-timedelta(hours=1),False,'model text'),
        (house.user.user_id,'human',NOW-timedelta(hours=1),True,'deleted'),
        (house.user.user_id,'human',NOW-timedelta(days=2),False,'before ride'),
        (house.user.user_id,'human',NOW+timedelta(hours=1),False,'after ride')]):
        await db.execute('''INSERT INTO messages(id,thread_id,sequence,created_at,speaker_type,user_id,message_type,content,is_deleted)
            VALUES ($1,$2,$3,$4,$5,$6,'text',$7,$8)''',uuid4(),house.thread,i,at,speaker,uid,text,deleted)
    other_room,other_thread=uuid4(),uuid4()
    await db.execute("INSERT INTO rooms(id,created_at,token,name) VALUES ($1,now(),$2,'Unbound')",other_room,str(other_room))
    await db.execute("INSERT INTO threads(id,room_id,created_at,title) VALUES ($1,$2,now(),'Main')",other_thread,other_room)
    await db.execute("INSERT INTO messages(id,thread_id,sequence,created_at,speaker_type,user_id,message_type,content) VALUES ($1,$2,1,$3,'human',$4,'text','other room private')",uuid4(),other_thread,NOW-timedelta(hours=1),house.user.user_id)
    run=sample['14'][0]
    run['stations'][-1].update(status='Station', arr='2026-10-30T02:58:00Z',dep='2026-10-30T04:00:00Z')
    monkeypatch.setattr(observe,'trains',AsyncMock(return_value=[run]))
    ctx=SchedulerContext(house.pool)
    monkeypatch.setenv('LONGWAY_COMMIT_ENABLED','1')
    await jobs.ride_watch(ctx,now=NOW)
    path=live_repo.root/f'trips/{SLUG}/rides/14-29.json'
    assert not path.exists()
    monkeypatch.setenv('LONGWAY_COMMIT_ENABLED','0')
    await jobs.ride_watch(ctx,now=NOW+timedelta(hours=7))
    assert not path.exists()
    # Feed gone: persisted stations must suffice, and estimates must stay out.
    monkeypatch.setattr(observe,'trains',AsyncMock(return_value=[]))
    unrelated=live_repo.root/'unrelated.txt'; unrelated.write_text('keep staged')
    git(live_repo.root,'add','unrelated.txt')
    monkeypatch.setenv('LONGWAY_COMMIT_ENABLED','1')
    await jobs.ride_watch(ctx,now=NOW+timedelta(hours=7))
    assert path.exists()
    book=json.loads(path.read_text())
    assert [n['text'] for n in book['notes']] == ['lake note']
    assert book['stops'][-1]['arr']=='2026-10-30T02:58:00Z' and book['stops'][-1]['dep'] is None
    assert book['written_by']=='house' and len(book['track'])==1
    assert git(live_repo.root,'log','-1','--format=%an <%ae>') == f'Alice <{house.user.email}>'
    assert f'Longway-Ride: {SLUG}/14-29' in git(live_repo.root,'log','-1','--format=%B')
    assert git(live_repo.root,'show','--format=','--name-only','HEAD') == f'trips/{SLUG}/rides/14-29.json'
    assert git(live_repo.root,'diff','--cached','--name-only') == 'unrelated.txt'
    before=git(live_repo.root,'rev-parse','HEAD')
    await jobs.ride_watch(ctx,now=NOW+timedelta(hours=8))
    assert git(live_repo.root,'rev-parse','HEAD') == before


def test_write_door_guards(live_repo,monkeypatch):
    book={'trip':SLUG,'ride':'14-29'}
    monkeypatch.setenv('LONGWAY_COMMIT_ENABLED','0')
    with pytest.raises(CommitsDisabled):
        live_repo.write_logbook(SLUG,'14-29',book,'Alice','alice@example.org')
    monkeypatch.setenv('LONGWAY_COMMIT_ENABLED','1')
    with pytest.raises(KeyError):
        live_repo.write_logbook(SLUG,'not-a-ride',book,'Alice','alice@example.org')
    with pytest.raises(ValueError):
        live_repo.write_logbook(SLUG,'14-29',dict(book,trip='other'),'Alice','alice@example.org')
    with pytest.raises(ValueError):
        live_repo.write_logbook(SLUG,'14-29',book,'Alice\nInjected','alice@example.org')
    path=live_repo.root/f'trips/{SLUG}/rides/14-29.json'
    path.write_text('uncommitted human logbook')
    with pytest.raises(RuntimeError,match='dirty logbook'):
        live_repo.write_logbook(SLUG,'14-29',book,'Alice','alice@example.org')
    assert path.read_text()=='uncommitted human logbook'
    git(live_repo.root,'add',str(path.relative_to(live_repo.root)))
    git(live_repo.root,'commit','-qm','Human logbook')
    before=git(live_repo.root,'rev-parse','HEAD')
    assert live_repo.write_logbook(SLUG,'14-29',book,'Alice','alice@example.org') == {'existing':True}
    assert path.read_text()=='uncommitted human logbook'
    assert git(live_repo.root,'rev-parse','HEAD')==before


def test_ship_dates_selection_and_track():
    ship=dict(date='2026-10-29',vehicle={'mmsi':'431347000'})
    assert rides.state_for(ship,{},None,None,NOW-timedelta(days=2))[0]=='waiting'
    assert rides.state_for(ship,{},None,None,NOW)[0]=='riding'
    assert rides.state_for(ship,{},None,None,NOW+timedelta(days=1))[0]=='riding'
    assert rides.state_for(ship,{},None,None,NOW+timedelta(days=2))[0]=='arrived'
    items=[dict(id='a',date='2026-10-28',state='arrived'),dict(id='b',date='2026-10-30',state='waiting'),dict(id='c',date='2026-10-29',state='riding')]
    assert rides.pick(items)['id']=='c'
    assert rides.pick(items[:2])['id']=='b'
    assert rides.pick(items,'a')['id']=='a'
    rows=[dict(at=NOW+timedelta(minutes=i),lat=40,lon=-120,km=km) for i,km in enumerate([1.1,1.2,2.1])]
    assert len(ride_watch.track_points(rows))==2
    track=[[observe.iso(r['at']),r['lat'],r['lon'],r['km']] for r in rows]
    assert ride_watch.interpolate(NOW+timedelta(seconds=90),track)==1.65
    assert ride_watch.interpolate(NOW-timedelta(seconds=1),track) is None


@pytest.mark.asyncio
async def test_history_45_days_five_concurrent_actual_only(monkeypatch):
    requests=[]; active=0; peak=0
    class Client:
        def __init__(self, **kwargs):
            assert kwargs['headers']['User-Agent']=='Mozilla/5.0'
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def get(self,url):
            nonlocal active,peak
            import asyncio
            active+=1; peak=max(peak,active); requests.append(url)
            await asyncio.sleep(0)
            active-=1
            return httpx.Response(200,request=httpx.Request('GET',url),json={'stops':[
                {'code':'KFS','arrive':{'type':'ACTUAL','variance':-6060}},
                {'code':'SEA','arrive':{'type':'ESTIMATED','variance':-3600}}]})
    monkeypatch.setattr(observe.httpx,'AsyncClient',Client)
    result=await observe._history('14',NOW.astimezone(observe.CHICAGO).date())
    assert len(requests)==45 and peak==5
    assert requests[0].endswith('/2026/10/28/A/14') and requests[-1].endswith('/2026/09/14/A/14')
    assert result=={'days':45,'at':{'KFS':{'median':101,'worst':101,'n':45}}}


@pytest.mark.asyncio
async def test_watch_date_window_and_riding_continuation(db,house,live_repo,sample,monkeypatch):
    await bind(db,house)
    feed=AsyncMock(return_value=[])
    monkeypatch.setattr(observe,'trains',feed)
    ctx=SchedulerContext(house.pool)
    await jobs.ride_watch(ctx,now=NOW-timedelta(days=4))
    feed.assert_not_awaited()
    await jobs.ride_watch(ctx,now=NOW+timedelta(days=2))
    feed.assert_not_awaited()
    await db.execute("UPDATE longway_rides SET state='riding' WHERE ride_id='14-29'")
    await jobs.ride_watch(ctx,now=NOW+timedelta(days=4))
    feed.assert_awaited_once()


@pytest.mark.asyncio
async def test_gap_needs_riding_fresh_forward_position(db,house,live_repo,offline):
    await bind(db,house)
    ride=live_repo.ride(SLUG)['rides'][0]
    leg={'coverage':{'gaps':[{'km0':637,'km1':640,'minutes':8}]}}
    row={'state':'riding','departed_at':None,'arrived_at':None,'departed_pushed':True,'arrived_pushed':True,'warned_gaps':[]}
    fix={'age_min':1,'speed_mph':40}
    for changes,position,at in [({'state':'waiting'},fix,635), ({},dict(fix,age_min=11),635),
                               ({},dict(fix,speed_mph=0),635), ({},fix,600), ({},fix,638)]:
        await ride_watch.notifications(db,SLUG,ride,dict(row,**changes),leg,position,at)
    offline.assert_not_awaited()


@pytest.mark.asyncio
async def test_ship_observation_without_leg_keeps_track(monkeypatch):
    monkeypatch.setattr(fixes,'fetch_feed',AsyncMock(return_value={'fixes':{'123':{
        'lat':40,'lon':-120,'fix':'2026-10-30T02:55:00Z','sog':10,'heading':90}}}))
    run,fix=await rides.observation({'vehicle':{'mmsi':'123'}},NOW)
    assert run is None and fix['source']=='ais' and fix['speed_mph']==pytest.approx(11.50779)
    points=ride_watch.track_points([dict(at=NOW,lat=40,lon=-120,km=None),
                                   dict(at=NOW+timedelta(minutes=1),lat=40.1,lon=-120,km=None)])
    assert len(points)==2 and all(p[3] is None for p in points)


def test_window_side_distance_and_check(real_repo):
    leg=real_repo.leg('amtrak-313-14')
    leg['check']={'score':{'agree':12,'total':13}}
    result=rides.window(leg,635,'left')
    assert result['check']['score']=={'agree':12,'total':13}
    assert all(s['side']=='left' and s['distance_km']<=2 for s in result['sights'])
    assert not rides.window(leg,-100,'both')['sights']
    with pytest.raises(ValueError):
        rides.window(leg,635,'back')


@pytest.mark.asyncio
async def test_no_house_author_and_disabled_job_do_not_call_write_door(db,house,live_repo,monkeypatch):
    await bind(db,house)
    ride=live_repo.ride(SLUG)['rides'][0]
    row={'state':'arrived','arrived_at':NOW-timedelta(hours=7),'logbook_written_at':None}
    write=AsyncMock()
    monkeypatch.setattr(live_repo,'write_logbook',write)
    monkeypatch.setenv('LONGWAY_COMMIT_ENABLED','0')
    await ride_watch.write_book(db,live_repo,SLUG,ride,row,None,NOW)
    write.assert_not_called()
    monkeypatch.setenv('LONGWAY_COMMIT_ENABLED','1')
    # Alice is a member of a ride room but has no house membership.
    await ride_watch.write_book(db,live_repo,SLUG,ride,row,None,NOW)
    write.assert_not_called()


@pytest.mark.asyncio
async def test_feed_cache_number_and_plain_agent(sample,monkeypatch):
    calls=[]
    class Client:
        def __init__(self,**kwargs):
            assert kwargs['headers']=={'User-Agent':'Mozilla/5.0'}
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def get(self,url):
            calls.append(url)
            return httpx.Response(200,request=httpx.Request('GET',url),json=sample)
    monkeypatch.setattr(fixes.httpx,'AsyncClient',Client)
    monkeypatch.setattr(observe,'fetch_feed',REAL_FETCH)
    monkeypatch.setattr(fixes,'_cache',{})
    for _ in range(2):
        assert (await REAL_TRAINS('14'))[0]['trainID']=='14-29'
    assert calls==['https://api-v3.amtraker.com/v3/trains/14']
    with pytest.raises(ValueError):
        await REAL_TRAINS('../private')


@pytest.mark.asyncio
async def test_history_singleflight_chicago_day(monkeypatch):
    import asyncio
    monkeypatch.setattr(observe,'_history_cache',{})
    monkeypatch.setattr(observe,'_history_tasks',{})
    loader=AsyncMock(return_value={'days':1,'at':{}})
    monkeypatch.setattr(observe,'_history',loader)
    first,second=await asyncio.gather(REAL_HISTORY('14',NOW),REAL_HISTORY('14',NOW))
    assert first==second=={'days':1,'at':{}}
    assert loader.await_count==1
    # UTC midnight is not the Chicago cache boundary.
    await REAL_HISTORY('14',NOW-timedelta(hours=4))
    assert loader.await_count==1
    await REAL_HISTORY('14',NOW+timedelta(hours=3))
    assert loader.await_count==2


@pytest.mark.asyncio
async def test_existing_book_does_not_abandon_pending_push(db,house,real_repo,offline):
    await bind(db,house)
    await db.execute('''INSERT INTO longway_rides(trip_slug,ride_id,state,arrived_at,departed_pushed)
        VALUES ($1,'14-22','arrived',$2,true)''',SLUG,NOW-timedelta(days=6))
    ctx=SchedulerContext(house.pool)
    offline.return_value={'sent':0,'errors':['vapid_unconfigured']}
    await jobs.ride_watch(ctx,now=NOW)
    assert not await db.fetchval("SELECT arrived_pushed FROM longway_rides WHERE ride_id='14-22'")
    offline.return_value={'sent':1,'errors':[]}
    await jobs.ride_watch(ctx,now=NOW)
    assert await db.fetchval("SELECT arrived_pushed FROM longway_rides WHERE ride_id='14-22'")
    assert offline.await_count==2
    await jobs.ride_watch(ctx,now=NOW)
    assert offline.await_count==2
