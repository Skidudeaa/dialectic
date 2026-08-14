"""
Release 3 — TG-H integrated-gate browser acceptance.

Drives the PRODUCTION build through vite preview (:4173) against the isolated
backend on :8013 (DB dialectic_browser). No production service is touched.
Extends the Release 1 harness's conventions: service workers unregistered and
caches cleared before anything is believed, timezone pinned America/Chicago,
REAL DOM markers read from the shipped components (never guessed), nonzero
size asserted before any fit/visibility claim.

Release 3 scenarios (PLAN.md §7.3):
  1. Field reachable in an ordinary room; a seeded provisional mark renders
     with the literal "provisional" chip (never color-only) and dashed rule.
  2. Confirm flips styling WITHOUT reordering — DOM-order assertion
     before/after a real review round-trip through the live POST.
  3. `&object=` deep link opens Focus and survives reload.
  4. The Field empty state teaches (SceneEmpty contract) in an empty room.
  5. Atlas renders at Home root and navigates a room node.
  6. Compose→accept proposal round-trip across two real users.
  7. Restoration: kill-and-reopen (new tab, sessionStorage gone,
     localStorage install tier) lands on the exact room/scene/object.
  8. An explicit deep link overrides restoration.
  9. A composer draft survives reload, unsent.
"""

import json
import subprocess
import sys
import urllib.request

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:4173"
API = "http://localhost:8013"
EMAIL, PASSWORD = "scene@fixture.example.com", "scene-fixture-pw-123"
USER2_EMAIL, USER2_PASSWORD = "gate2@fixture.example.com", "gate2-fixture-pw-123"
ROOM_ID = "11111111-1111-1111-1111-111111111111"       # Scheme Room (seeded)
EMPTY_ROOM_ID = "7fb49e4d-a09a-42bd-9de1-3aee80b88499"  # Solo Study (no marks)
SHOT = "/tmp/claude-0/-root-DwoodAmo/e755f0aa-0b98-4ba7-819f-39d142a62adb/scratchpad"

results = []


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  — {detail}" if detail else ""))


def api_post(path, body, token=None):
    req = urllib.request.Request(
        f"{API}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})},
    )
    return json.load(urllib.request.urlopen(req))


def psql(q):
    out = subprocess.run(
        ["psql", "dialectic_browser", "-t", "-A", "-c", q],
        capture_output=True, text=True, check=True,
    )
    return [line for line in out.stdout.strip().split("\n") if line]


def fresh_context(browser, width=1440, height=900):
    ctx = browser.new_context(
        viewport={"width": width, "height": height},
        timezone_id="America/Chicago",
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


def settle(page, ms=700):
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(ms)


def mark_order(page):
    """The DOM order of top-level mark rows, by data id in document order."""
    return page.eval_on_selector_all(
        ".field-mark-row:not(.is-superseded)",
        "els => els.map(e => e.querySelector('.field-mark-title')?.textContent ?? '')",
    )


def main():
    tokens = api_post("/auth/login", {"email": EMAIL, "password": PASSWORD})

    # Second real user for the accept half of the propose round-trip.
    try:
        tokens2 = api_post("/auth/login", {"email": USER2_EMAIL, "password": USER2_PASSWORD})
    except Exception:
        api_post("/auth/signup", {"email": USER2_EMAIL, "password": USER2_PASSWORD,
                                  "display_name": "Gate Second"})
        tokens2 = api_post("/auth/login", {"email": USER2_EMAIL, "password": USER2_PASSWORD})
    room_token = psql(f"SELECT token FROM rooms WHERE id = '{ROOM_ID}'")[0]
    joined = api_post(f"/rooms/{ROOM_ID}/join?token={room_token}",
                      {"user_id": tokens2["user_id"]}, token=tokens2["access_token"])
    print(f"user2 join: {joined}")

    # Fixture-only reset so every run starts from a pristine Field — the
    # append-only rule binds PRODUCTION code paths, not the disposable
    # browser fixture's own seed hygiene.
    psql(f"DELETE FROM field_marks WHERE room_id = '{ROOM_ID}'")

    # Seed two provisional inferred marks (direct SQL — a seed, not a probe).
    msg_ids = psql(
        "SELECT m.id FROM messages m JOIN threads t ON t.id = m.thread_id "
        f"WHERE t.room_id = '{ROOM_ID}' AND NOT m.is_deleted "
        "ORDER BY m.created_at LIMIT 2"
    )
    for msg_id, relation, title in [
        (msg_ids[0], "unanswered_question", "Does freight lead crude here?"),
        (msg_ids[1], "emerging_position", "Tanker rates lead crude"),
    ]:
        psql(
            "INSERT INTO field_marks (room_id, mark_kind, relation, origin, provenance, "
            "subjects, title, dedup_key) VALUES "
            f"('{ROOM_ID}', 'relation', '{relation}', 'inferred', 'field_inference', "
            f"'[{{\"entity\": \"messages\", \"id\": \"{msg_id}\"}}]'::jsonb, '{title}', "
            f"'{relation}|messages:{msg_id}') "
            "ON CONFLICT (room_id, dedup_key) WHERE dedup_key IS NOT NULL DO NOTHING"
        )

    with sync_playwright() as p:
        browser = p.chromium.launch()

        # ---- 1. Field reachable; provisional mark labeled, dashed ----------
        ctx, page = fresh_context(browser)
        sign_in(page, tokens)
        page.goto(f"{BASE}/?room={ROOM_ID}&scene=field", wait_until="domcontentloaded")
        settle(page)
        frame = page.locator("[data-workspace-scene='field']")
        check("field scene installs from the URL", frame.count() == 1)
        row = page.locator(".field-mark-row.is-provisional").first
        box = row.bounding_box() if row.count() else None
        check("provisional mark visible at nonzero size", bool(box and box["width"] > 100 and box["height"] > 10),
              f"box={box}")
        chip_text = row.inner_text() if row.count() else ""
        check("provisional state carried by a literal label", "provisional" in chip_text.lower())
        dashed = row.evaluate("e => getComputedStyle(e).borderLeftStyle") if row.count() else ""
        check("provisional rule is dashed (not color-only either)", dashed == "dashed", f"style={dashed}")
        page.screenshot(path=f"{SHOT}/gate-01-field.png", full_page=True)

        # ---- 2. confirm restyles IN PLACE — DOM order proof ---------------
        before = mark_order(page)
        check("field renders at least the two seeded marks", len(before) >= 2, f"n={len(before)}")
        row.click()
        settle(page)
        focus = page.locator("aside.focus-surface")
        check("tapping a mark opens Focus (no scene change)", focus.count() == 1
              and page.locator("[data-workspace-scene='field']").count() == 1)
        focus.get_by_role("button", name="Confirm").click()
        settle(page, 1200)
        after = mark_order(page)
        check("review round-trips: a row is now confirmed",
              page.locator(".field-mark-row.is-confirmed").count() >= 1)
        check("confirm did NOT reorder the Field (DOM-order identical)",
              before == after, f"before={before} after={after}")
        page.screenshot(path=f"{SHOT}/gate-02-confirmed.png", full_page=True)
        obj_url = page.url
        check("focus selection rides the URL as &object=", "object=" in obj_url, obj_url)

        # ---- 3. &object= deep link opens Focus, survives reload -----------
        ctx2, page2 = fresh_context(browser)
        sign_in(page2, tokens)
        page2.goto(obj_url, wait_until="domcontentloaded")
        settle(page2)
        check("object deep link opens Focus in a fresh context",
              page2.locator("aside.focus-surface").count() == 1)
        page2.reload(wait_until="domcontentloaded")
        settle(page2)
        check("focus survives reload (URL-authoritative)",
              page2.locator("aside.focus-surface").count() == 1)
        ctx2.close()

        # ---- 4. empty Field teaches ---------------------------------------
        page.goto(f"{BASE}/?room={EMPTY_ROOM_ID}&scene=field", wait_until="domcontentloaded")
        settle(page)
        empty = page.locator("[data-testid='scene-empty']")
        empty_text = empty.inner_text() if empty.count() else ""
        check("empty Field shows the teaching state, with substance",
              empty.count() == 1 and len(empty_text) > 120, f"len={len(empty_text)}")

        # ---- 5. Atlas at Home root, navigates ------------------------------
        page.goto(f"{BASE}/?scene=atlas", wait_until="domcontentloaded")
        settle(page)
        check("atlas scene installs at Home root",
              page.locator("[data-workspace-scene='atlas']").count() == 1)
        room_rows = page.locator(".atlas-row[data-kind='room']")
        first_box = room_rows.first.bounding_box() if room_rows.count() else None
        check("atlas lists room nodes at nonzero size",
              room_rows.count() >= 2 and bool(first_box and first_box["width"] > 100),
              f"rooms={room_rows.count()}")
        page.screenshot(path=f"{SHOT}/gate-05-atlas.png", full_page=True)
        target = room_rows.filter(has_text="Scheme Room").first
        target.locator(".atlas-row-open").click()
        settle(page)
        check("an atlas room node navigates into the room",
              f"room={ROOM_ID}" in page.url, page.url)

        # ---- 6. compose→accept across two users ---------------------------
        page.goto(f"{BASE}/?room={ROOM_ID}", wait_until="domcontentloaded")
        settle(page)
        page.get_by_role("button", name="+ Make a move").click()
        panel = page.locator(".propose-panel")
        check("Make a move opens without hover", panel.count() == 1)
        panel.get_by_role("button", name="Prediction").click()
        page.get_by_label("Statement").fill("Gate proof: brent settles above 90 by December")
        page.get_by_label("Confidence (%)").fill("70")
        page.get_by_label("Deadline").fill("2026-12-01")
        panel.get_by_role("button", name="Send to the room").click()
        settle(page, 1500)
        card = page.locator(".msg", has_text="Gate proof: brent settles above 90").last
        check("the proposal lands in the record as a normal message",
              card.count() >= 1)
        page.screenshot(path=f"{SHOT}/gate-06-proposed.png", full_page=True)

        ctx3, page3 = fresh_context(browser)
        sign_in(page3, tokens2)
        page3.goto(f"{BASE}/?room={ROOM_ID}", wait_until="domcontentloaded")
        settle(page3)
        card2 = page3.locator(".msg", has_text="Gate proof: brent settles above 90").last
        card2.wait_for(timeout=15000)  # count() is a snapshot; wait for the load
        check("the other user sees the proposal", card2.count() >= 1)
        card2.get_by_role("button", name="Accept").first.click()
        settle(page3, 1500)
        accepted = psql(
            "SELECT metadata->'proposal'->>'accepted_by' FROM messages "
            "WHERE metadata->'proposal'->>'statement' LIKE 'Gate proof:%' "
            "ORDER BY created_at DESC LIMIT 1"
        )
        check("acceptance stamps WHO in the stored row",
              bool(accepted and accepted[0] == tokens2["user_id"]),
              f"accepted_by={accepted}")
        ctx3.close()

        # ---- 7. restoration: kill-and-reopen to the exact spot -------------
        page.goto(f"{BASE}/?room={ROOM_ID}&scene=field", wait_until="domcontentloaded")
        settle(page)
        # Wait for the field scene to actually INSTALL before tapping — a tap
        # that outruns the URL's scene installation adopts the store's current
        # scene (the destination writer's stay-in-place semantics), which
        # would make this scenario test a click race instead of restoration.
        page.wait_for_selector("[data-workspace-scene='field']", timeout=10000)
        page.locator(".field-mark-row").first.click()
        settle(page)
        resumed_url = page.url
        check("a focus selection is installed before the kill",
              "object=" in resumed_url and "scene=field" in resumed_url, resumed_url)
        reopened = ctx.new_page()  # new tab: sessionStorage gone, localStorage lives
        reopened.goto(BASE, wait_until="domcontentloaded")
        settle(reopened, 1500)
        check("kill-and-reopen restores room, scene AND object",
              f"room={ROOM_ID}" in reopened.url and "scene=field" in reopened.url
              and "object=" in reopened.url, reopened.url)
        check("restored focus is actually open",
              reopened.locator("aside.focus-surface").count() == 1)
        reopened.screenshot(path=f"{SHOT}/gate-07-restored.png", full_page=True)

        # ---- 8. an explicit deep link outranks restoration -----------------
        override = ctx.new_page()
        override.goto(f"{BASE}/?room={ROOM_ID}&scene=ledger", wait_until="domcontentloaded")
        settle(override)
        check("explicit deep link overrides restoration",
              override.locator("[data-workspace-scene='ledger']").count() == 1
              and "object=" not in override.url)
        override.close()

        # ---- 9. a draft survives reload, unsent ----------------------------
        n_before = int(psql(
            "SELECT COUNT(*) FROM messages m JOIN threads t ON t.id = m.thread_id "
            f"WHERE t.room_id = '{ROOM_ID}'")[0])
        # The composer lives on the Record surface; restoration now correctly
        # reopens the Field scene, so move there explicitly for the draft test.
        reopened.goto(f"{BASE}/?room={ROOM_ID}", wait_until="domcontentloaded")
        settle(reopened)
        composer = reopened.locator(".message-input textarea, textarea").first
        composer.fill("gate draft: never sent, must survive")
        reopened.wait_for_timeout(800)  # let the axes sync effect persist it
        reopened.reload(wait_until="domcontentloaded")
        settle(reopened, 1200)
        restored_value = reopened.locator("textarea").first.input_value()
        check("draft text survives reload", restored_value == "gate draft: never sent, must survive",
              f"value={restored_value!r}")
        n_after = int(psql(
            "SELECT COUNT(*) FROM messages m JOIN threads t ON t.id = m.thread_id "
            f"WHERE t.room_id = '{ROOM_ID}'")[0])
        check("the draft was never sent", n_before == n_after, f"{n_before}->{n_after}")

        ctx.close()
        browser.close()

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
