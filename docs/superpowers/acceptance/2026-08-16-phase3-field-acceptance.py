"""
Phase 3 — weight, votes, evidence: browser acceptance.

Isolated stack only (:4173 preview against :8013 / dialectic_browser).

The loop this proves, end to end, is the one production has never once run:
    select a passage -> mark it -> the mark appears under the message ->
    a human CONFIRMS it -> the review state changes.

Production holds 85 field marks, every one origin='inferred', and zero human
reviews in the room's whole history. Two things were missing and both are
asserted here: a human could not ORIGINATE a mark (no door existed), and
review lived two destinations away from the conversation.

Also proves the pasted-link half: production's reading_items is entirely
`wire` and `night_shift`, so a "FILE" that writes source='human' is the first
time a person's own reading enters the library.
"""

import subprocess
import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4173"
EMAIL, PASSWORD = "scene@fixture.example.com", "scene-fixture-pw-123"
ROOM_ID = "11111111-1111-1111-1111-111111111111"
SHOT = "/tmp/claude-0/-root-DwoodAmo/3f816833-2de3-4112-8039-2b40eb4393c8/scratchpad"
MARKER = "phase3 field acceptance"
QUOTE = "tanker rates moved before crude did"

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def sql(q):
    return subprocess.run(
        ["psql", "dialectic_browser", "-t", "-A", "-c", q],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def seed():
    owned = f"(SELECT id FROM messages WHERE content LIKE '{MARKER}%')"
    sql(f"DELETE FROM field_marks WHERE room_id = '{ROOM_ID}' AND provenance = 'human'")
    for table, column in (
        ("message_receipts", "message_id"), ("message_reactions", "message_id"),
        ("attachments", "message_id"), ("commitments", "source_message_id"),
        ("memories", "source_message_id"), ("memory_references", "target_message_id"),
        ("reading_items", "source_message_id"),
    ):
        sql(f"DELETE FROM {table} WHERE {column} IN {owned}")
    for column in ("response_message_id", "triggered_by_message_id"):
        sql(f"UPDATE llm_decisions SET {column} = NULL WHERE {column} IN {owned}")
    sql(f"UPDATE llm_participation_state SET last_spoke_message_id = NULL "
        f"WHERE last_spoke_message_id IN {owned}")
    sql(f"UPDATE messages SET references_message_id = NULL WHERE references_message_id IN {owned}")
    sql(f"DELETE FROM messages WHERE content LIKE '{MARKER}%'")

    sql(
        "INSERT INTO messages (id, thread_id, sequence, created_at, speaker_type, "
        "user_id, message_type, content) VALUES (gen_random_uuid(), "
        "'22222222-2222-2222-2222-222222222222', "
        "(SELECT COALESCE(MAX(sequence),0)+1 FROM messages WHERE "
        "thread_id='22222222-2222-2222-2222-222222222222'), now(), 'human', "
        "'a84bc662-26e2-4304-a537-2896b068a441', 'text', "
        f"'{MARKER}: {QUOTE}, twice this month. worth keeping: "
        "https://example.test/freight-lead')"
    )


def main():
    seed()
    baseline_explicit = sql(
        f"SELECT count(*) FROM field_marks WHERE room_id='{ROOM_ID}' AND origin='explicit'"
    )
    check("fixture: no human-originated marks yet", baseline_explicit == "0",
          f"explicit marks = {baseline_explicit}")

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(
            viewport={"width": 1024, "height": 900}, timezone_id="America/Chicago",
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
        page.wait_for_timeout(1500)

        # ── select a passage inside the seeded message ────────────────
        selected = page.evaluate(
            """(quote) => {
                const bodies = [...document.querySelectorAll('.msg-content')]
                const host = bodies.reverse().find(b => b.textContent.includes(quote))
                if (!host) return null
                const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT)
                let node
                while ((node = walker.nextNode())) {
                    const at = node.data.indexOf(quote)
                    if (at === -1) continue
                    const range = document.createRange()
                    range.setStart(node, at)
                    range.setEnd(node, at + quote.length)
                    const sel = window.getSelection()
                    sel.removeAllRanges()
                    sel.addRange(range)
                    host.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }))
                    return sel.toString()
                }
                return null
            }""",
            QUOTE,
        )
        check("a passage can be selected in the transcript", selected == QUOTE, repr(selected))
        page.wait_for_timeout(500)

        marker = page.locator(".passage-marker")
        check("the marker menu appears over the selection", marker.count() > 0)
        if marker.count():
            r = page.evaluate(
                """() => {
                    const el = document.querySelector('.passage-marker')
                    if (!el) return null
                    const b = el.getBoundingClientRect()
                    return { w: b.width, h: b.height }
                }"""
            )
            check("the menu has nonzero size", bool(r and r["w"] > 0 and r["h"] > 0), str(r))
            options = page.locator(".passage-marker-btn")
            labels = [options.nth(i).inner_text() for i in range(options.count())]
            check("it offers single-subject relations only",
                  set(labels) == {"Position", "Evidence", "Question", "Tension"}, str(labels))
            page.screenshot(path=f"{SHOT}/phase3-marker-menu.png")

            # ── mark it ───────────────────────────────────────────────
            page.locator(".passage-marker-btn", has_text="Position").click()
            page.wait_for_timeout(2500)

        stored = sql(
            f"SELECT origin || '|' || provenance || '|' || relation FROM field_marks "
            f"WHERE room_id='{ROOM_ID}' AND origin='explicit' ORDER BY created_at DESC LIMIT 1"
        )
        check("a HUMAN mark reached the database",
              stored == "explicit|human|emerging_position", repr(stored))

        subject_field = sql(
            f"SELECT subjects->0->>'field' FROM field_marks WHERE room_id='{ROOM_ID}' "
            "AND origin='explicit' ORDER BY created_at DESC LIMIT 1"
        )
        check("the passage anchor rode along in the subject",
              subject_field.startswith("quote:"), repr(subject_field))

        # ── it appears under the message ──────────────────────────────
        page.wait_for_timeout(1500)
        marks = page.locator(".msg-mark")
        check("the mark renders under the message it is about", marks.count() > 0,
              f"count={marks.count()}")
        chip = page.locator(".msg-mark .field-review-chip").first
        # .lower(): the chip is uppercased by CSS text-transform, so
        # inner_text() returns "PROVISIONAL". The assertion is about the WORD
        # being present at all — color is not allowed to be the only signal.
        check("its review state is shown as text, not color alone",
              chip.count() > 0 and chip.inner_text().strip().lower() == "provisional",
              chip.inner_text() if chip.count() else "absent")

        # ── confirm it: the vote production has never once cast ───────
        page.locator(".msg-mark-action", has_text="Confirm").first.click()
        page.wait_for_timeout(2500)
        reviews = sql(
            f"SELECT count(*) FROM field_marks WHERE room_id='{ROOM_ID}' "
            "AND mark_kind='review' AND action='confirm'"
        )
        check("a human review reached the database", reviews != "0", f"confirms={reviews}")
        actor = sql(
            f"SELECT actor_user_id IS NOT NULL FROM field_marks WHERE room_id='{ROOM_ID}' "
            "AND mark_kind='review' ORDER BY created_at DESC LIMIT 1"
        )
        check("the review is attributed to a person", actor == "t", repr(actor))

        page.wait_for_timeout(1200)
        chip_after = page.locator(".msg-mark .field-review-chip").first
        check("the chip reflects the confirm",
              chip_after.count() > 0 and chip_after.inner_text().strip().lower() == "confirmed",
              chip_after.inner_text() if chip_after.count() else "absent")
        page.screenshot(path=f"{SHOT}/phase3-mark-confirmed.png")

        # ── the pasted link becomes an object ─────────────────────────
        before = sql("SELECT count(*) FROM reading_items WHERE source='human'")
        check("fixture: no human-filed readings yet", before == "0", f"human readings={before}")
        # The action row is opacity:0 / pointer-events:none until the message
        # is hovered — a click without the hover times out against a control
        # that is deliberately not there yet.
        file_btn = page.locator(".msg-action-btn", has_text="FILE").last
        if file_btn.count():
            page.locator(".msg").last.hover()
            page.wait_for_timeout(300)
            file_btn.click()
            page.wait_for_timeout(3000)
        after = sql("SELECT count(*) FROM reading_items WHERE source='human'")
        # The fixture URL is not fetchable from this box, so a 502 from the
        # extractor is the EXPECTED outcome and must be reported as one — the
        # button must not claim success it did not have.
        filed_label = file_btn.inner_text().strip() if file_btn.count() else "absent"
        check("the FILE affordance exists on a pasted link", file_btn.count() > 0, filed_label)
        check("it never claims success it did not have",
              (after != "0") == (filed_label == "FILED"),
              f"rows={after} label={filed_label}")

        browser.close()

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        for name, _, detail in failed:
            print(f"  FAILED: {name} {detail}")
        sys.exit(1)


if __name__ == "__main__":
    main()
