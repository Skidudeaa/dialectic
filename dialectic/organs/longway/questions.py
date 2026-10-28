"""Journey question queue: text is deduplicated durably, provenance is retained."""
from uuid import uuid4

from .register import get_register
from .proposals import review


async def binding(db, room_id, journey=None):
    room = await db.fetchrow("SELECT linked_journey,is_home FROM rooms WHERE id=$1", room_id)
    if not room:
        raise ValueError("Unknown room")
    slug = journey or room['linked_journey']
    if not slug or (not room['is_home'] and slug != room['linked_journey']):
        raise ValueError("A question must name this room's journey")
    get_register().journey(slug)
    return slug


async def add(db, room_id, text, *, journey=None, source='human', source_message_id=None, asked_by=None):
    text = ' '.join(text.split())
    if not text or len(text) > 4000:
        raise ValueError('Question must contain 1–4000 characters')
    async with db.transaction():
        await db.fetchval('SELECT id FROM rooms WHERE id=$1 FOR NO KEY UPDATE', room_id)
        slug = await binding(db, room_id, journey)
        if source_message_id and not await db.fetchval('''SELECT 1 FROM messages m JOIN threads t ON t.id=m.thread_id
                WHERE m.id=$1 AND t.room_id=$2 AND NOT m.is_deleted''', source_message_id, room_id):
            raise ValueError('Source message must belong to this room')
        row = await db.fetchrow('''INSERT INTO longway_questions
            (id,room_id,journey,text,source,source_message_id,asked_by)
            VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (journey,text)
            DO UPDATE SET text=EXCLUDED.text RETURNING *''',
            uuid4(), room_id, slug, text, source, source_message_id, asked_by)
    return dict(row)


async def list_questions(db, room_id):
    rows = await db.fetch('''SELECT q.*,u.display_name AS asked_by_name FROM longway_questions q JOIN rooms r ON r.id=$1
        LEFT JOIN users u ON u.id=q.asked_by
        WHERE q.closed_at IS NULL AND (r.is_home OR q.journey=r.linked_journey)
        ORDER BY q.created_at DESC,q.id''', room_id)
    result = []
    for row in rows:
        state = None
        if row['answered_by_proposal']:
            proposal = await db.fetchrow('SELECT * FROM longway_evidence_proposals WHERE id=$1', row['answered_by_proposal'])
            state = (await review(db, proposal))['review_state']
        result.append(dict(row, answer_review={'provisional':'proposed', 'superseded':'corrected'}.get(state,state)))
    return result


async def close(db, room_id, question_id, user_id):
    return await db.fetchrow('''UPDATE longway_questions q SET closed_at=clock_timestamp(),closed_by=$3
        FROM rooms r WHERE r.id=$1 AND q.id=$2 AND (r.is_home OR q.journey=r.linked_journey)
        RETURNING q.*''', room_id, question_id, user_id)


async def seed(db, room_id, user_id=None):
    slug = await binding(db, room_id)
    item = get_register().journey(slug)
    return [await add(db, room_id, text, journey=slug, source='dossier', asked_by=user_id)
            for text in item.get('questions', [])]


async def select_open(db, journey, ids=None):
    rows = await db.fetch('''SELECT * FROM longway_questions WHERE journey=$1 AND closed_at IS NULL
        AND ($2::uuid[] IS NULL OR id=ANY($2))
        ORDER BY created_at,id LIMIT 5''', journey, ids)
    if ids is not None and {r['id'] for r in rows} != set(ids):
        raise ValueError('Choose up to five open questions from this journey')
    return rows
