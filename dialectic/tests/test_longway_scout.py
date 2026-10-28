"""Load-bearing gates; removing any gate changes the asserted product outcome."""
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from organs.longway import proposals,scout,jobs
from tests.test_longway_api import db,house,client
from tests.test_longway_register import longway_repo


@pytest.mark.asyncio
async def test_whole_sentence_gate_rejects_navigation_and_overlong_context(db,house,longway_repo,monkeypatch):
    args=(db,house.room,'ogasawara','https://example.org/ferry','The ferry sails weekly','Tokyo')
    extract=AsyncMock(return_value={'content':'## The ferry sails weekly','site':'Operator'})
    monkeypatch.setattr(proposals.defuddle_client,'extract_article',extract)
    assert not (await proposals.propose(*args))['filed']
    extract.return_value={'content':'The ferry sails weekly '+ 'only '*45+'in summer.','site':'Operator'}
    assert not (await proposals.propose(*args))['filed']
    extract.return_value={'content':'The ferry sails weekly, except when the service is suspended.','site':'Operator'}
    result=await proposals.propose(*args)
    assert result['filed']
    assert await db.fetchval('SELECT support FROM longway_evidence_proposals WHERE id=$1',UUID(result['id']))==extract.return_value['content']


@pytest.mark.asyncio
async def test_field_requires_counter_409(db,house,client,longway_repo,monkeypatch):
    monkeypatch.setattr(proposals.defuddle_client,'extract_article',AsyncMock(return_value={'content':'The ferry sails weekly.','site':'Operator'}))
    result=await proposals.propose(db,house.room,'ogasawara','https://example.org/ferry','The ferry sails weekly','schedule')
    route=f"/rooms/{house.room}/field/marks/{result['field_mark_id']}/review"
    response=await client.post(route,json={'action':'confirm'})
    assert response.status_code==409 and response.json()['detail']=='load-bearing claim has no contrary search yet'
    rows=(await client.get(f'/rooms/{house.room}/longway/proposals')).json()
    assert rows[0]['requires_counter']
    await db.execute('UPDATE longway_evidence_proposals SET counter_searched_at=clock_timestamp() WHERE id=$1',UUID(result['id']))
    assert (await client.post(route,json={'action':'confirm'})).status_code==200


@pytest.mark.asyncio
async def test_one_running_journey_is_a_database_rule(db,house,longway_repo,monkeypatch):
    monkeypatch.setenv('LONGWAY_SEARCH_PROVIDER','none')
    first=await scout.reserve(house.pool,house.room,'ogasawara')
    with pytest.raises(scout.AlreadyRunning):
        await scout.reserve(house.pool,house.room,'ogasawara')
    await scout.kill(house.pool,house.room,first['id'])
    assert (await scout.reserve(house.pool,house.room,'ogasawara'))['id']!=first['id']


@pytest.mark.asyncio
async def test_leg_and_provenance_validation(db,house,longway_repo,monkeypatch):
    fetch=AsyncMock(return_value={'content':'The ferry sails weekly.'})
    monkeypatch.setattr(proposals.defuddle_client,'extract_article',fetch)
    args=(db,house.room,'ogasawara','https://example.org/ferry','The ferry sails weekly','Tokyo')
    with pytest.raises(ValueError,match='neighbouring'):
        await proposals.propose(*args,leg_from='Tokyo',leg_to='Ambon')
    fetch.assert_not_called()
    from uuid import uuid4
    with pytest.raises(ValueError,match='Question'):
        await proposals.propose(*args,question_id=uuid4())
    with pytest.raises(ValueError,match='precedes'):
        await proposals.propose(*args,applies_from='2027-09-30',applies_to='2027-08-24')


@pytest.mark.asyncio
async def test_nightly_disabled_and_serial_bound_rooms(db,house,longway_repo,monkeypatch):
    from organs.longway import questions
    from tests.test_longway_questions import make_manager
    home=await make_manager(db,house)
    await db.execute('UPDATE rooms SET linked_journey=NULL WHERE id<>$1',house.room)
    await db.execute("UPDATE rooms SET linked_journey='ogasawara' WHERE id=$1",home)
    await questions.add(db,house.room,'Which month?')
    fake=AsyncMock(return_value={'status':'done'})
    monkeypatch.setattr(scout,'run',fake)
    monkeypatch.delenv('LONGWAY_SCOUT_ENABLED',raising=False)
    ctx=SimpleNamespace(pool=house.pool)
    assert await jobs.scout_nightly(ctx)=={'skipped':'disabled'}
    fake.assert_not_called()
    monkeypatch.setenv('LONGWAY_SCOUT_ENABLED','1')
    assert await jobs.scout_nightly(ctx)=={str(house.room):{'status':'done'}}
    args,kwargs=fake.await_args   # the run gets the room's researchable question ids
    assert args[:3]==(house.pool,house.room,'ogasawara') and len(args[3])==1 and kwargs=={'trigger':'nightly','ctx':ctx}


@pytest.mark.asyncio
async def test_proposal_budget_stops_before_another_insert(db,house,longway_repo,monkeypatch):
    monkeypatch.setenv('LONGWAY_SEARCH_PROVIDER','none')
    monkeypatch.setenv('LONGWAY_SCOUT_BUDGET_PROPOSALS','1')
    row=await scout.reserve(house.pool,house.room,'ogasawara')
    research=scout.Research(house.pool,row,AsyncMock(return_value={'content':'The ferry sails weekly.'}))
    args=dict(candidate='ogasawara',url='https://example.org/ferry',claim='The ferry sails weekly',scope='Tokyo',load_bearing=False)
    assert (await research.propose(args))['filed']
    with pytest.raises(scout.BudgetStop,match='proposals budget exhausted'):
        await research.propose(args)
    receipt=await scout.finish(house.pool,row['id'],'done',research.reason)
    assert receipt['proposals']==1 and receipt['error']=='proposals budget exhausted'


def test_nightly_registration_is_explicitly_disabled(monkeypatch):
    from scheduler import Scheduler,SchedulerContext
    monkeypatch.delenv('LONGWAY_SCOUT_ENABLED',raising=False)
    scheduler=Scheduler(SchedulerContext(None))
    jobs.register_jobs(scheduler)
    job=next(j for j in scheduler.jobs if j.name=='scout_nightly')
    assert job.enabled_env=='LONGWAY_SCOUT_ENABLED' and job.enabled_default is False and not job.enabled()
    assert job.daily_at=='02:00' and job.daily_tz=='America/Chicago'


@pytest.mark.asyncio
async def test_room_member_names_never_reach_search_provider(db,house,longway_repo,monkeypatch):
    from organs.longway import search
    monkeypatch.setenv('LONGWAY_SEARCH_PROVIDER','brave')
    monkeypatch.setenv('LONGWAY_SEARCH_KEY','secret')
    row=await scout.reserve(house.pool,house.room,'ogasawara')
    provider=AsyncMock()
    monkeypatch.setattr(search,'search',provider)
    research=scout.Research(house.pool,row)
    for query in ('Alice travel plans','alice@example.org','+1 202 555 1234'):
        with pytest.raises(ValueError,match='never people'):
            await research.search({'query':query})
    provider.assert_not_called()


@pytest.mark.asyncio
async def test_independence_counts_publishers_for_same_claim_words(db,house,longway_repo,monkeypatch):
    monkeypatch.setenv('LONGWAY_SEARCH_PROVIDER','none')
    row=await scout.reserve(house.pool,house.room,'ogasawara')
    extract=AsyncMock()
    monkeypatch.setattr(proposals.defuddle_client,'extract_article',extract)
    # Three pages, two publishers: the same words from one page would be a single proposal.
    for url,publisher,claim in [('https://example.org/ferry','Operator','The ferry sails weekly'),
                                ('https://local.example/ferry','Local account','THE FERRY SAILS WEEKLY.'),
                                ('https://example.org/ferry-faq','Operator','The ferry sails weekly.')]:
        extract.return_value={'content':'The ferry sails weekly.','site':publisher}
        assert (await proposals.propose(db,house.room,'ogasawara',url,claim,'Tokyo',run_id=row['id']))['filed']
    await scout.finish(house.pool,row['id'],'done','proposals budget exhausted')
    counts=await db.fetch('SELECT publisher_count FROM longway_evidence_proposals WHERE run_id=$1',row['id'])
    assert [r['publisher_count'] for r in counts]==[2,2,2]


def test_timetable_lines_are_their_own_passages():
    """A list item or table row is a unit; a heading is not. The Bluemotion schedule is a nested list."""
    from organs.longway.proposals import whole_sentence_passage
    content = ("# Getting here\n\n- Prices (incl. booking fee):\n\t- VIP IDR 800,000\n- Schedule:\n"
               "\t- Tulehu-Banda: Thursdays, 9:00 am\n\t\t- Banda-Tulehu: Sundays, 1:00 pm\n\n"
               "| Ship | Ambon-Banda |\n| KM Pangrango | cancelled until further notice |\n\n"
               "## Tulehu-Banda: Thursdays\n")
    assert whole_sentence_passage('Tulehu-Banda: Thursdays, 9:00 am', content) == 'Tulehu-Banda: Thursdays, 9:00 am'
    assert whole_sentence_passage('Banda-Tulehu: Sundays, 1:00 pm', content) == 'Banda-Tulehu: Sundays, 1:00 pm'
    assert whole_sentence_passage('KM Pangrango cancelled until further notice', content) == 'KM Pangrango cancelled until further notice'
    assert whole_sentence_passage('Getting here', 'x') is None
    assert whole_sentence_passage('Tulehu-Banda: Thursdays', '## Tulehu-Banda: Thursdays\n') is None
