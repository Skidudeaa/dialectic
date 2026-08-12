# Dialectic Home Base

**Date:** 2026-08-11
**Status:** Approved

## Goal

Give Dialectic a shared Home that is the normal place Amo, Dan, and Claude
meet, while keeping durable schemes in their own rooms and side discussions in
visible branches.

Home must do three things at once:

1. provide a real main conversation rather than a dashboard;
2. show what changed in the rooms and branches shared by everyone in Home;
3. preserve each source room's membership, memory, transcript, and LLM context
   boundaries.

The result should feel like one collaborative place with rooms, not a room
selector leading to disconnected chat silos.

## Current-state audit

The existing implementation explains the poor flow:

- Authenticated users restore directly into a persisted room. There is no
  shared landing surface.
- `RoomSelector` and the in-room `RoomList` duplicate room navigation and use
  different entry code.
- Branches appear in a header select and a right-panel tab, both as flat lists.
  The existing genealogy endpoint is unused.
- Below 1024px both navigation rails disappear, including every path to rooms,
  branches, memory, stakes, history, and sharing.
- A notification deep link can open a room, but normal navigation erases the
  room query parameter, so the URL does not preserve location on refresh.
- The room list already has reliable unread counts, previews, and read
  boundaries. The redesign should reuse that truth rather than create a
  notification center.

Production evidence captured during design on 2026-08-11:

- 22 rooms;
- 23 threads;
- one branch in the entire system;
- 194 messages during the preceding seven days.

The system is being used. Branch creation and navigation are not being
discovered.

## Product decisions

- Use a hybrid Home: a real room and main thread plus a compact derived
  cross-room activity pulse.
- Home is the destination for a bare application launch.
- Explicit room/thread links and notification links override Home.
- Home initially contains Amo and Dan only.
- Amo and Dan may add Home members. Added members cannot add anyone else.
- Claude is a complete participant in Home. Home does not disable or narrow
  the shipped participant architecture.
- The Home activity pulse and Claude use the same membership-fenced source.
- Only rooms accessible to every current Home member may appear in shared Home
  activity or Claude's Home context.
- Branch visibility ships in the MVP; it is not deferred.
- Mobile uses drawers rather than a persistent bottom bar that would reduce
  composer and keyboard space.

## Home is a real room

Home uses the existing room, thread, message, memory, event, receipt, presence,
push, protocol, commitment, replay, and LLM pipelines. It is not a synthetic
feed masquerading as a conversation.

Home has one root thread titled `Main`. It may be forked through the same
message-level branch action as any other room. Home messages and memories stay
in Home. Entering a scheme room resets and reloads the existing room-scoped
client state exactly as it does today.

The Home activity pulse is read-only navigation context above the Home
transcript. It never becomes a second message store and never writes into the
source rooms.

## Data model

Migration `013` is the next migration. `012_user_memory_promotions.sql` is
already deployed and must not be reused.

Add to `rooms`:

- `is_home BOOLEAN NOT NULL DEFAULT FALSE`
- a partial unique index permitting at most one row where `is_home`

A boolean is intentional. Dialectic has one special Home case; a speculative
room-kind framework would add indirection without another real behavior.

Add to `room_memberships`:

- `can_manage_home BOOLEAN NOT NULL DEFAULT FALSE`

This is a specific capability, not a generalized role system. It is meaningful
only for the Home membership checks.

Migration `013` creates, idempotently:

- one Home room with a new random room token;
- one root `Main` thread;
- the existing `room_created` and `thread_created` events.

The schema migration does not infer founders from names or from all accounts.
Production activation performs a separate, reviewed transaction that resolves
the exact existing credential identities for Amo and Dan, requires exactly one
match for each, inserts their Home memberships, and sets
`can_manage_home = TRUE`. It emits one existing `user_joined_room` event per
membership. The source tree and fresh-database baseline contain the schema, not
hard-coded production user IDs or emails.

## Home membership administration

Home administrators add an existing registered user by normalized email from a
Home settings surface.

The endpoint requires:

- a valid access JWT;
- the valid Home room token;
- current Home membership;
- `can_manage_home = TRUE` on the caller's Home membership.

The target must have exactly one `user_credentials` row. The write inserts the
membership with `can_manage_home = FALSE` and emits `user_joined_room` with the
new member as the event user and the administrator ID in the payload.
Repeated addition is idempotent.

The generic room-token join endpoint rejects Home. The Home Share panel is not
rendered, because its bearer invite code cannot represent nondelegable
authority. Existing room invite behavior remains unchanged for ordinary
rooms.

An unknown email returns a clear not-found result. Creating a new account is a
separate operation: signups are closed and the repository has no invitation
delivery system. This tranche does not disguise a placeholder email flow as a
working invitation system.

There is no member-removal UI and no generalized roles UI in this MVP.

## Shared-activity authorization

The eligible source set is the intersection of room memberships:

- exclude Home itself;
- consider a source room only when there is no current Home member missing
  from that source room.

This condition is enforced in the database query, not filtered after content
has been fetched. Adding a Home member therefore contracts the shared source
set immediately. A source room becomes visible again only after every Home
member has joined it.

Each viewer may have different unread counts and read boundaries inside the
same safe source set. That personalization is permitted because the source
content is already shared by all Home members. Private room names, IDs,
previews, counts, and tokens never enter the Home projection.

The activity response never carries room tokens. Navigation resolves the
target through the caller's existing token-bearing saved-room response.

## Activity projection

Do not add an activity table, dismissal state, or new activity event types.
The activity projection is derived from existing append-only truth and its
current projections:

- messages;
- threads and parentage;
- message receipts;
- room memberships;
- active commitments.

One focused projection service has two consumers:

1. `GET /users/me/home/activity`;
2. Home LLM context assembly.

For the HTTP response, the activity window begins at the requesting viewer's
existing source-room read boundary (`last_read_at`, falling back to
`joined_at`) and is capped to the 100 most recent messages per room. For a Home
LLM turn, the most recent human speaker is the requesting viewer, matching the
existing personal cross-room-memory path. Unresolved questions are calculated
inside that explicit window. Commitments due within 72 hours are included
regardless of unread state.

The projection returns a generated timestamp and room entries containing:

- room ID and name;
- last-message timestamp, speaker, and short preview;
- the requesting viewer's unread count using the existing receipt boundary;
- branch ID, parent ID, title, depth, message count, unread count, and latest
  activity;
- unresolved questions in the activity window;
- active commitments due within 72 hours.

The default ordering is:

1. rooms with unread activity, newest first;
2. remaining rooms, newest first;
3. branches within a room, newest activity first while preserving parent/depth
   metadata for tree rendering.

The endpoint is read-only. Viewing Home does not mark a source-room message as
read. A source unread badge clears only through the existing receipt written
when that source message is actually seen.

There are no Home actions for dismiss, archive, mute, or mark-all-read. An
activity row navigates; it does not create another workflow.

## Claude in Home

The current code defines Claude as an equal co-thinker, invokes the
participation machinery after every human message, defaults autonomous
interjection on, and maintains room-specific identity, user models, memory,
and participation state. Home inherits all of it:

- explicit summons and streaming;
- autonomous heuristic participation;
- provoker mode;
- protocols and facilitator mode;
- attributed room memory and personally promoted cross-room memory;
- room-specific evolved identity and user models;
- self-model and participation FSM;
- tools, attachments, and vision;
- offline annotations;
- capped silence follow-ups;
- local morning briefs;
- push notifications and effectiveness measurement.

No `is_home` condition disables Protocol, auto-interjection, the sweep, or the
normal prompt layers.

Home primary and forced-response turns receive a compact, capped rendering of
the shared-activity projection. This makes the third participant aware of the
same safe cross-room changes shown to the humans. Provoker turns remain short,
and protocol turns remain procedurally focused under their existing mode
rules.

Normal rooms do not receive the Home digest. Their prompt isolation is
unchanged. Existing transcript and memory tools remain bound to the current
room; this design does not turn them into unrestricted cross-room search.

If activity assembly fails, the prompt receives an explicit unavailable marker
and Claude must not claim the digest is current. The failure is logged with the
existing request context. The conversation turn still proceeds with Home's own
transcript and memory.

## Desktop information architecture

The existing three-column layout remains.

### Left rail

- Pin `Home` above the ordinary room list.
- Separate Home and Rooms with labels rather than another screen.
- Expand only the active room to show its branch genealogy.
- Show unread counts on rooms and branches.
- Keep inactive rooms compact so 20-plus rooms remain scannable.
- The `+` action opens Create/Join as an overlay; it does not call
  `leaveRoom()` or navigate to a duplicate selector.

### Header

- Replace the ambiguous branch control with a visible `Room / Branch`
  breadcrumb.
- Retain a compact select as a keyboard-friendly fallback.
- Keep Search, Help, Settings, Protocol, and connection state.

### Center column

Home displays:

1. header and participants;
2. a compact, collapsible activity pulse;
3. existing Home briefing/protocol/commitment surfaces;
4. the Home transcript;
5. typing/tool activity and composer.

The pulse has a capped height and cannot push the composer off a short
viewport. Each room card shows its unread count, latest speaker/preview, and
changed branches. Selecting an item opens the exact room and branch.

Ordinary rooms continue to show their transcript without the Home pulse.

### Right rail

Home retains Users, Memory, Branches, Insights, Stakes, History, AI, and its
Home settings. Trading remains conditional on the existing trading binding;
there is no additional Home-specific protocol or LLM gate.

The Branches panel renders the existing genealogy endpoint as an indented tree
with fork markers, activity, and counts. The active branch is also exposed in
the left rail so branches are discoverable before the user opens the panel.

## Mobile information architecture

Below 1024px, navigation must remain functional rather than disappear.

- A navigation button opens a slide-over containing Home, rooms, and the active
  room's branch tree. It reuses the desktop room/branch navigation component.
- A context button opens a second slide-over containing the right-rail tabs:
  Memory, Stakes, History, Users, Share or Home settings, and the other existing
  tools.
- The Home title acts as a direct Home action when the user is elsewhere.
- Header text actions collapse to labeled icons where space requires it.
- Neither drawer remains open after selecting a destination.
- The composer stays fixed and usable with the software keyboard open.
- No persistent bottom bar consumes vertical conversation space.

The mobile drawers are layout plumbing around existing functions, not parallel
mobile implementations.

## URL and navigation state

The URL is navigation authority; persisted Zustand state is a cache.

- `/` means Home.
- `/?room=<room-id>` means that room's oldest root thread.
- `/?room=<room-id>&thread=<thread-id>` means the exact branch.

An explicit room/thread URL wins over Home. Notification and service-worker
messages use the same navigation function and URL shape.

In-app room and branch selections call `history.pushState`. Initial resolution
and canonical corrections use `replaceState`. A `popstate` listener re-enters
the destination through the same function, so browser back/forward works.

The existing one-shot behavior that consumes and erases `?room=` is removed.
The ordering regression it previously fixed remains covered: navigation cannot
run against an old closure or an empty room list.

One navigation hook owns:

- resolving the caller's saved-room descriptor and token;
- validating an optional thread against its room;
- setting the API room token;
- fetching threads;
- setting the room and selected thread;
- updating URL history;
- closing mobile drawers;
- handling revoked access.

`RoomSelector`, the room rail, Home pulse, branch tree, notification handler,
and browser history all call this path. Create and Join use it after their
existing write succeeds.

For an authenticated Home member, a bare launch resolves Home even when a
different room remains in persisted state. Refreshing an explicit room URL
stays in that room. A denied or missing explicit destination clears the invalid
query, opens Home, and shows the access error. If Home itself is unavailable or
the caller is not a member, the existing selector is the terminal fallback;
there is no redirect loop.

## Create and Join

The existing create and invite-code join logic remains, but moves into a modal
or drawer reachable from the room rail. It no longer duplicates the saved room
list.

The full-screen selector remains only for:

- authenticated users with no Home membership and no active room;
- guest/invite entry;
- terminal recovery when Home cannot be resolved.

Home membership is never granted by the ordinary invite-code form.

## Refresh and staleness

While Home is visible, activity refreshes:

- on Home entry;
- when the document returns to the foreground;
- on manual retry;
- every 60 seconds while visible.

Only one refresh may be in flight. Successful data carries `generated_at`.
When a later refresh fails, the last successful snapshot remains visible with a
stale label and retry action. If no snapshot exists, the pulse shows the error
without blocking the Home transcript, WebSocket, or composer.

Claude's digest is assembled server-side for the turn and does not trust the
client snapshot.

## Failure behavior

- Unknown member email: explicit not-found; no partial membership write.
- Nonadministrator member add: 403; do not reveal whether the target exists.
- Ordinary invite against Home: 403.
- Activity query failure: visible stale/error state; Home conversation remains
  usable.
- Claude activity failure: explicit unavailable marker; no fabricated catch-up.
- Invalid room/thread URL: visible error then Home fallback.
- Revoked room token or membership: clear that room state and fall back to
  Home; if Home is also denied, show the selector.
- Genealogy failure: keep the active transcript and show retry in the branch
  surface; do not eject the room.
- Offline launch: render the cached PWA shell and explicit disconnected state;
  do not claim activity is current.

Required authentication, membership, migration, and projection invariants fail
hard. Optional context failures degrade visibly rather than being swallowed.

## Performance

Before UI work depends on the projection, benchmark its SQL on seeded data at
or above production scale. Target p95 is 150 ms for a Home with 25 source rooms
and 100 branches.

Use the existing receipt boundary and add covering indexes only when
`EXPLAIN ANALYZE` demonstrates the need. Do not add a cache table before the
derived query is measured. The endpoint caps previews and activity-window
items; the Claude formatter applies a separate prompt-size cap.

## Verification

### Backend contracts

Tests must prove:

- at most one Home can exist;
- migration `013` is idempotent;
- the activation transaction adds exactly Amo and Dan, not all credentialed
  users;
- both founders can add an existing account;
- an added member cannot add another member;
- generic room join cannot grant Home membership;
- repeated Home addition is idempotent and event-correct;
- adding a Home member immediately removes source rooms they cannot access;
- a source room returns only after every Home member belongs to it;
- no activity response contains a room token;
- room and branch unread counts use the existing receipt boundary;
- viewing Home does not write source receipts;
- Home prompt context contains shared activity and excludes every unshared
  source room;
- normal-room prompts contain no Home digest;
- activity failure produces the explicit prompt marker;
- Home retains normal interjection, protocol, FSM, and silence-sweep behavior.

Shared-activity and migration tests use real Postgres where query semantics or
concurrency matter.

### Frontend and navigation

The repository has no frontend unit-test framework. Do not introduce one only
for this tranche. Run lint and production build, then use repeatable headless
browser checks for:

- bare launch to Home;
- explicit room and thread launch;
- refresh preserving an explicit destination;
- browser back/forward;
- open- and closed-app notification navigation;
- room and branch selection from Home;
- Create/Join overlay success and cancellation;
- revoked-room fallback;
- Home activity stale/error rendering;
- desktop navigation at 1440, 1200, and 1024 pixels;
- mobile drawers at 768 and 390 pixels.

### Device acceptance

Release requires the installed PWA on the actual iPhone and Android devices:

- bare icon launch opens Home;
- navigation drawer reaches every room and active branch;
- context drawer reaches Memory and Stakes;
- activity tap opens the expected unread boundary;
- notification tap with the app closed opens its source room;
- notification tap with the app open switches correctly;
- background eviction and relaunch return to Home unless an explicit deep link
  launched the app;
- the composer remains visible and usable with the keyboard open;
- offline opening is visibly stale/disconnected rather than blank.

## Rollout and rollback

Implementation should be delivered in independently reviewable stages:

1. migration, Home membership administration, and shared-activity projection;
2. URL-authoritative navigation and Home room bootstrap;
3. Home pulse, Claude digest, and genealogy rendering;
4. mobile navigation/context drawers and final responsive work.

Production activation preserves the documented order:

1. apply migration `013`;
2. run and verify the exact Amo/Dan activation transaction;
3. restart the backend and verify Home/member/activity contracts;
4. build an immutable frontend release;
5. flip the frontend symlink;
6. complete browser and device acceptance.

The schema migration is additive. A frontend rollback flips the symlink back;
the old backend ignores the new columns. A backend rollback can run against the
additive schema. Do not remove the Home data during rollback.

## Non-goals

- No enterprise inbox or notification center.
- No activity dismissal, archive, mute, or mark-all-read.
- No unrestricted cross-room transcript or memory search.
- No exposure of private-room activity to Home.
- No new-account invitation or email-delivery system.
- No delegated Home administration beyond Amo and Dan.
- No member-removal or generalized roles UI.
- No replacement of event truth with an activity cache table.
- No native mobile application work.
- No tradingDesk changes.

## Success condition

On a normal launch, Amo or Dan lands in a living shared conversation with
Claude. They can see which shared scheme and branch changed, understand enough
to choose where to go, and arrive at the exact unread boundary in one action.
They can return Home just as directly. The same safe activity context lets
Claude connect the work without weakening any room's membership boundary.
