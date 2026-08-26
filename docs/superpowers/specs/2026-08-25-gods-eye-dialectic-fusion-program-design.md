# God's Eye x Dialectic — One Living Causal World

**Date:** 2026-08-25

**Status:** Approved umbrella design; implementation decomposes into separately
qualified phases

**Branch context:** `codex/world-lens-truth-before-spectacle` after Tasks 1–5

**Product position:** God's Eye is Dialectic's sensory body. Dialectic is God's
Eye's reasoning mind.

## 1. The decision

Build deep projection fusion.

World is not a second application, a microfrontend, a data warehouse, a map
dashboard, or a cinematic skin around Dialectic. House and World are two
embodiments of the same room-fenced objects, history, participant, navigation,
and human authority. A person can move between them without changing the
meaning or identity of what is selected.

The alternative designs are rejected:

- **World-first shell:** visually dramatic, but forces geography onto rooms
  where it adds no meaning and weakens reading, accessibility, and mobile use.
- **Separate World workbench:** easier to expand independently, but creates a
  permanent seam in identity, navigation, annotations, and authority.
- **Provider-first globe:** produces interesting dots before proving that a
  signal changes an argument. Provider count is not product value.

World-first presentation remains available as a room posture when geography
earns it. It does not become the universal home screen.

## 2. The experience to create

The finished organism is a living causal model of the world that a person can
enter.

A person can select a claim in House, move to World, and see the same claim's
geographic evidence without losing Focus, history, or room context. Selecting
a world observation opens the exact source and the exact causal relation it
bears upon. Moving through time shows two histories together: what changed in
the world, and what the room believed at that moment.

The participant can answer:

- What changed?
- Where did it happen?
- Which source observed it, when, and with what coverage?
- Which claim does it support, challenge, or contextualize?
- Who accepted that interpretation?
- What evidence most strongly contradicts the current thesis?
- What future observation would falsify each competing branch?
- What did we know when we made the decision?

The participant may assemble a cited tour, propose a scope, propose a watch,
or bring a contradiction to the humans. It never silently turns an
observation into geographic authority, causal meaning, durable memory, or a
thesis edit.

## 3. Current substrate — preserve, do not rebuild

Tasks 1–5 already establish the organs this program extends:

- Atlas is the room-fenced projection owner.
- House is the complete list-first authority and accessibility fallback.
- World is the `view` axis of Atlas, not a competing scene or router.
- `useRoomNavigation` is the sole destination writer.
- `GeoScope` is durable, append-only geographic authority with lineage,
  review, source state, and provenance.
- `WorldSignal` is an ephemeral, bounded provider observation; it is not
  geographic memory.
- Explicit human placement copies current same-room signal bytes into a
  durable `GeoScope`.
- Causal meaning lives in Field through `supports`, `challenges`, or
  `context` relations to a current authenticated thesis node.
- Builder is the sole thesis writer.
- `world_query` gives the participant read-only, room-fenced sight with
  truthful totals, bounds, provenance, freshness, and failure states.
- Focus and `ScopeReview` own geographic lineage and human adjudication.

The fusion must extend those owners rather than create parallel substitutes.

## 4. The Siamese-twin contract

### 4.1 One identity

Every durable item shown in World is an existing Dialectic object or an
existing object with a `GeoScope`. An ephemeral observation retains its
provider identity until explicit placement creates a distinct durable object.

The same object identifier must drive:

- House selection;
- World selection and framing;
- Focus inspection;
- Field causal display;
- shareable URL state;
- notifications and deep links;
- participant tool results;
- history and review.

No renderer-owned shadow identifiers may escape the renderer.

### 4.2 One navigation transaction

House/World changes, object selection, room/branch changes, and participant
destinations all flow through `useRoomNavigation`. Camera state is a bounded
presentation axis, not object identity and not a second history stack.

Continuity requirements:

1. House -> World preserves the selected object and Focus state.
2. World -> House reveals the same object in the complete list.
3. Back/Forward restores room, branch, view, object, and bounded camera state.
4. Shared links degrade to the complete House/Focus path when WebGL fails.
5. A room switch cannot carry a selected object, camera target, signal, or
   provider state across the room fence.

### 4.3 One source vocabulary

Every external or derived layer uses the existing evidence vocabulary. At
minimum, the projection distinguishes:

- live;
- cached;
- stale;
- partial;
- confirmed empty;
- unavailable;
- rate-limited;
- not configured;
- expired.

Absence is never silently converted into zero. A provider envelope's expiry
overrides its child observations. Observation time, retrieval time, expiry,
coverage, provider, source identifier, URL, acquisition path, and credit
remain inspectable outside the globe.

### 4.4 One authority ladder

The authority sequence remains:

```text
provider observation or participant proposal
  -> explicit human placement or confirmation
    -> durable GeoScope lineage
      -> explicit causal Field binding
        -> human confirm / contest / correct
          -> optional explicit Builder edit
```

Rendering, animation, spatial proximity, clustering, model confidence, and
provider reputation never skip a rung.

### 4.5 One third mind

Dialectic has one participant. World does not acquire a second agent persona,
memory, tool registry, or action vocabulary. World-specific sight and proposed
destinations extend the existing participant through owner services.

## 5. Product capabilities

### 5.1 Absolute object continuity

House, World, Focus, and Field expose the same selection. A person can begin
with prose, move to geography, inspect provenance, adjudicate meaning, and
return to the argument without manually finding the object again.

World hover may highlight a House row or Field relation, but only selection
changes URL/Focus state. Hover remains ephemeral and never becomes authority.

### 5.2 Causal rays

World can render a bounded, read-only causal overlay from an accepted live
scope to its adjudicated Field binding and current thesis node. It may also
show the relation as `supports`, `challenges`, or `context`.

The overlay is a projection, not a new edge table. Selecting a ray opens the
existing Field mark and its review state. The renderer must not infer a ray
from spatial proximity, prose similarity, or an unreviewed proposal.

### 5.3 Belief weather

World can summarize where a room's claims are strengthening, weakening,
contested, stale, or unsupported. This is a visual aggregation of exact
underlying bindings and review states.

Every aggregate must disclose:

- included and omitted counts;
- the time window;
- the relevant thesis version;
- the rule that produced the state;
- a path to the constituent evidence.

No model-generated heatmap may masquerade as measured confidence.

### 5.4 Dual temporal replay

Replay has two synchronized clocks:

1. **World time:** when observations occurred and when providers retrieved
   them.
2. **Belief time:** when scopes, Field judgments, and thesis versions became
   authoritative in Dialectic.

The default view never rewrites present truth. Historical replay is visibly
historical, carries its exact as-of boundary, and does not expose present-only
actions as though they applied to the past.

Durable world replay is not enabled merely because the UI exists. It requires
the World Memory gate in section 8.

### 5.5 Competing futures

A thesis branch may define observable future signatures: expected events,
regions, routes, source types, windows, and absence conditions. World renders
those signatures as expectations, categorically distinct from observations.

When reality arrives, the system may calculate a deterministic comparison and
propose a Field judgment. A human adjudicates its causal meaning. The system
does not auto-select the winning thesis.

### 5.6 Falsification watches

A human can define what observation would materially challenge or falsify a
branch. A watch contains:

- the owning room and thesis version;
- one or more accepted scopes;
- explicit provider/source requirements;
- a deterministic condition and time window;
- required coverage for interpreting absence;
- notification severity and fatigue bounds;
- owner, creation time, and review history.

A watch never converts missing coverage into evidence. Its firing creates an
inspectable proposal/event; it does not mutate the thesis.

### 5.7 Participant-directed evidence tours

The participant can compose a bounded ordered tour of exact objects, scopes,
signals, and causal bindings. A tour step carries a destination, a concise
claim, source references, and the reason it follows the prior step.

Tours use ordinary navigation and Focus. They do not own a competing camera
router. A person can stop, inspect, branch, or share at every step. Cinematic
motion is optional and reduced-motion-safe.

### 5.8 Living World Brief

For a room with meaningful geographic evidence, the Home/room briefing may
report only world changes that altered causal state, triggered a watch, or
created a material contradiction. The brief states `none` when nothing earned
attention.

Provider heartbeat, marker motion, and novelty alone do not qualify.

### 5.9 Cross-room echoes

One observation may bear upon several rooms. The server computes echoes only
inside the viewer's accessible room set. Results disclose the count of hidden
or inaccessible rooms only if that count itself cannot leak sensitive room
existence; the safe default is no disclosure.

Every visible echo opens the exact room, object, and causal relation through
the normal destination writer. No cross-room inference creates a causal mark.

### 5.10 Evidence constellations

Related observations may be clustered for navigation and scale. Clustering is
presentation only. Each constituent keeps its provider, clocks, source state,
coverage, and causal relations. Expanding a cluster never fabricates a single
combined event or consensus.

### 5.11 Multimodal situated evidence

Existing readings and attachments can be associated with accepted geographic
scope. Images, charts, PDFs, and extracted video frames remain ordinary
protected artifacts with their own provenance. Georeferencing creates or
revises `GeoScope`; it does not modify the artifact itself.

Automated image-change detection is a source-reported or machine-proposed
observation until human adjudication. Original bytes remain inspectable.

### 5.12 Shared live command

People may share object selection, tour step, and optional camera following in
a room. Presence is ephemeral. Each person can detach their camera without
leaving the shared object or discussion.

Only ordinary authenticated human actions create durable scopes, reviews, or
Field marks. A leader/follower presentation role grants no additional
authority.

### 5.13 Voice and command-deck presentation

Voice commands resolve to the same typed destinations and proposed actions as
keyboard/pointer use. Ambiguous targets produce candidates; they never guess a
room, object, location, or destructive action.

A wall-scale command-deck layout may emphasize World, causal overlays, watches,
and current briefs. It remains a responsive presentation of the same PWA, not
a privileged operator product. Phone, tablet, keyboard, reduced-motion, and
failed-WebGL paths remain complete.

### 5.14 Spatial computing

Room-scale or headset presentation is a late renderer over the same projection
and navigation contract. It earns implementation only after desktop/tablet
World proves durable causal value. No authority rule is relaxed for immersion.

## 6. Provider and layer architecture

Each provider adapter terminates behind authenticated, bounded backend owner
services. A layer declares:

- provider and contractual status;
- observation schema and stable source identity;
- geographic geometry types;
- observation, retrieval, and expiry semantics;
- coverage and confirmed-empty semantics;
- pagination, rate, spend, and byte bounds;
- outage, partial, stale, reconnect, and replay behavior;
- attribution requirements;
- room/thesis selection rule;
- exact actions exposed to humans and the participant.

Adapters replace bounded immutable snapshots in `WorldSignalStore` or a future
owner with the same projection contract. They do not write `GeoScope`, Field,
messages, or theses. Provider polling never holds a database transaction over
the network boundary.

The target layer library may include maritime movement, aviation, weather,
fires, earthquakes, energy, ports, supply chains, infrastructure, economic
releases, markets, public reporting, and satellite change. This is a wish
list, not blanket activation. Each source passes the entry gate below.

### Layer entry gate

A layer does not enter an implementation phase until it has:

1. a named room/thesis question;
2. one causal decision it could change;
3. authoritative source and terms review;
4. exact freshness, coverage, and absence semantics;
5. bounded operating cost and failure behavior;
6. a list-first projection and failed-renderer path;
7. a one-week ordinary-use qualification protocol;
8. explicit owner approval.

“Interesting dots” is a failed gate.

## 7. Temporal and memory architecture

Current `WorldSignal` snapshots are intentionally ephemeral. World Memory is a
separate product and retention decision, not an incidental database table.

If approved after ordinary-use proof, memory records immutable observation
envelopes with:

- provider and source identity;
- original provider clocks and retrieval clock;
- exact payload hash and normalized projection version;
- coverage and source state;
- room selection rule at capture time;
- retention class and expiry/deletion policy;
- links to later human placements without conflating the two.

Replay reads immutable captured envelopes; it never reconstructs history from
the current provider response. Corrections append. Provider licenses and
privacy rules can prohibit or shorten retention per layer.

## 8. Program phases and hard gates

Phases are separate specifications and implementation plans. Completing one
does not silently authorize the next.

### Phase 3 — Synapse

Fuse the objects that already exist:

- absolute House/World/Focus/Field selection continuity;
- room-fenced causal overlay projection;
- accepted-scope-to-thesis rays;
- complete keyboard/list fallback;
- participant read-only explanation of the selected causal chain;
- exact browser acceptance across Back/Forward, share links, room switches,
  390 px, reduced motion, and failed WebGL.

This phase adds no provider, polling, world memory, or automatic action.

**Pass:** a person can move from claim -> evidence -> geography -> provenance
-> causal judgment -> claim without losing identity or crossing authority.

### Phase 4 — First Sense

Activate one provider that passes the layer entry gate:

- one bounded adapter;
- truthful current/empty/partial/stale/unavailable states;
- one selected room/thesis wedge;
- explicit placement into durable authority;
- a written daily value/error ledger.

**Pass:** the layer changes at least one documented causal decision during one
week of ordinary use without a source, fence, absence, or authority breach.

### Phase 5 — Causal Airspace

Add belief weather, evidence constellations, participant tours, and the Living
World Brief over exact current evidence.

**Pass:** aggregates are bounded, drillable, deterministic, and never hide a
contradictory constituent or unknown source state.

### Phase 6 — Time and World Memory

After separate retention approval, add immutable capture, dual temporal
replay, comparison, and decision retrospectives.

**Pass:** an as-of view reproduces exact retained source and belief state and
cannot expose present truth or actions as historical.

### Phase 7 — Competing Futures

Add observable signatures, falsification watches, deterministic comparisons,
and forecast scorecards.

**Pass:** a branch makes a pre-observation commitment, reality scores it, and a
human adjudicates the result with no automatic thesis mutation.

### Phase 8 — World Echoes

Add viewer-fenced cross-room implications, echo navigation, and bounded
multi-room briefs.

**Pass:** authorized rooms connect causally while inaccessible room existence,
content, counts, and timing remain unobservable.

### Phase 9 — Command and Embodiment

Add shared live command, voice navigation, wall-scale presentation, and only
then evaluate spatial computing.

**Pass:** collaboration adds no authority, privacy, navigation, accessibility,
or renderer-only dependency.

## 9. Failure, performance, and accessibility

### Failure is product state

Every layer and aggregate distinguishes:

- never configured;
- configured but unavailable;
- partial coverage;
- stale cached evidence;
- confirmed empty coverage;
- rate/spend limited;
- expired;
- malformed/rejected.

No generic empty map is accepted as a failure UI.

### Performance laws

- Cesium remains lazy and outside PWA precache.
- Idle World uses request-render behavior.
- Layer enable/disable/destroy lifecycles cancel work and release resources.
- Provider payloads and projected objects are bounded server-side.
- Clustering and level-of-detail never alter source truth.
- Users who never open World pay no default globe bundle or GPU cost.
- Camera motion and animation stop under reduced motion.

### Complete fallback

House and the text list expose every accessible object, signal, source state,
action, and destination needed to complete the workflow. Failed WebGL may
remove only spatial presentation. Keyboard order reaches the full list without
traversing a dead canvas.

## 10. Security and privacy

- Every projection is authenticated and room-fenced at its owner query.
- Client filtering never substitutes for the server fence.
- Provider credentials never enter browser bundles, URLs, screenshots, or
  participant context.
- External URLs are safe-link constrained; original source identity remains
  visible even when a URL cannot be linked.
- No named-person tracking or covert surveillance layer.
- Presence and camera following are opt-in and ephemeral.
- Cross-room echoes reveal only objects already authorized to the viewer.
- Attachment and private-layer bytes retain ordinary membership checks.
- A model never receives inaccessible geometry or provider payloads merely
  because the renderer could have displayed them for another viewer.

## 11. Acceptance and evidence ledger

Every phase reports these surfaces independently:

1. source checkout and exact commit;
2. tests and static checks actually run;
3. migration state;
4. backend runtime/PID and loaded checkout;
5. frontend build and selected served asset;
6. public-browser delivery;
7. provider configuration and real source condition;
8. activation flags;
9. physical-device proof;
10. ordinary-use and human qualification.

Core browser acceptance must use visible UI actions and retain URLs, source
payload summaries, screenshots, geometry, timing, network errors, page errors,
and backend exceptions. Droplet-local proof is not public delivery or physical
qualification.

## 12. Rejected shortcuts

- iframe or fork the upstream God's Eye application;
- copy its Vite key broker into production;
- create a second router, globe object store, annotations table, agent, or
  source-state vocabulary;
- infer authoritative coordinates from prose;
- infer causal meaning from proximity or model confidence;
- store every provider tick before a retention decision;
- treat cached, absent, or failed data as current zero;
- auto-edit a thesis from a signal, watch, or forecast score;
- enable a provider because it is inexpensive or visually impressive;
- hide incomplete coverage behind a clean visualization;
- call local tests deployment or ordinary-use value.

## 13. First implementation boundary

The next executable design is **Phase 3 — Synapse**, not the whole program.
It operates only on already-existing durable scopes, causal Field bindings,
thesis nodes, navigation, Focus, and participant sight. It requires no provider
choice, license decision, migration, background poller, retention policy, or
production activation.

Its implementation plan must trace the exact current consumers before naming
new types or endpoints. The preferred shape is one server-owned, room-fenced
causal projection consumed by House, World, Focus, Field, and `world_query`,
not five client-side joins.

## 14. Product test

The fusion succeeds when the globe is no longer the memorable part.

The memorable experience is selecting a real-world observation, understanding
exactly why it matters, seeing the argument it changes, inspecting every
source and human judgment, and moving through that chain without ever leaving
the same living room of thought.

That is God's Eye made native to Dialectic: not omniscience, but situated,
inspectable, collaborative causal reasoning with eyes open to the world.
