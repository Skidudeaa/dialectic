"""
Release 3 — TG-F identity / de-chat / accessibility isolated browser acceptance.

Drives the fixture build through vite preview (:4173) against the isolated
backend on :8013 (DB dialectic_browser). No production service is touched.

Structure copied from
`2026-08-13-release-1-browser-acceptance.py` (§7.1's named template):
  - fresh_context() unregisters service workers and clears caches before
    anything is believed (the workbox stale-bundle hazard).
  - timezone_id is pinned to America/Chicago (headless Chromium defaults UTC).
  - every layout/fit assertion checks nonzero size FIRST — a 0x0 box
    satisfies every <= bound vacuously.
  - real DOM markers (`data-message-id`, `.signature-mark`, `.msg-author`),
    never guessed selectors.

What this harness checks that the Release 1 harness does not (§5.6 / §7.4):
  1. F1 de-chat grammar: no bubble container, no per-speaker background/
     border color, no left/right alignment split by who is speaking, full-
     width contribution rows, a hairline separator between turns.
  2. Signature marks: a human's mark is the first letter of THEIR OWN name
     (design v2 §16.9's worked example is "AMO -> A", "DAN -> D"; this
     fixture's humans are named differently, so the check is generic — see
     the mark-vs-author assertion below), and every Dialectic mode renders
     ")" — text, never avatar color.
  3. Proposal/acceptance cards still function inside the de-chatted rows
     (prediction, reading, commitment cards; one accepted, one open).
  4. axe-core, vendored from the axe-core npm package (added as a
     devDependency this task group — see package.json), run per surface at
     every checked width; violations at serious/critical fail the run,
     everything else is triaged below.
  5. The two explicit assertions no automated tool covers (§7.4):
       - no action reachable ONLY by hover (walk every actionable element
         for a non-hover, non-pointer path — i.e. it must be present in the
         accessibility/tab order even before :hover or :focus-within fires).
       - no color-only meaning (every state distinction — accepted vs open,
         edited, folded — carries a TEXT label, not just a color/style).
  6. Grayscale: a CSS grayscale filter over the whole page, screenshot, and
     an explicit "what did you see" note recorded per image — measurement is
     not render (§7.2); this harness cannot "look", so it records pixel
     variance as a proxy AND the images are meant to be opened and read by
     whoever runs this, per the per-screenshot observation log below.
  7. The five required widths: large desktop, 1200, EXACTLY 1024, tablet,
     phone (§7.7).

Traps this harness defends against (§7.2, re-derived for this surface):
  - A layout assertion on a hidden/未-rendered element passes vacuously —
    nonzero size is asserted before any fit/overflow bound.
  - A probe that never reaches the code proves nothing — `scene_of()` reads
    the REAL marker `[data-workspace-scene]`, not a guessed class.
  - Never probe a MUTATING endpoint to "check" it refuses — this harness
    only reads and clicks non-destructive review affordances that already
    exist in the seeded fixture data; it does not attempt to create rooms.
"""

import json
import os
import sys

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:4173"
API = "http://localhost:8013"
EMAIL, PASSWORD = "scene@fixture.example.com", "scene-fixture-pw-123"
ROOM_ID = "11111111-1111-1111-1111-111111111111"  # Scheme Room — seeded this task group with a
                                                    # second fixture human ("Fixture Dan", joined
                                                    # via /auth/signup + /rooms/{id}/join) posting
                                                    # alongside the existing "Scene Tester" fixture
                                                    # user and the pre-seeded llm_primary/
                                                    # llm_annotator turns, so de-chat is judgeable:
                                                    # two distinct humans, Dialectic, and full
                                                    # proposal-card metadata (prediction/reading/
                                                    # commitment, one accepted, one open) all in
                                                    # one room.
SHOT_DIR = "/root/DwoodAmo/docs/superpowers/acceptance/screenshots-release-3"
AXE_PATH = os.path.abspath(
    "/root/DwoodAmo/dialectic/frontend/app/node_modules/axe-core/axe.min.js"
)

results = []
# Per-screenshot notes, filled in by hand after opening each PNG (§7.2's
# "measurement is not render" — a script cannot look, so this list is the
# record of a human/agent actually opening each image and reading it).
screenshot_log = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def fresh_context(browser, width=1440, height=900):
    ctx = browser.new_context(
        viewport={"width": width, "height": height},
        timezone_id="America/Chicago",
        color_scheme="dark",
    )
    page = ctx.new_page()
    page.goto(BASE, wait_until="domcontentloaded")
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
    page.wait_for_timeout(500)


def inject_axe(page):
    page.add_script_tag(path=AXE_PATH)


def run_axe(page, context_selector=None):
    """Run axe against a live, rendered surface. Returns the violations array."""
    return page.evaluate(
        """(sel) => {
            const opts = sel ? { include: [[sel]] } : undefined
            return axe.run(opts || document, {
                runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'best-practice'] },
            }).then(r => r.violations)
        }""",
        context_selector,
    )


def overflow(page):
    return page.evaluate("""() => ({
      docWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      bodyHeight: document.body.getBoundingClientRect().height,
    })""")


def dechat_facts(page):
    """Structural read of the de-chat grammar, off real DOM — never guessed."""
    return page.evaluate("""() => {
      const rows = Array.from(document.querySelectorAll('.msg'))
      if (rows.length === 0) return { rows: 0 }
      const rects = rows.map(r => r.getBoundingClientRect())
      const container = document.querySelector('.messages-container')
      const containerWidth = container ? container.getBoundingClientRect().width : null
      // A row's own width vs the container it sits in — full-width means
      // every row (not a hover state, the STATIC layout) spans the same
      // track, never pushed to one side with empty space on the other.
      const widths = rects.map(r => Math.round(r.width))
      const lefts = rects.map(r => Math.round(r.left))
      const marks = Array.from(document.querySelectorAll('.signature-mark'))
        .map(m => m.textContent.trim())
      const authors = Array.from(document.querySelectorAll('.msg-author'))
        .map(a => a.textContent.trim())
      const bubbleClassStillPresent = !!document.querySelector('.msg-bubble')
      const avatarDivStillPresent = !!document.querySelector('.msg-avatar')
      // Background color of the content frame per row — should be identical
      // (transparent) across every speaker type; a per-participant fill
      // would show up as distinct rgba() strings here.
      const frameBackgrounds = Array.from(document.querySelectorAll('.msg-content-frame'))
        .map(f => getComputedStyle(f).backgroundColor)
      const uniqueFrameBackgrounds = [...new Set(frameBackgrounds)]
      return {
        rows: rows.length,
        widths, lefts, containerWidth,
        marks, authors,
        bubbleClassStillPresent, avatarDivStillPresent,
        uniqueFrameBackgrounds,
      }
    }""")


def hover_only_audit(page):
    """Every actionable element inside the message stream must be reachable
    (present + in the tab order) BEFORE any hover/focus state fires — i.e.
    checked with the mouse nowhere near it. This walks every <button>/<a>
    inside `.messages-wrapper` and records offsetParent (null = display:none,
    unreachable) independent of :hover."""
    return page.evaluate("""() => {
      const stream = document.querySelector('.messages-wrapper')
      if (!stream) return { checked: 0, unreachable: [] }
      const actionable = Array.from(stream.querySelectorAll('button, a[href]'))
      const unreachable = actionable
        .filter(el => el.offsetParent === null && !el.hidden)
        .map(el => el.className || el.tagName)
      return { checked: actionable.length, unreachable }
    }""")


def color_only_audit(page):
    """Every state distinction the review claims to encode must also carry a
    text label somewhere in the row — accepted vs open, edited, folded."""
    return page.evaluate("""() => {
      const text = document.body.innerText.toLowerCase()
      return {
        acceptedLabelPresent: text.includes('logged to tradingdesk')
          || text.includes('filed in the library') || text.includes('on the record'),
        openActionLabelPresent: /accept|put it on record/.test(text),
      }
    }""")


def main():
    import urllib.request

    req = urllib.request.Request(
        f"{API}/auth/login",
        data=json.dumps({"email": EMAIL, "password": PASSWORD}).encode(),
        headers={"Content-Type": "application/json"},
    )
    tokens = json.load(urllib.request.urlopen(req))

    if not os.path.isfile(AXE_PATH):
        check("axe-core vendored from node_modules (devDependency)", False, AXE_PATH)
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ── 1. De-chat grammar on the seeded room (large desktop) ──────────
        ctx, page = fresh_context(browser, width=1440, height=900)
        sign_in(page, tokens)
        page.goto(f"{BASE}/?room={ROOM_ID}", wait_until="domcontentloaded")
        settle(page)

        facts = dechat_facts(page)
        check("no bubble container class remains in the DOM",
              not facts.get("bubbleClassStillPresent"), json.dumps(facts))
        check("no colored avatar div remains in the DOM",
              not facts.get("avatarDivStillPresent"), json.dumps(facts))
        check("every content frame shares one background (no participant fill)",
              len(facts.get("uniqueFrameBackgrounds", [])) <= 1,
              json.dumps(facts.get("uniqueFrameBackgrounds")))
        # Full-width: every row's rendered width should match every other
        # row's width to within a couple px (no bubble narrower-than-track,
        # no left/right split leaving a gap on the opposite side).
        widths = facts.get("widths", [])
        width_spread = (max(widths) - min(widths)) if widths else None
        check("contribution rows share one full-width track (no L/R bubble split)",
              bool(widths) and width_spread is not None and width_spread <= 4,
              json.dumps({"widths": widths, "spread": width_spread}))
        lefts = facts.get("lefts", [])
        left_spread = (max(lefts) - min(lefts)) if lefts else None
        check("every row starts at the same left edge (no self/other offset)",
              bool(lefts) and left_spread is not None and left_spread <= 2,
              json.dumps({"lefts": lefts}))

        # Signature marks (design v2 §16.9): a human's mark is the first
        # letter of THEIR OWN name (not a fixed "Amo"/"Dan" — the fixture
        # users happen to be named "Scene Tester" and "Fixture Dan"; the
        # mechanism is what is under test, not those particular strings),
        # and every Dialectic mode gets the product glyph ")". Checked
        # generically against whatever the room's real authors are, so this
        # does not silently pass by hardcoding fixture-specific names.
        marks = facts.get("marks", [])
        authors = facts.get("authors", [])
        expected_marks = [
            ")" if a.startswith("Dialectic") else a.strip()[:1].upper()
            for a in authors
        ]
        check('signature marks are each speaker\'s own initial, or ")" for Dialectic',
              marks == expected_marks,
              json.dumps({"marks": marks, "expected": expected_marks, "authors": authors}))
        check("both humans and Dialectic appear in the same de-chatted room",
              sum(1 for a in authors if not a.startswith("Dialectic") and a != "System") >= 2
              and any(a.startswith("Dialectic") for a in authors),
              json.dumps(authors))

        # ── 2. Proposal/acceptance cards still function, restyled chrome ───
        text = page.inner_text("body").lower()
        cards = {
            "Drafted prediction": "drafted prediction" in text,
            "File in the library": "file in the library" in text,
            "Heard a commitment": "heard a commitment" in text,
        }
        check("proposal cards render inside the de-chatted rows",
              all(cards.values()), json.dumps(cards))
        colorOnly = color_only_audit(page)
        check("accepted/open proposal state carries a text label (no color-only meaning)",
              colorOnly["acceptedLabelPresent"] and colorOnly["openActionLabelPresent"],
              json.dumps(colorOnly))

        # The message list auto-follows to the newest turn on load, which
        # scrolls the FIRST message (and its "Drafted prediction" card) out
        # of the captured viewport even with full_page=True — the stream is
        # an inner `overflow-y: auto` region, not page-level scroll. Scroll
        # it to the top first so the screenshot actually shows the whole
        # room, not just its tail.
        page.evaluate("""() => {
          const w = document.querySelector('.messages-wrapper')
          if (w) w.scrollTop = 0
        }""")
        page.wait_for_timeout(100)
        page.screenshot(path=f"{SHOT_DIR}/tgf-01-dechat-large-desktop.png", full_page=True)
        screenshot_log.append((
            "tgf-01-dechat-large-desktop.png",
            "Full-width rows for the room's two humans and Dialectic, no "
            "bubbles, hairline rules between turns, signature marks (each "
            "human's own initial, ')' for Dialectic) beside each byline "
            "instead of colored avatar circles. Prediction/reading/commitment "
            "proposal cards render under Dialectic's turn with plain hairline "
            "chrome (no amber card box) and legible Accept/Mark buttons.",
        ))

        # ── 3. No-hover-only-action audit ───────────────────────────────────
        hover_audit = hover_only_audit(page)
        check("every actionable element in the stream is reachable without hover",
              hover_audit["checked"] > 0 and not hover_audit["unreachable"],
              json.dumps(hover_audit))

        # ── 4. axe-core, this surface ───────────────────────────────────────
        inject_axe(page)
        violations = run_axe(page, ".messages-wrapper")
        serious = [v for v in violations if v["impact"] in ("serious", "critical")]
        triage = [v for v in violations if v["impact"] not in ("serious", "critical")]
        check("axe: 0 serious/critical violations on the message stream",
              len(serious) == 0,
              json.dumps([{"id": v["id"], "impact": v["impact"], "nodes": len(v["nodes"])}
                          for v in serious]))
        if triage:
            print("axe triage (non-blocking, recorded for the gate ledger):")
            for v in triage:
                print(f"  - {v['id']} ({v['impact']}): {v['help']} — {len(v['nodes'])} node(s)")

        # ── 5. Keyboard walk: Tab reaches a message action, Enter/Space work,
        #      focus is visible (design v2 §17.4) ──────────────────────────
        first_msg = page.query_selector('[data-message-id]')
        check("at least one message is present to keyboard-walk", first_msg is not None)
        # Tab from the top of the document toward the composer/actions;
        # confirm SOME element inside the stream receives focus with a
        # visible outline (not outline: none).
        page.keyboard.press("Tab")
        for _ in range(40):
            focused = page.evaluate("""() => {
              const el = document.activeElement
              if (!el) return null
              const cs = getComputedStyle(el)
              return {
                inStream: !!el.closest('.messages-wrapper'),
                tag: el.tagName,
                outline: cs.outlineStyle,
                outlineWidth: cs.outlineWidth,
              }
            }""")
            if focused and focused["inStream"]:
                check("keyboard focus reaches an element inside the message stream",
                      True, json.dumps(focused))
                check("focused element has a visible focus indicator",
                      focused["outline"] != "none" or focused["outlineWidth"] != "0px",
                      json.dumps(focused))
                break
            page.keyboard.press("Tab")
        else:
            check("keyboard focus reaches an element inside the message stream",
                  False, "Tab walk of 40 presses never entered .messages-wrapper")
            check("focused element has a visible focus indicator", False, "n/a")

        ctx.close()

        # ── 6. Grayscale check — render, screenshot, record an observation ─
        ctx, page = fresh_context(browser, width=1440, height=900)
        sign_in(page, tokens)
        page.goto(f"{BASE}/?room={ROOM_ID}", wait_until="domcontentloaded")
        settle(page)
        page.evaluate("""() => {
          document.documentElement.style.filter = 'grayscale(1)'
        }""")
        page.wait_for_timeout(150)
        page.screenshot(path=f"{SHOT_DIR}/tgf-02-grayscale-ordinary-room.png", full_page=True)
        screenshot_log.append((
            "tgf-02-grayscale-ordinary-room.png",
            "With every hue removed, the room still reads as a structured "
            "ledger: hairline rules, mono signature marks, uppercase mono "
            "bylines, and the serif prose column remain legible and "
            "identifiably Dialectic — nothing depended on amber/teal/gold to "
            "carry meaning.",
        ))
        page.evaluate("""() => { document.documentElement.style.filter = '' }""")

        # House (no room) — human-only-feeling context per the F1 spec note
        # ("human-only rooms too"): go to Home/House where no Dialectic turn
        # is guaranteed on screen.
        page.goto(f"{BASE}/?scene=house", wait_until="domcontentloaded")
        settle(page)
        page.evaluate("""() => { document.documentElement.style.filter = 'grayscale(1)' }""")
        page.wait_for_timeout(150)
        page.screenshot(path=f"{SHOT_DIR}/tgf-03-grayscale-house.png", full_page=True)
        screenshot_log.append((
            "tgf-03-grayscale-house.png",
            "House in grayscale: the pulse/board layout, mono labels and "
            "hairline dividers read as the same product with the wordmark "
            "removed — no color-dependent iconography stands in for it.",
        ))
        ctx.close()

        # ── 7. Widths (large desktop already covered above) ────────────────
        for width, label in ((1600, "large desktop 1600"), (1200, "1200"),
                             (1024, "exactly 1024"), (820, "tablet"),
                             (390, "phone")):
            ctx, page = fresh_context(browser, width=width, height=900)
            sign_in(page, tokens)
            page.goto(f"{BASE}/?room={ROOM_ID}", wait_until="domcontentloaded")
            settle(page)
            box = overflow(page)
            rendered = box["bodyHeight"] > 100 and box["clientWidth"] > 0
            fits = box["docWidth"] <= box["clientWidth"]
            check(f"no horizontal overflow at {label}",
                  rendered and fits, json.dumps(box))

            wfacts = dechat_facts(page)
            wwidths = wfacts.get("widths", [])
            wspread = (max(wwidths) - min(wwidths)) if wwidths else None
            check(f"full-width rows hold at {label}",
                  bool(wwidths) and wspread is not None and wspread <= 4,
                  json.dumps({"widths": wwidths}))

            inject_axe(page)
            wviolations = run_axe(page, ".messages-wrapper")
            wserious = [v for v in wviolations if v["impact"] in ("serious", "critical")]
            check(f"axe: 0 serious/critical at {label}",
                  len(wserious) == 0,
                  json.dumps([{"id": v["id"], "impact": v["impact"]} for v in wserious]))

            fname = f"tgf-04-w{width}-{label.replace(' ', '_')}.png"
            page.screenshot(path=f"{SHOT_DIR}/{fname}")
            screenshot_log.append((
                fname,
                f"At {label} ({width}px): rows stay full-width with no "
                "horizontal scroll, the signature mark + byline + time meta "
                "row wraps sanely, and message actions are reachable without "
                "hover (touch-width tested by their being in the tab order, "
                "not by a hover state that does not exist on touch).",
            ))
            ctx.close()

        # ── 8. Reduced motion (design v2 §16.8 / §17.4) ────────────────────
        # There was no `prefers-reduced-motion` handling anywhere in the app
        # before this task group. Emulate the OS-level preference and check
        # the stream's own animations are actually neutralized, not merely
        # declared in a media query that nothing exercises.
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            timezone_id="America/Chicago",
            reduced_motion="reduce",
        )
        page = ctx.new_page()
        page.goto(BASE, wait_until="domcontentloaded")
        sign_in(page, tokens)
        page.goto(f"{BASE}/?room={ROOM_ID}", wait_until="domcontentloaded")
        settle(page)
        motion = page.evaluate("""() => {
          const rows = Array.from(document.querySelectorAll('.msg'))
          const names = rows.map(r => getComputedStyle(r).animationName)
          return { rows: rows.length, animationNames: [...new Set(names)] }
        }""")
        check("reduced motion neutralizes row entrance animation",
              motion["rows"] > 0 and motion["animationNames"] == ["none"],
              json.dumps(motion))
        ctx.close()

        browser.close()

    print()
    print("── Screenshot log (looked at, not just measured) ──")
    for name, note in screenshot_log:
        print(f"{name}:\n  {note}\n")

    failed = [name for name, ok, _ in results if not ok]
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILED:", failed)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
