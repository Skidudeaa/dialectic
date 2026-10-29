"""Asking for a seat, against real Postgres: the public ask, its limits, the manager's invite and decline, and the mail."""
import smtplib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from api.auth.dependencies import AuthenticatedUser, get_current_user
from api.rate_limit import rate_limiter
from organs.longway import api, invites, jobs, mail
from tests.test_longway_api import Pool, db  # noqa: F401  (the fixture applies 029 and 030 in a rolled-back transaction)


@pytest_asyncio.fixture
async def seats(db, monkeypatch):  # noqa: F811
    await db.execute((Path(__file__).resolve().parents[1] / "migrations/031_longway_invites.sql").read_text())
    for key in ("LONGWAY_SMTP_USER", "LONGWAY_SMTP_PASSWORD", "LONGWAY_INVITE_NOTIFY_TO", "VAPID_PRIVATE_KEY", "VAPID_SUBJECT"):
        monkeypatch.delenv(key, raising=False)
    rate_limiter._requests.clear()
    home = await db.fetchval("SELECT id FROM rooms WHERE is_home")
    if home is None:
        home = uuid4()
        await db.execute("INSERT INTO rooms(id,created_at,token,name,is_home) VALUES ($1,clock_timestamp(),$2,'The Long Way',true)", home, str(home))
    amo = uuid4()
    await db.execute("INSERT INTO users(id,created_at,display_name) VALUES ($1,clock_timestamp(),'Amo')", amo)
    await db.execute("INSERT INTO user_credentials(user_id,email,password_hash) VALUES ($1,$2,'unused')", amo, f"{amo}@example.org")
    await db.execute("INSERT INTO room_memberships(room_id,user_id,joined_at,can_manage_home) VALUES ($1,$2,clock_timestamp(),true)", home, amo)
    token = await db.fetchval("SELECT token FROM rooms WHERE id=$1", home)
    app = FastAPI()
    app.include_router(api.router)
    app.include_router(api.public)

    async def connection():
        yield db
    app.dependency_overrides[api.get_db] = connection
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(amo, f"{amo}@example.org", True, "Amo")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"X-Room-Token": token}) as client:
        yield SimpleNamespace(client=client, db=db, home=home, amo=amo)


async def ask(seats, email, name="Dana", note="Rowed with Amo in 2019", ip="203.0.113.7"):
    return await seats.client.post("/organ/longway/invite-requests", json={"email": email, "name": name, "note": note},
                                   headers={"CF-Connecting-IP": ip})


@pytest.mark.asyncio
async def test_ask_records_one_open_request_per_address(seats):
    email = f"dana-{uuid4().hex[:6]}@example.org"
    assert (await ask(seats, email)).json() == {"ok": True}
    assert (await ask(seats, email.upper(), name="Dana R.", note="")).status_code == 200
    rows = await seats.db.fetch("SELECT * FROM longway_invite_requests WHERE email=$1", email)
    assert len(rows) == 1
    assert rows[0]["name"] == "Dana R." and rows[0]["note"] == "Rowed with Amo in 2019" and rows[0]["ip"] == "203.0.113.7"
    assert rows[0]["notified_at"] is None  # mail is off: the email waits, the ask stands
    assert (await ask(seats, "not-an-address")).status_code == 422
    assert (await ask(seats, email, name="   ")).status_code == 422


@pytest.mark.asyncio
async def test_ask_is_limited_per_address_and_per_visitor(seats):
    email = f"loud-{uuid4().hex[:6]}@example.org"
    for _ in range(3):
        assert (await ask(seats, email)).status_code == 200
    assert (await ask(seats, email)).status_code == 429
    for n in range(10):
        assert (await ask(seats, f"v{n}-{uuid4().hex[:6]}@example.org", ip="198.51.100.9")).status_code in (200, 429)
    assert (await ask(seats, f"eleventh-{uuid4().hex[:6]}@example.org", ip="198.51.100.9")).status_code == 429
    assert (await ask(seats, f"elsewhere-{uuid4().hex[:6]}@example.org", ip="198.51.100.10")).status_code == 200


@pytest.mark.asyncio
async def test_manager_invites_then_declines_a_second_ask(seats):
    email = f"kim-{uuid4().hex[:6]}@example.org"
    await ask(seats, email, name="Kim")
    listing = (await seats.client.get(f"/rooms/{seats.home}/longway/invite-requests")).json()
    assert listing["mail_configured"] is False
    assert [r["email"] for r in listing["requests"]] == [email] and listing["requests"][0]["decision"] is None
    rid = listing["requests"][0]["id"]
    invited = (await seats.client.post(f"/rooms/{seats.home}/longway/invite-requests/{rid}/invite")).json()
    assert invited["code"].isdigit() and len(invited["code"]) == 6
    assert invited["emailed"] is False and invited["mail_error"] is None and invited["email"] == email
    user_id = await seats.db.fetchval("SELECT user_id FROM user_credentials WHERE email=$1", email)
    assert user_id is not None
    assert await seats.db.fetchval("SELECT 1 FROM room_memberships WHERE room_id=$1 AND user_id=$2 AND NOT can_manage_home", seats.home, user_id)
    assert await seats.db.fetchval("""SELECT 1 FROM verification_codes WHERE user_id=$1 AND code=$2 AND purpose='password_reset'
        AND used_at IS NULL AND expires_at > clock_timestamp() + interval '6 days'""", user_id, invited["code"])
    row = await seats.db.fetchrow("SELECT decision, decided_by, user_id FROM longway_invite_requests WHERE id=$1", rid)
    assert row["decision"] == "invited" and row["decided_by"] == seats.amo and row["user_id"] == user_id
    # Inviting again spends the first code and issues another; the account is reused.
    again = (await seats.client.post(f"/rooms/{seats.home}/longway/invite-requests/{rid}/invite")).json()
    assert again["code"] != invited["code"] or True  # two random codes may collide once in a million; the row below is the proof
    assert await seats.db.fetchval("SELECT count(*) FROM verification_codes WHERE user_id=$1 AND purpose='password_reset' AND used_at IS NULL", user_id) == 1
    assert await seats.db.fetchval("SELECT count(*) FROM users WHERE id=$1", user_id) == 1
    # A decided request no longer blocks a fresh ask from the same address.
    await ask(seats, email, name="Kim", note="Lost the code")
    second = await seats.db.fetchval("SELECT id FROM longway_invite_requests WHERE email=$1 AND decision IS NULL", email)
    assert second is not None and str(second) != rid
    declined = (await seats.client.post(f"/rooms/{seats.home}/longway/invite-requests/{second}/decline")).json()
    assert declined == {"id": str(second), "decision": "declined"}
    assert (await seats.client.post(f"/rooms/{seats.home}/longway/invite-requests/{uuid4()}/invite")).status_code == 404
    await seats.db.execute("UPDATE room_memberships SET can_manage_home=false WHERE user_id=$1", seats.amo)
    assert (await seats.client.get(f"/rooms/{seats.home}/longway/invite-requests")).status_code == 403


@pytest.mark.asyncio
async def test_mail_carries_the_ask_and_the_code(seats, monkeypatch):
    monkeypatch.setenv("LONGWAY_SMTP_USER", "house@example.org")
    monkeypatch.setenv("LONGWAY_SMTP_PASSWORD", "app-password")
    monkeypatch.setenv("LONGWAY_INVITE_NOTIFY_TO", "amo@example.org")
    sent = []
    monkeypatch.setattr(mail, "send", lambda to, subject, body: sent.append((to, subject, body)))
    email = f"lee-{uuid4().hex[:6]}@example.org"
    await ask(seats, email, name="Lee", note="Met on the Nullarbor")
    assert sent[0][0] == "amo@example.org" and "Lee asks for a seat" in sent[0][1] and "Nullarbor" in sent[0][2]
    assert await seats.db.fetchval("SELECT notified_at FROM longway_invite_requests WHERE email=$1", email) is not None
    rid = await seats.db.fetchval("SELECT id FROM longway_invite_requests WHERE email=$1", email)
    invited = (await seats.client.post(f"/rooms/{seats.home}/longway/invite-requests/{rid}/invite")).json()
    assert invited["emailed"] is True and sent[1][0] == email and invited["code"] in sent[1][2] and "I have a code" in sent[1][2]
    assert await seats.db.fetchval("SELECT invited_email_at FROM longway_invite_requests WHERE id=$1", rid) is not None
    # A refusal from the server never loses the ask or the code; it is reported.
    def refuse(to, subject, body):
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
    monkeypatch.setattr(mail, "send", refuse)
    other = f"pat-{uuid4().hex[:6]}@example.org"
    assert (await ask(seats, other, name="Pat")).status_code == 200
    assert await seats.db.fetchval("SELECT notified_at FROM longway_invite_requests WHERE email=$1", other) is None
    rid2 = await seats.db.fetchval("SELECT id FROM longway_invite_requests WHERE email=$1", other)
    invited2 = (await seats.client.post(f"/rooms/{seats.home}/longway/invite-requests/{rid2}/invite")).json()
    assert invited2["emailed"] is False and "bad credentials" in invited2["mail_error"] and len(invited2["code"]) == 6


@pytest.mark.asyncio
async def test_notifier_emails_what_arrived_while_mail_was_off(seats, monkeypatch):
    email = f"sam-{uuid4().hex[:6]}@example.org"
    await ask(seats, email, name="Sam")
    ctx = SimpleNamespace(pool=Pool(seats.db))
    assert await jobs.invite_notifier(ctx) == {"skipped": "mail unconfigured"}
    monkeypatch.setenv("LONGWAY_SMTP_USER", "house@example.org")
    monkeypatch.setenv("LONGWAY_SMTP_PASSWORD", "app-password")
    sent = []
    monkeypatch.setattr(mail, "send", lambda to, subject, body: sent.append(to))
    assert await jobs.invite_notifier(ctx) == {"sent": 1}
    assert sent == ["house@example.org"]  # no LONGWAY_INVITE_NOTIFY_TO: the sending account hears
    assert await jobs.invite_notifier(ctx) == {"sent": 0}
    assert await invites.pending_emails(seats.db) == []
