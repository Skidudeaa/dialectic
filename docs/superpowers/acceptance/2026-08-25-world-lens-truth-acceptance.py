#!/usr/bin/env python3
"""Deterministic authenticated Task 5 acceptance on disposable local state.

The harness creates ``dialectic_world_acceptance`` from ``dialectic_test``,
applies migration 022, seeds one human/room/thread/message, and starts its own
backend and built-preview processes on spare loopback ports.  The backend is
the fixture-only app next to this script, which injects a WorldSignal snapshot
directly into the process.  There is no HTTP snapshot writer.

Evidence is intentionally small: two screenshots and a JSON result ledger are
written beneath ``/tmp/dialectic-world-lens-acceptance``.  The disposable DB is
dropped after both child processes stop, including on failure.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg
from playwright.sync_api import BrowserContext, Page, sync_playwright


ROOT = Path(__file__).resolve().parents[3]
DIALECTIC = ROOT / "dialectic"
FRONTEND = DIALECTIC / "frontend" / "app"
sys.path.insert(0, str(DIALECTIC))
DB_NAME = "dialectic_world_acceptance"
DB_URL = f"postgresql://root@localhost/{DB_NAME}"
SOURCE_DB = "dialectic_test"
BACKEND_PORT = 8025
PREVIEW_PORT = 4185
API = f"http://127.0.0.1:{BACKEND_PORT}"
BASE = f"http://127.0.0.1:{PREVIEW_PORT}"
EVIDENCE = Path("/tmp/dialectic-world-lens-acceptance")
BACKEND_LOG = EVIDENCE / "backend.log"
PREVIEW_LOG = EVIDENCE / "preview.log"
LEDGER = EVIDENCE / "results.json"

ROOM_ID = "11111111-1111-1111-1111-111111111111"
USER_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
THREAD_ID = "22222222-2222-4222-8222-222222222222"
MESSAGE_ID = "33333333-3333-4333-8333-333333333333"
READING_ID = "44444444-4444-4444-8444-444444444444"
ROOM_TOKEN = "world-acceptance-room-token"
EMAIL = "world-lens@fixture.example.com"
PASSWORD = "world-fixture-pw-2026"

checks: list[dict[str, Any]] = []


def check(name: str, passed: bool, detail: Any = "") -> None:
    row = {"name": name, "passed": bool(passed), "detail": detail}
    checks.append(row)
    suffix = f" — {detail}" if detail not in (None, "") else ""
    print(f"{'PASS' if passed else 'FAIL'}  {name}{suffix}")


def run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        command, cwd=cwd, env=env, check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    return completed.stdout


def prepare_database() -> None:
    if DB_NAME in {"dialectic", "dialectic_test", "dialectic_browser"}:
        raise RuntimeError(f"refusing non-disposable database name: {DB_NAME}")
    run(["dropdb", "--if-exists", DB_NAME])
    run(["createdb", "--template", SOURCE_DB, DB_NAME])
    migration_output = run(
        ["psql", DB_URL, "-v", "ON_ERROR_STOP=1", "-f", "migrations/022_geo_scope_lineage.sql"],
        cwd=DIALECTIC,
    )
    check(
        "migration 022 executes in the disposable database",
        "CREATE TRIGGER" in migration_output and "CREATE INDEX" in migration_output,
        migration_output.strip().replace("\n", " | "),
    )


async def seed_database() -> None:
    from api.auth.utils import get_password_hash

    db = await asyncpg.connect(DB_URL)
    try:
        now = datetime.now(timezone.utc)
        await db.execute(
            "INSERT INTO users (id,created_at,display_name) VALUES ($1,$2,$3)",
            USER_ID, now, "World Lens Fixture",
        )
        await db.execute(
            """INSERT INTO user_credentials
               (user_id,email,email_verified,password_hash,created_at,updated_at)
               VALUES ($1,$2,true,$3,$4,$4)""",
            USER_ID, EMAIL, get_password_hash(PASSWORD), now,
        )
        await db.execute(
            """INSERT INTO rooms
               (id,created_at,token,name,linked_book_id)
               VALUES ($1,$2,$3,$4,$5)""",
            ROOM_ID, now, ROOM_TOKEN, "World Acceptance Room", "world-acceptance-book",
        )
        await db.execute(
            "INSERT INTO room_memberships (room_id,user_id,joined_at) VALUES ($1,$2,$3)",
            ROOM_ID, USER_ID, now,
        )
        home_id = await db.fetchval("SELECT id FROM rooms WHERE is_home")
        if home_id is None:
            raise RuntimeError("template database has no Home room")
        await db.execute(
            """INSERT INTO room_memberships
               (room_id,user_id,joined_at,can_manage_home)
               VALUES ($1,$2,$3,true)""",
            home_id, USER_ID, now,
        )
        await db.execute(
            "INSERT INTO threads (id,room_id,created_at,title) VALUES ($1,$2,$3,'Main')",
            THREAD_ID, ROOM_ID, now,
        )
        await db.execute(
            """INSERT INTO messages
               (id,thread_id,sequence,created_at,speaker_type,user_id,message_type,content)
               VALUES ($1,$2,1,$3,'human',$4,'text',$5)""",
            MESSAGE_ID, THREAD_ID, now, USER_ID,
            "Acceptance destination: this message must retain its thread.",
        )
        await db.execute(
            """INSERT INTO reading_items
               (id,room_id,url,title,site,content,summary,source,
                source_message_id,saved_by_user_id,created_at)
               VALUES ($1,$2,$3,$4,'example.invalid',$5,$6,'human',$7,$8,$9)""",
            READING_ID, ROOM_ID, "https://example.invalid/world-reading",
            "Acceptance reading", "Acceptance reading body",
            "Acceptance reading summary", MESSAGE_ID, USER_ID, now,
        )
    finally:
        await db.close()


def wait_for(url: str, process: subprocess.Popen[str], *, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"process exited {process.returncode} before {url}")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status < 500:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.1)
    raise RuntimeError(f"timed out waiting for {url}")


def start_processes() -> tuple[subprocess.Popen[str], subprocess.Popen[str], Any, Any]:
    backend_env = os.environ.copy()
    backend_env.update({
        "DATABASE_URL": DB_URL,
        "JWT_SECRET_KEY": "world-acceptance-secret-key-at-least-32-bytes",
        "ANTHROPIC_API_KEY": "acceptance-dummy-key",
        "SCHEDULER_ENABLED": "0",
        "SIGNUPS_ENABLED": "0",
        "PYTHONPATH": os.pathsep.join((str(DIALECTIC), str(Path(__file__).parent))),
    })
    frontend_env = os.environ.copy()
    frontend_env["DIALECTIC_BACKEND_URL"] = API
    build_output = run(["npm", "run", "build"], cwd=FRONTEND, env=frontend_env)
    check("production frontend build completes", "built in" in build_output, build_output.splitlines()[-1])

    backend_log = BACKEND_LOG.open("w", encoding="utf-8")
    preview_log = PREVIEW_LOG.open("w", encoding="utf-8")
    backend: subprocess.Popen[str] | None = None
    preview: subprocess.Popen[str] | None = None
    try:
        backend = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "world_lens_fixture_app:app", "--host", "127.0.0.1", "--port", str(BACKEND_PORT)],
            cwd=DIALECTIC, env=backend_env, text=True, stdout=backend_log,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
        preview = subprocess.Popen(
            ["npm", "run", "preview", "--", "--host", "127.0.0.1", "--port", str(PREVIEW_PORT)],
            cwd=FRONTEND, env=frontend_env, text=True, stdout=preview_log,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
        wait_for(f"{API}/health", backend)
        wait_for(BASE, preview)
        return backend, preview, backend_log, preview_log
    except Exception:
        stop(preview)
        stop(backend)
        preview_log.close()
        backend_log.close()
        raise


def api(page: Page, path: str, access_token: str, *, method: str = "GET", body: Any = None) -> dict[str, Any]:
    result = page.evaluate(
        """async ({path, token, roomToken, method, body}) => {
          const response = await fetch(path, {
            method,
            headers: {
              Authorization: `Bearer ${token}`,
              'X-Room-Token': roomToken,
              'Content-Type': 'application/json',
            },
            body: body === null ? undefined : JSON.stringify(body),
          })
          const text = await response.text()
          return { status: response.status, body: text ? JSON.parse(text) : null }
        }""",
        {"path": path, "token": access_token, "roomToken": ROOM_TOKEN, "method": method, "body": body},
    )
    if result["status"] >= 400:
        raise RuntimeError(f"{method} {path}: {result}")
    return result["body"]


def bare(object_id: str) -> str:
    return object_id.split(":", 1)[-1]


def scalar(query: str) -> str:
    return run(["psql", DB_URL, "-t", "-A", "-c", query]).strip()


def login(page: Page) -> dict[str, Any]:
    page.goto(BASE, wait_until="domcontentloaded")
    page.fill('input[type="email"]', EMAIL)
    page.fill('input[type="password"]', PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_function(
        "() => localStorage.getItem('dialectic-auth') !== null",
        timeout=15_000,
    )
    token = page.evaluate(
        """() => JSON.parse(localStorage.getItem('dialectic-auth')).state""",
    )
    return token


def browser_context(browser: Any, *, width: int, reduced: bool = False, webgl: bool = True) -> BrowserContext:
    context = browser.new_context(
        viewport={"width": width, "height": 844 if width == 390 else 900},
        color_scheme="dark", reduced_motion="reduce" if reduced else "no-preference",
    )
    if not webgl:
        context.add_init_script(
            """(() => {
              const original = HTMLCanvasElement.prototype.getContext
              HTMLCanvasElement.prototype.getContext = function(kind, ...args) {
                if (kind === 'webgl' || kind === 'webgl2') return null
                return original.call(this, kind, ...args)
              }
            })()""",
        )
    return context


def exercise_api(page: Page, access_token: str) -> dict[str, str]:
    atlas = api(page, "/api/users/me/atlas?signals=1", access_token)
    check("snapshot is configured and current", atlas["signal_sources"]["status"] == "configured")
    check("signal is a distinct read-only projection", len(atlas["signals"]) == 1 and len(atlas["scopes"]) == 0)

    message_scope = api(
        page, f"/api/rooms/{ROOM_ID}/geo", access_token, method="POST",
        body={
            "subject": {"entity": "messages", "id": MESSAGE_ID},
            "kind": "point", "geometry": {"type": "Point", "coordinates": [56.1, 26.4]},
            "label": "Message placement",
        },
    )
    reading_scope = api(
        page, f"/api/rooms/{ROOM_ID}/geo", access_token, method="POST",
        body={
            "subject": {"entity": "reading_items", "id": READING_ID},
            "kind": "point", "geometry": {"type": "Point", "coordinates": [56.2, 26.5]},
            "label": "Reading placement",
        },
    )
    event_baseline = int(scalar(
        f"SELECT count(*) FROM events WHERE room_id='{ROOM_ID}' AND event_type LIKE 'geo_scope_%'",
    ))

    placed = api(
        page, f"/api/rooms/{ROOM_ID}/world-signals/world_signal%3Afixture%3Ahormuz-001/place",
        access_token, method="POST",
    )
    check("placing a signal creates durable source-reported authority", placed["authority"] == "source_reported")
    page.reload(wait_until="networkidle")
    check(
        "browser keeps the current signal distinct beside durable placement",
        page.locator(".world-signal-row").count() == 1
        and page.get_by_text("Acceptance vessel signal", exact=True).count() >= 2,
    )
    page.goto(
        f"{BASE}/?room={ROOM_ID}&object={urllib.parse.quote(placed['id'])}",
        wait_until="networkidle",
    )
    page.get_by_role("heading", name="Acceptance vessel signal").wait_for()
    check(
        "room scope inspector exposes its history",
        page.get_by_role("list", name="Scope history").get_by_role("listitem").count() == 1,
    )
    page.get_by_role("button", name="Open subject").click()
    page.wait_for_timeout(400)
    room_query = urllib.parse.parse_qs(urllib.parse.urlparse(page.url).query)
    check(
        "room subject destination retains the exact room without invented axes",
        room_query == {"room": [ROOM_ID]},
        page.url,
    )
    page.goto(
        f"{BASE}/?scene=atlas&view=world%3Broom%3D{ROOM_ID}",
        wait_until="networkidle",
    )
    ratified = api(page, f"/api/rooms/{ROOM_ID}/geo/{bare(placed['id'])}/ratify", access_token, method="POST", body={"note": "ratified in acceptance"})
    redrawn = api(
        page, f"/api/rooms/{ROOM_ID}/geo/{bare(ratified['id'])}/redraw", access_token,
        method="POST", body={"label": "Ratified and redrawn scope", "geometry": {"type": "Point", "coordinates": [56.3, 26.6]}, "note": "redraw in acceptance"},
    )

    mark = api(
        page, f"/api/rooms/{ROOM_ID}/field/marks", access_token, method="POST",
        body={
            "relation": "supports",
            "subjects": [
                {"entity": "rooms", "id": ROOM_ID, "field": "thesis_node:world-acceptance-book:shipping-chokepoint"},
                {"entity": "geo_scopes", "id": bare(redrawn["id"])},
            ],
            "title": "Current scope supports the shipping chokepoint thesis",
            "payload": {"node_label": "client value must not win"},
            "thread_id": THREAD_ID,
        },
    )
    check("causal Field mark resolves semantic roles", {item["entity"] for item in mark["subjects"]} == {"rooms", "geo_scopes"})
    confirmed = api(page, f"/api/rooms/{ROOM_ID}/field/marks/{bare(mark['id'])}/review", access_token, method="POST", body={"action": "confirm"})
    check("Field confirmation refreshes derived review state", confirmed["mark"]["review"] == "confirmed")

    superseded = api(page, f"/api/rooms/{ROOM_ID}/geo/{bare(redrawn['id'])}/supersede", access_token, method="POST", body={"note": "superseded in acceptance"})
    check(
        "ratify, redraw, and supersede append exact successors",
        [ratified["revision_action"], redrawn["revision_action"], superseded["revision_action"]] == ["ratify", "redraw", "supersede"],
    )
    chain_ids = [placed["id"], ratified["id"], redrawn["id"], superseded["id"]]
    direct_successors = [
        int(scalar(f"SELECT count(*) FROM geo_scopes WHERE supersedes_id='{bare(scope_id)}'"))
        for scope_id in chain_ids
    ]
    check("signal lineage has exactly one direct successor per nonterminal", direct_successors == [1, 1, 1, 0], direct_successors)
    event_total = int(scalar(
        f"SELECT count(*) FROM events WHERE room_id='{ROOM_ID}' AND event_type LIKE 'geo_scope_%'",
    ))
    check("place/ratify/redraw/supersede emit exactly four geo events", event_total - event_baseline == 4, event_total - event_baseline)

    geo = api(page, f"/api/rooms/{ROOM_ID}/geo", access_token)
    field = api(page, f"/api/rooms/{ROOM_ID}/field", access_token)
    signal_review = api(page, f"/api/rooms/{ROOM_ID}/geo/{bare(placed['id'])}/review", access_token)
    check("scope-history refresh resolves the canonical four-row chain", signal_review["current"]["id"] == superseded["id"] and len(signal_review["lineage"]) == 4)
    check("scope refresh retires superseded signal placement", {item["id"] for item in geo["scopes"]} == {message_scope["id"], reading_scope["id"]})
    check("Field refresh returns the causal mark and confirmation", any(item["id"] == mark["id"] and item["review"] == "confirmed" for item in field["marks"]))
    return {
        "message_scope": message_scope["id"],
        "reading_scope": reading_scope["id"],
        "signal_root": placed["id"],
        "mark": mark["id"],
    }


def exercise_browser(browser: Any) -> None:
    context = browser_context(browser, width=1280)
    page = context.new_page()
    auth = login(page)
    page.goto(f"{BASE}/?scene=atlas", wait_until="networkidle")
    modes = page.get_by_role("group", name="Atlas mode")
    check("House is the initial Atlas mode", modes.get_by_role("button", name="House").get_attribute("aria-pressed") == "true")
    modes.get_by_role("button", name="World").focus()
    page.keyboard.press("Enter")
    page.wait_for_selector('[data-atlas-mode="world"]')
    check("keyboard opens World and preserves encoded World URL", "view=world" in page.url)
    check("complete text path lists the ephemeral signal", page.get_by_text("Acceptance vessel signal", exact=True).count() == 1)
    check("signal and durable scopes remain separate before placement", page.locator(".world-signal-row").count() == 1 and page.locator(".world-scope-row").count() == 0)

    ids = exercise_api(page, auth["accessToken"])
    page.reload(wait_until="networkidle")
    check("refresh preserves the signal and both accepted subject scopes", page.locator(".world-signal-row").count() == 1 and page.locator(".world-scope-row").count() == 2)

    page.get_by_text("Message placement", exact=True).click()
    page.get_by_role("heading", name="Message placement").wait_for()
    check("message scope inspector exposes its history", page.get_by_role("list", name="Scope history").get_by_role("listitem").count() == 1)
    page.get_by_role("button", name="Open subject").click()
    page.wait_for_timeout(400)
    message_query = urllib.parse.parse_qs(urllib.parse.urlparse(page.url).query)
    check(
        "message subject destination retains exact thread and message",
        message_query.get("room") == [ROOM_ID]
        and message_query.get("thread") == [THREAD_ID]
        and message_query.get("message") == [MESSAGE_ID],
        page.url,
    )

    page.goto(
        f"{BASE}/?room={ROOM_ID}&object={urllib.parse.quote(ids['reading_scope'])}",
        wait_until="networkidle",
    )
    page.get_by_role("heading", name="Reading placement").wait_for()
    check("reading scope inspector exposes its history", page.get_by_role("list", name="Scope history").get_by_role("listitem").count() == 1)
    page.get_by_role("button", name="Open subject").click()
    page.wait_for_timeout(400)
    reading_query = urllib.parse.parse_qs(urllib.parse.urlparse(page.url).query)
    check(
        "reading subject destination retains the exact object",
        reading_query.get("room") == [ROOM_ID]
        and reading_query.get("object") == [f"reading:{READING_ID}"],
        page.url,
    )
    context.close()

    phone = browser_context(browser, width=390, reduced=True)
    phone_page = phone.new_page()
    login(phone_page)
    phone_page.goto(f"{BASE}/?scene=atlas&view=world%3Broom%3D{ROOM_ID}", wait_until="networkidle")
    facts = phone_page.evaluate(
        """() => ({
          scroll: document.documentElement.scrollWidth,
          client: document.documentElement.clientWidth,
          reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
          world: document.querySelector('[data-atlas-mode="world"]') !== null,
        })""",
    )
    check("390px World has no horizontal overflow", facts["scroll"] <= facts["client"], facts)
    check("reduced motion is honored by the browser context", facts["reduced"] is True)
    phone_page.screenshot(path=str(EVIDENCE / "world-390-reduced.png"), full_page=False)
    phone.close()

    failed_gl = browser_context(browser, width=1280, webgl=False)
    failed_page = failed_gl.new_page()
    failed_auth = login(failed_page)
    failed_page.goto(f"{BASE}/?scene=atlas&view=world%3Broom%3D{ROOM_ID}", wait_until="networkidle")
    failed_projection = api(failed_page, "/api/users/me/atlas?signals=1", failed_auth["accessToken"])
    check(
        "forced-WebGL API projection still carries both live scopes",
        {scope["label"] for scope in failed_projection["scopes"]}
        == {"Message placement", "Reading placement"},
        [scope["label"] for scope in failed_projection["scopes"]],
    )
    check("forced WebGL failure keeps the complete signal list", failed_page.get_by_text("Acceptance vessel signal", exact=True).count() == 1)
    fallback_rows = failed_page.locator(".world-scope-row").all_inner_texts()
    fallback_counts = {
        "message": sum("Message placement" in row for row in fallback_rows),
        "reading": sum("Reading placement" in row for row in fallback_rows),
        "retired": sum("Ratified and redrawn scope" in row for row in fallback_rows),
        "rows": fallback_rows,
    }
    check(
        "forced WebGL failure keeps the complete live scope list",
        fallback_counts["message"] >= 1 and fallback_counts["reading"] >= 1,
        fallback_counts,
    )
    check(
        "forced WebGL failure does not relist the retired scope as live",
        fallback_counts["retired"] == 0,
        fallback_counts,
    )
    failed_page.screenshot(path=str(EVIDENCE / "world-webgl-failure.png"), full_page=False)
    failed_gl.close()


def stop(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    backend: subprocess.Popen[str] | None = None
    preview: subprocess.Popen[str] | None = None
    logs: list[Any] = []
    try:
        prepare_database()
        import asyncio
        asyncio.run(seed_database())
        backend, preview, *logs = start_processes()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            exercise_browser(browser)
            browser.close()
    except Exception as exc:
        check("harness completed without exception", False, repr(exc))
    finally:
        stop(preview)
        stop(backend)
        for handle in logs:
            handle.close()
        run(["dropdb", "--if-exists", DB_NAME])

    failed = [row for row in checks if not row["passed"]]
    LEDGER.write_text(json.dumps({"checks": checks, "failed": len(failed)}, indent=2) + "\n", encoding="utf-8")
    print(f"\n{len(checks) - len(failed)}/{len(checks)} passed; evidence: {EVIDENCE}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
