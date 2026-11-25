"""Passphrase-gated public voyage page and no-sign-in friend notebook on /organ/longway/voyage/{slug}."""
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from api.rate_limit import rate_limiter
from organs.longway import api
from tests.test_longway_register import git, longway_repo, voyage_repo  # noqa: F401


@pytest_asyncio.fixture
async def public_client(voyage_repo, monkeypatch):  # noqa: F811
    rate_limiter._requests.clear()
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED", "1")
    monkeypatch.setenv("LONGWAY_VOYAGE_PASSPHRASE", "testpass")
    app = FastAPI()
    app.include_router(api.public)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, voyage_repo


async def unlock(client, slug="nile", passphrase="  TestPass  ", ip="203.0.113.41"):
    return await client.post(
        f"/organ/longway/voyage/{slug}/unlock",
        json={"passphrase": passphrase},
        headers={"CF-Connecting-IP": ip},
    )


@pytest.mark.asyncio
async def test_public_voyage_gates_behind_passphrase_then_serves_live_html(public_client, monkeypatch):
    client, repo = public_client

    # Locked request returns the passphrase gate with zero voyage data or noteApi.
    locked = await client.get("/organ/longway/voyage/nile")
    assert locked.status_code == 200
    assert locked.headers["content-type"].startswith("text/html")
    assert locked.headers["cache-control"] == "private, no-store"
    assert locked.headers["x-robots-tag"] == "noindex, nofollow"
    assert locked.headers["referrer-policy"] == "no-referrer"
    assert "Enter passphrase" in locked.text
    assert '"noteApi":' not in locked.text
    assert "A sail rounds the bend." not in locked.text

    # Trips, candidates without voyage.json, and missing slugs still 404 (never show a gate).
    for slug in ("friends-2027", "banda-islands", "missing", "bad_slug"):
        assert (await client.get(f"/organ/longway/voyage/{slug}")).status_code == 404
        assert (await unlock(client, slug=slug)).status_code == 404

    # Posting a note before unlocking is refused with 401.
    unauth = await client.post(
        "/organ/longway/voyage/nile/notebook",
        json={"kind": "thought", "by": "Sam", "text": "Blocked"},
        headers={"CF-Connecting-IP": "203.0.113.41"},
    )
    assert unauth.status_code == 401

    # Wrong passphrase returns 403 and sets no cookie; forged cookie is ignored.
    wrong = await unlock(client, passphrase="nope")
    assert wrong.status_code == 403
    assert api.VOYAGE_PASS_COOKIE not in client.cookies
    client.cookies.set(api.VOYAGE_PASS_COOKIE, "v1.9999999999.deadbeef")
    assert "Enter passphrase" in (await client.get("/organ/longway/voyage/nile")).text
    client.cookies.clear()

    # Correct passphrase (case- and whitespace-insensitive) sets HttpOnly cookie and unlocks.
    ok = await unlock(client, passphrase="  TestPass  ")
    assert ok.status_code == 200 and ok.json() == {"ok": True}
    assert api.VOYAGE_PASS_COOKIE in client.cookies

    res = await client.get("/organ/longway/voyage/nile")
    assert res.status_code == 200
    assert "A sail rounds the bend." in res.text
    assert '"noteApi": "/organ/longway/voyage/nile/notebook"' in res.text
    assert '<meta property="og:title" content="Fixture Nile — The Long Way">' in res.text
    assert '<meta property="og:description"' in res.text

    head_res = await client.head("/organ/longway/voyage/nile")
    assert head_res.status_code == 200
    assert head_res.headers["x-robots-tag"] == "noindex, nofollow"

    stop_res = await client.get("/organ/longway/voyage/nile?station=aswan")
    assert stop_res.status_code == 200
    assert '"station": "aswan"' in stop_res.text

    assert (await client.get("/organ/longway/voyage/nile?station=atlantis")).status_code == 400

    # Rotating the passphrase invalidates old cookies immediately.
    monkeypatch.setenv("LONGWAY_VOYAGE_PASSPHRASE", "rotated")
    assert "Enter passphrase" in (await client.get("/organ/longway/voyage/nile")).text
    monkeypatch.setenv("LONGWAY_VOYAGE_PASSPHRASE", "testpass")

    # When commits are off, the unlocked page still opens read-only without exposing noteApi.
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED", "0")
    readonly = await client.get("/organ/longway/voyage/nile")
    assert readonly.status_code == 200
    assert '"noteApi":' not in readonly.text
    assert "const HOST = null;" in readonly.text


@pytest.mark.asyncio
async def test_unlock_rate_limits_brute_force(public_client):
    client, _ = public_client
    ip = "198.51.100.55"
    for _ in range(15):
        assert (await unlock(client, passphrase="wrong", ip=ip)).status_code == 403
    assert (await unlock(client, passphrase="testpass", ip=ip)).status_code == 429


@pytest.mark.asyncio
async def test_public_globe_shares_passphrase_cookie_and_omits_trips(public_client):
    client, repo = public_client
    # Copy templates/globe.html and land-50m.json into the synthetic repo so globe_page renders live.
    import shutil
    from pathlib import Path
    src = Path("/root/theLongWay/templates")
    for name in ("globe.html", "land-50m.json"):
        shutil.copyfile(src / name, repo.root / "templates" / name)

    locked = await client.get("/organ/longway/globe")
    assert locked.status_code == 200
    assert locked.headers["cache-control"] == "private, no-store"
    assert locked.headers["x-robots-tag"] == "noindex, nofollow"
    assert "Enter passphrase" in locked.text
    assert "Not danger tourism" in locked.text
    assert "const DATA =" not in locked.text

    # Wrong passphrase refused.
    bad = await client.post(
        "/organ/longway/globe/unlock",
        json={"passphrase": "nope"},
        headers={"CF-Connecting-IP": "203.0.113.88"},
    )
    assert bad.status_code == 403

    # Unlocking via /globe/unlock opens BOTH /globe and /voyage/nile with the same cookie.
    ok = await client.post(
        "/organ/longway/globe/unlock",
        json={"passphrase": "testpass"},
        headers={"CF-Connecting-IP": "203.0.113.88"},
    )
    assert ok.status_code == 200 and ok.json() == {"ok": True}

    globe = await client.get("/organ/longway/globe")
    assert globe.status_code == 200
    assert "const DATA =" in globe.text
    assert "Not danger tourism" in globe.text
    assert "Fixture Nile" in globe.text
    assert "friends-2027" not in globe.text  # trips never appear on the globe

    head_globe = await client.head("/organ/longway/globe")
    assert head_globe.status_code == 200

    # Same cookie immediately opens /voyage/nile without re-entering the passphrase.
    nile = await client.get("/organ/longway/voyage/nile")
    assert nile.status_code == 200 and "A sail rounds the bend." in nile.text


@pytest.mark.asyncio
async def test_public_notebook_commits_friend_notes_and_guards_writes(public_client, monkeypatch):
    client, repo = public_client
    root = repo.root
    head = git(root, "rev-parse", "HEAD")

    assert (await unlock(client)).status_code == 200

    # Add a place with just a name (no sign-in).
    res = await client.post(
        "/organ/longway/voyage/nile/notebook",
        json={"kind": "place", "by": "  Sam <K> ", "place": "Dendera", "text": "The zodiac ceiling is wild."},
        headers={"CF-Connecting-IP": "203.0.113.41"},
    )
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["ok"] is True
    assert "commit" not in payload
    note = payload["note"]
    assert note["id"] == "N1" and note["kind"] == "place" and note["state"] == "open"
    assert note["by"] == "Sam K" and note["place"] == "Dendera"
    assert git(root, "rev-parse", "HEAD^") == head
    assert git(root, "log", "-1", "--format=%an <%ae>") == "Sam K <friend@thelongway.world>"
    msg = git(root, "log", "-1", "--format=%B")
    assert "Added-In: The Long Way house" in msg
    assert "Via: Public voyage page" in msg
    assert git(root, "show", "--format=", "--name-only", "HEAD").splitlines() == ["candidates/nile/notebook.jsonl"]

    # Add a thought anchored to a stop.
    thought = await client.post(
        "/organ/longway/voyage/nile/notebook",
        json={"kind": "thought", "by": "Mike", "text": "Stay on the deck at sunset.", "about": "aswan"},
        headers={"CF-Connecting-IP": "203.0.113.41"},
    )
    assert thought.status_code == 200
    assert thought.json()["note"]["about"] == "aswan"

    # Both notes immediately render on the live public page.
    html = (await client.get("/organ/longway/voyage/nile")).text
    assert "The zodiac ceiling is wild." in html
    assert "Stay on the deck at sunset." in html

    # Honeypot silently drops automated spam without touching git.
    before_hp = git(root, "rev-parse", "HEAD")
    hp = await client.post(
        "/organ/longway/voyage/nile/notebook",
        json={"kind": "thought", "by": "Bot", "text": "Buy cheap rugs", "website": "https://spam.example"},
        headers={"CF-Connecting-IP": "203.0.113.41"},
    )
    assert hp.status_code == 200 and hp.json() == {"ok": True, "note": None}
    assert git(root, "rev-parse", "HEAD") == before_hp

    # Validation & boundary checks.
    assert (await client.post(
        "/organ/longway/voyage/nile/notebook",
        json={"kind": "thought", "by": "   ", "text": "Hello"},
        headers={"CF-Connecting-IP": "203.0.113.41"},
    )).status_code == 400
    assert (await client.post(
        "/organ/longway/voyage/nile/notebook",
        json={"kind": "thought", "by": "Mike", "text": "Hello", "about": "atlantis"},
        headers={"CF-Connecting-IP": "203.0.113.41"},
    )).status_code == 400
    for slug in ("friends-2027", "banda-islands", "missing"):
        assert (await client.post(
            f"/organ/longway/voyage/{slug}/notebook",
            json={"kind": "thought", "by": "Mike", "text": "Hello"},
            headers={"CF-Connecting-IP": "203.0.113.41"},
        )).status_code == 404

    # Dirty file or disabled commits return 409 and never clobber.
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED", "0")
    assert (await client.post(
        "/organ/longway/voyage/nile/notebook",
        json={"kind": "thought", "by": "Mike", "text": "Disabled"},
        headers={"CF-Connecting-IP": "203.0.113.41"},
    )).status_code == 409
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED", "1")
    nb_path = root / "candidates/nile/notebook.jsonl"
    orig = nb_path.read_bytes()
    nb_path.write_bytes(orig + b"dirty")
    assert (await client.post(
        "/organ/longway/voyage/nile/notebook",
        json={"kind": "thought", "by": "Mike", "text": "Dirty"},
        headers={"CF-Connecting-IP": "203.0.113.41"},
    )).status_code == 409
    nb_path.write_bytes(orig)

    # Rate limit enforces 20 notes/day per IP.
    ip = "198.51.100.77"
    for i in range(20):
        r = await client.post(
            "/organ/longway/voyage/nile/notebook",
            json={"kind": "thought", "by": "Sam", "text": f"Note {i}"},
            headers={"CF-Connecting-IP": ip},
        )
        assert r.status_code == 200
    limited = await client.post(
        "/organ/longway/voyage/nile/notebook",
        json={"kind": "thought", "by": "Sam", "text": "One too many"},
        headers={"CF-Connecting-IP": ip},
    )
    assert limited.status_code == 429


@pytest.mark.asyncio
async def test_a_house_with_no_passphrase_in_its_environment_opens_for_nobody(public_client, monkeypatch):
    client, _ = public_client
    assert (await unlock(client)).status_code == 200
    assert "A sail rounds the bend." in (await client.get("/organ/longway/voyage/nile")).text
    monkeypatch.delenv("LONGWAY_VOYAGE_PASSPHRASE")
    monkeypatch.delenv("LONGWAY_VOYAGE_PASSPHRASE_HASH", raising=False)
    # No verifier is kept in the code, so with nothing set no passphrase and no earlier cookie opens the door.
    for guess in ("testpass", "anything"):
        refused = await unlock(client, passphrase=guess, ip="203.0.113.77")
        assert refused.status_code == 503 and "No passphrase is set" in refused.json()["detail"]
    globe = await client.post("/organ/longway/globe/unlock", json={"passphrase": "testpass"},
                              headers={"CF-Connecting-IP": "203.0.113.78"})
    assert globe.status_code == 503
    assert "Enter passphrase" in (await client.get("/organ/longway/globe")).text
    locked = await client.get("/organ/longway/voyage/nile")
    assert "Enter passphrase" in locked.text and "A sail rounds the bend." not in locked.text
    note = await client.post("/organ/longway/voyage/nile/notebook", json={"kind": "thought", "by": "Sam", "text": "Blocked"},
                             headers={"CF-Connecting-IP": "203.0.113.77"})
    assert note.status_code == 401
