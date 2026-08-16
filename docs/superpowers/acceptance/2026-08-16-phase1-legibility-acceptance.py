"""
Phase 1 — Legibility: browser acceptance.

Drives the PRODUCTION build through vite preview (:4173) against the isolated
backend on :8013 (DB dialectic_browser). No production service is touched.

Conventions inherited from the Release 1/3 harnesses: service workers
unregistered and caches cleared before anything is believed, timezone pinned
America/Chicago, REAL DOM markers read from the shipped components (never
guessed), and NONZERO SIZE asserted before any visibility claim — a 0x0 rect
satisfies every fit bound, which is how a hidden element passes a layout test.

What it proves (the asks, verbatim from the room):
  "I need highlights on text"          -> mention chips, three kinds
  "make the @llm a different color"    -> participant chip differs from human
  "I want to @ you easier"             -> the picker, keyboard-first
  "too hard to tell when users are
   talking to each other"              -> the address line on the byline
  three human users                    -> the SILENT member is offerable

Note preview binds ::1 only, so BASE uses localhost rather than 127.0.0.1.
"""

import subprocess
import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4173"
EMAIL, PASSWORD = "scene@fixture.example.com", "scene-fixture-pw-123"
ROOM_ID = "11111111-1111-1111-1111-111111111111"   # Scheme Room, 3 members
SHOT = "/tmp/claude-0/-root-DwoodAmo/3f816833-2de3-4112-8039-2b40eb4393c8/scratchpad"

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def sql(q):
    out = subprocess.run(
        ["psql", "dialectic_browser", "-t", "-A", "-c", q],
        capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def seed():
    """Messages that exercise every mention kind, written as a human would.

    The first is the real message from Home on 2026-08-15 that started all
    of this: addressed to a human, naming the participant as its SUBJECT.
    """
    # Receipts and reactions reference messages, and the first run of this
    # harness creates receipts by reading the transcript — so a re-run cannot
    # delete its own fixture without clearing them first.
    for table in ("message_receipts", "message_reactions"):
        sql(
            f"DELETE FROM {table} WHERE message_id IN (SELECT id FROM messages "
            "WHERE metadata->>'fixture' = 'phase1-legibility')"
        )
    sql("DELETE FROM messages WHERE metadata->>'fixture' = 'phase1-legibility'")
    rows = [
        ("a84bc662-26e2-4304-a537-2896b068a441",
         "@Fixture feature idea can you make it highlight the name if it is "
         "one of us and make the @llm a different color"),
        ("480a6ce9-4d61-4fd1-a052-39ae97541cb8",
         "@Scene good call. @Dialectic what do you make of it?"),
        ("a84bc662-26e2-4304-a537-2896b068a441",
         "no mentions here at all, just a plain sentence"),
    ]
    for i, (user_id, content) in enumerate(rows):
        safe = content.replace("'", "''")
        sql(
            "INSERT INTO messages (id, thread_id, sequence, created_at, "
            "speaker_type, user_id, message_type, content, metadata) VALUES "
            f"(gen_random_uuid(), '22222222-2222-2222-2222-222222222222', "
            f"(SELECT COALESCE(MAX(sequence),0)+1 FROM messages WHERE "
            f"thread_id='22222222-2222-2222-2222-222222222222'), "
            f"now() - interval '{10 - i} minutes', 'human', '{user_id}', "
            f"'text', '{safe}', '{{\"fixture\":\"phase1-legibility\"}}'::jsonb)"
        )


def rect(page, selector):
    return page.evaluate(
        """(sel) => {
            const el = document.querySelector(sel)
            if (!el) return null
            const r = el.getBoundingClientRect()
            return { w: r.width, h: r.height }
        }""",
        selector,
    )


def main():
    seed()
    silent = sql(
        "SELECT u.display_name FROM users u JOIN room_memberships rm "
        "ON rm.user_id = u.id WHERE rm.room_id = '%s' AND u.id NOT IN "
        "(SELECT DISTINCT user_id FROM messages WHERE user_id IS NOT NULL "
        "AND thread_id='22222222-2222-2222-2222-222222222222')" % ROOM_ID
    ).splitlines()
    check("fixture: a member exists who has never spoken", bool(silent),
          f"silent members: {silent}")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": 1024, "height": 900},
            timezone_id="America/Chicago",
        )
        page = ctx.new_page()

        page.goto(BASE)
        page.evaluate(
            """async () => {
                const regs = await navigator.serviceWorker?.getRegistrations?.() ?? []
                await Promise.all(regs.map(r => r.unregister()))
                const keys = await caches?.keys?.() ?? []
                await Promise.all(keys.map(k => caches.delete(k)))
            }"""
        )
        page.reload()

        page.fill('input[type="email"]', EMAIL)
        page.fill('input[type="password"]', PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_timeout(2500)

        page.goto(f"{BASE}/?room={ROOM_ID}")
        page.wait_for_selector(".msg-content", timeout=15000)
        page.wait_for_timeout(1200)

        # ── highlights on text ────────────────────────────────────────
        human = page.locator(".mention-human").first
        participant = page.locator(".mention-participant").first
        selfm = page.locator(".mention-self").first

        check("a human mention renders as a chip", human.count() > 0)
        check("the participant mention renders as a chip", participant.count() > 0)
        check("the reader's own mention renders as a chip", selfm.count() > 0)

        for name, sel in (("human", ".mention-human"),
                          ("participant", ".mention-participant"),
                          ("self", ".mention-self")):
            r = rect(page, sel)
            check(f"{name} chip has nonzero size", bool(r and r["w"] > 0 and r["h"] > 0), str(r))

        colors = page.evaluate(
            """() => {
                const pick = (sel) => {
                    const el = document.querySelector(sel)
                    return el ? getComputedStyle(el).color : null
                }
                return {
                    human: pick('.mention-human'),
                    participant: pick('.mention-participant'),
                    self: pick('.mention-self'),
                }
            }"""
        )
        check("@llm is a DIFFERENT color from a human mention",
              colors["participant"] != colors["human"], str(colors))
        check("your own mention differs from both",
              colors["self"] not in (colors["human"], colors["participant"]), str(colors))

        # Color is never the only signal (Release 3 a11y contract).
        borders = page.evaluate(
            """() => {
                const b = (sel) => {
                    const el = document.querySelector(sel)
                    return el ? getComputedStyle(el).borderBottomStyle : null
                }
                return { human: b('.mention-human'), participant: b('.mention-participant') }
            }"""
        )
        check("chips differ in more than color (border style)",
              borders["human"] != borders["participant"], str(borders))

        # ── who is talking to whom ────────────────────────────────────
        addressed = page.locator(".msg-addressed")
        check("the address line renders", addressed.count() > 0,
              f"count={addressed.count()}")
        if addressed.count():
            text = addressed.first.inner_text()
            check("the address line names a person", "→" in text and len(text) > 2, text)
            r = rect(page, ".msg-addressed")
            check("address line has nonzero size", bool(r and r["w"] > 0), str(r))

        # ── mentions must not leak into code ──────────────────────────
        check("no chip inside a code element",
              page.locator("code .mention").count() == 0)

        page.screenshot(path=f"{SHOT}/phase1-1024-transcript.png", full_page=False)

        # ── the @ picker ──────────────────────────────────────────────
        composer = page.locator(".msg-textarea")
        composer.click()
        composer.type("@")
        page.wait_for_timeout(400)
        picker = page.locator(".mention-picker")
        check("the picker opens on @", picker.count() > 0)

        options = page.locator(".mention-option")
        labels = [options.nth(i).inner_text().strip() for i in range(options.count())]
        check("the picker offers the SILENT member", any(s in " ".join(labels) for s in silent),
              f"offered: {labels}")
        check("the picker offers Dialectic", any("Dialectic" in l for l in labels),
              f"offered: {labels}")
        r = rect(page, ".mention-picker")
        check("picker has nonzero size", bool(r and r["w"] > 0 and r["h"] > 0), str(r))

        page.screenshot(path=f"{SHOT}/phase1-1024-picker.png", full_page=False)

        # Keyboard: Enter must choose a name, never send the message.
        before = page.locator(".msg-content").count()
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        page.wait_for_timeout(400)
        value = composer.input_value()
        check("Enter inserted a handle instead of sending",
              value.startswith("@") and value.endswith(" ") and
              page.locator(".msg-content").count() == before, repr(value))
        check("the picker closed after choosing", page.locator(".mention-picker").count() == 0)

        page.keyboard.press("Escape")
        composer.fill("")

        # ── phone width ───────────────────────────────────────────────
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(600)
        r = rect(page, ".mention-participant")
        check("chips still render at 390", bool(r and r["w"] > 0), str(r))
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth <= window.innerWidth"
        )
        check("no horizontal overflow at 390", overflow)

        composer = page.locator(".msg-textarea")
        composer.click()
        composer.type("@")
        page.wait_for_timeout(400)
        pr = rect(page, ".mention-picker")
        check("picker fits at 390", bool(pr and pr["w"] > 0 and pr["w"] <= 390), str(pr))
        page.screenshot(path=f"{SHOT}/phase1-390-picker.png", full_page=False)

        browser.close()

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        for name, _, detail in failed:
            print(f"  FAILED: {name} {detail}")
        sys.exit(1)


if __name__ == "__main__":
    main()
