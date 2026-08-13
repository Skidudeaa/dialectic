# Scene Kernel and Identity Shell Plan — Amendment 2

**Status:** Binding amendment  
**Date:** 2026-08-12 (America/Chicago)  
**Amends:** `docs/superpowers/plans/2026-08-12-dialectic-scene-kernel-and-identity-shell.md` at commit `65adf8b`  
**Preserves:** Amendment 1 at commit `0d549f5`

This amendment records the second self-review. It replaces the specific instructions below; every other task, interface, command, and constraint remains unchanged.

## 1. Task 1, Step 2 — test setup replacement

Create `src/test/setup.ts` with the jsdom behavior used by MessageList tests:

```ts
import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

Object.defineProperty(Element.prototype, 'scrollIntoView', {
  configurable: true,
  value: vi.fn(),
  writable: true,
})
```

Reason: `MessageList` scrolls its bottom sentinel in a layout effect. jsdom does not implement `Element.scrollIntoView`; without the shim the identity component test fails for an environment limitation rather than product behavior.

## 2. Task 4, Step 3 — active scene must not push duplicate history

Replace the `SceneSwitcher` click handler with:

```tsx
onClick={() => {
  if (candidate !== scene) onSelect(candidate)
}}
```

Extend the first `WorkspaceSceneFrame` test:

```tsx
const onSelect = vi.fn()
render(
  <WorkspaceSceneFrame
    scene="house"
    isHomeRoot
    onSelect={onSelect}
    house={<div>House content</div>}
    record={<div>Record content</div>}
  />,
)
fireEvent.click(screen.getByRole('button', { name: 'House' }))
expect(onSelect).not.toHaveBeenCalled()
```

Reason: clicking the already active scene must not create duplicate browser-history entries.

## 3. Task 4, Step 6 — render-node placement

Construct `recordSurface` and `houseSurface` only after this existing guard:

```tsx
if (!user || !currentRoom || !roomToken) return null
```

The scene nodes read `user.id`, `currentRoom.id`, and `roomToken`; defining them before the guard would either require unsafe assertions or dereference nullable state.

## 4. Task 5, Step 3 — mention regex replacement

Use this implementation in `dialectic/llm/mentions.py`:

```python
import re


# Product identity first; provider-era aliases remain accepted compatibility.
# The left boundary prevents an email/domain fragment such as
# `email@dialectic.example` from summoning the participant.
LLM_MENTION_RE = re.compile(
    r"(?<![\w.+-])@(dialectic|claude|llm)\b",
    re.IGNORECASE,
)


def contains_explicit_llm_mention(text: str) -> bool:
    """Return whether text explicitly summons the Dialectic participant."""
    return bool(LLM_MENTION_RE.search(text))
```

The original test case `email@dialectic.example` remains required and must pass. Do not weaken or remove it.

## 5. Task 6, Step 2 — isolated-worktree commands

Do not run the browser fixture from `/root/DwoodAmo`, because that checkout is production-coupled.

At the root of the isolated implementation worktree, set:

```bash
WORKTREE_ROOT="$(git rev-parse --show-toplevel)"
test -f "$WORKTREE_ROOT/dialectic/run.py"
```

Backend terminal:

```bash
cd "$WORKTREE_ROOT/dialectic"
export DATABASE_URL='postgresql://localhost/dialectic_browser'
export JWT_SECRET_KEY='browser-scene-kernel-secret-32-bytes-minimum'
export ANTHROPIC_API_KEY='browser-fixture-dummy-key'
export SIGNUPS_ENABLED=1
export SCHEDULER_ENABLED=0
export PORT=8013
python3 run.py
```

Frontend terminal:

```bash
cd "$WORKTREE_ROOT/dialectic/frontend/app"
DIALECTIC_BACKEND_URL=http://localhost:8013 npm run build
DIALECTIC_BACKEND_URL=http://localhost:8013 npm run preview -- --port 4173
```

The isolated database and spare ports remain mandatory. No production service is restarted.

## 6. Task 6, Step 8 — external-model boundary

Replace the instructions to start a real LLM stream and real Research run with deterministic UI and protocol checks:

- Verify the explicit summon copy presents `@Dialectic` and identifies `@Claude`/`@llm` as compatibility aliases.
- Verify the cancel control renders when the store/socket fixture receives the existing `llm_thinking` and `llm_streaming` events, then clears on `llm_cancelled` or `llm_done`.
- Verify the Research button sends the existing `deep_dive` vocabulary and disarms while the fixture emits `deep_dive_started`; verify it rearms on `deep_dive_done` and `deep_dive_error`.
- Verify proposal, Memory, Trading, Protocol, Stakes, Search, and genealogy surfaces remain reachable.

Do not spend external-model calls merely to prove the scene wrapper. A live provider smoke is a separate, explicit acceptance action when valid credentials and spend authorization are available.

## 7. Amendment 1, Task 7 pipeline — failure propagation replacement

Prefix the backend pipeline with `set -o pipefail`:

```bash
cd dialectic
set -o pipefail
python3 -m pytest tests/ -q | tee /tmp/dialectic-scene-kernel-pytest.txt
cd frontend/app
npm test
npm run lint
npm run build
```

Reason: without `pipefail`, `tee` can return success after pytest failed.

## 8. Task 7 journal date

When Amendment 1 appends the verified journal line, derive the date in the user's product timezone rather than hard-coding the planning date:

```bash
JOURNAL_DATE="$(TZ=America/Chicago date +%F)"
BACKEND_PASSED="$({ grep -Eo '[0-9]+ passed' /tmp/dialectic-scene-kernel-pytest.txt || true; } | tail -1 | cut -d' ' -f1)"
test -n "$BACKEND_PASSED"
! grep -Eq '[1-9][0-9]* failed|[1-9][0-9]* error' /tmp/dialectic-scene-kernel-pytest.txt
printf '%s\n' \
  "[${JOURNAL_DATE}] Landed the living-workroom scene kernel — Home root is explicit House, conversation is explicit Record, current room/branch URLs remain canonical, and @Dialectic is primary while @Claude/@llm remain compatibility aliases; verified ${BACKEND_PASSED} backend tests, frontend tests, lint, build, and isolated browser acceptance across desktop/tablet/phone widths." \
  >> ../JOURNAL.md
```

This supersedes only the journal-writing command in Amendment 1; its observed-count and failure checks remain binding.
