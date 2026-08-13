# Scene Kernel and Identity Shell Plan — Amendment 1

**Status:** Binding amendment  
**Date:** 2026-08-12 (America/Chicago)  
**Amends:** `docs/superpowers/plans/2026-08-12-dialectic-scene-kernel-and-identity-shell.md` at commit `65adf8b`

This amendment was produced by the required plan self-review. It replaces one execution instruction; every other task, interface, command, and constraint in the original plan remains unchanged.

## Replacement for Task 7, Step 1

Run the backend suite through `tee` so the journal count is derived from fresh evidence rather than copied from a historical report:

```bash
cd dialectic
python3 -m pytest tests/ -q | tee /tmp/dialectic-scene-kernel-pytest.txt
cd frontend/app
npm test
npm run lint
npm run build
```

Expected: all commands exit 0. The backend output file must contain exactly one final summary matching `[0-9]+ passed` and no `failed`, `error`, or interrupted summary.

## Replacement for Task 7, Step 3

Do not copy the pass-count template from the original plan. Append the journal entry with the integer extracted from the fresh Task 7 run:

```bash
BACKEND_PASSED="$({ grep -Eo '[0-9]+ passed' /tmp/dialectic-scene-kernel-pytest.txt || true; } | tail -1 | cut -d' ' -f1)"
test -n "$BACKEND_PASSED"
! grep -Eq '[1-9][0-9]* failed|[1-9][0-9]* error' /tmp/dialectic-scene-kernel-pytest.txt
printf '%s\n' \
  "[2026-08-12] Landed the living-workroom scene kernel — Home root is explicit House, conversation is explicit Record, current room/branch URLs remain canonical, and @Dialectic is primary while @Claude/@llm remain compatibility aliases; verified ${BACKEND_PASSED} backend tests, frontend tests, lint, build, and isolated browser acceptance across desktop/tablet/phone widths." \
  >> ../JOURNAL.md
```

Then inspect the appended line:

```bash
tail -1 ../JOURNAL.md
```

Expected: the line contains the observed integer and no angle-bracket token.

## Self-review correction

The original plan's self-review described `<actual backend count>` as an operational substitution. This amendment removes that ambiguity. The executable instruction now derives the value from fresh pytest output and refuses an empty or failing summary before writing the journal.
