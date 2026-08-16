"""Five-width browser gate for the big-bang stabilization worktree.

Drives an isolated ``dialectic_browser`` fixture through a Vite preview. The
default ports are 8013/4173 and environment overrides keep parallel fixtures
independent. It never calls a mutating product endpoint.
"""

import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Page, sync_playwright


BASE = os.environ.get("DIALECTIC_ACCEPTANCE_BASE", "http://localhost:4173")
API = os.environ.get("DIALECTIC_ACCEPTANCE_API", "http://127.0.0.1:8013")
EMAIL = "scene@fixture.example.com"
PASSWORD = "scene-fixture-pw-123"
ROOM_ID = "11111111-1111-1111-1111-111111111111"
AXE_PATH = (
    Path(__file__).resolve().parents[3]
    / "dialectic/frontend/app/node_modules/axe-core/axe.min.js"
)
SHOT_DIR = Path("/tmp/dialectic-big-bang-acceptance")
WIDTHS = (
    (390, 844, "phone"),
    (820, 1180, "ipad-portrait"),
    (1180, 820, "ipad-landscape"),
    (1366, 900, "laptop"),
    (1600, 1000, "wide-desktop"),
)

results: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    results.append((name, bool(passed), detail))
    suffix = f" — {detail}" if detail else ""
    print(f"{'PASS' if passed else 'FAIL'}  {name}{suffix}")


def login() -> dict[str, Any]:
    request = urllib.request.Request(
        f"{API}/auth/login",
        data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def fresh_page(
    browser: Browser,
    tokens: dict[str, Any],
    width: int,
    height: int,
) -> tuple[Any, Page]:
    context = browser.new_context(
        viewport={"width": width, "height": height},
        timezone_id="America/Chicago",
        color_scheme="dark",
    )
    page = context.new_page()
    page.goto(BASE, wait_until="domcontentloaded")
    page.evaluate(
        """async () => {
          if (navigator.serviceWorker) {
            const registrations = await navigator.serviceWorker.getRegistrations()
            await Promise.all(registrations.map((registration) => registration.unregister()))
          }
          if (window.caches) {
            const keys = await caches.keys()
            await Promise.all(keys.map((key) => caches.delete(key)))
          }
        }"""
    )
    page.evaluate(
        """([auth]) => localStorage.setItem('dialectic-auth', JSON.stringify({
          state: {
            user: { id: auth.user_id, display_name: auth.display_name },
            accessToken: auth.access_token,
            refreshToken: auth.refresh_token,
            isAuthenticated: true,
            currentRoom: null,
            roomToken: null,
          },
          version: 0,
        }))""",
        [tokens],
    )
    return context, page


def settle(page: Page) -> None:
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)


def visible_action_metrics(page: Page) -> list[dict[str, Any]]:
    return page.evaluate(
        """() => Array.from(document.querySelectorAll(
          'button, a[href], select, input, textarea, summary, [role="menuitem"]'
        )).filter((node) => {
          if (node.matches('a[href]') && node.closest('.msg-content, .prose-body')) {
            return false
          }
          const style = getComputedStyle(node)
          const rect = node.getBoundingClientRect()
          return node.getClientRects().length > 0
            && style.visibility !== 'hidden'
            && style.display !== 'none'
            && rect.right > 0 && rect.bottom > 0
            && rect.left < innerWidth && rect.top < innerHeight
        }).map((node) => {
          const rect = node.getBoundingClientRect()
          return {
            label: node.getAttribute('aria-label') || node.textContent.trim() || node.tagName,
            width: Math.round(rect.width * 10) / 10,
            height: Math.round(rect.height * 10) / 10,
            fontSize: parseFloat(getComputedStyle(node).fontSize),
          }
        })"""
    )


def shell_facts(page: Page) -> dict[str, Any]:
    return page.evaluate(
        """() => {
          const layout = document.querySelector('.app-layout')
          const rect = layout?.getBoundingClientRect()
          const selectedTabs = Array.from(document.querySelectorAll(
            '[role="tab"][aria-selected="true"]'
          )).filter((node) => {
            const box = node.getBoundingClientRect()
            return box.right > 0 && box.left < innerWidth && box.bottom > 0 && box.top < innerHeight
          })
          layout?.style.setProperty('--safe-top', '13px')
          layout?.style.setProperty('--safe-right', '11px')
          layout?.style.setProperty('--safe-bottom', '9px')
          layout?.style.setProperty('--safe-left', '7px')
          const safeStyle = layout ? getComputedStyle(layout) : null
          const safePadding = safeStyle ? {
            top: parseFloat(safeStyle.paddingTop),
            right: parseFloat(safeStyle.paddingRight),
            bottom: parseFloat(safeStyle.paddingBottom),
            left: parseFloat(safeStyle.paddingLeft),
          } : null
          for (const name of ['--safe-top', '--safe-right', '--safe-bottom', '--safe-left']) {
            layout?.style.removeProperty(name)
          }
          return {
            documentWidth: document.documentElement.scrollWidth,
            viewportWidth: document.documentElement.clientWidth,
            layoutTop: rect?.top ?? -1,
            layoutBottom: rect?.bottom ?? -1,
            viewportHeight: innerHeight,
            selectedTabs: selectedTabs.length,
            namedTabPanel: !!document.querySelector('[role="tabpanel"][aria-label]'),
            safePadding,
          }
        }"""
    )


def open_context(page: Page, width: int) -> None:
    if width < 1280:
        button = page.get_by_role("button", name="Open context drawer")
        if button.count() == 0:
            button = page.get_by_role("button", name="Open cockpit panel")
        if button.count() > 0:
            button.click()
    else:
        button = page.get_by_role("button", name="Open desktop context panel")
        if button.count() > 0:
            button.click()
    page.wait_for_timeout(200)


def run_axe(page: Page) -> list[dict[str, Any]]:
    page.add_script_tag(path=str(AXE_PATH))
    return page.evaluate(
        """() => axe.run(document, {
          runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag22aa'] },
        }).then((result) => result.violations)"""
    )


def check_scene_reachability(page: Page) -> None:
    scheme_scenes = ("record", "bench", "field", "library", "ledger")
    home_scenes = ("house", "atlas")
    for scene in scheme_scenes:
        page.goto(f"{BASE}/?room={ROOM_ID}&scene={scene}", wait_until="domcontentloaded")
        settle(page)
        check(
            f"scene reachable: {scene}",
            page.locator(f"[data-workspace-scene='{scene}']").count() == 1,
            page.url,
        )
    for scene in home_scenes:
        page.goto(f"{BASE}/?scene={scene}", wait_until="domcontentloaded")
        settle(page)
        check(
            f"scene reachable: {scene}",
            page.locator(f"[data-workspace-scene='{scene}']").count() == 1,
            page.url,
        )


def main() -> int:
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    if not AXE_PATH.is_file():
        check("axe-core is available from this worktree", False, str(AXE_PATH))
        return 1
    tokens = login()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width, height, label in WIDTHS:
            context, page = fresh_page(browser, tokens, width, height)
            page.goto(f"{BASE}/?room={ROOM_ID}", wait_until="domcontentloaded")
            settle(page)
            open_context(page, width)

            metrics = visible_action_metrics(page)
            undersized = [
                metric
                for metric in metrics
                if metric["width"] < 44 or metric["height"] < 44
            ]
            tiny_type = [metric for metric in metrics if metric["fontSize"] < 12]
            check(
                f"44px visible action targets at {label}",
                not undersized,
                json.dumps(undersized[:12]),
            )
            check(
                f"12px visible action type at {label}",
                not tiny_type,
                json.dumps(tiny_type[:12]),
            )

            facts = shell_facts(page)
            check(
                f"no horizontal overflow at {label}",
                facts["documentWidth"] <= facts["viewportWidth"],
                json.dumps(facts),
            )
            check(
                f"safe-area shell stays inside viewport at {label}",
                facts["layoutTop"] >= 0
                and facts["layoutBottom"] <= facts["viewportHeight"] + 1
                and facts["safePadding"] == {
                    "top": 13,
                    "right": 11,
                    "bottom": 9,
                    "left": 7,
                },
                json.dumps(facts),
            )
            check(
                f"one accessible active context tab at {label}",
                facts["selectedTabs"] == 1 and facts["namedTabPanel"],
                json.dumps(facts),
            )

            violations = run_axe(page)
            serious = [
                violation
                for violation in violations
                if violation["impact"] in ("serious", "critical")
            ]
            contrast = [
                violation
                for violation in violations
                if violation["id"] == "color-contrast"
            ]
            check(
                f"axe document has no serious or critical violations at {label}",
                not serious,
                json.dumps([
                    {
                        "id": violation["id"],
                        "impact": violation["impact"],
                        "nodes": len(violation["nodes"]),
                    }
                    for violation in serious
                ]),
            )
            check(
                f"normal text contrast is at least 4.5:1 at {label}",
                not contrast,
                json.dumps([
                    {"id": violation["id"], "nodes": len(violation["nodes"])}
                    for violation in contrast
                ]),
            )
            page.screenshot(path=str(SHOT_DIR / f"{label}-{width}.png"), full_page=True)
            context.close()

        context, page = fresh_page(browser, tokens, 820, 1180)
        check_scene_reachability(page)
        context.close()
        browser.close()

    failed = [name for name, passed, _ in results if not passed]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILED:", json.dumps(failed, indent=2))
    print(f"Screenshots: {SHOT_DIR}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
