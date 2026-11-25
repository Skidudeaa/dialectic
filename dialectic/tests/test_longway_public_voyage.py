"""Public voyage page and no-sign-in friend notebook endpoint on /organ/longway/voyage/{slug}."""
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
    app = FastAPI()
    app.include_router(api.public)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, voyage_repo


@pytest.mark.asyncio
async def test_public_voyage_serves_live_html_and_refuses_non_voyages(public_client, monkeypatch):
    client, repo = public_client
    res = await client.get("/organ/longway/voyage/nile")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/html")
    assert res.headers["cache-control"] == "no-store"
    assert res.headers["x-robots-tag"] == "noindex, nofollow"
    assert res.headers["referrer-policy"] == "no-referrer"
    assert '"noteApi": "/organ/longway/voyage/nile/notebook"' in res.text
    assert '<meta property="og:title" content="Fixture Nile — The Long Way">' in res.text
    assert '<meta property="og:description"' in res.text

    head_res = await client.head("/organ/longway/voyage/nile")
    assert head_res.status_code == 200
    assert head_res.headers["x-robots-tag"] == "noindex, nofollow"

    stop_res = await client.get("/organ/longway/voyage/nile?station=aswan")
    assert stop_res.status_code == 200
    assert '"station": "aswan"' in stop_res.text

    bad_stop = await client.get("/organ/longway/voyage/nile?station=atlantis")
    assert bad_stop.status_code == 400

    # Trips, candidates without voyage.json, and missing slugs must 404.
    for slug in ("friends-2027", "banda-islands", "missing", "bad_slug"):
        assert (await client.get(f"/organ/longway/voyage/{slug}")).status_code == 404

    # When commits are off, the page still opens read-only without exposing noteApi.
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED", "0")
    readonly = await client.get("/organ/longway/voyage/nile")
    assert readonly.status_code == 200
    assert '"noteApi":' not in readonly.text
    assert "const HOST = null;" in readonly.text


@pytest.mark.asyncio
async def test_public_notebook_commits_friend_notes_and_guards_writes(public_client, monkeypatch):
    client, repo = public_client
    root = repo.root
    head = git(root, "rev-parse", "HEAD")

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
