# Dialectic World Lens — A Causal Observatory

*Recorded 2026-08-25 after inspecting Bilawal Sidhu's
[God's Eye View](https://github.com/bilawalsidhu/gods-eye-view), tracing the
current Dialectic architecture, and running the upstream test and build suites.*

*Status: product vision and technical judgment, not an approved implementation
specification or roadmap.*

## Immediate conclusion

Hard yes.

God's Eye View contains the beginnings of something that could become one of
Dialectic's defining capabilities. But the right move is to extract its nervous
system, not transplant the whole animal.

Dialectic should not become a surveillance globe, a cinematic dashboard, or a
fork of someone else's application. It should become capable of looking outward
at the world while preserving what makes it Dialectic: durable rooms, causal
theses, attributed evidence, a participant with memory, explicit source state,
human adjudication, and disciplined authority.

The product is a **causal observatory**:

> See a world signal. Connect it to a causal claim. Inspect the evidence.
> Discuss it. Confirm, contest, or correct its meaning. Change the thesis only
> through a deliberate human act.

Every globe can show where something is. Dialectic can show why it matters,
what it supports, what it contradicts, how fresh the observation is, and which
human accepted that interpretation. That combination is genuinely new.

## Why the idea fits Dialectic

Dialectic already has the conceptual organ this belongs inside: Atlas.

Atlas is currently a per-viewer semantic projection of rooms, branches,
theses, readings, briefs, commitments, and unresolved Field marks. Its backend
was deliberately written as nodes and edges without assuming a particular
renderer. Its frontend is deliberately list/tree first and explicitly reserves
a later spatial rendering of the same authority-fenced projection. The project
handoff already names Spatial Atlas as a high-value next move.

That is a remarkable fit, but it needs one important correction: the current
Atlas is semantically spatial, not geographically spatial. Its objects do not
carry verified coordinates, routes, regions, or geofences. We must not pretend
that titles and prose can simply be geocoded into truth.

The geographic view should therefore be a second Atlas mode:

- **House** — the complete, authoritative semantic list/tree that exists now.
- **World** — an optional rendering of only the objects and signals that carry
  explicit, provenance-backed geographic scope.

This avoids creating a third graph metaphor. It also means the globe never
becomes a second source of truth or a navigation system competing with the
rest of the PWA.

## The experience I can see

A user opens the Hormuz room and moves from Atlas / House to Atlas / World.
The camera frames a human-confirmed Strait of Hormuz region and shipping route.
The room's causal thesis appears as a compact argument, not as map decoration.
Live and recent signals appear only when they are relevant and source-backed.

A vessel movement, port disruption, military notice, headline cluster, or
other event is not merely a glowing dot. Selecting it opens the existing
Dialectic Reading or Focus object with its provider, observation time,
freshness state, evidence, and relationship to the thesis.

From there the humans can:

- connect the signal to a thesis node;
- mark it as supporting, contradicting, or context only;
- create a Field mark that asks whether the geometry or interpretation is
  correct;
- confirm, contest, correct, split, merge, or supersede that mark through the
  existing human adjudication vocabulary;
- accept a proposed thesis change deliberately, with provenance intact.

The participant might say:

> Tanker traffic through the western lane has fallen relative to the room's
> prior observation. This supports the disruption branch, but the AIS source is
> degraded and the port notice is fourteen hours newer. Want me to open the two
> pieces of evidence side by side?

That is not an assistant operating a map. That is the third participant using
the world as evidence inside an argument.

## The architecture that preserves the idea

The flow should remain subordinate to Dialectic's existing authority:

```text
authenticated source adapters
  -> typed GeoSignalProjection
    -> Atlas / World renderer
      -> Focus and Reading evidence
        -> Field human adjudication
          -> optional accepted thesis change
```

A geographic object needs at least:

- geometry: point, route, polygon, or bounded region;
- provenance: source provider, source identifier or URL, and acquisition path;
- authority: human-confirmed, source-reported, or machine-proposed;
- observation, retrieval, and expiration times;
- source state using Dialectic's evidence vocabulary: live, cached, stale,
  confirmed empty, partial, unavailable, rate-limited, or not configured;
- links to the relevant room, thesis, reading, or Field mark.

An LLM may propose that a reading concerns the Strait of Hormuz. It may not
silently convert prose into authoritative coordinates. Machine-proposed
geometry remains visibly provisional until a human or an authoritative source
confirms it.

All external feeds should terminate in authenticated, bounded FastAPI
adapters. They should inherit Dialectic's scheduler, caching, cooldown,
freshness, provenance, and spend-governance semantics. The upstream Vite proxy
must not become a production service inside Dialectic.

On the client, Cesium should be dynamically imported only when World opens.
The current Atlas list remains complete on low-power devices, reduced-motion
clients, failed WebGL initialization, and any scene where geography adds no
meaning. Camera and layer state must serialize through Dialectic's sole
navigation writer rather than creating an independent hash router.

## What God's Eye View proved

The upstream project is much more serious than its theatrical presentation
initially suggests. At public commit `880a672`, its test suite passed 2,587
tests locally and its production build completed. Its production dependency
audit was clean. It contains real work on lifecycle cancellation, source
status, bounded proxies, annotation round-tripping, request-render governance,
motion interpolation, attribution, ephemeral OpenAI Realtime credentials, and
fixed-tool voice authority.

The project also reports source freshness and degraded states instead of
pretending every absent marker means the same thing. That instinct is deeply
compatible with Dialectic.

But it is not directly integrable as an application:

- roughly 155,000 lines of JavaScript;
- a DOM-coupled UI module of roughly 10,000 lines;
- a Vite configuration of roughly 7,000 lines acting as development server,
  proxy, cache, key broker, voice endpoint, and provider adapter;
- a production bundle of roughly 31 MB, versus Dialectic's current PWA output
  of less than 1 MB;
- a Node engine declaration newer than the current Dialectic host;
- desktop Apple M5 performance evidence, but no equivalent iPhone or iPad
  guarantee;
- public history that currently exposes only a small number of large commits.

The upstream security document itself describes the application as a
local-first public-data explorer for demonstrations and learning, not a
hardened production service. That is honest and useful. It is also a decisive
reason not to embed the app, deploy its Vite key broker publicly, or iframe it
as though authentication and state ownership would somehow solve themselves.

## Selective acquisition

### Take and adapt

1. **Render governor.** Preserve Cesium's request-render mode and ref-counted
   activity holds so an idle scene stops consuming GPU. Recast it as an
   instance-scoped TypeScript service rather than a global singleton.
2. **Layer lifecycle.** Keep the disciplined init, enable, disable, update,
   destroy, and statistics contract. Map its states into Dialectic's stricter
   evidence vocabulary.
3. **GeoJSON annotations.** Acquire the routes, boundaries, points, hybrid
   screen/world rendering, cancellation, and round-trip invariants. Bind them
   to Field marks instead of creating a separate annotation authority.
4. **Camera and share-state invariants.** Preserve compact scene serialization,
   ownership, and supersession while routing it through `useRoomNavigation`.
5. **Motion and trail mathematics.** Reuse selectively when moving objects
   become evidence rather than ornamental animation.
6. **Attribution discipline.** Keep provider credits visible and attach them to
   the evidence objects as well as the visual layer.

### Evaluate later

1. Individual FIRMS, USGS, Launch Library, AIS, aircraft, satellite, weather,
   and traffic adapters after each source earns a Dialectic use case.
2. The voice system's ephemeral-token and fixed-tool patterns after World has a
   stable action contract. Dialectic must not acquire a second competing agent
   personality or authority model.
3. Cinematic scene direction only if it helps explain a causal sequence. A
   beautiful flyover that does not change understanding is wasted complexity.

### Reject

1. The monolithic DOM UI, giant stylesheet, and Vite backend.
2. A full fork, iframe, or microfrontend presented as integration.
3. Bundled models and local datasets without item-by-item licensing review.
4. Military installations or a "spy console" as the product center.
5. Google photorealistic tiles as a foundational dependency.
6. A globe on every room regardless of whether geography matters.

## The first wedge: Hormuz Situation Lens

The first vertical slice should prove causal value without adding another live
provider.

1. Lazy-load a Dark Roast Cesium scene from Atlas / World.
2. Use a keyless, attribution-correct basemap rather than Google
   photorealistic tiles.
3. Add a human-authored Hormuz polygon and shipping route with explicit
   provenance.
4. Project existing Dialectic/GDELT readings associated with that geographic
   scope.
5. Open the real Reading or Focus object when a signal is selected.
6. Show source state and observation time in the scene itself.
7. Allow the user to create an evidence-linked Field mark from a region,
   route, or signal.
8. Prove the unchanged list-first Atlas on iPhone, iPad, desktop, reduced
   motion, keyboard, and failed-WebGL paths.

Only after that loop is useful should we add AIS. AIS is the obvious live
layer for Hormuz, but obvious is not the same as ready: provider terms,
coverage, cache behavior, outage semantics, cost, and public-product use must
be resolved first.

## The long arc

If the first slice works, World can grow from a renderer into a reasoning
instrument:

- **Temporal replay:** show what changed geographically between thesis
  versions, not just what exists now.
- **Thesis-defined watches:** alert when a source-backed signal crosses a
  human-defined region or route and meets a causal relevance threshold.
- **Competing futures:** render the observable consequences expected under
  rival thesis branches.
- **Counterfactual inspection:** ask which real-world observations would
  falsify a branch and where those observations should appear.
- **Cross-room echoes:** reveal that a port closure supporting one room also
  contests an inflation assumption in another, without leaking inaccessible
  rooms.
- **Participant-directed inquiry:** "Show the world signals that most strongly
  contradict our base case, then open the freshest evidence."
- **Geographic memory:** let the pair return months later to a region and see
  what they believed, which evidence changed their minds, and what remained
  unresolved.

The radical endpoint is not omniscience. It is inspectable situated reasoning:
the system knows what it observed, where, when, through which provider, with
what confidence, and how that observation entered a human argument.

## Non-negotiable boundaries

- World is an evidence instrument, not the home screen.
- House remains the complete authority and accessibility fallback.
- Geographic absence means "not geographically modeled," never "irrelevant."
- No LLM-invented authoritative coordinates.
- No cached marker presented as a current observation.
- No direct thesis mutation from a map interaction.
- No competing navigation writer or source-state vocabulary.
- No public unauthenticated key broker.
- No named-person tracking.
- No provider or dataset without explicit terms, attribution, and operating
  limits.
- No default bundle-weight or GPU regression for users who never open World.

## Commercial and licensing reality

The upstream source code is MIT, but its third-party datasets, 3D models, and
runtime feeds are not. TeleGeography's bundled cable data is noncommercial and
share-alike. OpenSky carries noncommercial restrictions without separate
terms. Google News RSS is described as personal and noncommercial. AISStream
is beta and documents no formal terms. Google photorealistic tiles require a
billing-enabled key and can create direct usage cost.

Therefore we should port small, attributable code units and create a fresh
provider ledger. We should not copy the upstream data/model directories or
assume that MIT at the repository root blesses everything visible in the app.

Primary references:

- [God's Eye View repository](https://github.com/bilawalsidhu/gods-eye-view)
- [Security model](https://github.com/bilawalsidhu/gods-eye-view/blob/main/SECURITY.md)
- [Data sources and provider terms](https://github.com/bilawalsidhu/gods-eye-view/blob/main/DATA_SOURCES.md)
- [License and third-party carve-outs](https://github.com/bilawalsidhu/gods-eye-view/blob/main/LICENSE)
- [Published performance baseline](https://github.com/bilawalsidhu/gods-eye-view/blob/main/docs/PERFORMANCE.md)
- [Google Maps Platform pricing](https://developers.google.com/maps/billing-and-pricing/pricing)

## The judgment to preserve

This direction deserves real enthusiasm. It joins two systems whose missing
halves fit unusually well: God's Eye View has geographic embodiment without a
durable theory of meaning; Dialectic has durable collaborative reasoning
without geographic embodiment.

The synthesis is not "add a map." It is giving the third mind eyes on the
world while refusing to let those eyes become an unaccountable oracle.

Build the Hormuz slice. Make every point answer where it came from, how old it
is, what claim it bears on, and who accepted that interpretation. If that loop
feels electric in daily use, then expand aggressively into live maritime
signals, temporal replay, thesis watches, and counterfactual world scenes.

That is the vision worth protecting.

---

## Amendment 2026-08-25 — what shipped against this (amend-beside)

Phases 0–2 of the plan drawn from this document are live (commits 0be95ae,
58d702f, 011d666, eab5178). Three places the build read the vision more
narrowly than written, recorded rather than edited above:

- **Cesium loads on demand, but not "only when World opens" from a cold
  cache the first time** — the chunk is fetched the first time a person
  opens World and thereafter comes from the browser's HTTP cache, never the
  PWA precache. Same intent; the mechanism is the SW's `globIgnores`.
- **"A second Atlas mode" is a URL axis (`view`), not a scene** — so Back,
  share links and the sole navigation writer all keep working without a
  second router, and House stays under the globe rather than beside it.
- **The first wedge added no live provider, as asked; it did add a
  proposal tool.** `propose_geo_scope` resolves names to geometry that
  already exists and writes only `machine_proposed` rows the Field refuses
  until confirmed — the "no LLM-invented coordinates" boundary enforced in
  SQL, not in a prompt.

Provider terms now live in `WORLD_PROVIDERS.md`. Phase 3 waits on the gate
this document sets ("feels electric in daily use") and on an AIS terms
decision.
