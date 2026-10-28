"""Source-backed proposals and their existing Field adjudication trail."""
import asyncio
import calendar
import re
from datetime import date
from uuid import UUID, uuid4
from urllib.parse import urlsplit

from field_marks import compute_dedup_key, current_review_state
from llm import defuddle_client
from .register import get_register


def supported_passage(claim, content):
    """Require the bounded claim itself, not a few overlapping keywords.

    WHY conservative lexical matching: a matching noun cannot establish a
    negation, duration or route. This gate establishes page presence only;
    the Field's human confirmation still owns the truth of the claim.
    """
    words = list(re.finditer(r"\w+", content, re.UNICODE))
    wanted = re.findall(r"\w+", claim.casefold(), re.UNICODE)
    if not 3 <= len(wanted) <= 35:
        return None
    tokens = [w.group().casefold() for w in words]
    for start in range(len(tokens) - len(wanted) + 1):
        if tokens[start:start+len(wanted)] == wanted:
            passage = content[words[start].start():words[start+len(wanted)-1].end()]
            return passage if len(passage.split()) < 40 else None
    return None


def units_of(content):
    """The quotable units of extracted text, in page order.

    Sentences of prose paragraphs; list items and table rows as their own units
    (a timetable line "Tulehu-Banda: Thursdays, 9:00 am" or "cancelled until further
    notice" carries its own negation, and schedules are written that way, not as
    prose); never headings or link-only menus.
    """
    for paragraph in re.split(r"\n\s*\n", content):
        paragraph = paragraph.strip()
        if not paragraph or re.match(r"^#{1,6}\s", paragraph):
            continue
        # Every line that is a table row or a list item is one unit, never split at a full stop, wherever
        # it sits: run 6 quoted "6 Okt 2026 01:00 | KM.LABOBAR | AMBON → KAB. TUAL" from a table whose first
        # line was a caption, and the whole table was refused as one paragraph. Prose splits into sentences.
        lines = paragraph.splitlines()
        pieces = lines if any(re.match(r"^\s*(?:[-*+]\s|\|)", line) for line in lines) else [paragraph]
        for piece in pieces:
            if re.match(r"^\s*\|?\s*:?-{2,}", piece):
                continue   # a markdown table's rule line is not text
            is_row = bool(re.match(r"^\s*(?:[-*+]\s|\|)", piece))
            plain = re.sub(r"^\s*(?:[-*+]\s+|\|)", "", piece).replace("|", " ") if is_row else piece
            if re.search(r"\[[^]]+\]\([^)]*\)", plain):
                # Link-only menus are not prose; inline editorial links are prose.
                if len(re.findall(r"\w+", re.sub(r"\[[^]]+\]\([^)]*\)", "", plain))) < 3:
                    continue
                plain = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", plain)
            for sentence in ([plain] if is_row else re.split(r'(?<=[.!?])\s+(?=[A-Z0-9"“])', plain)):
                sentence = ' '.join(sentence.split())
                if sentence:
                    yield sentence


def whole_sentence_passage(claim, content):
    """Preserve the sentence around a lexical match, including its negation.

    WHY: the old gate could extract a positive phrase from a suspended-service
    sentence. Do not trim a long sentence to fit; refuse it.
    """
    for sentence in units_of(content):
        if len(sentence.split()) < 40 and supported_passage(claim, sentence):
            return sentence
    return None


def closest_unit(claim, content):
    """The page's own line nearest to a refused claim, so the Scout can quote it.

    WHY: the fifth live run refused six paraphrases of a schedule sheet, the most
    useful claims of the run, and the refusal said only "quote the page". Returning
    the nearest line turns a paraphrase into a quotation on the next attempt.
    """
    wanted = set(re.findall(r"\w+", claim.casefold(), re.UNICODE)) - {'the', 'a', 'an', 'of', 'to', 'in', 'on', 'and', 'is', 'are'}
    best, score = None, 0
    for sentence in units_of(content):
        words = sentence.split()
        if not 3 <= len(words) < 40:
            continue
        overlap = len(wanted & set(re.findall(r"\w+", sentence.casefold(), re.UNICODE)))
        if overlap > score:
            best, score = sentence, overlap
    return best if score >= 2 else None


PROPOSAL_FIELDS = ('question_id', 'run_id', 'search_result_id', 'contradicts',
    'applies_from', 'applies_to', 'direction', 'passport', 'vehicle', 'leg_from', 'leg_to', 'load_bearing')


def requires_counter(proposal):
    # A contradiction is the result of a contrary search; it needs none of its own (run 6 left ten unconfirmable).
    return bool(proposal['load_bearing'] and not proposal['counter_searched_at'] and not proposal['contradicts'])


async def propose(db, room_id, candidate, url, claim, scope, *, proposed_by="llm", user_id=None, source_message_id=None, fetcher=None, **fields):
    get_register().candidate(candidate)
    if set(fields) - set(PROPOSAL_FIELDS):
        raise ValueError("Unknown proposal fields")
    values = {key: fields.get(key) for key in PROPOSAL_FIELDS}
    for key in ('question_id', 'run_id', 'search_result_id', 'contradicts'):
        if values[key] is not None:
            try:
                values[key] = UUID(str(values[key]))
            except ValueError:
                # The fourth live run sent S-numbers and claim text here; the parser's own message taught nothing.
                raise ValueError(f'{key} must be the id of a proposal or question (a UUID), never an S-number or a claim') from None
    for key in ('applies_from', 'applies_to'):
        if isinstance(values[key], str):
            text = values[key].strip()
            # A year or a month is a period: applies_from takes its first day, applies_to its last.
            if re.fullmatch(r'\d{4}', text):
                text += '-01' if key == 'applies_from' else '-12'
            if re.fullmatch(r'\d{4}-\d{2}', text):
                year, month = map(int, text.split('-'))
                day = 1 if key == 'applies_from' else calendar.monthrange(year, month)[1]
                text = f'{year:04d}-{month:02d}-{day:02d}'
            values[key] = date.fromisoformat(text)
    if values['applies_from'] and values['applies_to'] and values['applies_from'] > values['applies_to']:
        raise ValueError('applies_to precedes applies_from')
    values['load_bearing'] = bool(values['load_bearing'] or re.search(
        r'\b(schedules?|timetables?|operating status|entry rules?|entry requirements?|prices?|fares?)\b', scope, re.I))
    if values['leg_from'] is not None or values['leg_to'] is not None:
        route = get_register().journey(candidate)['route']
        pairs = [(a[2], b[2]) for a,b in zip(route, route[1:])]
        pair = (values['leg_from'], values['leg_to'])
        if pair not in pairs and pair[::-1] not in pairs:
            raise ValueError('leg_from and leg_to must name neighbouring route stops')
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("Evidence needs an original http(s) URL without credentials")
    if not claim.strip() or not scope.strip():
        raise ValueError("claim and scope are required")
    room = await db.fetchrow("SELECT linked_journey, is_home FROM rooms WHERE id=$1", room_id)
    if not room or (not room["is_home"] and room["linked_journey"] != candidate):
        raise ValueError("Propose evidence in the candidate's bound room or the house")
    article = await asyncio.wait_for((fetcher or defuddle_client.extract_article)(url), timeout=22)
    passage = supported_passage(claim, str(article.get("content") or "")) if isinstance(article, dict) else None
    if not passage:
        hint = closest_unit(claim, str(article.get("content") or "")) if isinstance(article, dict) else None
        return {"filed": False, "why": "the page does not contain the claim's key phrase; quote the page's own words"
                + (f'; the closest line on the page: "{hint}"' if hint else '')}
    passage = whole_sentence_passage(claim, str(article.get('content') or ''))
    if not passage:
        return {"filed": False, "why": "support must be a whole sentence or paragraph of main text under 40 words"}
    publisher = article.get("site") or parts.hostname
    published = None
    try:
        published = date.fromisoformat(str(article.get("published"))[:10])
    except ValueError:
        pass
    proposal_id, mark_id = uuid4(), uuid4()
    subjects = [{"entity": "longway_evidence_proposals", "id": str(proposal_id)}]
    async with db.transaction():
        # Recheck binding under a row lock after network I/O.
        current = await db.fetchrow("SELECT linked_journey, is_home FROM rooms WHERE id=$1 FOR NO KEY UPDATE", room_id)
        if not current or (not current["is_home"] and current["linked_journey"] != candidate):
            raise ValueError("Room binding changed while reading the source")
        if values['run_id']:
            run = await db.fetchrow('SELECT * FROM longway_scout_runs WHERE id=$1 FOR UPDATE', values['run_id'])
            if not run or run['status'] != 'running' or run['room_id'] != room_id or run['journey'] != candidate:
                raise ValueError('Proposal must belong to its running journey')
        if values['question_id'] and not await db.fetchval(
                'SELECT 1 FROM longway_questions WHERE id=$1 AND journey=$2 AND closed_at IS NULL', values['question_id'], candidate):
            raise ValueError('Question must be open in this journey')
        if values['search_result_id'] and not await db.fetchval(
                'SELECT 1 FROM longway_search_results WHERE id=$1 AND run_id=$2 AND url=$3',
                values['search_result_id'], values['run_id'], url):
            raise ValueError('Search result must belong to this run and URL')
        if values['contradicts'] and not await db.fetchval(
                'SELECT 1 FROM longway_evidence_proposals WHERE id=$1 AND room_id=$2 AND candidate=$3',
                values['contradicts'], room_id, candidate):
            raise ValueError('Contrary proposal must name evidence in this room and journey')
        # The same words from the same page are one proposal. WHY: the fourth live run's counter phases filed
        # the car ferry's "has not operated yet" line six times and spent half the proposals budget on copies
        # the Field would have had to read six times. The existing id lets the Scout file a contradiction instead.
        same = await db.fetchval('''SELECT id FROM longway_evidence_proposals WHERE room_id=$1 AND candidate=$2 AND url=$3
            AND btrim(regexp_replace(lower(claim),'[^[:alnum:]]+',' ','g'))=btrim(regexp_replace(lower($4),'[^[:alnum:]]+',' ','g'))
            ORDER BY created_at,id LIMIT 1''', room_id, candidate, url, claim)
        if same:
            return {"filed": False, "id": str(same),
                    "why": f"already filed as proposal {same}; file a different claim, or a contradiction with contradicts={same}"}
        await db.execute("""INSERT INTO longway_evidence_proposals
            (id,room_id,created_at,candidate,url,claim,scope,support,publisher,published_at,
             proposed_by,proposer_user_id,source_message_id)
            VALUES ($1,$2,clock_timestamp(),$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
            proposal_id, room_id, candidate, url, claim, scope, passage, publisher,
            published, proposed_by, user_id, source_message_id)
        columns = ','.join(f'{key}=${i+2}' for i,key in enumerate(PROPOSAL_FIELDS))
        await db.execute(f'UPDATE longway_evidence_proposals SET {columns} WHERE id=$1',
                         proposal_id, *(values[key] for key in PROPOSAL_FIELDS))
        if values['question_id']:
            await db.execute('UPDATE longway_questions SET answered_by_proposal=COALESCE(answered_by_proposal,$2) WHERE id=$1',
                             values['question_id'], proposal_id)
        if values['run_id']:
            await db.execute('''UPDATE longway_scout_runs SET proposals=proposals+1,
                counter_proposals=counter_proposals+$2 WHERE id=$1''', values['run_id'], int(bool(values['contradicts'])))
        await db.execute("""INSERT INTO field_marks
            (id,room_id,mark_kind,relation,origin,subjects,title,payload,actor_user_id,provenance,dedup_key,created_at)
            VALUES ($1,$2,'relation','evidence_attachment',$3,$4,$5,$6,$7,$8,$9,clock_timestamp())""",
            mark_id, room_id, "inferred" if proposed_by == "llm" else "explicit",
            subjects, claim, {"url": url, "support": passage, "scope": scope}, user_id,
            "longway_scout" if proposed_by == "llm" else "human",
            compute_dedup_key("evidence_attachment", subjects))
    return {"filed": True, "id": str(proposal_id), "field_mark_id": str(mark_id)}


async def review(db, proposal, *, lock=False):
    """Derive state through the Field's relation→review structure.

    WHY lock the parent marks: the existing review route locks those same rows,
    serializing a contest/correction with the writer's authority check.
    TRADEOFF: a short git commit holds these locks; source fetches never do.
    """
    subjects = [{"entity": "longway_evidence_proposals", "id": str(proposal["id"])}]
    # A confirmed contextual relation about a proposal is not confirmation of
    # its claim. Only the canonical evidence-attachment mark grants authority.
    marks = await db.fetch("""SELECT * FROM field_marks
        WHERE room_id=$1 AND mark_kind='relation' AND dedup_key=$2
        ORDER BY created_at,id""" + (" FOR UPDATE" if lock else ""),
        proposal["room_id"], compute_dedup_key("evidence_attachment", subjects))
    if not marks:
        return {"review_state": "provisional", "field_mark_id": None, "confirmation": None}
    reviews = await db.fetch("""SELECT * FROM field_marks
        WHERE room_id=$1 AND mark_kind='review' AND target_mark_id=ANY($2::uuid[])
        ORDER BY created_at,id""", proposal["room_id"], [m["id"] for m in marks])
    state = await current_review_state(db, marks[0]["id"])
    contested = any(r["action"] == "contest" for r in reviews)
    confirms = [r for r in reviews if r["action"] == "confirm"]
    # Preserve the Field's latest-action review state. The writer has the
    # contract's stricter no-contest rule even if someone later reconfirms.
    eligible = state == "confirmed" and confirms and not contested
    return {"review_state": state, "field_mark_id": str(marks[0]["id"]),
            "write_blocked": "contested evidence needs a new proposal" if contested else None,
            "confirmation": dict(confirms[-1]) if eligible else None}



async def list_proposals(db, room_id):
    rows = await db.fetch("""SELECT p.*,q.text AS question_text FROM longway_evidence_proposals p JOIN rooms r ON r.id=p.room_id
        LEFT JOIN longway_questions q ON q.id=p.question_id
        WHERE p.room_id=$1 AND (r.is_home OR p.candidate=r.linked_journey)
        ORDER BY p.created_at DESC""", room_id)
    result = []
    for row in rows:
        state = await review(db, row)
        confirmation = state.pop("confirmation")
        label = {"provisional": "proposed", "superseded": "corrected"}.get(state["review_state"], state["review_state"])
        result.append(dict(row, **state, review=label, requires_counter=requires_counter(row),
                           queued=confirmation is not None and row["written_at"] is None))
    return result


async def chart_overlay(db, chart, room_id):
    """Only this authorized room's proposals become provisional chart ink."""
    overlay = {}
    for row in await list_proposals(db, room_id):
        if row['written_at'] or row['review'] in ('contested', 'corrected'):
            continue
        overlay.setdefault(row['candidate'], []).append({key: row[key] for key in (
            'id','claim','support','review','url','publisher','leg_from','leg_to','load_bearing','requires_counter')})
    for journey in chart['journeys']:
        for segment in journey['segments']:
            segment['proposed'] = any(
                (p['leg_from'], p['leg_to']) in ((segment['from'], segment['to']), (segment['to'], segment['from']))
                for p in overlay.get(journey['slug'], []))
    return dict(chart, proposals=overlay)
