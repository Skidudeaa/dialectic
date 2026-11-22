"""The house notebook through HTTP, the research tool loop, and the real register in a temp repo."""
import asyncio
import base64
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest

from organs.longway import api, fixes, jobs, photos, scout
from organs.longway.identity import journey_brief
from organs.longway.tools import build_tools
from tests.conftest import make_room
from tests.test_longway_api import client, db, home_room, house, make_manager
from tests.test_longway_register import git, longway_repo, voyage_repo
from tests.test_longway_scout_run import response
from tests.test_longway_tools import post_message

PLACE = dict(kind="place", place="Dendera", text="I want to see the zodiac ceiling.")
PHOTO = "File:Dendera temple.jpg"
SOURCES = [
    dict(url="https://egymonuments.gov.eg/temples", claim="The hall has a painted ceiling.",
         phrase="a painted ceiling", scope="inside the hall"),
    dict(url="https://egymonuments.gov.eg/visits", claim="The group can arrive by ferry.",
         phrase="by ferry from Luxor", scope="visitor access"),
]
PAGES = ["The hall has a painted ceiling at 26.14 N, 32.67 E.", "Groups can arrive by ferry from Luxor."]
DRAFT = dict(note_id="N1", name="Dendera", lat=26.14, lon=32.67, after="aswan",
             moment={"text": "Look up at the ceiling.", "cite": ["E1"]},
             text="Arrive by ferry [E2].", photo_title=PHOTO, sources=SOURCES, status="Ready for a look.")
STEER = "Find a photograph of the temple from the water."


def file_page(title=PHOTO, licence="CC BY-SA 4.0", width=2400, **metadata):
    return {"title": title, "imageinfo": [{
        "width": width, "height": 1600, "mime": "image/jpeg", "thumbwidth": min(width, 1600),
        "thumburl": "https://upload.wikimedia.org/test.jpg", "descriptionurl": "https://commons.wikimedia.org/wiki/" + title,
        "extmetadata": {"Artist": {"value": "<a>Fixture &amp; friend</a>"}, "LicenseShortName": {"value": licence},
                        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0/"},
                        **{key: {"value": value} for key, value in metadata.items()}},
    }]}


def snapshot(root):
    return {p.name: p.read_bytes() for p in (root / "candidates/nile").iterdir() if p.is_file()}


def changed(root):
    return git(root, "show", "--format=", "--name-only", "HEAD").splitlines()


@pytest.mark.asyncio
async def test_member_notebook_and_manager_guards(client, db, house, home_room, voyage_repo, monkeypatch):
    root = voyage_repo.root
    base = f"/rooms/{home_room['id']}/longway"
    url = base + "/notebook/nile"
    client.headers["X-Room-Token"] = home_room["token"]
    assert (await client.get(url)).status_code == 403
    await db.execute("INSERT INTO room_memberships(room_id,user_id,joined_at) VALUES ($1,$2,now())",
                     home_room["id"], house.user.user_id)
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED", "1")
    head = git(root, "rev-parse", "HEAD")
    assert "notebook.jsonl" not in snapshot(root)
    added = await client.post(url, json=PLACE)
    assert added.status_code == 200, added.text
    note, sha = added.json()["note"], added.json()["commit"]
    assert note["state"] == "open" and note["by"] == "Alice" and note["place"] == "Dendera"
    assert git(root, "rev-parse", "HEAD^") == head and git(root, "rev-parse", "HEAD") == sha
    assert git(root, "log", "-1", "--format=%an <%ae>") == f"Alice <{house.user.email}>"
    assert git(root, "log", "-1", "--format=%B") == "Note nile N1: Dendera\n\nAdded-In: The Long Way house"
    assert changed(root) == ["candidates/nile/notebook.jsonl"]
    assert (await client.get(url)).json() == dict(slug="nile", notes=[note], writable=True, can_review=False, why=None)
    monkeypatch.setattr(fixes, "fetch_feed", AsyncMock(return_value={"fixes": {}}))
    chart = (await client.get(base + "/chart")).json()
    assert next(j for j in chart["journeys"] if j["slug"] == "nile")["notes"] == {"open": 1}
    before = snapshot(root)
    refusal = await client.post(url, json=dict(kind="thought", text="Stay here", about="Atlantis"))
    assert refusal.status_code == 400 and refusal.json()["detail"] == "'Atlantis' is not a stop of this journey"
    for method, path in (("POST", url + "/N1/accept"), ("POST", url + "/N1/set-aside"),
                         ("GET", base + "/voyage/nile/page?preview=N1"), ("POST", url + "/scout")):
        res = await client.request(method, path)
        assert res.status_code == 403 and "house manager" in res.json()["detail"]
    back = await client.post(url + "/N1/send-back", json={"why": STEER})
    assert back.status_code == 403 and "house manager" in back.json()["detail"]
    assert not await db.fetchval("SELECT 1 FROM longway_scout_runs WHERE journey='nile'")
    for slug in ("friends-2027", "missing"):
        assert (await client.get(base + "/notebook/" + slug)).status_code == 404
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED", "0")
    assert (await client.get(url)).json()["writable"] is False
    assert (await client.post(url, json=PLACE)).status_code == 409
    assert git(root, "rev-parse", "HEAD") == sha and snapshot(root) == before
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED", "1")
    path = root / changed(root)[0]
    path.write_bytes(before["notebook.jsonl"] + b"dirty")
    dirty = await client.post(url, json=PLACE)
    assert dirty.status_code == 409 and "uncommitted" in dirty.json()["detail"]
    assert path.read_bytes().endswith(b"dirty") and git(root, "rev-parse", "HEAD") == sha


@pytest.mark.asyncio
async def test_send_back_research_refusal_correction_preview_and_accept(client, db, house, home_room, voyage_repo, monkeypatch, tmp_path):
    root = voyage_repo.root
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED", "1")
    monkeypatch.setenv("LONGWAY_SEARCH_PROVIDER", "none")
    monkeypatch.delenv("LONGWAY_FIRECRAWL_KEY", raising=False)
    await make_manager(db, home_room, house.user.user_id)
    client.headers["X-Room-Token"] = home_room["token"]
    base = f"/rooms/{home_room['id']}/longway"
    url, page = base + "/notebook/nile", base + "/voyage/nile/page"
    assert (await client.post(url + "/scout")).status_code == 409
    voyage_repo.add_note("nile", "place", PLACE["text"], "Dendera", None, "Mira", "mira@localhost")
    await client.post(url, json=dict(kind="thought", text="Leave time on deck.", about="aswan"))
    assert (await client.get(page + "?preview=N1")).status_code == 400
    assert (await client.post(url + "/N7/accept")).status_code == 404
    back_url = url + "/N1/send-back"
    no_draft = await client.post(back_url, json={"why": STEER})
    assert no_draft.status_code == 400 and no_draft.json()["detail"] == "N1 has no draft to send back"
    first = voyage_repo.draft_note("nile", "N1", dict(name="Dendera", lat=26.14, lon=32.67, after="aswan"), "First try")
    before = snapshot(root)
    blank = await client.post(back_url, json={"why": "   "})
    assert blank.status_code == 400 and blank.json()["detail"] == "Say what to change, in a few words"
    assert snapshot(root) == before and git(root, "rev-parse", "HEAD") == first["commit"]
    back = await client.post(back_url, json={"why": STEER})
    assert back.status_code == 200, back.text
    assert git(root, "rev-parse", "HEAD") == back.json()["commit"]
    assert git(root, "rev-parse", "HEAD^") == first["commit"] and changed(root) == ["candidates/nile/notebook.jsonl"]
    assert git(root, "log", "-1", "--format=%an <%ae>") == f"Alice <{house.user.email}>"
    assert git(root, "log", "-1", "--format=%B") == "Send back nile N1: Dendera\n\nSent-Back-In: The Long Way house"
    reopened = (await client.get(url)).json()["notes"][0]
    assert reopened == back.json()["note"] and reopened["state"] == "open" and "draft" not in reopened
    assert reopened["steer"] == dict(by="Alice", at=voyage_repo.module.today(), text=STEER)
    agenda_line = f"N1 · place · Dendera · Mira: {PLACE['text']} · open · Alice sent the last draft back: {STEER}"
    assert agenda_line in journey_brief("nile").split("### From friends")[1]
    initial, head = snapshot(root), git(root, "rev-parse", "HEAD")
    entered, resume = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(api, "_pool", house.pool)
    monkeypatch.setattr(api, "scout_context", lambda: SimpleNamespace(broadcast=None))
    river_view = "Beyond the boat's bow are six columns with faces, lit from the side."
    titles = ["File:Nearby building.jpg", "File:Unavailable.jpg", PHOTO]
    metadata = dict(ImageDescription="Temple of Hathor at Dendera", DateTimeOriginal="2015-05-25")
    api_times = []
    copies = {1: b"\xff\xd8\xffexterior", 3: b"\x89PNG\r\n\x1a\ncolumns"}

    def commons(request):
        assert "TheLongWayScout" in request.headers["User-Agent"]
        if request.url.host == "upload.wikimedia.org":
            number = int(request.url.path[1:])
            if number == 2:
                return httpx.Response(404)
            return httpx.Response(200, content=copies[number],
                                  headers={"Content-Type": "image/jpeg" if number == 1 else "image/png"})
        assert request.url.host == "commons.wikimedia.org"
        api_times.append(photos.time.monotonic())
        params = request.url.params
        if "generator" in params:
            assert params["gsrsearch"] == "Dendera temple ceiling"
            pages = [file_page(title, **metadata) for title in titles]
        else:
            assert params["titles"].split("|") == titles and int(params["iiurlwidth"]) <= 500
            pages = [{"title": title, "imageinfo": [{"thumburl": f"https://upload.wikimedia.org/{n}", "thumbwidth": 500}]}
                     for n, title in reversed(list(enumerate(titles, 1)))]
        return httpx.Response(200, json={"query": {"pages": dict(enumerate(pages))}})

    factory = httpx.AsyncClient
    monkeypatch.setattr(photos.httpx, "AsyncClient", lambda **kw: factory(transport=httpx.MockTransport(commons), **kw))
    monkeypatch.setattr(photos.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setenv("DIALECTIC_VISION_ENABLED", "1")
    monkeypatch.setenv("LONGWAY_SCOUT_MODEL", "fixture-scout")
    monkeypatch.setenv("LONGWAY_SCOUT_BUDGET_OUTPUT_TOKENS", "500")
    articles = {s["url"]: dict(content=text, site="Fixture museum") for s, text in zip(SOURCES, PAGES)}
    read = AsyncMock(side_effect=articles.__getitem__)
    monkeypatch.setattr(scout.defuddle_client, "extract_article", read)

    class Script:
        client = SimpleNamespace(aclose=AsyncMock())
        step = 0

        async def complete(self, request):
            assert request.model == "fixture-scout"
            if not request.tools:
                assert "Describe only what is visible" in request.system and request.max_tokens == 489
                assert len(request.messages) == 1
                blocks = request.messages[0]["content"]
                assert [b["type"] for b in blocks] == ["text", "image", "text", "image"]
                assert [b["text"] for b in blocks[::2]] == ["Picture 1", "Picture 3"]
                assert [base64.b64decode(b["source"]["data"]) for b in blocks[1::2]] == [copies[1], copies[3]]
                return replace(response(), content=f"3. {river_view}\n1. A small building with a square doorway.")
            self.step += 1
            if self.step == 1:
                assert agenda_line in request.messages[0]["content"]
                assert "N2 · thought · aswan · Alice: Leave time on deck." in request.messages[0]["content"]
                entered.set()
                await resume.wait()
                return response("find_photo", {"query": "Dendera temple ceiling"})
            tool_result = json.loads(request.messages[-1]["content"][0]["content"])
            if self.step == 2:
                found = tool_result["photos"]
                assert [p["shows"] for p in found] == ["A small building with a square doorway.", "could not be viewed", river_view]
                assert {p["description"] for p in found} == {metadata["ImageDescription"]}
                self.selected = next(p["title"] for p in found if p["shows"] == river_view)
                return response("draft_stop", dict(DRAFT, photo_title="File:Never returned.jpg"))
            if self.step == 3:
                assert not tool_result["filed"] and "find_photo returned" in tool_result["why"]
                assert snapshot(root) == initial and git(root, "rev-parse", "HEAD") == head
                return response("draft_stop", dict(DRAFT, sources=[SOURCES[0], dict(SOURCES[1], phrase="by air from Aswan")]))
            if self.step == 4:
                assert not tool_result["filed"] and "E2: the page does not contain" in tool_result["why"]
                assert snapshot(root) == initial and git(root, "rev-parse", "HEAD") == head
                return response("draft_stop", dict(DRAFT, photo_title=self.selected))
            assert tool_result["state"] == "drafted"
            return response()

    monkeypatch.setattr(scout, "AnthropicProvider", Script)
    started = await client.post(url + "/scout")
    assert started.status_code == 200, started.text
    task = scout._TASKS[UUID(started.json()["run_id"])]
    try:
        await asyncio.wait_for(entered.wait(), 5)
        conflict = await client.post(url + "/scout")
        assert conflict.status_code == 409 and "already running" in conflict.json()["detail"]
    finally:
        resume.set()
    receipt = await task
    assert receipt["status"] == "done", receipt["error"]
    assert receipt["room_id"] == home_room["id"] and receipt["pages_read"] == read.await_count == 2
    assert len(api_times) == 2 and api_times[1] - api_times[0] >= 1.9
    assert receipt["input_tokens"] == 6 * 17 and receipt["output_tokens"] == 6 * 11
    assert [e["viewed"] for e in receipt["log"] if e["tool"] == "find_photo"] == [2]
    assert git(root, "rev-parse", "HEAD^") == head
    assert changed(root) == ["candidates/nile/notebook.jsonl"]
    assert git(root, "log", "-1", "--format=%an <%ae>") == "The Long Way Scout <scout@thelongway.world>"
    notes = (await client.get(url)).json()["notes"]
    assert notes[0]["state"] == "drafted"
    draft = notes[0]["draft"]
    assert [r["support"] for r in draft["evidence"]] == PAGES
    assert all(r["status"] == "verified" and r["publisher"] == "Fixture museum" and
               r["checked_at"] == voyage_repo.module.today() for r in draft["evidence"])
    assert draft["photo"]["author"] == "Fixture & friend"
    assert draft["photo"]["page"].endswith(PHOTO)
    assert set(draft["photo"]) == {"url", "page", "author", "licence", "licence_url"}
    assert river_view not in json.dumps(draft)
    before = snapshot(root)
    sha = git(root, "rev-parse", "HEAD")
    assert '"id":"dendera"' not in (await client.get(page)).json()["html"]
    preview = (await client.get(page + "?preview=N1")).json()["html"]
    assert '"id":"dendera"' in preview and 'const HOST = {"embed": true, "station": "dendera"};' in preview
    assert snapshot(root) == before and git(root, "rev-parse", "HEAD") == sha
    accepted = await client.post(url + "/N1/accept")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["note"]["became"] == "stations/dendera"
    assert git(root, "rev-parse", "HEAD^") == sha
    assert changed(root) == ["candidates/nile/" + n for n in ("evidence.jsonl", "notebook.jsonl", "voyage.json")]
    assert git(root, "log", "-1", "--format=%an <%ae>") == f"Alice <{house.user.email}>"
    film = (await client.get(page)).json()["html"]
    assert film.index('"id":"aswan"') < film.index('"id":"dendera"') < film.index('"id":"luxor"')
    assert "Arrive by ferry [S3]." in film
    aside = await client.post(url + "/N2/set-aside", json={"why": "Another trip."})
    assert aside.json()["note"]["state"] == "set aside" and "Leave time on deck" not in journey_brief("nile")


def test_accept_commit_failure_restores_all_targets_and_index(voyage_repo, monkeypatch):
    root = voyage_repo.root
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED", "1")
    voyage_repo.add_note("nile", "place", PLACE["text"], "Dendera", None, "Alice", "alice@localhost")
    draft = dict(name="Dendera", lat=26.14, lon=32.67, after="aswan",
                 evidence=[dict(claim="Fixture observation", status="unverified")])
    voyage_repo.draft_note("nile", "N1", draft, "Ready")
    before, sha = snapshot(root), git(root, "rev-parse", "HEAD")
    (root / "other").write_text("keep staged")
    git(root, "add", "other")
    hook = root / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    with pytest.raises(subprocess.CalledProcessError) as refused:
        voyage_repo.accept_note("nile", "N1", "Mira", "mira@localhost")
    assert "commit" in refused.value.cmd and git(root, "rev-parse", "HEAD") == sha
    assert snapshot(root) == before and git(root, "status", "--porcelain") == "A  other"


@pytest.mark.asyncio
async def test_chat_add_uses_asking_member_and_brief(db, house, voyage_repo, monkeypatch):
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED", "1")
    await db.execute("UPDATE rooms SET linked_journey='nile' WHERE id=$1", house.room)
    message = await post_message(db, house.thread, 1, house.user.user_id, "@Scout add Kom Ombo, I want a night moored there")
    tool = next(t for t in build_tools(make_room(id=house.room), db) if t.name == "add_note")
    args = dict(slug="nile", kind="place", place="Kom Ombo", text="I want a night moored there")
    assert "message_id" in (await tool.execute(dict(args, message_id=str(uuid4()))))["error"]
    note = (await tool.execute(dict(args, message_id=message)))["note"]
    assert note["by"] == "Alice" and note["state"] == "open"
    assert "From friends\nN1 · place · Kom Ombo · Alice: I want a night moored there · open" in journey_brief("nile")
    assert git(voyage_repo.root, "log", "-1", "--format=%an <%ae>") == f"Alice <{house.user.email}>"
    assert git(voyage_repo.root, "log", "-1", "--format=%(trailers:only)").splitlines() == [
        "Added-In: The Long Way house", f"Asked-In: {message}"]


@pytest.mark.asyncio
async def test_nightly_open_places_choose_house_without_seeding_it(db, house, home_room, voyage_repo, monkeypatch):
    monkeypatch.setenv("LONGWAY_COMMIT_ENABLED", "1")
    monkeypatch.setenv("LONGWAY_SCOUT_ENABLED", "1")
    await db.execute("UPDATE rooms SET linked_journey=NULL WHERE id=$1", house.room)
    author = ("Alice", "alice@localhost")
    for slug in ("nile", "ogasawara"):
        voyage_repo.add_note(slug, "place", "Stay a night", "Dendera", None, *author)
    voyage_repo.draft_note("nile", "N1", dict(name="Dendera", lat=26.14, lon=32.67, after="aswan"), "First try")
    voyage_repo.send_back_note("nile", "N1", STEER, "Amo", "amo@localhost")

    class Unlocated:
        def __init__(self, slug):
            self.slug = slug

        async def complete(self, request):
            brief = request.messages[0]["content"]
            assert "Dendera · Alice: Stay a night" in brief
            assert (f"Amo sent the last draft back: {STEER}" in brief) == (self.slug == "nile")
            return replace(response(), content="Dendera stays open because I could not verify the coordinates.")

    real_run = scout.run

    async def offline_run(pool, room_id, slug, question_ids, **kwargs):
        return await real_run(pool, room_id, slug, question_ids, **kwargs, provider=Unlocated(slug))

    runner = AsyncMock(side_effect=offline_run)
    monkeypatch.setattr(scout, "run", runner)
    monkeypatch.setenv("LONGWAY_SEARCH_PROVIDER", "none")
    ctx = SimpleNamespace(pool=house.pool, broadcast=None)
    first = await jobs.scout_nightly(ctx)
    assert [c.args[1:] for c in runner.await_args_list] == [
        (home_room["id"], "nile", []), (home_room["id"], "ogasawara", [])]
    assert all(first[slug]["status"] == "done" for slug in ("nile", "ogasawara"))
    assert not await db.fetchval("SELECT 1 FROM longway_questions WHERE room_id=$1", home_room["id"])
    assert voyage_repo.notebook("nile")[0]["state"] == "open"
    content = await db.fetchval("""SELECT content FROM messages WHERE metadata->'longway_scout_run'->>'run_id'=$1""",
                                str(first["nile"]["id"]))
    assert "could not verify the coordinates" in content
    voyage_repo.draft_note("nile", "N1", dict(name="Dendera", lat=26.14, lon=32.67, after="aswan"), "Ready")
    voyage_repo.add_note("nile", "thought", "Rainy days on deck.", None, "aswan", *author)
    runner.reset_mock()
    await jobs.scout_nightly(ctx, now=datetime.now(timezone.utc) + timedelta(days=1))
    runner.assert_awaited_once_with(house.pool, home_room["id"], "ogasawara", [], trigger="nightly", ctx=ctx)


@pytest.mark.asyncio
async def test_commons_filters_credit_and_backs_off(monkeypatch, tmp_path):
    description = '<span title="one > two">People &amp; boats</span>\n  by the temple. ' + "On deck. " * 40
    pages = {str(i): page for i, page in enumerate([
        file_page(ImageDescription=description, DateTimeOriginal="  <time>2020-10-05</time> "),
        file_page("File:Untitled view.jpg"), file_page(licence="CC BY-NC 4.0"), file_page(width=800)])}
    requests = []

    def server(request):
        requests.append(request)
        assert request.url.params["gsrnamespace"] == "6" and request.url.params["iiurlwidth"] == "1600"
        assert {"ImageDescription", "DateTimeOriginal"} <= set(request.url.params["iiextmetadatafilter"].split("|"))
        assert "TheLongWayScout" in request.headers["User-Agent"]
        if len(requests) == 2:
            return httpx.Response(429, headers={"Retry-After": "60"})
        return httpx.Response(200, json={"query": {"pages": pages}})

    factory = httpx.AsyncClient
    monkeypatch.setattr(photos.httpx, "AsyncClient", lambda **kw: factory(transport=httpx.MockTransport(server), **kw))
    monkeypatch.setattr(photos.tempfile, "gettempdir", lambda: str(tmp_path))
    result = await photos.find("Dendera")
    assert [p["title"] for p in result] == [PHOTO, "File:Untitled view.jpg"]
    assert result[0]["licence"] == "CC BY-SA 4.0" and result[0]["author"] == "Fixture & friend"
    assert result[0]["description"] == ("People & boats by the temple. " + "On deck. " * 40)[:300].rstrip()
    assert result[0]["date"] == "2020-10-05"
    assert result[1]["description"] == "" and result[1]["date"] is None
    first = photos.time.monotonic()
    with pytest.raises(ValueError, match="Commons asked us to wait"):
        await photos.find("Dendera hall")
    assert photos.time.monotonic() - first >= 1.9
    assert float(next(tmp_path.glob("longway-commons-*.lock")).read_text()) - photos.time.time() > 59
    with pytest.raises(ValueError, match="Commons asked us to wait"):
        await photos.find("Dendera gate")
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_unusable_photo_bytes_stay_out_of_vision_batch(monkeypatch, tmp_path):
    titles = [f"File:View {n}.jpg" for n in range(1, 7)]
    downloaded = []

    def server(request):
        if request.url.host == "commons.wikimedia.org":
            pages = {n: {"title": title, "imageinfo": [{"thumbwidth": 500,
                        "thumburl": f"https://upload.wikimedia.org/{n}"}]} for n, title in enumerate(titles, 1)}
            return httpx.Response(200, json={"query": {"pages": pages}})
        number = int(request.url.path[1:])
        downloaded.append(number)
        mime = "text/html" if number == 2 else "image/jpeg"
        data = b"\xff\xd8\xff" + bytes([number])
        if number == 3:
            data += bytes(400 * 1024)
        if number == 4:
            data = b"<html>not a JPEG</html>"
        # No Content-Length. The streaming limit must also catch an oversized response.
        return httpx.Response(200, stream=httpx.ByteStream(data), headers={"Content-Type": mime})

    factory = httpx.AsyncClient
    monkeypatch.setattr(photos.httpx, "AsyncClient", lambda **kw: factory(transport=httpx.MockTransport(server), **kw))
    monkeypatch.setattr(photos.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setenv("DIALECTIC_VISION_ENABLED", "1")
    research = scout.Research(None, {}, provider=object())
    long_line = " ".join(["sunlit"] * 30)
    complete = AsyncMock(return_value=replace(response(), content=f"5. {long_line}\n1. A facade with columns.\n2. Invented."))
    monkeypatch.setattr(research, "complete", complete)
    found = [{"title": title} for title in titles]
    assert await research.describe_photos(found) == 2
    assert downloaded == list(range(1, 7))
    assert [p["shows"] for p in found] == ["A facade with columns.", "could not be viewed", "could not be viewed",
                                           "could not be viewed", " ".join(["sunlit"] * 25), "not described"]
    complete.assert_awaited_once()
    blocks = complete.await_args.args[0].messages[0]["content"]
    assert [b["text"] for b in blocks if b["type"] == "text"] == ["Picture 1", "Picture 5", "Picture 6"]


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled,reason", [(True, "vision request timed out"), (False, "vision is unavailable")])
async def test_find_photo_returns_credits_and_blind_choice_on_vision_failure(monkeypatch, enabled, reason):
    monkeypatch.setenv("DIALECTIC_VISION_ENABLED", "1" if enabled else "0")
    found = photos.candidates({"query": {"pages": {"one": file_page()}}})
    research = scout.Research(None, {}, provider=object())
    monkeypatch.setattr(research, "place_query", AsyncMock(return_value="Dendera temple"))
    monkeypatch.setattr(research, "log", AsyncMock())
    monkeypatch.setattr(photos, "find", AsyncMock(return_value=found))
    copies = AsyncMock(return_value={1: {"type": "image"}})
    monkeypatch.setattr(photos, "small_copies", copies)
    complete = AsyncMock(side_effect=httpx.ReadTimeout("private provider details"))
    monkeypatch.setattr(research, "complete", complete)
    result = await research.find_photo({"query": "Dendera temple"})
    assert result["photos"][0]["shows"] == reason and result["photos"][0]["author"] == "Fixture & friend"
    assert "pictures were not viewed" in result["why"] and "status line" in result["why"]
    assert research.photos[PHOTO] == found[0] and "private provider details" not in json.dumps(result)
    assert complete.await_count == copies.await_count == int(enabled)
    research.log.assert_awaited_once_with("find_photo", query="Dendera temple", titles=[PHOTO], viewed=0)


@pytest.mark.asyncio
@pytest.mark.parametrize(("url", "fetched"), [
    ("https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/X.jpg/500px-X.jpg", True),
    ("https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/X.jpg/500px-X.jpg", True),
    ("https://example.org/X.jpg", False),
    ("http://thumb.wikimedia.org/X.jpg", False),
])
async def test_small_copies_come_from_the_hosts_commons_really_uses(url, fetched):
    """The lead's live search got thumbnails from thumb.wikimedia.org only; anything else is not fetched at all."""
    asked = []

    def server(request):
        asked.append(str(request.url))
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b"\xff\xd8\xff" + b"0" * 64)
    async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
        block = await photos._download(client, url)
    assert (block is not None) is fetched
    assert asked == ([url] if fetched else [])
