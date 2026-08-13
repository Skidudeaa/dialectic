"""
Release 1 — F3 isolated browser acceptance.

Drives the PRODUCTION build through vite preview against the isolated backend
on :8013 (DB dialectic_browser). No production service is touched.

Recorded hazards this harness defends against:
  - workbox served a STALE bundle during Task Group A and a working fix read as
    broken. Every context unregisters service workers and clears caches first.
  - headless Chromium defaults to UTC; the app's clock is America/Chicago, and
    it is currently near the date boundary. The timezone is pinned.
  - a layout assertion on a hidden element passes vacuously — a 0x0 box
    satisfies every <= bound. Nonzero size is asserted BEFORE any fit bound.
"""

import json
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:4173"
API = "http://localhost:8013"
EMAIL, PASSWORD = "scene@fixture.example.com", "scene-fixture-pw-123"
HOME_ID = "0e260a3b-7c83-4ec1-8f0d-7178cbbabb0a"
ROOM_ID = "11111111-1111-1111-1111-111111111111"
SHOT = "/tmp/claude-0/-root-DwoodAmo/281c2af1-6479-4568-95d1-fced1e002bff/scratchpad"

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def fresh_context(browser, width=1440, height=900):
    ctx = browser.new_context(
        viewport={"width": width, "height": height},
        timezone_id="America/Chicago",
    )
    page = ctx.new_page()
    page.goto(BASE, wait_until="domcontentloaded")
    # The stale-bundle defence, before anything is believed.
    page.evaluate("""async () => {
      if (navigator.serviceWorker) {
        const regs = await navigator.serviceWorker.getRegistrations()
        await Promise.all(regs.map(r => r.unregister()))
      }
      if (window.caches) {
        const keys = await caches.keys()
        await Promise.all(keys.map(k => caches.delete(k)))
      }
    }""")
    return ctx, page


def sign_in(page, tokens):
    """Install the fixture identity the way the app persists it, then reload."""
    page.evaluate(
        """([auth]) => {
            localStorage.setItem('dialectic-auth', JSON.stringify({
              state: {
                user: { id: auth.user_id, display_name: auth.display_name },
                accessToken: auth.access_token,
                refreshToken: auth.refresh_token,
                isAuthenticated: true,
                currentRoom: null, roomToken: null,
              },
              version: 0,
            }))
        }""",
        [tokens],
    )


def settle(page):
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(600)


def scene_of(page):
    """What the app says it is showing, read off the REAL markers.

    The first version of this harness guessed `[data-scene]`, `.home-pulse` and
    a bare `[aria-current]`, and reported the House missing when it was there —
    the attribute is `data-workspace-scene`, the container is `.home-house`, and
    the room rail carries an `aria-current` of its own that a bare selector
    grabs first. A probe that never reaches the code proves nothing about it.
    """
    return page.evaluate("""() => ({
      url: location.pathname + location.search,
      scene: document.querySelector('[data-workspace-scene]')
               ?.getAttribute('data-workspace-scene') ?? null,
      house: !!document.querySelector('.home-house'),
      record: !!document.querySelector('.msg, .composer'),
      switcher: document.querySelector('.scene-switcher [aria-current="page"]')
                  ?.textContent?.trim() ?? null,
      switcherPresent: !!document.querySelector('.scene-switcher'),
    })""")


def overflow(page):
    return page.evaluate("""() => ({
      docWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      bodyHeight: document.body.getBoundingClientRect().height,
    })""")


def main():
    import urllib.request

    req = urllib.request.Request(
        f"{API}/auth/login",
        data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
        headers={"Content-Type": "application/json"},
    )
    tokens = json.load(urllib.request.urlopen(req))

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # --- 1. bare / with nothing stored -> Home -> House ----------------
        ctx, page = fresh_context(browser)
        sign_in(page, tokens)
        page.goto(BASE + "/", wait_until="domcontentloaded")
        settle(page)
        state = scene_of(page)
        check("bare / opens Home -> House",
              state["url"] == "/" and state["scene"] == "house"
              and state["house"] and state["switcher"] == "House",
              json.dumps(state))
        page.screenshot(path=f"{SHOT}/f3-01-home-house.png")

        # --- 2. Home -> Record has a canonical URL surviving reload -------
        page.goto(BASE + "/?scene=record", wait_until="domcontentloaded")
        settle(page)
        after = scene_of(page)
        check("/?scene=record renders Record",
              "scene=record" in after["url"] and after["scene"] == "record"
              and after["record"] and not after["house"],
              json.dumps(after))
        page.reload(wait_until="domcontentloaded")
        settle(page)
        reloaded = scene_of(page)
        check("Record survives reload",
              "scene=record" in reloaded["url"] and reloaded["scene"] == "record",
              json.dumps(reloaded))
        page.screenshot(path=f"{SHOT}/f3-02-home-record.png")

        # Back/Forward must be exercised IN-DOCUMENT. Driving it with
        # page.goto() then go_back() produces a full page LOAD, which re-boots
        # the app and tests restoration instead of history — the harness would
        # then be reporting on a code path it never reached.
        # A FRESH window: by this point the previous one has stored a scene,
        # and restoration would answer the bare `/` before history ever got a
        # say — the check would then be reporting on the wrong feature.
        ctx.close()
        ctx, page = fresh_context(browser)
        sign_in(page, tokens)
        page.goto(BASE + "/", wait_until="domcontentloaded")
        settle(page)
        # By TEXT, not by `:not([aria-current])` — the attribute selector
        # matched without clicking the button meant, and the harness then read
        # an unchanged page as a broken switcher.
        page.get_by_role("button", name="Record").first.click()
        settle(page)
        switched = scene_of(page)
        check("the switcher pushes a canonical Record URL",
              "scene=record" in switched["url"] and switched["scene"] == "record",
              json.dumps(switched))
        page.go_back()
        settle(page)
        back = scene_of(page)
        check("Back returns to House at /",
              back["url"] == "/" and back["scene"] == "house", json.dumps(back))
        page.go_forward()
        settle(page)
        fwd = scene_of(page)
        check("Forward returns to Record",
              "scene=record" in fwd["url"] and fwd["scene"] == "record",
              json.dumps(fwd))

        # --- 3. ordinary room URL unchanged --------------------------------
        page.goto(f"{BASE}/?room={ROOM_ID}", wait_until="domcontentloaded")
        settle(page)
        room = scene_of(page)
        check("ordinary room serializes ?room= with no scene param, no switcher",
              f"room={ROOM_ID}" in room["url"] and "scene=" not in room["url"]
              and not room["switcherPresent"],
              json.dumps(room))

        # --- 6. proposal cards (D) -----------------------------------------
        text = page.inner_text("body").lower()
        cards = {
            "Drafted prediction": "drafted prediction" in text,
            "File in the library": "file in the library" in text,
            "Heard a commitment": "heard a commitment" in text,
        }
        check("proposal cards render from stored metadata",
              all(cards.values()), json.dumps(cards))
        disarm = page.evaluate("""() => {
          const t = document.body.innerText
          return {
            accepted_shown: t.toLowerCase().includes('on the record'),
            open_button: !!Array.from(document.querySelectorAll('button'))
              .find(b => b.textContent.toLowerCase().includes('put it on record')),
          }
        }""")
        check("the accepted commitment is disarmed, the open one is not",
              disarm["accepted_shown"] and disarm["open_button"],
              json.dumps(disarm))
        page.screenshot(path=f"{SHOT}/f3-03-proposals.png", full_page=True)

        # --- 4. E: bare / restores the window's last room -------------------
        page.goto(BASE + "/", wait_until="domcontentloaded")
        settle(page)
        restored = scene_of(page)
        check("bare / restores the window's last room (E)",
              f"room={ROOM_ID}" in restored["url"] and not restored["switcherPresent"],
              json.dumps(restored))

        # --- 5. E: a deep link still overrides stored state -----------------
        page.goto(BASE + "/?scene=record", wait_until="domcontentloaded")
        settle(page)
        deep = scene_of(page)
        check("a deep link overrides the restored room (E)",
              "scene=record" in deep["url"] and f"room={ROOM_ID}" not in deep["url"],
              json.dumps(deep))
        ctx.close()

        # --- 7. widths ------------------------------------------------------
        for width, label in ((1600, "large desktop"), (1200, "1200"),
                             (1024, "exactly 1024"), (820, "tablet"),
                             (390, "phone")):
            ctx, page = fresh_context(browser, width=width, height=900)
            sign_in(page, tokens)
            page.goto(f"{BASE}/?room={ROOM_ID}", wait_until="domcontentloaded")
            settle(page)
            box = overflow(page)
            # Nonzero FIRST: a collapsed page satisfies every <= bound.
            rendered = box["bodyHeight"] > 100 and box["clientWidth"] > 0
            fits = box["docWidth"] <= box["clientWidth"]
            check(f"no horizontal overflow at {label}",
                  rendered and fits, json.dumps(box))
            page.screenshot(path=f"{SHOT}/f3-w{width}.png")
            ctx.close()

        browser.close()

    print()
    failed = [name for name, ok, _ in results if not ok]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILED:", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
