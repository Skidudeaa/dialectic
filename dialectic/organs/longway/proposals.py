"""Source-backed proposals and their existing Field adjudication trail."""
import asyncio
import re
from datetime import date
from uuid import uuid4
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


async def propose(db, room_id, candidate, url, claim, scope, *, proposed_by="llm", user_id=None, source_message_id=None):
    get_register().candidate(candidate)
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError("Evidence needs an original http(s) URL without credentials")
    if not claim.strip() or not scope.strip():
        raise ValueError("claim and scope are required")
    room = await db.fetchrow("SELECT linked_journey, is_home FROM rooms WHERE id=$1", room_id)
    if not room or (not room["is_home"] and room["linked_journey"] != candidate):
        raise ValueError("Propose evidence in the candidate's bound room or the house")
    article = await asyncio.wait_for(defuddle_client.extract_article(url), timeout=22)
    passage = supported_passage(claim, str(article.get("content") or "")) if isinstance(article, dict) else None
    if not passage:
        return {"filed": False, "why": "the page does not contain the claim's key phrase; use a bounded phrase from the extracted text"}
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
        await db.execute("""INSERT INTO longway_evidence_proposals
            (id,room_id,created_at,candidate,url,claim,scope,support,publisher,published_at,
             proposed_by,proposer_user_id,source_message_id)
            VALUES ($1,$2,clock_timestamp(),$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)""",
            proposal_id, room_id, candidate, url, claim, scope, passage, publisher,
            published, proposed_by, user_id, source_message_id)
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
    rows = await db.fetch("""SELECT p.* FROM longway_evidence_proposals p JOIN rooms r ON r.id=p.room_id
        WHERE p.room_id=$1 AND (r.is_home OR p.candidate=r.linked_journey)
        ORDER BY p.created_at DESC""", room_id)
    result = []
    for row in rows:
        state = await review(db, row)
        confirmation = state.pop("confirmation")
        label = {"provisional": "proposed", "superseded": "corrected"}.get(state["review_state"], state["review_state"])
        result.append(dict(row, **state, review=label,
                           queued=confirmation is not None and row["written_at"] is None))
    return result
