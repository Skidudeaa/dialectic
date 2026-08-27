# Handoff — the four thinking-protocol fractures are closed

**Date:** 2026-08-26 (America/Chicago)
**Commits:** `3b1b4b1` (the fix) and `1211b7c` (backfill script hardening), on
`master`, pushed to `origin/master`.
**Live from:** backend PID `3027133` (started 23:14:44 CDT); PWA release
`20260827T041529Z-protocol-fractures-3b1b4b1` (bundle `index-DUwqbvj-.js`);
superseded by `20260827T045615Z-protocol-docs-59ddae1` (`index-C09f12Hp.js`),
which adds only the What Changed entry.
**Origin:** fracture review `4bc57d094a71f126` against HEAD `c9f18a5`,
scope repository, verdict FIX. All four findings were PREEXISTING — none was
introduced by the World cockpit work the review was nominally aimed at.

## What was broken, in one line each

| | Symptom | Root cause |
|---|---|---|
| F-001 | Steelman / Devil's Advocate ignored the claim typed into the picker | `config.target_claim` was persisted (`thread_protocols.config`) and never read; `get_protocol_instructions` rendered header + phase text only |
| F-002 | Reload, second device, or thread switch lost the protocol banner and its Advance/Abort | the client learned of protocols only from transient `protocol_started/…` broadcasts; nothing re-sent state on connect |
| F-003 | Every concluded protocol's "synthesis memory" was the literal text `[Protocol … — synthesis pending]`, forever | `_conclude_protocol` wrote a placeholder and no code path ever replaced it; `synthesis_prompt` had zero consumers |
| F-004 | Tapping Invoke with a dead socket closed the modal and destroyed the pasted claim | `send()` returned `false`, `invokeProtocol` dropped it, `ProtocolPicker` closed unconditionally |

## What changed

### F-001 — `dialectic/llm/protocol_library.py`
`get_protocol_instructions` now inserts, between the phase header and the
phase instruction:

```
**Claim under examination (supplied by the invoking participant):**
> {claim}
```

The claim is `strip()`ped, capped at 2000 chars, and every line is
blockquoted — it is rendered as **participant data**, not as instruction.
No per-protocol branching: any protocol whose config carries `target_claim`
gets it; Socratic and Synthesis (no claim) are byte-for-byte unchanged.

Live proof: the facilitator's framing reply quoted the sentinel verbatim
and — usefully — recognised it as a placeholder rather than a real position,
which is exactly the behaviour of a model that has *read* the claim.

### F-002 — a new WebSocket message: `protocol_state`

```json
{"type": "protocol_state",
 "payload": {"thread_id": "<uuid>|null",
             "protocol": null | {"id","thread_id","protocol_type","status",
                                 "current_phase","total_phases",
                                 "display_name","current_phase_name"}}}
```

- Built by `transport/handlers.py::protocol_state_payload(protocols, thread_id)`
  — a module-level function so the endpoint can call it without a
  `MessageHandler` (the handler is constructed per inbound frame).
- Sent **directed** (`send_to_user`, all of that user's tabs), never broadcast,
  at two moments: `api/main.py` right after `connection_manager.connect()` for
  the handshake's `thread_id`, and at the end of `_handle_switch_thread`.
- Client (`useDialecticSocket.ts`): `case 'protocol_state'` **replaces**
  `activeProtocol` with `payload.protocol ?? null`. Never merges. The existing
  `payloadMatchesActiveThread` fence applies, so a snapshot for a thread the
  client has since left is ignored.
- Why the handshake path is enough for a cold reload: the client sends
  `thread_id` in the auth frame when the store already holds a thread; when it
  does not, selecting one fires the existing `switch_thread` effect, which
  now returns a snapshot. Either way the first paint has the truth.

Law: **the lifecycle broadcasts are events; `protocol_state` is state.** If a
future change adds a third lifecycle transition, it must still be visible
through `get_active` — the snapshot is derived from the row, not from a
client-side reduction of events.

### F-003 — the synthesis is the final facilitator message

`_conclude_protocol` now fetches

```sql
SELECT id, content FROM messages WHERE protocol_id = $1
ORDER BY protocol_phase DESC NULLS LAST, sequence DESC LIMIT 1
```

and writes **that content** as the synthesis memory, with
`source_message_id` set, `dedup=False` (unchanged — distinct runs must not
collapse onto one slot). The placeholder text survives only when a protocol
concludes with no messages at all, and that case logs a warning.

`ProtocolDefinition.synthesis_prompt` is still defined and still
**unconsumed**. Left in place per amend-beside; the final phase instruction
already asks for the structured document, so a second LLM call would be a
cost with no new information. Delete it or wire it — do not assume it runs.

**Backfill executed once on production:** `deploy/backfill_protocol_synthesis.py`
found the 2 existing placeholders (`b1dfeb5a…`, `e0bc2169…`), appended
version 2 through `MemoryManager.edit_memory` (so `memory_versions` keeps v1
as history), linked `source_message_id`, and re-embedded at 1024 dims. A
`--dry-run` afterwards reports 0. The first pass embedded at 1536 and failed
— see "Lessons".

### F-004 — `ProtocolPicker` keeps the claim on a failed send
`invokeProtocol` returns the `send()` boolean; `onInvoke` is typed
`=> boolean`; the picker closes only on `true` and otherwise renders
`<p role="alert" class="protocol-send-error">` ("Not connected — your claim
is kept…") with the textarea still mounted. No queue, no retry — the
connection hook already reconnects on `online`/`focus`, so the honest thing
is to keep the words on screen and let the person tap again.

## Tests

- `tests/test_protocol_library_claim.py` — sentinel rendered as blockquote
  and placed before `Your task:`; no-claim output identical to before.
- `tests/test_protocol_handlers_fracture.py` — `_handle_switch_thread` emits
  exactly one `protocol_state` (parametrised with/without an active row, and
  asserts `get_active` was awaited with the validated thread id);
  `_conclude_protocol` passes the final message content + `source_message_id`
  to `add_memory`, or the placeholder + `None` when no message exists.
- `ProtocolPicker.test.tsx` — `onInvoke → false` keeps the modal, the alert,
  and the typed claim; `onInvoke → true` calls `onClose` once and passes
  `{target_claim}`.
- Mutation check: all five guard tests fail on the pre-fix tree (`git stash`
  run). Suites at this gate: backend **2156**, frontend **604**.

## Live proof (production, headless)

The Chrome extension was not connected this session, so the proof is a
WebSocket probe as Test User (`83550fe3`, has credentials) in the E2E Test
Room (`e78ebe5c`, root thread `a53cd484`), JWT minted with
`api.auth.utils.create_access_token`:

1. handshake → `protocol_state {protocol: null}`
2. `invoke_protocol steelman {target_claim: SENTINEL}` → `protocol_started`
3. `message_created` from the facilitator contains the sentinel
4. close socket, reconnect → `protocol_state.protocol.id` == the started id,
   phase 0/4 "Framing"
5. `switch_thread` on the same thread → snapshot again, same id
6. `abort_protocol` → `protocol_aborted`

Step 4 is the F-002 proof; step 3 is F-001. **Not visually proven:** the
F-004 alert line (unit test only). First owner with a browser should open the
picker, go offline, tap Invoke, and see the claim stay.

## Lessons (also in the memory index)

- **Deploy scripts that open their own `asyncpg.connect` must do two things
  the app pool does for free:** `load_dotenv('.env')` *before* importing
  anything that reads provider config, and `set_type_codec('jsonb', …)`.
  Missing the first made the embedding provider default to 1536 dims against a
  1024-wide column; missing the second made `edit_memory`'s dict payload fail
  to encode. `deploy/seed_hormuz_geo.py` had the codec; the pattern is now in
  `backfill_protocol_synthesis.py` too.
- A "placeholder now, fill later" write with no consumer for "later" is a
  permanent placeholder. When adding one, name the code path that replaces it
  in the same commit or write the real thing.

## Rollback

Backend: `git checkout c9f18a5 -- dialectic && systemctl restart dialectic`
(no migration to reverse). Frontend: point `/var/www/dialectic-current` back
at `20260827T003007Z-world-cockpit-0ebd535` and `systemctl reload nginx`. The
two backfilled memories keep their v1 in `memory_versions`; reverting them is
`edit_memory` back to the v1 content, but there is no reason to — the v2
content is the message that was always on screen.
