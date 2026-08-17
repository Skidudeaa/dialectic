"""Isolated warm/cold notification landing acceptance.

Drives the production PWA build on :4173 against the isolated :8013 backend
and ``dialectic_browser``. It dispatches the same service-worker message event
used by a warm notification click; cold entry uses the exact URL that the
worker opens. Production users, rooms, subscriptions, and services are untouched.
"""

from pathlib import Path
import subprocess
import sys
from typing import Any

from playwright.sync_api import Browser, Page, sync_playwright

BASE = "http://localhost:4173"
EMAIL = "scene@fixture.example.com"
PASSWORD = "scene-fixture-pw-123"
SHOT_DIR = Path(__file__).parent / "screenshots-push-deep-link"

ROOM_COLD = "91000000-0000-0000-0000-000000000001"
ROOM_WARM = "91000000-0000-0000-0000-000000000002"
ROOT_COLD = "92000000-0000-0000-0000-000000000001"
ROOT_WARM = "92000000-0000-0000-0000-000000000002"
THREAD_COLD = "93000000-0000-0000-0000-000000000001"
THREAD_WARM = "93000000-0000-0000-0000-000000000002"
MESSAGE_COLD = "94000000-0000-0000-0000-000000000001"
MESSAGE_WARM = "94000000-0000-0000-0000-000000000002"

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    suffix = f" — {detail}" if detail else ""
    print(f"{'PASS' if ok else 'FAIL'}  {name}{suffix}")


def sql(query: str) -> str:
    result = subprocess.run(
        ["psql", "dialectic_browser", "-t", "-A", "-c", query],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def seed() -> None:
    user_id = sql(
        "SELECT user_id FROM user_credentials "
        "WHERE email = 'scene@fixture.example.com'",
    )
    if not user_id:
        raise RuntimeError("release fixture user is missing")

    sql(
        "DELETE FROM message_receipts WHERE message_id IN "
        "(SELECT id FROM messages WHERE metadata->>'fixture' = 'push-deep-link');"
        "DELETE FROM messages WHERE metadata->>'fixture' = 'push-deep-link';"
        f"INSERT INTO rooms (id, created_at, token, name) VALUES "
        f"('{ROOM_COLD}', now(), 'push-cold-room-token', 'Cold Signal Room'),"
        f"('{ROOM_WARM}', now(), 'push-warm-room-token', 'Warm Signal Room') "
        "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name;"
        f"INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES "
        f"('{ROOM_COLD}', '{user_id}', now()),"
        f"('{ROOM_WARM}', '{user_id}', now()) "
        "ON CONFLICT (room_id, user_id) DO NOTHING;"
        f"INSERT INTO threads (id, room_id, created_at, title) VALUES "
        f"('{ROOT_COLD}', '{ROOM_COLD}', now(), 'Cold Root'),"
        f"('{ROOT_WARM}', '{ROOM_WARM}', now(), 'Warm Root') "
        "ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title;"
        f"INSERT INTO threads (id, room_id, created_at, parent_thread_id, title) VALUES "
        f"('{THREAD_COLD}', '{ROOM_COLD}', now(), '{ROOT_COLD}', 'Cold Branch'),"
        f"('{THREAD_WARM}', '{ROOM_WARM}', now(), '{ROOT_WARM}', 'Warm Branch') "
        "ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title;"
        f"INSERT INTO messages (id, thread_id, sequence, created_at, speaker_type, "
        "user_id, message_type, content, metadata) "
        f"SELECT CASE WHEN n = 13 THEN '{MESSAGE_COLD}'::uuid ELSE gen_random_uuid() END, "
        f"'{THREAD_COLD}', n, now() - ((26 - n) || ' minutes')::interval, 'human', "
        f"'{user_id}', 'text', CASE WHEN n = 13 THEN 'Cold notification target' "
        "ELSE 'Cold branch context line ' || n END, "
        "'{\"fixture\":\"push-deep-link\"}'::jsonb FROM generate_series(1, 25) n;"
        f"INSERT INTO messages (id, thread_id, sequence, created_at, speaker_type, "
        "user_id, message_type, content, metadata) "
        f"SELECT CASE WHEN n = 13 THEN '{MESSAGE_WARM}'::uuid ELSE gen_random_uuid() END, "
        f"'{THREAD_WARM}', n, now() - ((26 - n) || ' minutes')::interval, 'human', "
        f"'{user_id}', 'text', CASE WHEN n = 13 THEN 'Warm notification target' "
        "ELSE 'Warm branch context line ' || n END, "
        "'{\"fixture\":\"push-deep-link\"}'::jsonb FROM generate_series(1, 25) n;"
    )


def login(page: Page) -> None:
    page.goto(BASE)
    page.evaluate(
        """async () => {
          const regs = await navigator.serviceWorker?.getRegistrations?.() ?? []
          await Promise.all(regs.map(reg => reg.unregister()))
          const keys = await caches?.keys?.() ?? []
          await Promise.all(keys.map(key => caches.delete(key)))
        }""",
    )
    page.reload()
    page.fill('input[type="email"]', EMAIL)
    page.fill('input[type="password"]', PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_selector(".room-title", timeout=15_000)


def wait_for_target(page: Page, message_id: str) -> None:
    page.wait_for_function(
        """messageId => {
          const target = document.querySelector(`[data-message-id="${messageId}"]`)
          return target?.classList.contains('msg-flash') === true
        }""",
        arg=message_id,
        timeout=15_000,
    )
    # The component deliberately uses a smooth centered scroll. The flash is
    # applied at animation start, so wait on geometry as the separate proof
    # that the scroll completed instead of sampling that first frame.
    page.wait_for_function(
        """messageId => {
          const target = document.querySelector(`[data-message-id="${messageId}"]`)
          const stream = document.querySelector('.messages-wrapper')
          if (!target || !stream) return false
          const targetRect = target.getBoundingClientRect()
          const streamRect = stream.getBoundingClientRect()
          const delta = Math.abs(
            targetRect.top + targetRect.height / 2
            - (streamRect.top + streamRect.height / 2)
          )
          return delta <= streamRect.height * 0.35
        }""",
        arg=message_id,
        timeout=5_000,
    )


def destination_state(page: Page, message_id: str) -> dict[str, Any]:
    return page.evaluate(
        """messageId => {
          const target = document.querySelector(`[data-message-id="${messageId}"]`)
          const stream = document.querySelector('.messages-wrapper')
          const targetRect = target?.getBoundingClientRect()
          const streamRect = stream?.getBoundingClientRect()
          return {
            room: document.querySelector('.room-title')?.textContent?.trim() ?? null,
            branch: document.querySelector('select[aria-label="Branch"]')?.value ?? null,
            visible: Boolean(targetRect && targetRect.width > 0 && targetRect.height > 0),
            flashed: target?.classList.contains('msg-flash') ?? false,
            centerDelta: targetRect && streamRect
              ? Math.abs(
                  targetRect.top + targetRect.height / 2
                  - (streamRect.top + streamRect.height / 2)
                )
              : null,
            streamHeight: streamRect?.height ?? null,
          }
        }""",
        message_id,
    )


def run_viewport(browser: Browser, width: int, height: int) -> None:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        timezone_id="America/Chicago",
    )
    page = context.new_page()
    login(page)

    cold_url = (
        f"{BASE}/?room={ROOM_COLD}&thread={THREAD_COLD}&message={MESSAGE_COLD}"
    )
    page.goto(cold_url)
    wait_for_target(page, MESSAGE_COLD)
    cold = destination_state(page, MESSAGE_COLD)
    check(f"{width}: cold URL retains every axis", page.url == cold_url, page.url)
    check(f"{width}: cold tap names the canonical room", cold["room"] == "Cold Signal Room", str(cold))
    check(f"{width}: cold tap selects the persisted branch", cold["branch"] == THREAD_COLD, str(cold))
    check(f"{width}: cold target is visible and flashing", cold["visible"] and cold["flashed"], str(cold))

    page.evaluate(
        """destination => navigator.serviceWorker.dispatchEvent(
          new MessageEvent('message', { data: destination })
        )""",
        {
            "type": "open-message",
            "roomId": ROOM_WARM,
            "threadId": THREAD_WARM,
            "messageId": MESSAGE_WARM,
        },
    )
    wait_for_target(page, MESSAGE_WARM)
    warm_url = (
        f"{BASE}/?room={ROOM_WARM}&thread={THREAD_WARM}&message={MESSAGE_WARM}"
    )
    warm = destination_state(page, MESSAGE_WARM)
    page.screenshot(
        path=str(SHOT_DIR / f"push-message-{width}.png"),
        full_page=False,
    )
    check(f"{width}: warm tap writes exact history", page.url == warm_url, page.url)
    check(f"{width}: warm tap switches to the canonical room", warm["room"] == "Warm Signal Room", str(warm))
    check(f"{width}: warm tap selects the persisted branch", warm["branch"] == THREAD_WARM, str(warm))
    check(f"{width}: warm target is visible and flashing", warm["visible"] and warm["flashed"], str(warm))
    centered = (
        isinstance(warm["centerDelta"], (int, float))
        and isinstance(warm["streamHeight"], (int, float))
        and warm["centerDelta"] <= warm["streamHeight"] * 0.35
    )
    check(f"{width}: warm target lands near stream center", centered, str(warm))
    context.close()


def main() -> None:
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    seed()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        run_viewport(browser, 390, 844)
        run_viewport(browser, 1024, 900)
        browser.close()

    failed = [result for result in results if not result[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        for name, _, detail in failed:
            print(f"  FAILED: {name} — {detail}")
        sys.exit(1)


if __name__ == "__main__":
    main()
