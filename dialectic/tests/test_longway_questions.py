"""Queue contracts exercised through authenticated HTTP against Postgres."""
from uuid import uuid4

import pytest
from organs.longway import api, questions
from tests.test_longway_api import db, house, client
from tests.test_longway_register import longway_repo


async def make_manager(db, house):
    home = await db.fetchval('SELECT id FROM rooms WHERE is_home')
    if not home:
        home = uuid4()
        await db.execute("INSERT INTO rooms(id,created_at,token,name,is_home) VALUES ($1,clock_timestamp(),$2,'Home',true)",home,str(home))
    await db.execute('''INSERT INTO room_memberships(room_id,user_id,joined_at,can_manage_home)
        VALUES ($1,$2,clock_timestamp(),true) ON CONFLICT (room_id,user_id) DO UPDATE SET can_manage_home=true''',home,house.user.user_id)
    return home


@pytest.mark.asyncio
async def test_queue_dedup_seed_provenance_and_close(db,house,client,longway_repo):
    base = f'/rooms/{house.room}/longway'
    question = {'text':'Which month should we investigate?'}
    first = await client.post(base+'/questions',json=question)
    assert first.status_code == 200,first.text
    assert first.json()['source']=='human'
    second = await client.post(base+'/questions',json=question)
    assert first.json()['id']==second.json()['id']
    assert len((await client.get(base+'/questions')).json())==1
    assert (await client.post(base+'/questions/seed')).status_code==403
    await make_manager(db,house)
    dossier=longway_repo.root/'candidates/ogasawara/dossier.md'
    dossier.write_text(dossier.read_text()+'\n## Decisive research questions\n- Is the ferry operating?\n- Which month should we investigate?\n')
    seed=await client.post(base+'/questions/seed')
    assert seed.status_code==200,seed.text
    assert len(seed.json())==2 and seed.json()[0]['source']=='dossier'
    await client.post(base+'/questions/seed')
    assert len((await client.get(base+'/questions')).json())==2
    assert (await client.post(base+'/questions',json={'text':' ', 'source':'human'})).status_code==422
    assert (await client.post(base+'/questions',json={'text':'Question?', 'source':'scout'})).status_code==422
    assert (await client.post(base+'/questions',json={'text':'Question?', 'journey':'friends-2027'})).status_code==422
    assert (await client.post(base+'/questions',json={'text':'Question?', 'source_message_id':str(uuid4())})).status_code==422
    assert (await client.post(base+f"/questions/{first.json()['id']}/close")).status_code==200
    assert len((await client.get(base+'/questions')).json())==1
    assert (await client.post(base+f'/questions/{uuid4()}/close')).status_code==404


@pytest.mark.asyncio
async def test_oldest_five_and_home_across_journeys(db,house,longway_repo):
    home=await make_manager(db,house)
    rows=[await questions.add(db,house.room,f'Question {i}?') for i in range(7)]
    assert [r['id'] for r in await questions.select_open(db,'ogasawara')]==[r['id'] for r in rows[:5]]
    other=await questions.add(db,home,'Which dates?',journey='friends-2027')
    assert other['id'] in [r['id'] for r in await questions.list_questions(db,home)]
    assert other['id'] not in [r['id'] for r in await questions.list_questions(db,house.room)]
    with pytest.raises(ValueError):
        await questions.select_open(db,'ogasawara',[other['id']])
