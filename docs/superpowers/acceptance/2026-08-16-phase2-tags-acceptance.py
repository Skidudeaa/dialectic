"""
Phase 2 — the meta tag: browser acceptance.

Isolated stack only (:4173 preview against :8013 / dialectic_browser).

What it proves, end to end and through the REAL socket:
  compose with a tag -> the server validates it -> it is stored -> it
  broadcasts -> it renders -> and it can be FOUND again.

The last one is the whole feature. The ask was "a tag or marker ... so we
don't lose track of them"; a tag that stores but cannot be retrieved is
decoration, so the search half is asserted as hard as the write half.
"""

import subprocess
import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:4173"
EMAIL, PASSWORD = "scene@fixture.example.com", "scene-fixture-pw-123"
ROOM_ID = "11111111-1111-1111-1111-111111111111"
SHOT = "/tmp/claude-0/-root-DwoodAmo/3f816833-2de3-4112-8039-2b40eb4393c8/scratchpad"

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def sql(q):
    return subprocess.run(
        ["psql", "dialectic_browser", "-t", "-A", "-c", q],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def main():
    marker = "phase2 tag acceptance marker"
    # Eleven foreign keys reference messages.id, and this harness trips at
    # least three of them on its own second run: reading the transcript writes
    # a receipt, and sending a message writes an llm_decisions row (the
    # interjection decision is logged even when the participant stays silent).
    # Enumerated from information_schema rather than guessed, so a new FK
    # shows up as a clear failure here rather than a mystery on re-run.
    owned = f"(SELECT id FROM messages WHERE content LIKE '{marker}%')"
    for table, column in (
        ("message_receipts", "message_id"),
        ("message_reactions", "message_id"),
        ("attachments", "message_id"),
        ("commitments", "source_message_id"),
        ("memories", "source_message_id"),
        ("memory_references", "target_message_id"),
        ("reading_items", "source_message_id"),
    ):
        sql(f"DELETE FROM {table} WHERE {column} IN {owned}")
    for column in ("response_message_id", "triggered_by_message_id"):
        sql(f"UPDATE llm_decisions SET {column} = NULL WHERE {column} IN {owned}")
    sql(f"UPDATE llm_participation_state SET last_spoke_message_id = NULL "
        f"WHERE last_spoke_message_id IN {owned}")
    sql(f"UPDATE messages SET references_message_id = NULL "
        f"WHERE references_message_id IN {owned}")
    sql(f"DELETE FROM messages WHERE content LIKE '{marker}%'")

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
        page.wait_for_selector(".msg-textarea", timeout=15000)
        page.wait_for_timeout(1200)

        # ── the toggles exist and are real buttons ────────────────────
        toggles = page.locator(".tag-btn")
        check("the composer offers tags", toggles.count() == 3,
              f"count={toggles.count()}")
        labels = [toggles.nth(i).inner_text().strip() for i in range(toggles.count())]
        check("the vocabulary is meta / bug / idea",
              set(labels) == {"#Meta", "#Bug", "#Idea"}, str(labels))
        check("a toggle reports its state to assistive tech",
              toggles.first.get_attribute("aria-pressed") == "false")

        # ── compose a tagged message through the REAL socket ──────────
        page.locator(".tag-btn", has_text="#Bug").click()
        page.wait_for_timeout(200)
        check("the toggle turns on",
              page.locator(".tag-btn.active").count() == 1,
              page.locator(".tag-btn", has_text="#Bug").get_attribute("aria-pressed"))

        composer = page.locator(".msg-textarea")
        composer.click()
        composer.type(f"{marker} — the picker lingered after choosing")
        page.keyboard.press("Enter")
        page.wait_for_timeout(2500)

        # ── it was stored, validated, as a JSON array ─────────────────
        stored = sql(
            f"SELECT metadata->>'tags' FROM messages WHERE content LIKE '{marker}%'"
        )
        check("the server stored the tag", stored == '["bug"]', repr(stored))

        # ── it renders ────────────────────────────────────────────────
        chip = page.locator(".msg-tag").last
        check("the tag renders on the message", chip.count() > 0)
        if chip.count():
            check("the chip reads as the tag", chip.inner_text().strip() == "#bug",
                  chip.inner_text())
            r = page.evaluate(
                """() => {
                    const els = document.querySelectorAll('.msg-tag')
                    const el = els[els.length - 1]
                    if (!el) return null
                    const b = el.getBoundingClientRect()
                    return { w: b.width, h: b.height }
                }"""
            )
            check("the chip has nonzero size", bool(r and r["w"] > 0 and r["h"] > 0), str(r))

        # ── the toggle cleared, so the NEXT message is not tagged too ─
        check("the toggle cleared after sending",
              page.locator(".tag-btn.active").count() == 0)

        page.screenshot(path=f"{SHOT}/phase2-tagged-message.png")

        # ── and it can be FOUND again ─────────────────────────────────
        page.keyboard.press("Control+k")
        page.wait_for_timeout(600)
        if page.locator(".search-overlay").count() == 0:
            page.locator("button[title*='Search'], .search-trigger, .icon-btn").first.click()
            page.wait_for_timeout(600)
        check("search opens", page.locator(".search-overlay").count() > 0)

        page.locator(".search-tag-btn", has_text="#bug").click()
        page.wait_for_timeout(1500)
        hits = page.locator(".search-result")
        found = [hits.nth(i).inner_text() for i in range(hits.count())]
        check("a tag ALONE is a valid search (no text typed)",
              any(marker in h for h in found),
              f"{hits.count()} hits")

        page.screenshot(path=f"{SHOT}/phase2-tag-search.png")
        browser.close()

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        for name, _, detail in failed:
            print(f"  FAILED: {name} {detail}")
        sys.exit(1)


if __name__ == "__main__":
    main()
