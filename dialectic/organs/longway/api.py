"""Room-fenced Long Way projections, evidence proposals, consent ledger, and the public door for asking for a seat."""
import asyncio
import hashlib
import hmac
import html as html_mod
import os
import time
from datetime import date
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator
from typing import Literal

from api.auth.dependencies import get_current_user
from api.token_utils import extract_room_token
from api.field import _authorize
from api.home import _require_home_manager
from api.rate_limit import _reject_if_limited
from .register import CommitsDisabled, DirtyDocument, UnknownCandidate, get_register, open_place
from .fixes import overlay
from .proposals import propose, list_proposals, chart_overlay
from . import invites, questions as question_queue, scout as scout_runner

router = APIRouter(prefix="/rooms/{room_id}/longway", tags=["longway"])
_pool = None


def set_db_pool(pool):
    global _pool
    _pool = pool


async def get_db():
    async with _pool.acquire() as conn:
        yield conn


async def authorized(room_id: UUID, token=Depends(extract_room_token), user=Depends(get_current_user), db=Depends(get_db)):
    await _authorize(room_id, token, user.user_id, db)
    return user


async def ride_authorized(room_id: UUID, token=Depends(extract_room_token), user=Depends(get_current_user), db=Depends(get_db)):
    try:
        return await authorized(room_id, token, user, db)
    except HTTPException as exc:
        if exc.status_code == 403:
            raise HTTPException(404, "No such ride in this room") from exc
        raise


async def manager(user, db):
    # The credential on this request is the journey's room token; the reused
    # Home capability check needs Home's token after that room was authorized.
    token = await db.fetchval("SELECT token FROM rooms WHERE is_home")
    if not token:
        raise HTTPException(403, "A Home administrator is required")
    await _require_home_manager(token, user.user_id, db)


MANAGERS_ONLY = "Only a house manager changes a journey's voyage, dossier or record here."


async def can_edit(user, db):
    """Amo, 2026-11-21: the record-level editor is not for everyone. Members ride and read; house managers edit."""
    return bool(await db.fetchval("""SELECT m.can_manage_home FROM rooms r JOIN room_memberships m ON m.room_id=r.id
        WHERE r.is_home AND m.user_id=$1""", user.user_id))


def journey(slug):
    try:
        return get_register().journey(slug)
    except (KeyError, ValueError):
        raise HTTPException(404, "Unknown journey")


@router.get("/chart")
async def chart(room_id: UUID, user=Depends(authorized), db=Depends(get_db)):
    result = await chart_overlay(db, await overlay(await asyncio.to_thread(get_register().chart)), room_id)
    room = await db.fetchrow("SELECT id,linked_journey,is_home FROM rooms WHERE id=$1", room_id)
    rooms = await db.fetch("""SELECT r.id,r.name,r.linked_journey FROM rooms r
        JOIN room_memberships m ON m.room_id=r.id WHERE m.user_id=$1 ORDER BY r.created_at,r.id""", user.user_id)
    return dict(result, room=dict(room, can_edit=await can_edit(user, db)), rooms=[dict(r) for r in rooms])


@router.get("/journey/{slug}")
async def get_journey(room_id: UUID, slug: str, user=Depends(authorized)):
    result = journey(slug)
    live = await overlay({"vehicles": result["vehicles"]})
    return dict(result, vehicles=live["vehicles"])


async def require_notebook_manager(user, db):
    if not await can_edit(user, db):
        raise HTTPException(403, "Only a house manager can review a draft or start the Scout.")


async def notebook_call(method, *args):
    try:
        return await asyncio.to_thread(method, *args)
    except (UnknownCandidate, FileNotFoundError) as exc:
        raise HTTPException(404, "Unknown journey") from exc
    except KeyError as exc:
        raise HTTPException(404, str(exc.args[0])) from exc
    except (CommitsDisabled, DirtyDocument) as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


async def git_author(user, db):
    actor = await db.fetchrow("""SELECT u.display_name,c.email FROM users u
        JOIN user_credentials c ON c.user_id=u.id WHERE u.id=$1""", user.user_id)
    return (actor["display_name"], actor["email"]) if actor else (None, None)


class NotebookNote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["place", "thought"]
    text: str = Field(min_length=1, max_length=2000)
    place: str | None = None
    about: str | None = None


class SetAside(BaseModel):
    model_config = ConfigDict(extra="forbid")
    why: str = ""


class SendBack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    why: str


@router.get("/notebook/{slug}")
async def get_notebook(room_id: UUID, slug: str, user=Depends(authorized), db=Depends(get_db)):
    register = get_register()
    notes = await notebook_call(register.notebook, slug)
    why = "Notebook writes are disabled in this house." if register.edit_disabled_reason() else None
    return dict(slug=slug, notes=notes, can_review=await can_edit(user, db), writable=why is None, why=why)


@router.post("/notebook/{slug}")
async def add_note(room_id: UUID, slug: str, body: NotebookNote, user=Depends(authorized), db=Depends(get_db)):
    return await notebook_call(get_register().add_note, slug, body.kind, body.text, body.place, body.about,
                               *await git_author(user, db))


@router.post("/notebook/{slug}/{note_id}/accept")
async def accept_note(room_id: UUID, slug: str, note_id: str, user=Depends(authorized), db=Depends(get_db)):
    await require_notebook_manager(user, db)
    return await notebook_call(get_register().accept_note, slug, note_id, *await git_author(user, db))


@router.post("/notebook/{slug}/{note_id}/set-aside")
async def set_aside_note(room_id: UUID, slug: str, note_id: str, body: SetAside | None = None,
                        user=Depends(authorized), db=Depends(get_db)):
    await require_notebook_manager(user, db)
    return await notebook_call(get_register().set_aside_note, slug, note_id, *await git_author(user, db),
                               body.why if body else "")


@router.post("/notebook/{slug}/{note_id}/send-back")
async def send_back_note(room_id: UUID, slug: str, note_id: str, body: SendBack,
                         user=Depends(authorized), db=Depends(get_db)):
    await require_notebook_manager(user, db)
    return await notebook_call(get_register().send_back_note, slug, note_id, body.why, *await git_author(user, db))


@router.post("/notebook/{slug}/scout")
async def scout_notebook(room_id: UUID, slug: str, user=Depends(authorized), db=Depends(get_db)):
    await require_notebook_manager(user, db)
    notes = await notebook_call(get_register().notebook, slug)
    if not any(open_place(n) for n in notes):
        raise HTTPException(409, "This journey has no open place for the Scout.")
    target = await scout_runner.notebook_room(db, slug)
    if target is None:
        raise HTTPException(409, "This journey needs a bound room or a house room for its Scout run.")
    question_ids = [q["id"] for q in await question_queue.researchable(db, slug)]
    try:
        run_id = await scout_runner.start(_pool, target, slug, question_ids, started_by=user.user_id, ctx=scout_context())
    except scout_runner.AlreadyRunning as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"run_id": str(run_id)}


@router.get("/voyage/{slug}/page")
async def get_voyage_page(room_id: UUID, slug: str, response: Response, station: str | None = None,
                          preview: str | None = None, user=Depends(authorized), db=Depends(get_db)):
    if preview is not None:
        await require_notebook_manager(user, db)
    html = await notebook_call(get_register().voyage_page, slug, station, preview)
    response.headers["Cache-Control"] = "no-store"
    return {"html": html}


@router.get("/document/{slug}/{name}")
async def get_document(room_id: UUID, slug: str, name: str, user=Depends(authorized), db=Depends(get_db)):
    register = get_register()
    try:
        document = await asyncio.to_thread(register.document, slug, name)
    except (UnknownCandidate, KeyError, FileNotFoundError) as exc:
        raise HTTPException(404, "Unknown document") from exc
    why = register.edit_disabled_reason() or (None if await can_edit(user, db) else MANAGERS_ONLY)
    return dict(document, writable=why is None, why=why)


class DocumentEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ops: list[dict] | None = Field(default=None, max_length=200)
    text: str | None = Field(default=None, max_length=200_000)

    @model_validator(mode="after")
    def one_edit(self):
        if (self.ops is None) == (self.text is None):
            raise ValueError("Supply exactly one of ops or text")
        return self


@router.post("/document/{slug}/{name}")
async def edit_document(room_id: UUID, slug: str, name: str, body: DocumentEdit, user=Depends(authorized), db=Depends(get_db)):
    if not await can_edit(user, db):
        raise HTTPException(403, MANAGERS_ONLY)
    try:
        return await asyncio.to_thread(get_register().edit_document, slug, name, body.ops, body.text,
                                       *await git_author(user, db))
    except (UnknownCandidate, KeyError, FileNotFoundError) as exc:
        raise HTTPException(404, "Unknown document") from exc
    except (CommitsDisabled, DirtyDocument) as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/ride")
async def get_ride(room_id: UUID, ride: str | None = None, user=Depends(ride_authorized), db=Depends(get_db)):
    from .rides import payload
    try:
        return await payload(db, room_id, ride)
    except (KeyError, ValueError):
        raise HTTPException(404, "No such ride in this room")


@router.get("/ride/leg")
async def get_ride_leg(room_id: UUID, leg: str, response: Response, user=Depends(ride_authorized), db=Depends(get_db)):
    from .rides import bound_trip
    try:
        trip = await bound_trip(db, room_id)
        if not any(r["leg"] == leg for r in trip["rides"]):
            raise KeyError(leg)
        model = get_register().leg(leg)
    except (KeyError, ValueError):
        raise HTTPException(404, "No such leg in this room")
    built = (model.get("leg") or {}).get("built") or model["sights"].get("built")
    response.headers["Cache-Control"] = "private, max-age=86400"
    response.headers["ETag"] = '"' + hashlib.sha256(str(built).encode()).hexdigest() + '"'
    return model


@router.get("/riding")
async def get_riding(room_id: UUID, user=Depends(authorized), db=Depends(get_db)):
    from .rides import riding
    return await riding(db, user.user_id)


class Bind(BaseModel):
    slug: str


@router.post("/bind")
async def bind(room_id: UUID, body: Bind, user=Depends(authorized), db=Depends(get_db)):
    await manager(user, db)
    journey(body.slug)
    await db.execute("UPDATE rooms SET linked_journey=$2 WHERE id=$1", room_id, body.slug)
    return {"linked_journey": body.slug}


class Proposal(BaseModel):
    candidate: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=4000)
    claim: str = Field(min_length=1, max_length=2000)
    scope: str = Field(min_length=1, max_length=4000)
    question_id: UUID | None = None
    search_result_id: UUID | None = None
    contradicts: UUID | None = None
    applies_from: date | None = None
    applies_to: date | None = None
    direction: str | None = Field(default=None, max_length=500)
    passport: str | None = Field(default=None, max_length=500)
    vehicle: str | None = Field(default=None, max_length=500)
    leg_from: str | None = Field(default=None, max_length=300)
    leg_to: str | None = Field(default=None, max_length=300)
    load_bearing: bool = False


@router.get("/proposals")
async def proposals(room_id: UUID, user=Depends(authorized), db=Depends(get_db)):
    return await list_proposals(db, room_id)


@router.post("/proposals")
async def post_proposal(room_id: UUID, body: Proposal, user=Depends(authorized), db=Depends(get_db)):
    try:
        return await propose(db, room_id, **body.model_dump(), proposed_by="human", user_id=user.user_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


class Confirmation(BaseModel):
    member_id: UUID
    binds: str = Field(min_length=1, max_length=4000)
    confirmed_on: date
    channel: str = Field(min_length=1, max_length=300)


@router.get("/confirmations")
async def confirmations(room_id: UUID, user=Depends(authorized), db=Depends(get_db)):
    return [dict(r) for r in await db.fetch("SELECT c.*,u.display_name AS member_name FROM longway_confirmations c JOIN users u ON u.id=c.member_id WHERE c.room_id=$1 ORDER BY c.created_at,c.id", room_id)]


@router.post("/confirmations")
async def post_confirmation(room_id: UUID, body: Confirmation, user=Depends(authorized), db=Depends(get_db)):
    await manager(user, db)
    async with db.transaction():
        member = await db.fetchrow("SELECT u.display_name FROM room_memberships m JOIN users u ON u.id=m.user_id WHERE m.room_id=$1 AND m.user_id=$2 FOR SHARE OF m", room_id, body.member_id)
        if not member:
            raise HTTPException(422, "Consent must name a member of this room")
        row = await db.fetchrow("""INSERT INTO longway_confirmations
            (id,room_id,member_id,binds,confirmed_on,channel,recorded_by,created_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,clock_timestamp()) RETURNING *""",
            uuid4(), room_id, body.member_id, body.binds, body.confirmed_on, body.channel, user.user_id)
    return dict(row, member_name=member["display_name"])


@router.post("/dispatch/now")
async def dispatch_now_route(room_id: UUID, user=Depends(authorized), db=Depends(get_db)):
    """Send this week's dispatch to this room now (house managers). Posts, broadcasts and pushes like Sunday's job."""
    await manager(user, db)
    from types import SimpleNamespace
    from api import main as app_main  # fully imported by request time; jobs never import it themselves
    from .jobs import dispatch_now
    manager_obj = app_main.connection_manager

    async def broadcast(target_room_id, message):
        if manager_obj is not None:
            await manager_obj.broadcast(target_room_id, message)

    ctx = SimpleNamespace(pool=_pool, broadcast=broadcast, connection_manager=manager_obj)
    try:
        return await dispatch_now(ctx, room_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:  # the model or the repo refused: say so, do not 500
        raise HTTPException(502, f"The dispatch could not be drafted: {type(exc).__name__}: {str(exc)[:200]}") from exc


@router.get("/dispatch/latest")
async def latest_dispatch(room_id: UUID, user=Depends(authorized), db=Depends(get_db)):
    row = await db.fetchrow("""SELECT m.* FROM messages m JOIN threads t ON t.id=m.thread_id
        WHERE t.room_id=$1 AND NOT m.is_deleted AND m.metadata ? 'longway_dispatch'
        ORDER BY m.created_at DESC,m.id DESC LIMIT 1""", room_id)
    if not row:
        raise HTTPException(404, "No dispatch yet")
    return dict(row)


class Question(BaseModel):
    journey: str | None = None
    text: str = Field(min_length=1, max_length=4000)
    source: Literal['human','reaction','message'] = 'human'
    source_message_id: UUID | None = None


@router.get('/questions')
async def get_questions(room_id: UUID, user=Depends(authorized), db=Depends(get_db)):
    return await question_queue.list_questions(db, room_id)


@router.post('/questions')
async def post_question(room_id: UUID, body: Question, user=Depends(authorized), db=Depends(get_db)):
    try:
        return await question_queue.add(db, room_id, **body.model_dump(), asked_by=user.user_id)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/questions/seed')
async def seed_questions(room_id: UUID, user=Depends(authorized), db=Depends(get_db)):
    await manager(user, db)
    try:
        return await question_queue.seed(db, room_id, user.user_id)
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post('/questions/{question_id}/close')
async def close_question(room_id: UUID, question_id: UUID, user=Depends(authorized), db=Depends(get_db)):
    row = await question_queue.close(db, room_id, question_id, user.user_id)
    if row is None:
        raise HTTPException(404, 'Question not found')
    return dict(row)


class ScoutRequest(BaseModel):
    question_ids: list[UUID] | None = Field(default=None, max_length=5)


def scout_context():
    from types import SimpleNamespace
    from api import main as app_main
    async def broadcast(room_id, message):
        if app_main.connection_manager is not None:
            await app_main.connection_manager.broadcast(room_id, message)
    return SimpleNamespace(pool=_pool, broadcast=broadcast)


@router.post('/scout')
async def post_scout(room_id: UUID, body: ScoutRequest = ScoutRequest(), user=Depends(authorized), db=Depends(get_db)):
    await manager(user, db)
    try:
        slug = await question_queue.binding(db, room_id)
        run_id = await scout_runner.start(_pool, room_id, slug, body.question_ids,
            started_by=user.user_id, ctx=scout_context())
    except scout_runner.AlreadyRunning as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, str(exc)) from exc
    return {'run_id': str(run_id)}


@router.get('/scout/runs')
async def scout_runs(room_id: UUID, user=Depends(authorized), db=Depends(get_db)):
    return [{k: v for k, v in r.items() if k != 'log'} for r in await db.fetch('''SELECT * FROM longway_scout_runs
        WHERE room_id=$1 ORDER BY started_at DESC,id DESC LIMIT 20''', room_id)]


@router.get('/scout/runs/{run_id}')
async def scout_run(room_id: UUID, run_id: UUID, user=Depends(authorized), db=Depends(get_db)):
    row = await db.fetchrow('SELECT * FROM longway_scout_runs WHERE id=$1 AND room_id=$2', run_id, room_id)
    if row is None:
        raise HTTPException(404, 'Scout run not found')
    return dict(row)


@router.post('/scout/runs/{run_id}/kill')
async def kill_scout(room_id: UUID, run_id: UUID, user=Depends(authorized), db=Depends(get_db)):
    await manager(user, db)
    row = await scout_runner.kill(_pool, room_id, run_id, ctx=scout_context())
    if row is None:
        raise HTTPException(404, 'Scout run not found')
    return dict(row)


@router.get('/invite-requests')
async def invite_requests(room_id: UUID, user=Depends(authorized), db=Depends(get_db)):
    """Who is asking for a seat (house managers), open requests first, and whether mail is on."""
    await manager(user, db)
    return await invites.listing(db)


@router.post('/invite-requests/{request_id}/invite')
async def invite_requester(room_id: UUID, request_id: UUID, user=Depends(authorized), db=Depends(get_db)):
    """Seat the requester (house managers): account, membership, a 7-day code, and the email when mail is on."""
    await manager(user, db)
    try:
        return await invites.decide_invite(db, request_id, user.user_id)
    except KeyError:
        raise HTTPException(404, 'Unknown request')


@router.post('/invite-requests/{request_id}/decline')
async def decline_requester(room_id: UUID, request_id: UUID, user=Depends(authorized), db=Depends(get_db)):
    await manager(user, db)
    try:
        return await invites.decline(db, request_id, user.user_id)
    except KeyError:
        raise HTTPException(404, 'Unknown request')


# The one door a stranger may knock on. /organ is already proxied by nginx, so no server change opens it.
public = APIRouter(prefix='/organ/longway', tags=['longway'])


class Ask(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=80)
    note: str = Field(default='', max_length=1000)


def _asker_ip(request: Request) -> str:
    # Behind Cloudflare and nginx the peer is 127.0.0.1; the visitor's address rides in these headers.
    return (request.headers.get('cf-connecting-ip') or request.headers.get('x-real-ip')
            or (request.client.host if request.client else 'unknown'))


@public.post('/invite-requests')
async def ask_for_seat(request: Request, body: Ask, db=Depends(get_db)):
    """A stranger asks for a seat: the request is recorded, the house managers pushed, the planner emailed.

    The answer is the same whether or not the address is known. Ten asks a day per visitor address and three per
    email address: more than friends need, less than a nuisance wants.
    """
    name = body.name.strip()
    if not name:
        raise HTTPException(422, 'A name is required')
    _reject_if_limited(f'ip:{_asker_ip(request)}:longway-ask', 10, 86400)
    _reject_if_limited(f'account:{hashlib.sha256(body.email.lower().encode()).hexdigest()}:longway-ask', 3, 86400)
    row = await invites.ask(db, body.email.lower(), name, body.note.strip(), _asker_ip(request))
    await invites.announce(db, row)
    return {'ok': True}


VOYAGE_PASS_COOKIE = "longway_voyage_pass"
VOYAGE_PASS_TTL = 90 * 86400
# The passphrase lives only in the house's environment (LONGWAY_VOYAGE_PASSPHRASE). Nothing derived from it is kept
# in git: this repository is public, and a fast hash of a short passphrase gives the passphrase away to a word list.
_PUBLIC_VOYAGE_HEADERS = {
    "Cache-Control": "private, no-store",
    "X-Robots-Tag": "noindex, nofollow",
    "Referrer-Policy": "no-referrer",
}


def _passphrase_hash(value: str) -> str:
    normalized = " ".join(str(value or "").strip().lower().split())
    return hashlib.sha256(f"longway-voyage-pass:{normalized}".encode("utf-8")).hexdigest()


def _active_passphrase_hash() -> str | None:
    """The gate's passphrase as its hash, read from the environment. None when the house has none set: the gate
    then opens for nobody."""
    override = os.environ.get("LONGWAY_VOYAGE_PASSPHRASE")
    if override and override.strip():
        return _passphrase_hash(override)
    return os.environ.get("LONGWAY_VOYAGE_PASSPHRASE_HASH") or None


def _cookie_secret() -> bytes:
    server_secret = os.environ.get("JWT_SECRET_KEY") or "longway-local"
    return hashlib.sha256(f"longway-voyage-cookie:{_active_passphrase_hash()}:{server_secret}".encode("utf-8")).digest()


def _issue_pass_cookie() -> str:
    exp = int(time.time()) + VOYAGE_PASS_TTL
    payload = f"v1.{exp}"
    sig = hmac.new(_cookie_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _has_valid_pass(request: Request) -> bool:
    if _active_passphrase_hash() is None:
        return False
    raw = request.cookies.get(VOYAGE_PASS_COOKIE) or ""
    parts = raw.split(".")
    if len(parts) != 3:
        return False
    ver, exp_s, sig = parts
    if ver != "v1" or not exp_s.isdigit() or int(exp_s) <= int(time.time()):
        return False
    expected = hmac.new(_cookie_secret(), f"{ver}.{exp_s}".encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)


def _gate_html(unlock_url: str, title: str, subtitle: str, pitch: str | None = None, kicker: str = "The Long Way") -> str:
    esc_title = html_mod.escape(title, quote=True)
    esc_kicker = html_mod.escape(kicker, quote=True)
    esc_sub = html_mod.escape(subtitle or "Private voyage", quote=True)
    esc_unlock = html_mod.escape(unlock_url, quote=True)
    page_title = html_mod.escape(title if title == "The Long Way" else f"{title} — The Long Way", quote=True)
    pitch_html = f'<p class="pitch">{html_mod.escape(pitch)}</p>' if pitch else ""
    og_desc = html_mod.escape(pitch or subtitle or "Private voyage", quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="theme-color" content="#070c0c">
<title>{page_title}</title>
<meta name="description" content="{og_desc}">
<meta property="og:type" content="website">
<meta property="og:title" content="{page_title}">
<meta property="og:description" content="{og_desc}">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Condensed:wght@400;500;600&family=Libre+Caslon+Display&family=Libre+Caslon+Text:ital,wght@0,400;1,400&display=swap">
<style>
:root {{
  color-scheme: dark;
  --bg: #070c0c;
  --surface: rgba(13, 21, 21, 0.9);
  --ink: #f6f1e4;
  --ink-soft: #d7d4c8;
  --muted: #9ea9a1;
  --rule: rgba(232, 196, 116, 0.24);
  --rule-soft: rgba(246, 241, 228, 0.14);
  --gold: #e8c474;
  --gold-bright: #f5da94;
  --display: "Libre Caslon Display", Georgia, serif;
  --body: "Libre Caslon Text", Georgia, serif;
  --ui: "IBM Plex Sans Condensed", "Arial Narrow", system-ui, sans-serif;
}}
* {{ box-sizing: border-box; }}
html, body {{ margin: 0; min-height: 100%; background: var(--bg); color: var(--ink); font: 16px/1.5 var(--body); -webkit-font-smoothing: antialiased; }}
body {{
  min-height: 100dvh; display: grid; place-items: center; padding: 1.5rem;
  background: radial-gradient(circle at 60% 34%, #111c21 0%, #070c0d 58%, #040708 100%);
}}
main {{
  width: min(28rem, 100%); padding: 2.2rem 2rem 2rem; border-radius: 16px;
  background: var(--surface); border: 1px solid var(--rule);
  box-shadow: 0 28px 80px rgba(0, 0, 0, 0.65); backdrop-filter: blur(18px);
}}
.brand {{
  margin: 0 0 0.7rem; font: 600 0.72rem/1 var(--ui); letter-spacing: 0.22em;
  text-transform: uppercase; color: var(--gold);
}}
h1 {{
  margin: 0; font: 400 clamp(2.5rem, 9vw, 3.4rem)/0.98 var(--display);
  letter-spacing: -0.04em; color: var(--ink);
}}
.sub {{
  margin: 0.55rem 0 1.2rem; font: italic 1.02rem/1.38 var(--body); color: var(--ink-soft);
}}
.pitch {{
  margin: 0 0 1.5rem; font: 400 0.92rem/1.55 var(--body); color: var(--muted);
}}
form {{ display: flex; flex-direction: column; gap: 0.85rem; }}
label {{
  display: block; font: 600 0.7rem/1.2 var(--ui); letter-spacing: 0.16em;
  text-transform: uppercase; color: var(--muted); margin-bottom: 0.35rem;
}}
input {{
  width: 100%; padding: 0.72rem 0.85rem; border-radius: 10px;
  background: rgba(246, 241, 228, 0.06); border: 1px solid var(--rule-soft);
  color: var(--ink); font: 400 16px/1.35 var(--body);
  transition: border-color 0.2s, background-color 0.2s;
}}
input:focus {{ outline: none; border-color: var(--gold); background: rgba(246, 241, 228, 0.09); }}
button {{
  appearance: none; border: 1px solid var(--gold); background: var(--gold); color: #16140d;
  border-radius: 999px; padding: 0.78rem 1.4rem; cursor: pointer;
  font: 600 0.92rem/1.1 var(--ui); letter-spacing: 0.1em; text-transform: uppercase;
  transition: background-color 0.2s, transform 0.2s, opacity 0.2s;
}}
button:hover {{ background: var(--gold-bright); transform: translateY(-1px); }}
button:disabled {{ opacity: 0.45; cursor: default; transform: none; }}
.err {{
  margin: 0; font: 500 0.86rem/1.35 var(--ui); color: #ea9c87;
  padding: 0.55rem 0.75rem; border-radius: 8px;
  background: rgba(214, 122, 99, 0.12); border: 1px solid rgba(214, 122, 99, 0.38);
}}
.hint {{ margin: 0.25rem 0 0; font: 400 0.78rem/1.4 var(--ui); color: var(--muted); }}
</style>
</head>
<body>
<main>
  <p class="brand">{esc_kicker}</p>
  <h1>{esc_title}</h1>
  <p class="sub">{esc_sub}</p>
  {pitch_html}
  <form id="gateForm" novalidate>
    <div>
      <label for="pass">Passphrase</label>
      <input id="pass" name="passphrase" type="text" autocomplete="off" autocapitalize="none" autocorrect="off" spellcheck="false" enterkeyhint="go" placeholder="Enter passphrase" autofocus required>
    </div>
    <p id="err" class="err" role="alert" hidden></p>
    <button id="go" type="submit">Enter &#8594;</button>
    <p class="hint">No account needed. Once unlocked, this browser remembers it.</p>
  </form>
</main>
<script>
"use strict";
const form = document.getElementById("gateForm");
const input = document.getElementById("pass");
const err = document.getElementById("err");
const btn = document.getElementById("go");
form.addEventListener("submit", async (e) => {{
  e.preventDefault();
  const passphrase = input.value.trim();
  if (!passphrase) {{ err.textContent = "Enter the passphrase."; err.hidden = false; input.focus(); return; }}
  btn.disabled = true;
  err.hidden = true;
  try {{
    const res = await fetch("{esc_unlock}", {{
      method: "POST",
      headers: {{"Content-Type": "application/json"}},
      body: JSON.stringify({{passphrase}}),
    }});
    const body = await res.json().catch(() => ({{}}));
    if (!res.ok) {{
      err.textContent = typeof body.detail === "string" ? body.detail : "Could not unlock right now.";
      err.hidden = false;
      input.select();
      return;
    }}
    location.reload();
  }} catch {{
    err.textContent = "Could not reach the server. Try again.";
    err.hidden = false;
  }} finally {{
    btn.disabled = false;
  }}
}});
</script>
</body>
</html>
"""


_GLOBE_PITCH = (
    "Real trips outside the US with close friends—mostly by working boat, river, or rail—to places "
    "with their own priorities instead of ones performing for tourists. Not danger tourism, not a resort "
    "itinerary, not a brochure."
)


def _verify_and_set_pass(request: Request, response: Response, passphrase: str) -> dict:
    _reject_if_limited(f"ip:{_asker_ip(request)}:longway-voyage-unlock", 15, 900)
    active = _active_passphrase_hash()
    if active is None:
        raise HTTPException(503, "No passphrase is set on this house yet.")
    if not hmac.compare_digest(_passphrase_hash(passphrase), active):
        raise HTTPException(403, "That's not it — try again.")
    is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(
        key=VOYAGE_PASS_COOKIE,
        value=_issue_pass_cookie(),
        max_age=VOYAGE_PASS_TTL,
        path="/",
        httponly=True,
        samesite="lax",
        secure=is_https,
    )
    return {"ok": True}


class VoyageUnlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passphrase: str = Field(min_length=1, max_length=120)


class PublicNotebookNote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["place", "thought"]
    by: str = Field(min_length=1, max_length=60)
    text: str = Field(min_length=1, max_length=2000)
    place: str | None = Field(default=None, max_length=120)
    about: str | None = Field(default=None, max_length=120)
    website: str = Field(default="", max_length=200)


@public.api_route("/globe", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def public_globe(request: Request):
    """Passphrase-gated 19-destination candidate globe; never includes trips or private details."""
    if not _has_valid_pass(request):
        return HTMLResponse(
            _gate_html(
                "/organ/longway/globe/unlock",
                "The Long Way",
                "Do we actually want to live through this, or just tell a story about it?",
                pitch=_GLOBE_PITCH,
                kicker="Private atlas · 19 journeys",
            ),
            headers=_PUBLIC_VOYAGE_HEADERS,
        )
    html = await asyncio.to_thread(get_register().globe_page)
    return HTMLResponse(html, headers=_PUBLIC_VOYAGE_HEADERS)


@public.post("/globe/unlock")
async def unlock_public_globe(request: Request, response: Response, body: VoyageUnlock):
    """Verify the shared voyage passphrase and unlock both /globe and all public voyages for 90 days."""
    return _verify_and_set_pass(request, response, body.passphrase)


@public.api_route("/voyage/{slug}", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def public_voyage(request: Request, slug: str, station: str | None = None):
    """Passphrase-gated voyage page for candidates with voyage.json; never trips, rides or private data."""
    register = get_register()
    meta = await notebook_call(register.public_voyage_meta, slug)
    if not _has_valid_pass(request):
        return HTMLResponse(
            _gate_html(f"/organ/longway/voyage/{slug}/unlock", meta["title"], meta["subtitle"]),
            headers=_PUBLIC_VOYAGE_HEADERS,
        )
    note_api = None if register.edit_disabled_reason() else f"/organ/longway/voyage/{slug}/notebook"
    html = await notebook_call(register.public_voyage_page, slug, station, note_api)
    return HTMLResponse(html, headers=_PUBLIC_VOYAGE_HEADERS)


@public.post("/voyage/{slug}/unlock")
async def unlock_public_voyage(request: Request, response: Response, slug: str, body: VoyageUnlock):
    """Verify the short shared voyage passphrase and issue a 90-day signed HttpOnly cookie."""
    await notebook_call(get_register().public_voyage_meta, slug)
    return _verify_and_set_pass(request, response, body.passphrase)


@public.post("/voyage/{slug}/notebook")
async def add_public_note(request: Request, slug: str, body: PublicNotebookNote):
    """A friend drops a place or thought on an unlocked voyage without signing in.

    Places wait in open state for the Scout to research and a house manager to review.
    """
    if not _has_valid_pass(request):
        raise HTTPException(401, "Enter the voyage passphrase first.")
    if body.website.strip():
        return {"ok": True, "note": None}
    _reject_if_limited(f"ip:{_asker_ip(request)}:longway-public-note", 20, 86400)
    saved = await notebook_call(
        get_register().add_public_note,
        slug, body.kind, body.by, body.text, body.place, body.about,
    )
    return {"ok": True, "note": saved["note"]}
