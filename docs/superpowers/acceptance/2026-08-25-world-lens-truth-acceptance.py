#!/usr/bin/env python3
"""Deterministic authenticated Task 5 acceptance on disposable local state.

The harness creates a uniquely suffixed disposable database from ``dialectic_test``,
applies migration 022, seeds one human/room/thread/message, and starts its own
backend and built-preview processes on spare loopback ports.  The backend is
the fixture-only app next to this script, which injects a WorldSignal snapshot
directly into the process.  There is no HTTP snapshot writer.

Evidence is intentionally small: two screenshots and a JSON result ledger are
written beneath a uniquely suffixed ``/tmp/dialectic-world-lens-acceptance-*``.  The disposable DB is
dropped after both child processes stop, including on failure.
"""

from __future__ import annotations

import json
import os
import re
import signal
import socket
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
RUN_SUFFIX = f"{os.getpid()}_{time.time_ns() % 1_000_000_000}"
DB_NAME = f"dialectic_world_acceptance_{RUN_SUFFIX}"
DB_URL = f"postgresql://root@localhost/{DB_NAME}"
SOURCE_DB = "dialectic_test"


def free_loopback_port() -> int:
    """Ask the kernel for one currently unused loopback port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reservation:
        reservation.bind(("127.0.0.1", 0))
        return int(reservation.getsockname()[1])


BACKEND_PORT = free_loopback_port()
PREVIEW_PORT = free_loopback_port()
while PREVIEW_PORT == BACKEND_PORT:
    PREVIEW_PORT = free_loopback_port()
API = f"http://127.0.0.1:{BACKEND_PORT}"
BASE = f"http://127.0.0.1:{PREVIEW_PORT}"
EVIDENCE = Path(f"/tmp/dialectic-world-lens-acceptance-{RUN_SUFFIX}")
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
browser_issues: list[str] = []


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
    named_ui_write = method != "GET" and (
        "/world-signals/" in path
        or path.endswith(("/ratify", "/redraw", "/supersede"))
        or "/field/marks" in path
    )
    if named_ui_write:
        raise RuntimeError(f"named acceptance write must use visible UI controls: {method} {path}")
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


def wait_scalar(query: str, *, timeout: float = 10) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = scalar(query)
        if value:
            return value
        time.sleep(0.1)
    raise RuntimeError(f"timed out waiting for database result: {query}")


def watch_page(page: Page) -> None:
    page.on("pageerror", lambda error: browser_issues.append(f"pageerror: {error}"))
    page.on(
        "response",
        lambda response: browser_issues.append(
            f"HTTP 500: {response.request.method} {response.url}",
        ) if response.status == 500 else None,
    )


def tab_to(page: Page, locator: Any, *, max_stops: int = 120) -> list[str]:
    """Reach one visible control using only real keyboard Tab traversal."""
    visited: list[str] = []
    for _ in range(max_stops):
        page.keyboard.press("Tab")
        active = page.evaluate(
            """() => {
              const active = document.activeElement
              return active ? `${active.tagName}:${active.textContent?.trim().slice(0, 80)}` : 'none'
            }""",
        )
        visited.append(str(active))
        if locator.evaluate("element => element === document.activeElement"):
            return visited
    raise RuntimeError(f"Tab did not reach control after {max_stops} stops: {visited[-10:]}")


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


def seed_subject_scopes(page: Page, access_token: str) -> dict[str, str | int]:
    """Seed only the unrelated message/reading fixtures allowed by the plan."""
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

    return {
        "message_scope": message_scope["id"],
        "reading_scope": reading_scope["id"],
        "event_baseline": event_baseline,
    }


def open_home_world(page: Page) -> None:
    page.get_by_role("button", name="Go Home").click()
    page.get_by_text("Home", exact=True).first.wait_for()
    house = page.get_by_role("button", name="House", exact=True)
    check("real Home navigation returns to the House", house.get_attribute("aria-current") == "page")
    page.get_by_role("button", name="Atlas", exact=True).click()
    modes = page.get_by_role("group", name="Atlas mode")
    modes.get_by_role("button", name="World").click()
    page.wait_for_selector('[data-atlas-mode="world"]')


def exercise_named_ui_writes(
    page: Page, access_token: str, fixture_ids: dict[str, str | int],
) -> dict[str, str]:
    writes: list[dict[str, str | None]] = []

    def capture_write(request: Any) -> None:
        path = urllib.parse.urlparse(request.url).path
        action: str | None = None
        if request.method == "POST" and path.endswith("/place") and "/world-signals/" in path:
            action = "place"
        elif request.method == "POST" and path.endswith("/ratify"):
            action = "ratify"
        elif request.method == "POST" and path.endswith("/redraw"):
            action = "redraw"
        elif request.method == "POST" and path.endswith("/supersede"):
            action = "supersede"
        elif request.method == "POST" and path.endswith("/field/marks"):
            action = "bind"
        elif request.method == "POST" and "/field/marks/" in path and path.endswith("/review"):
            action = "confirm"
        if action:
            writes.append({
                "action": action,
                "path": path,
                "room_token": request.headers.get("x-room-token"),
            })

    page.on("request", capture_write)
    page.get_by_role("button", name="Place Acceptance vessel signal").click()
    signal_row = page.locator(".world-scope-row", has_text="Acceptance vessel signal")
    signal_row.wait_for()
    placed_id = f"geo_scope:{wait_scalar(f'''SELECT id FROM geo_scopes WHERE room_id='{ROOM_ID}' AND revision_action='place_signal' ORDER BY created_at DESC LIMIT 1''')}"
    check(
        "visible Place keeps the current signal distinct beside a durable placement",
        page.locator(".world-signal-row").count() == 1 and signal_row.count() == 1,
    )
    signal_row.get_by_role("button").click()
    page.get_by_role("heading", name="Acceptance vessel signal").wait_for()
    history = page.get_by_role("list", name="Scope history")
    check("visible Place refreshes one-row scope history", history.get_by_role("listitem").count() == 1)
    page.get_by_role("button", name="Open subject").click()
    page.wait_for_timeout(400)
    room_query = urllib.parse.parse_qs(urllib.parse.urlparse(page.url).query)
    check(
        "room subject destination retains the exact room without invented axes",
        room_query == {"room": [ROOM_ID]}, page.url,
    )

    open_home_world(page)
    page.goto(
        f"{BASE}/?room={ROOM_ID}&scene=field&object={urllib.parse.quote(placed_id)}",
        wait_until="networkidle",
    )
    page.get_by_role("heading", name="Acceptance vessel signal").wait_for()

    page.get_by_label("Review note").fill("ratified through the visible review")
    page.get_by_role("button", name="Ratify").click()
    page.wait_for_function(
        "() => document.querySelectorAll('[aria-label=\"Scope history\"] li').length === 2",
    )
    ratified_uuid = wait_scalar(
        f"SELECT id FROM geo_scopes WHERE supersedes_id='{bare(placed_id)}'",
    )
    ratified_id = f"geo_scope:{ratified_uuid}"
    check("visible Ratify refreshes two-row history", history.get_by_role("listitem").count() == 2)

    page.get_by_role("button", name="Redraw").click()
    page.get_by_label("Placement label").fill("Ratified and redrawn scope")
    page.get_by_label("GeoJSON geometry").fill(
        json.dumps({"type": "Point", "coordinates": [56.3, 26.6]}),
    )
    page.get_by_label("Review note").fill("redrawn through the visible review")
    page.get_by_role("button", name="Save redraw").click()
    page.get_by_role("heading", name="Ratified and redrawn scope").wait_for()
    page.wait_for_function(
        "() => document.querySelectorAll('[aria-label=\"Scope history\"] li').length === 3",
    )
    redrawn_uuid = wait_scalar(
        f"SELECT id FROM geo_scopes WHERE supersedes_id='{bare(ratified_id)}'",
    )
    redrawn_id = f"geo_scope:{redrawn_uuid}"
    check("visible Redraw refreshes label and three-row history", history.get_by_role("listitem").count() == 3)

    page.get_by_role("button", name="Bind to thesis node").click()
    page.get_by_label("Causal relation").select_option("supports")
    page.get_by_label("Thesis node").select_option("shipping-chokepoint")
    page.get_by_role("button", name="Add to Field").click()
    mark_uuid = wait_scalar(
        f"SELECT id FROM field_marks WHERE room_id='{ROOM_ID}' ORDER BY created_at DESC LIMIT 1",
    )
    mark_id = f"field_mark:{mark_uuid}"

    page.goto(f"{BASE}/?room={ROOM_ID}&scene=field", wait_until="networkidle")
    mark_title = "Ratified and redrawn scope supports Shipping chokepoint"
    mark_row = page.locator(".field-mark-open", has_text=mark_title)
    mark_row.wait_for()
    check("visible Add to Field refreshes the Field scene", mark_row.count() == 1)
    mark_row.click()
    page.get_by_role("heading", name=mark_title).wait_for()
    page.get_by_role("button", name="Confirm").click()
    page.wait_for_function(
        "() => document.querySelector('button[disabled]')?.textContent?.trim() === 'Confirm'",
    )
    check("visible Confirm refreshes the Field mark", page.get_by_role("button", name="Confirm").is_disabled())

    page.goto(
        f"{BASE}/?room={ROOM_ID}&scene=field&object={urllib.parse.quote(redrawn_id)}",
        wait_until="networkidle",
    )
    page.get_by_role("heading", name="Ratified and redrawn scope").wait_for()
    page.get_by_label("Review note").fill("superseded through the visible review")
    page.get_by_role("button", name="Supersede").click()
    page.wait_for_function(
        "() => document.querySelectorAll('[aria-label=\"Scope history\"] li').length === 4",
    )
    superseded_uuid = wait_scalar(
        f"SELECT id FROM geo_scopes WHERE supersedes_id='{bare(redrawn_id)}'",
    )
    superseded_id = f"geo_scope:{superseded_uuid}"
    check("visible Supersede refreshes the canonical four-row history", history.get_by_role("listitem").count() == 4)

    expected_actions = ["place", "ratify", "redraw", "bind", "confirm", "supersede"]
    check("all named writes came from the visible UI in order", [row["action"] for row in writes] == expected_actions, writes)
    check(
        "every named UI write carries the exact target-room token and room path",
        all(row["room_token"] == ROOM_TOKEN and f"/rooms/{ROOM_ID}/" in str(row["path"]) for row in writes),
        writes,
    )

    chain_ids = [placed_id, ratified_id, redrawn_id, superseded_id]
    direct_successors = [
        int(scalar(f"SELECT count(*) FROM geo_scopes WHERE supersedes_id='{bare(scope_id)}'"))
        for scope_id in chain_ids
    ]
    check("signal lineage has exactly one direct successor per nonterminal", direct_successors == [1, 1, 1, 0], direct_successors)
    event_total = int(scalar(
        f"SELECT count(*) FROM events WHERE room_id='{ROOM_ID}' AND event_type LIKE 'geo_scope_%'",
    ))
    event_delta = event_total - int(fixture_ids["event_baseline"])
    check("Place/Ratify/Redraw/Supersede emit exactly four geo events", event_delta == 4, event_delta)

    geo = api(page, f"/api/rooms/{ROOM_ID}/geo", access_token)
    field = api(page, f"/api/rooms/{ROOM_ID}/field", access_token)
    signal_review = api(page, f"/api/rooms/{ROOM_ID}/geo/{bare(placed_id)}/review", access_token)
    mark = next(item for item in field["marks"] if item["id"] == mark_id)
    check(
        "causal Field mark resolves exact semantic roles",
        mark["review"] == "confirmed"
        and {item["entity"] for item in mark["subjects"]} == {"rooms", "geo_scopes"}
        and any(item.get("field") == "thesis_node:world-acceptance-book:shipping-chokepoint" for item in mark["subjects"]),
    )
    check("scope-history read resolves the canonical four-row chain", signal_review["current"]["id"] == superseded_id and len(signal_review["lineage"]) == 4)
    check("scope refresh retires superseded signal placement", {item["id"] for item in geo["scopes"]} == {fixture_ids["message_scope"], fixture_ids["reading_scope"]})
    return {
        "message_scope": str(fixture_ids["message_scope"]),
        "reading_scope": str(fixture_ids["reading_scope"]),
        "signal_root": placed_id,
        "mark": mark_id,
    }


def exercise_browser(browser: Any) -> None:
    context = browser_context(browser, width=1280)
    page = context.new_page()
    watch_page(page)
    auth = login(page)
    page.goto(f"{BASE}/?scene=atlas", wait_until="networkidle")
    modes = page.get_by_role("group", name="Atlas mode")
    check("House is the initial Atlas mode", modes.get_by_role("button", name="House").get_attribute("aria-pressed") == "true")
    tab_to(page, modes.get_by_role("button", name="World"))
    page.keyboard.press("Enter")
    page.wait_for_selector('[data-atlas-mode="world"]')
    check("keyboard opens World and preserves encoded World URL", "view=world" in page.url)
    check("complete text path lists the ephemeral signal", page.get_by_text("Acceptance vessel signal", exact=True).count() == 1)
    check("signal and durable scopes remain separate before placement", page.locator(".world-signal-row").count() == 1 and page.locator(".world-scope-row").count() == 0)

    fixture_ids = seed_subject_scopes(page, auth["accessToken"])
    page.reload(wait_until="networkidle")
    check("API fixture seed refreshes only the two unrelated subject scopes", page.locator(".world-signal-row").count() == 1 and page.locator(".world-scope-row").count() == 2)
    ids = exercise_named_ui_writes(page, auth["accessToken"], fixture_ids)

    open_home_world(page)

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
    watch_page(phone_page)
    login(phone_page)
    phone_page.goto(f"{BASE}/?scene=atlas&view=world%3Broom%3D{ROOM_ID}", wait_until="networkidle")
    facts = phone_page.evaluate(
        """() => ({
          scroll: document.documentElement.scrollWidth,
          client: document.documentElement.clientWidth,
          reduced: matchMedia('(prefers-reduced-motion: reduce)').matches,
          world: document.querySelector('[data-atlas-mode="world"]') !== null,
          placeHeight: document.querySelector('.world-signal-place')?.getBoundingClientRect().height ?? 0,
          signalMetaFont: parseFloat(getComputedStyle(document.querySelector('.world-signal-meta')).fontSize),
          sourceMetaFont: parseFloat(getComputedStyle(document.querySelector('.world-source-list')).fontSize),
        })""",
    )
    check("390px World has no horizontal overflow", facts["scroll"] <= facts["client"], facts)
    check("reduced motion is honored by the browser context", facts["reduced"] is True)
    check("390px signal Place target is at least 44px", facts["placeHeight"] >= 44, facts)
    check("390px signal metadata is at least 12px", facts["signalMetaFont"] >= 12, facts)
    check("390px source metadata is at least 12px", facts["sourceMetaFont"] >= 12, facts)
    phone_page.screenshot(path=str(EVIDENCE / "world-390-reduced.png"), full_page=False)
    phone.close()

    failed_gl = browser_context(browser, width=1280, webgl=False)
    failed_page = failed_gl.new_page()
    watch_page(failed_page)
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
    check(
        "forced WebGL fallback removes Cesium's partial modal panel",
        failed_page.locator(".cesium-widget-errorPanel").count() == 0
        and failed_page.get_by_text("Error constructing CesiumWidget.", exact=True).count() == 0,
    )
    canvas_facts = failed_page.locator(".world-canvas").evaluate(
        "element => ({ hidden: element.hidden, height: element.getBoundingClientRect().height })",
    )
    check(
        "forced WebGL fallback collapses the unusable canvas region",
        canvas_facts == {"hidden": True, "height": 0}, canvas_facts,
    )
    failed_page.screenshot(path=str(EVIDENCE / "world-webgl-failure.png"), full_page=False)
    fallback_control = failed_page.locator(".world-scope-row", has_text="Message placement").get_by_role("button")
    visited = tab_to(failed_page, fallback_control)
    check(
        "actual Tab traversal reaches the forced-WebGL text-list scope",
        fallback_control.evaluate("element => element === document.activeElement"),
        {"tab_stops": len(visited), "last": visited[-1]},
    )
    failed_page.keyboard.press("Enter")
    failed_page.get_by_role("heading", name="Message placement").wait_for()
    check("forced WebGL text-list scope activates from the keyboard", "object=geo_scope" in failed_page.url)
    failed_gl.close()
    check("browser qualification saw no page errors or HTTP 500 responses", browser_issues == [], browser_issues)


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
    backend_before_stop = ""
    try:
        prepare_database()
        import asyncio
        asyncio.run(seed_database())
        backend, preview, *logs = start_processes()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            exercise_browser(browser)
            browser.close()
        if logs:
            logs[0].flush()
            backend_before_stop = BACKEND_LOG.read_text(encoding="utf-8")
    except Exception as exc:
        check("harness completed without exception", False, repr(exc))
    finally:
        if logs:
            logs[0].flush()
            backend_before_stop = BACKEND_LOG.read_text(encoding="utf-8")
        stop(preview)
        stop(backend)
        for handle in logs:
            handle.close()
        run(["dropdb", "--if-exists", DB_NAME])

    backend_after_stop = (
        BACKEND_LOG.read_text(encoding="utf-8") if BACKEND_LOG.exists() else ""
    )
    teardown_tail = backend_after_stop[len(backend_before_stop):]
    reset_markers = ("ConnectionResetError", "ECONNRESET")
    runtime_resets = [
        marker for marker in reset_markers if marker in backend_before_stop
    ]
    teardown_resets = [
        marker for marker in reset_markers if marker in teardown_tail
    ]
    asgi_exception_count = backend_after_stop.count(
        "ERROR:    Exception in ASGI application",
    )
    expected_ws_closes = re.findall(
        r"ERROR:    Exception in ASGI application\n"
        r".*?starlette\.websockets\.WebSocketDisconnect: \(1001, ''\)\n"
        r"INFO:     connection closed",
        backend_after_stop,
        flags=re.DOTALL,
    )
    check(
        "backend emitted no HTTP 500 responses",
        ' 500 Internal Server Error' not in backend_after_stop,
    )
    check(
        "websocket/ECONNRESET noise is absent at runtime and classified at teardown",
        runtime_resets == [],
        (
            f"teardown-only markers: {teardown_resets}"
            if teardown_resets else "no reset markers observed"
        ),
    )
    check(
        "every ASGI exception is exactly browser-context WebSocketDisconnect 1001",
        asgi_exception_count == len(expected_ws_closes),
        {
            "asgi_exception_blocks": asgi_exception_count,
            "browser_context_ws_1001": len(expected_ws_closes),
        },
    )

    failed = [row for row in checks if not row["passed"]]
    LEDGER.write_text(json.dumps({"checks": checks, "failed": len(failed)}, indent=2) + "\n", encoding="utf-8")
    print(f"\n{len(checks) - len(failed)}/{len(checks)} passed; evidence: {EVIDENCE}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
