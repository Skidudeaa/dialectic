# Phase 3 World Synapse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make God's Eye and Dialectic one navigable causal organism: House, World, Focus, Field, and `world_query` preserve one room-fenced object identity and consume one server-owned causal binding projection.

**Architecture:** Extend the existing Atlas read model; do not add an app, router, database table, migration, provider, poller, or writer. `FieldMarkService` owns one bounded set-wise causal projection. Atlas adds current-to-root scope identity and ships those bindings only in its already opt-in enhanced response. The frontend carries the same object through the sole navigation writer, statically highlights real geometry, and renders semantic causality in DOM rather than inventing a geographic line to a non-geographic thesis node.

**Tech Stack:** Python 3.12, FastAPI, Pydantic, asyncpg/PostgreSQL recursive CTEs, React 19, TypeScript 5.9, CesiumJS 1.144, Vitest/Testing Library, pytest/pytest-asyncio, Playwright.

---

## Scope and invariants

This plan executes only Phase 3 — Synapse from the approved umbrella design.

- No provider activation, external feed, API key, background job, or World Memory.
- No migration and no new durable state.
- No second route, app shell, participant, annotation store, source vocabulary, or thesis writer.
- Default `GET /users/me/atlas` remains the exact four-key source-compatible response.
- `GET /users/me/atlas?signals=1`, already used by the frontend, becomes the enhanced World/causal projection.
- Every binding is an existing append-only Field mark. Every scope is an existing append-only GeoScope revision.
- `useRoomNavigation.navigate` remains the only destination writer.
- Builder remains the only thesis writer.
- A scope revision and its lineage root are coordinates of one durable object, not two objects.
- A thesis node has no geometry. Phase 3 must not draw a globe arc to it. The selected scope receives a static globe highlight; the semantic edge renders as accessible text: `scope -> supports|challenges|context -> thesis node`.
- Bounds and omission are explicit. Cross-room privacy is enforced in SQL on candidates, successor hydration, and review hydration.
- Production checkout, runtime, providers, migrations, public deployment, and feature activation remain untouched by this implementation branch.

## Contract to deliver

The enhanced Atlas response gains:

```json
{
  "causal_bindings": [
    {
      "id": "field_mark:<uuid>",
      "current_scope_id": "geo_scope:<uuid>",
      "evidence_scope_id": "geo_scope:<uuid>",
      "relation": "supports",
      "review_state": "confirmed",
      "provisional": false,
      "target": {
        "room_id": "<uuid>",
        "book_id": "book-id",
        "node_id": "node-id",
        "node_label": "Shipping chokepoint"
      }
    }
  ],
  "causal_bindings_total": 1,
  "causal_bindings_omitted": 0,
  "causal_bindings_complete": true
}
```

Each enhanced Atlas scope also gains a projection-only `lineage_root_id`:

```json
{
  "id": "geo_scope:<current-uuid>",
  "lineage_root_id": "geo_scope:<root-uuid>"
}
```

The existing `world_query` selected-scope result returns the identical causal binding shape and adds the exact selected root object to `show_on_world`:

```json
{
  "show_on_world": {
    "room_id": "<uuid>",
    "scene": "atlas",
    "view": "world;room=<uuid>",
    "object": "geo_scope:<root-uuid>"
  }
}
```

The deliberate wire change is that `evidence_scope_id`, previously a bare UUID in `world_query`, becomes the canonical `geo_scope:<uuid>` object ID. This is an internal participant-tool result, and the change is required to make tool destinations, Atlas, Focus, and Field use the same identity.

## Task 1: Own one causal binding DTO and one cross-room read

**Files:**

- Modify: `dialectic/field_marks.py`
- Modify: `dialectic/tests/test_field_marks_pg.py`

- [ ] **Step 1: Write the pure-adapter tests first**

Add imports and a unit-sized assertion in `dialectic/tests/test_field_marks_pg.py` proving semantic subject order does not matter and every identifier is canonical:

```python
from field_marks import (
    CausalGeoBinding,
    FieldMark,
    FieldMarkService,
    FieldSubjectRef,
    causal_geo_binding_from_mark,
)


def test_causal_binding_adapter_emits_canonical_object_ids() -> None:
    mark = FieldMark(
        id=f"field_mark:{MARK_CONFIRM}", room_id=ROOM, thread_id=TH,
        relation="supports", origin="explicit", review="confirmed",
        deliberative_status="active",
        subjects=[
            FieldSubjectRef(
                entity="rooms", id=str(ROOM),
                field="thesis_node:hormuz-book:shipping",
            ),
            FieldSubjectRef(entity="geo_scopes", id=str(_uid(0xFA1))),
        ],
        title="Hormuz supports shipping", payload={"node_label": "Shipping"},
        provenance="human", created_at=BASE,
    )

    binding = causal_geo_binding_from_mark(
        mark, current_scope_id=f"geo_scope:{_uid(0xFA2)}",
    )

    assert binding == CausalGeoBinding(
        id=f"field_mark:{MARK_CONFIRM}",
        current_scope_id=f"geo_scope:{_uid(0xFA2)}",
        evidence_scope_id=f"geo_scope:{_uid(0xFA1)}",
        relation="supports", review_state="confirmed", provisional=False,
        target={
            "room_id": ROOM, "book_id": "hormuz-book",
            "node_id": "shipping", "node_label": "Shipping",
        },
    )
```

- [ ] **Step 2: Run the focused red test**

Run:

```bash
cd dialectic
python3 -m pytest tests/test_field_marks_pg.py -q -k causal_binding_adapter
```

Expected: collection fails because `CausalGeoBinding` and `causal_geo_binding_from_mark` do not exist.

- [ ] **Step 3: Add the canonical models and adapter**

Add the three models immediately after `CausalFieldRoles` in
`dialectic/field_marks.py`:

```python
class CausalGeoTarget(BaseModel):
    room_id: UUID
    book_id: str
    node_id: str
    node_label: str


class CausalGeoBinding(BaseModel):
    """One existing Field interpretation joined to its current scope lineage."""

    id: str
    current_scope_id: str
    evidence_scope_id: str
    relation: str
    review_state: str
    provisional: bool
    target: CausalGeoTarget


class CausalGeoBindingsProjection(BaseModel):
    generated_at: datetime
    bindings: list[CausalGeoBinding]
    total: int
    omitted: int
    complete: bool
```

Add the adapter immediately after the existing `FieldMark` model:

```python
def causal_geo_binding_from_mark(
    mark: FieldMark, *, current_scope_id: str,
) -> Optional[CausalGeoBinding]:
    """Project one causal Field mark without deriving a second semantics."""

    roles = causal_subject_roles(
        mark.relation, [subject.model_dump() for subject in mark.subjects],
    )
    if roles is None:
        return None
    return CausalGeoBinding(
        id=mark.id,
        current_scope_id=current_scope_id,
        evidence_scope_id=f"geo_scope:{roles.evidence['id']}",
        relation=mark.relation,
        review_state=mark.review,
        provisional=mark.review == "provisional",
        target=CausalGeoTarget(
            room_id=mark.room_id,
            book_id=roles.book_id,
            node_id=roles.node_id,
            node_label=str(mark.payload.get("node_label") or roles.node_id),
        ),
    )
```

- [ ] **Step 4: Prove the set-wise cross-room contract in real PostgreSQL**

Add one test to `dialectic/tests/test_field_marks_pg.py` that creates:

- two accepted live scope chains in `ROOM` and `OTHER`;
- a binding against the root revision whose current live revision is a successor;
- a same-shaped other-room sentinel binding;
- a malformed other-room review and successor naming the in-room mark;
- 26 in-room bindings so the per-room cap is exercised;
- an audited connection wrapper proving one candidate statement and one total read.

The terminal assertions must be:

```python
projection = await FieldMarkService(audited).atlas_causal_geo_bindings(
    [ROOM], {current_scope_id}, per_room_limit=25, limit=200,
)

assert projection.total == 26
assert len(projection.bindings) == 25
assert projection.omitted == 1
assert projection.complete is False
assert all(binding.current_scope_id == f"geo_scope:{current_scope_id}"
           for binding in projection.bindings)
assert any(binding.evidence_scope_id == f"geo_scope:{root_scope_id}"
           for binding in projection.bindings)
assert "OTHER-ROOM-CAUSAL-SENTINEL" not in projection.model_dump_json()
assert all(binding.target.room_id == ROOM for binding in projection.bindings)
assert audited.candidate_calls == 1
assert audited.read_calls == 1
```

Update the test module's setup comment to require migrations 021 and 022. If the fixture database lacks `geo_scopes`, skip with the same explicit message used by `test_world_tools.py`; never replace the real SQL test with a mock.

- [ ] **Step 5: Run the new PostgreSQL test and confirm it fails**

Run:

```bash
cd dialectic
DIALECTIC_TEST_DATABASE_URL=postgresql://root@localhost/dialectic_test \
  python3 -m pytest tests/test_field_marks_pg.py -q \
  -k 'causal_binding_adapter or atlas_causal_geo_bindings'
```

Expected: the adapter test passes after Step 3; the query test fails because `atlas_causal_geo_bindings` does not exist.

- [ ] **Step 6: Implement one bounded recursive query**

Add this statement beside `_CAUSAL_GEO_BINDINGS_SQL`:

```python
_ATLAS_CAUSAL_GEO_BINDINGS_SQL = """
WITH RECURSIVE scope_lineage AS (
    SELECT g.id AS revision_id, g.id AS current_scope_id,
           g.room_id, g.supersedes_id
    FROM geo_scopes g
    WHERE g.id = ANY($2::uuid[])
      AND g.room_id = ANY($1::uuid[])
    UNION ALL
    SELECT predecessor.id, lineage.current_scope_id,
           predecessor.room_id, predecessor.supersedes_id
    FROM scope_lineage lineage
    JOIN geo_scopes predecessor
      ON predecessor.id = lineage.supersedes_id
     AND predecessor.room_id = lineage.room_id
    WHERE predecessor.room_id = ANY($1::uuid[])
), matching AS (
    SELECT fm.id, fm.room_id, fm.thread_id, fm.mark_kind, fm.relation,
           fm.action, fm.origin, fm.deliberative_status, fm.subjects,
           fm.target_mark_id, fm.title, fm.payload, fm.supersedes_id,
           fm.caused_by_id, fm.actor_user_id, fm.provenance, fm.created_at,
           lineage.current_scope_id,
           count(*) OVER () AS matching_total,
           row_number() OVER (
               PARTITION BY fm.room_id
               ORDER BY fm.created_at DESC, fm.id DESC
           ) AS room_rank
    FROM field_marks fm
    JOIN scope_lineage lineage
      ON lineage.room_id = fm.room_id
     AND EXISTS (
         SELECT 1
         FROM jsonb_array_elements(fm.subjects) AS subject
         WHERE subject->>'entity' = 'geo_scopes'
           AND subject->>'id' = lineage.revision_id::text
     )
    WHERE fm.room_id = ANY($1::uuid[])
      AND fm.mark_kind = 'relation'
      AND fm.relation = ANY($3::text[])
      AND jsonb_array_length(fm.subjects) = 2
      AND EXISTS (
          SELECT 1
          FROM jsonb_array_elements(fm.subjects) AS subject
          WHERE subject->>'entity' = 'rooms'
            AND subject->>'id' = fm.room_id::text
            AND subject->>'field' ~ '^thesis_node:[^:]+:[^:]+$'
      )
), candidates AS (
    SELECT * FROM matching
    WHERE room_rank <= $4
    ORDER BY created_at DESC, id DESC
    LIMIT $5
), candidate_successors AS (
    SELECT successor.supersedes_id AS target_id,
           successor.room_id
    FROM field_marks successor
    JOIN candidates
      ON candidates.id = successor.supersedes_id
     AND candidates.room_id = successor.room_id
    WHERE successor.room_id = ANY($1::uuid[])
    GROUP BY successor.supersedes_id, successor.room_id
), candidate_reviews AS (
    SELECT review.target_mark_id, review.room_id,
           jsonb_agg(
               jsonb_build_object(
                   'id', review.id,
                   'action', review.action,
                   'actor_user_id', review.actor_user_id,
                   'payload', review.payload,
                   'created_at', review.created_at
               ) ORDER BY review.created_at, review.id
           ) AS reviews
    FROM field_marks review
    JOIN candidates
      ON candidates.id = review.target_mark_id
     AND candidates.room_id = review.room_id
    WHERE review.room_id = ANY($1::uuid[])
      AND review.mark_kind = 'review'
    GROUP BY review.target_mark_id, review.room_id
)
SELECT candidates.*,
       candidate_successors.target_id IS NOT NULL AS has_successor,
       COALESCE(candidate_reviews.reviews, '[]'::jsonb) AS reviews
FROM candidates
LEFT JOIN candidate_successors
  ON candidate_successors.target_id = candidates.id
 AND candidate_successors.room_id = candidates.room_id
LEFT JOIN candidate_reviews
  ON candidate_reviews.target_mark_id = candidates.id
 AND candidate_reviews.room_id = candidates.room_id
ORDER BY candidates.created_at DESC, candidates.id DESC
"""
```

Do not cast JSON subject IDs to UUID. Comparing the untrusted JSON text to `revision_id::text` is the fail-closed path for malformed subjects.

Add the service method:

```python
    async def atlas_causal_geo_bindings(
        self,
        room_ids: list[UUID],
        current_scope_ids: set[UUID],
        *,
        per_room_limit: int = 25,
        limit: int = 200,
    ) -> CausalGeoBindingsProjection:
        if not room_ids or not current_scope_ids:
            return CausalGeoBindingsProjection(
                generated_at=datetime.now(timezone.utc), bindings=[],
                total=0, omitted=0, complete=True,
            )
        if per_room_limit < 1 or per_room_limit > 100:
            raise ValueError("causal per-room limit must be between 1 and 100")
        if limit < 1 or limit > 400:
            raise ValueError("causal total limit must be between 1 and 400")
        rows = await self.db.fetch(
            _ATLAS_CAUSAL_GEO_BINDINGS_SQL,
            room_ids,
            sorted(current_scope_ids),
            list(FIELD_CAUSAL_RELATIONS),
            per_room_limit,
            limit,
        )
        total = int(rows[0]["matching_total"]) if rows else 0
        bindings: list[CausalGeoBinding] = []
        for row in rows:
            reviews = _jsonb_list(row["reviews"])
            mark = _to_field_mark(
                dict(row),
                _derive_review_state(bool(row["has_successor"]), reviews),
                reviews,
            )
            binding = causal_geo_binding_from_mark(
                mark,
                current_scope_id=f"geo_scope:{row['current_scope_id']}",
            )
            if binding is None:
                raise ValueError("causal query returned a non-causal Field mark")
            bindings.append(binding)
        omitted = max(0, total - len(bindings))
        return CausalGeoBindingsProjection(
            generated_at=datetime.now(timezone.utc), bindings=bindings,
            total=total, omitted=omitted, complete=omitted == 0,
        )
```

- [ ] **Step 7: Run the Field tests**

Run:

```bash
cd dialectic
DIALECTIC_TEST_DATABASE_URL=postgresql://root@localhost/dialectic_test \
  python3 -m pytest tests/test_field_marks_pg.py -q
```

Expected: all tests pass; the new read audit reports exactly one statement.

- [ ] **Step 8: Commit the owner projection**

```bash
git add dialectic/field_marks.py dialectic/tests/test_field_marks_pg.py
git commit -m "feat(world): project causal scope bindings set-wise"
```

## Task 2: Add lineage identity and causality to the enhanced Atlas projection

**Files:**

- Modify: `dialectic/atlas_objects.py`
- Modify: `dialectic/tests/test_atlas_pg.py`
- Modify: `dialectic/tests/test_atlas_api.py`

- [ ] **Step 1: Seed an old-revision binding and write Atlas contract tests**

Extend `atlas_world` in `dialectic/tests/test_atlas_pg.py` with a root accepted scope, a current accepted redraw successor, and a confirmed causal mark that still names the root. Add assertions:

```python
projection = await AtlasService(atlas_world).build(AMO, include_signals=True)

scope = next(item for item in projection.scopes if item.id == f"geo_scope:{current_scope_id}")
assert scope.lineage_root_id == f"geo_scope:{root_scope_id}"
assert projection.causal_bindings_total == 1
assert projection.causal_bindings_omitted == 0
assert projection.causal_bindings_complete is True
assert projection.causal_bindings[0].model_dump(mode="json") == {
    "id": f"field_mark:{causal_mark_id}",
    "current_scope_id": f"geo_scope:{current_scope_id}",
    "evidence_scope_id": f"geo_scope:{root_scope_id}",
    "relation": "supports",
    "review_state": "confirmed",
    "provisional": False,
    "target": {
        "room_id": str(ROOM_SHARED),
        "book_id": "atlas-thesis-graph",
        "node_id": "shipping",
        "node_label": "Shipping chokepoint",
    },
}
```

Add a Dan-side assertion that AMO-only binding labels and IDs do not occur in `dan_projection.model_dump_json()`.

In `dialectic/tests/test_atlas_api.py`, preserve the existing default exact-key test and add:

```python
def test_enhanced_atlas_response_names_empty_causal_state_exactly() -> None:
    body = _client().get(f"{PATH}?signals=1").json()
    assert body["causal_bindings"] == []
    assert body["causal_bindings_total"] == 0
    assert body["causal_bindings_omitted"] == 0
    assert body["causal_bindings_complete"] is True
```

- [ ] **Step 2: Run the red Atlas slice**

Run:

```bash
cd dialectic
DIALECTIC_TEST_DATABASE_URL=postgresql://root@localhost/dialectic_test \
  python3 -m pytest tests/test_atlas_pg.py tests/test_atlas_api.py -q \
  -k 'causal or lineage_root or source_compatible'
```

Expected: failures for missing `lineage_root_id` and causal response fields; the existing default exact-key test remains green.

- [ ] **Step 3: Derive lineage roots set-wise inside the existing scope query**

Replace `_GEO_SCOPES_SQL` with a recursive statement that ranks and bounds live scopes before walking only those selected rows to their roots:

```python
_GEO_SCOPES_SQL = f"""
WITH RECURSIVE ranked AS (
    SELECT g.id, g.room_id, g.subject, g.kind, g.geometry, g.label,
           g.authority, g.provenance, g.source_state, g.observed_at,
           g.retrieved_at, g.expires_at, g.confirmed_by, g.confirmed_at,
           g.supersedes_id, g.revision_action, g.review_note,
           g.created_by, g.created_at,
           row_number() OVER (
               PARTITION BY g.room_id ORDER BY g.created_at DESC
           ) AS rn
    FROM geo_scopes g
    WHERE g.room_id = ANY($1::uuid[]) AND {_geo_live_predicate("g")}
), selected AS (
    SELECT * FROM ranked
    WHERE rn <= $2
    ORDER BY created_at DESC
    LIMIT $3
), lineage AS (
    SELECT selected.id AS current_scope_id,
           selected.id AS revision_id,
           selected.room_id,
           selected.supersedes_id
    FROM selected
    UNION ALL
    SELECT lineage.current_scope_id,
           predecessor.id,
           predecessor.room_id,
           predecessor.supersedes_id
    FROM lineage
    JOIN geo_scopes predecessor
      ON predecessor.id = lineage.supersedes_id
     AND predecessor.room_id = lineage.room_id
    WHERE predecessor.room_id = ANY($1::uuid[])
), roots AS (
    SELECT current_scope_id, revision_id AS root_scope_id
    FROM lineage
    WHERE supersedes_id IS NULL
)
SELECT selected.*, roots.root_scope_id
FROM selected
JOIN roots ON roots.current_scope_id = selected.id
ORDER BY selected.created_at DESC
"""
```

Add a projection-only subtype and use it only in Atlas:

```python
class AtlasGeoScope(GeoScope):
    """A live GeoScope plus the canonical object identity of its lineage."""

    lineage_root_id: str


def _atlas_scope_from_row(row: Any) -> AtlasGeoScope:
    scope = scope_from_row(row)
    return AtlasGeoScope(
        **scope.model_dump(),
        lineage_root_id=f"geo_scope:{row['root_scope_id']}",
    )
```

Change `AtlasProjection.scopes` to `list[AtlasGeoScope]`. Do not add `lineage_root_id` to the room-local `GeoScope` contract.

- [ ] **Step 4: Add causality only to the enhanced response**

Import `CausalGeoBinding` and `CausalGeoBindingsProjection`. Extend `AtlasSignalProjection`:

```python
class AtlasSignalProjection(AtlasProjection):
    signals: list[WorldSignal]
    signal_sources: WorldSignalSources
    causal_bindings: list[CausalGeoBinding]
    causal_bindings_total: int
    causal_bindings_omitted: int
    causal_bindings_complete: bool
```

Add constants:

```python
_ATLAS_CAUSAL_PER_ROOM_CAP = 25
_ATLAS_CAUSAL_TOTAL_CAP = 200
```

After `_GEO_SCOPES_SQL`, call the owner only when `include_signals=True`:

```python
        causal = CausalGeoBindingsProjection(
            generated_at=generated_at, bindings=[], total=0,
            omitted=0, complete=True,
        )
        if include_signals:
            causal = await FieldMarkService(self.db).atlas_causal_geo_bindings(
                room_ids,
                {row["id"] for row in scope_rows},
                per_room_limit=_ATLAS_CAUSAL_PER_ROOM_CAP,
                limit=_ATLAS_CAUSAL_TOTAL_CAP,
            )

        projection = AtlasProjection(
            generated_at=generated_at, nodes=nodes, edges=edges,
            scopes=[_atlas_scope_from_row(row) for row in scope_rows],
        )
        return (
            self._with_signals(projection, room_ids, causal)
            if include_signals else projection
        )
```

Change `_with_signals` to accept `causal` and copy its four fields. The no-membership enhanced path must pass an explicit empty causal projection. The default path must not execute the causal statement or expose its fields.

- [ ] **Step 5: Run the complete Atlas contracts**

Run:

```bash
cd dialectic
DIALECTIC_TEST_DATABASE_URL=postgresql://root@localhost/dialectic_test \
  python3 -m pytest tests/test_atlas_pg.py tests/test_atlas_api.py \
  tests/test_geo_scopes_pg.py -q
```

Expected: all tests pass; default Atlas still serializes exactly `generated_at`, `nodes`, `edges`, and `scopes`.

- [ ] **Step 6: Commit the Atlas wire contract**

```bash
git add dialectic/atlas_objects.py dialectic/tests/test_atlas_pg.py dialectic/tests/test_atlas_api.py
git commit -m "feat(atlas): expose scope lineage and causal bindings"
```

## Task 3: Make participant sight consume the same causal DTO

**Files:**

- Modify: `dialectic/llm/world.py`
- Modify: `dialectic/tests/test_world_tools.py`

- [ ] **Step 1: Change the expected selected-scope tool result first**

Update the exact causal assertion in `dialectic/tests/test_world_tools.py`:

```python
assert out["scope"]["causal_bindings"] == [{
    "id": f"field_mark:{mark_id}",
    "current_scope_id": f"geo_scope:{scope_id}",
    "evidence_scope_id": f"geo_scope:{scope_id}",
    "relation": "supports",
    "review_state": "provisional",
    "provisional": True,
    "target": {
        "room_id": str(ROOM),
        "book_id": "hormuz-book",
        "node_id": "shipping",
        "node_label": "Shipping chokepoint",
    },
}]
assert out["show_on_world"] == {
    "room_id": str(ROOM),
    "scene": "atlas",
    "view": f"world;room={ROOM}",
    "object": f"geo_scope:{scope_id}",
}
```

In the long-lineage test, assert that `current_scope_id` names the current revision while `evidence_scope_id` names the root. Preserve the existing exact total, omitted, completeness, and bounded-lineage assertions.

- [ ] **Step 2: Run the red tool slice**

Run:

```bash
cd dialectic
DIALECTIC_TEST_DATABASE_URL=postgresql://root@localhost/dialectic_test \
  python3 -m pytest tests/test_world_tools.py -q -k world_query
```

Expected: exact-shape failures because the tool still emits a locally assembled DTO and omits the object destination.

- [ ] **Step 3: Replace local assembly with the owner adapter**

Change the import:

```python
from field_marks import FieldMarkService, causal_geo_binding_from_mark
```

Replace the manual binding dictionary loop with:

```python
        bindings = []
        for mark in field.marks:
            binding = causal_geo_binding_from_mark(
                mark, current_scope_id=review.current.id,
            )
            if binding is None:
                raise ValueError("scope binding projection returned a non-causal mark")
            bindings.append(binding.model_dump(mode="json"))
```

After review resolution, add the canonical object to the existing destination:

```python
        result["show_on_world"]["object"] = review.root_id
```

The overview call with no selected scope keeps its current three-field destination and no fabricated object.

- [ ] **Step 4: Run all World tool tests**

Run:

```bash
cd dialectic
DIALECTIC_TEST_DATABASE_URL=postgresql://root@localhost/dialectic_test \
  python3 -m pytest tests/test_world_tools.py tests/test_tools_registry.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit participant parity**

```bash
git add dialectic/llm/world.py dialectic/tests/test_world_tools.py
git commit -m "feat(world): share causal bindings with participant sight"
```

## Task 4: Fuse room navigation before rendering new spectacle

**Files:**

- Modify: `dialectic/frontend/app/src/lib/workspaceRoute.ts`
- Modify: `dialectic/frontend/app/src/lib/workspaceRoute.test.ts`
- Modify: `dialectic/frontend/app/src/App.tsx`
- Modify: `dialectic/frontend/app/src/App.notification.test.tsx`

- [ ] **Step 1: Write route and integration failures first**

Change the ordinary-room scene expectation:

```typescript
expect(scenesForDestination(scheme, root)).toEqual([
  'record', 'bench', 'field', 'atlas', 'library', 'ledger',
])
```

Add cases to `App.notification.test.tsx` proving:

1. `useAtlas(true)` is called for an ordinary room whose active scene is `atlas`.
2. Bench's World button navigates to the same room, `scene: 'atlas'`, `view: 'world;room=<room>'`, and preserves the current `objectId`.
3. House/World mode writes preserve the current room and object.
4. Selecting a scope from Atlas keeps `scene: 'atlas'`; selecting another room clears the object and resets the World room focus instead of carrying a foreign camera/object.

Use the existing `navigation(...).navigate` mock as the assertion seam. Do not mount a second router.

- [ ] **Step 2: Run the red route/App slice**

Run:

```bash
cd dialectic/frontend/app
npm test -- src/lib/workspaceRoute.test.ts src/App.notification.test.tsx
```

Expected: the ordinary scene list and same-room World destinations fail.

- [ ] **Step 3: Admit Atlas as a room scene**

Change only the ordinary root list in `workspaceRoute.ts`:

```typescript
return ['record', 'bench', 'field', 'atlas', 'library', 'ledger'] as const
```

Home root remains `['house', 'atlas', 'mirror', 'record']`; every branch remains Record-only.

- [ ] **Step 4: Enable Atlas exactly where Synapse needs it**

Replace the Home-only enable in `App.tsx` with:

```typescript
  const causalObjectSelected = objectId?.startsWith('geo_scope:')
    || objectId?.startsWith('field_mark:')
  const atlas = useAtlas(Boolean(accessToken) && (
    isHome
    || workspaceScene === 'atlas'
    || workspaceScene === 'field'
    || causalObjectSelected
  ))
```

This avoids turning every ordinary Record session into a cross-room Atlas read while ensuring World, Field, and either causal Focus kind receive the shared projection.

- [ ] **Step 5: Centralize the World destination in `App.tsx`**

Add one local function beside `openWorkspaceObject`:

```typescript
  const openWorldEvidence = (scopeObjectId: string, selectedObject: string = scopeObjectId) => {
    void navigate({
      roomId: currentRoom.id,
      threadId: null,
      scene: 'atlas',
      object: selectedObject,
      view: `world;room=${currentRoom.id}`,
    }, 'push')
  }
```

Use it from Bench and later from Field/Focus. Bench passes `objectId ?? null` directly through its destination rather than silently selecting a scope it does not know.

Change Atlas mode writes to preserve room and object:

```typescript
        onView={(view, mode) => {
          const decodedView = decodeWorldView(view)
          const nextView = !isHome && decodedView
            ? encodeWorldView({
                camera: decodedView.camera,
                roomId: currentRoom.id,
              })
            : view
          void navigate({
            roomId: currentRoom.id,
            threadId: null,
            scene: 'atlas',
            object: objectId,
            view: nextView,
          }, mode)
        }}
```

Import `decodeWorldView` and `encodeWorldView` from the existing World camera
module. This normalization matters when an ordinary-room House view has no
encoded room yet: its first World tap must frame the active room, not the
cross-room globe.

Change Atlas object/room navigation:

```typescript
        onNavigate={(destination) => {
          if (destination.threadId && !destination.object) {
            void navigate({
              roomId: destination.roomId,
              threadId: destination.threadId,
              object: null,
            }, 'push')
            return
          }
          const nextWorldView = isWorldView(viewId)
            ? `world;room=${destination.roomId}`
            : null
          void navigate({
            roomId: destination.roomId,
            threadId: null,
            scene: 'atlas',
            object: destination.object ?? null,
            messageId: destination.messageId ?? null,
            view: nextWorldView,
          }, 'push')
        }}
```

Import and use `isWorldView` from the existing camera module. Deliberately drop the prior room's camera on a room change; camera state may not cross the room fence.

Change Bench's button destination to:

```typescript
void navigate({
  roomId: currentRoom.id,
  threadId: null,
  scene: 'atlas',
  object: objectId,
  view: `world;room=${currentRoom.id}`,
}, 'push')
```

- [ ] **Step 6: Render Focus beside ordinary-room Atlas**

Keep the existing `!isHome && objectId` guard. Because Atlas now remains in the ordinary room, a Home Atlas scope tap changes to the owning ordinary room, keeps `scene='atlas'`, and mounts the existing Focus surface beside the still-visible World. Do not enable room-local Focus at Home or fetch ordinary-room projections at Home.

- [ ] **Step 7: Run navigation tests**

Run:

```bash
cd dialectic/frontend/app
npm test -- src/lib/workspaceRoute.test.ts src/hooks/useRoomNavigation.focus.test.tsx \
  src/App.notification.test.tsx
```

Expected: all tests pass and every asserted destination comes from the existing navigation mock.

- [ ] **Step 8: Commit the fused route**

```bash
git add dialectic/frontend/app/src/lib/workspaceRoute.ts \
  dialectic/frontend/app/src/lib/workspaceRoute.test.ts \
  dialectic/frontend/app/src/App.tsx \
  dialectic/frontend/app/src/App.notification.test.tsx
git commit -m "feat(world): keep Atlas inside the active room"
```

## Task 5: Render one selected object and honest causal rays

**Files:**

- Modify: `dialectic/frontend/app/src/types/atlas.ts`
- Modify: `dialectic/frontend/app/src/components/workspace/scenes/AtlasScene.tsx`
- Modify: `dialectic/frontend/app/src/components/workspace/scenes/AtlasScene.css`
- Modify: `dialectic/frontend/app/src/components/workspace/scenes/AtlasScene.test.tsx`
- Modify: `dialectic/frontend/app/src/components/workspace/world/WorldView.tsx`
- Modify: `dialectic/frontend/app/src/components/workspace/world/WorldView.test.ts`
- Modify: `dialectic/frontend/app/src/components/workspace/world/World.css`
- Create: `dialectic/frontend/app/src/components/workspace/world/CausalBindingList.tsx`
- Create: `dialectic/frontend/app/src/components/workspace/world/CausalBindingList.test.tsx`

- [ ] **Step 1: Mirror the enhanced wire types**

Add to `types/atlas.ts`:

```typescript
export interface AtlasGeoScope extends GeoScope {
  lineage_root_id: string
}

export interface CausalGeoTarget {
  room_id: string
  book_id: string
  node_id: string
  node_label: string
}

export interface CausalGeoBinding {
  id: string
  current_scope_id: string
  evidence_scope_id: string
  relation: 'supports' | 'challenges' | 'context'
  review_state: 'provisional' | 'confirmed' | 'contested' | 'superseded'
  provisional: boolean
  target: CausalGeoTarget
}
```

Change `AtlasProjection.scopes` to `AtlasGeoScope[]` and add optional enhanced fields:

```typescript
causal_bindings?: CausalGeoBinding[]
causal_bindings_total?: number
causal_bindings_omitted?: number
causal_bindings_complete?: boolean
```

Optionality is required because the default Atlas endpoint remains source-compatible. The frontend's `useAtlas` still requests `signals: true`, so ready production UI receives explicit values.

- [ ] **Step 2: Write rendering tests before components**

In `AtlasScene.test.tsx`, extend the ready fixture with `lineage_root_id` and add tests proving:

- `selectedObjectId` equal to the lineage root gives the current live scope row `aria-current="true"`;
- selecting a Field mark highlights its `current_scope_id` scope;
- House and World render the same `scope -> relation -> target` text;
- clicking the causal relation navigates to `{roomId, object: field_mark:<uuid>}`;
- omitted bindings render an explicit `N more causal bindings omitted` note;
- the WorldView mock receives `selectedScopeId`.

Change `readyWithScopes` to accept `AtlasGeoScope[]`, and declare
`hormuzScope` as `AtlasGeoScope` with
`lineage_root_id: 'geo_scope:s1'`. Do not cast old `GeoScope[]` fixtures over
the stronger Atlas wire type.

In `WorldView.test.ts`, export and test `addScope`:

```typescript
addScope(viewer, hormuzScope, true)
expect(add.mock.calls[0][0]).toMatchObject({
  id: hormuzScope.id,
  properties: { worldScope: true, selected: true },
})
```

In the new `CausalBindingList.test.tsx`, assert visible words `Strait of Hormuz`, `Supports`, `Shipping chokepoint`, and `Confirmed`, then assert the relation button opens the Field mark. Include a provisional case whose visible text says `Provisional`.

- [ ] **Step 3: Run the red component slice**

Run:

```bash
cd dialectic/frontend/app
npm test -- src/components/workspace/scenes/AtlasScene.test.tsx \
  src/components/workspace/world/WorldView.test.ts \
  src/components/workspace/world/CausalBindingList.test.tsx
```

Expected: missing type/component/prop failures.

- [ ] **Step 4: Implement one shared semantic renderer**

Create `CausalBindingList.tsx`:

```tsx
import type { CausalGeoBinding } from '../../../types/atlas.ts'

interface CausalBindingListProps {
  scopeLabel: string
  bindings: CausalGeoBinding[]
  onOpenMark: (binding: CausalGeoBinding) => void
}

function displayLabel(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1)
}

export function CausalBindingList({
  scopeLabel, bindings, onOpenMark,
}: CausalBindingListProps) {
  if (bindings.length === 0) return null
  return (
    <ul className="world-causal-list" aria-label={`Causal bindings for ${scopeLabel}`}>
      {bindings.map((binding) => (
        <li key={binding.id} className="world-causal-binding">
          <span>{scopeLabel}</span>
          <span aria-hidden="true"> -> </span>
          <button type="button" onClick={() => onOpenMark(binding)}>
            {displayLabel(binding.relation)}
          </button>
          <span aria-hidden="true"> -> </span>
          <span>{binding.target.node_label}</span>
          <span className={`world-causal-review is-${binding.review_state}`}>
            {displayLabel(binding.review_state)}
          </span>
        </li>
      ))}
    </ul>
  )
}
```

This shared component is the one justified new file: both Atlas and ScopeReview must render identical causal semantics without copying relationship wording.

- [ ] **Step 5: Compute selection once in AtlasScene**

Add props:

```typescript
selectedObjectId?: string | null
```

Compute:

```typescript
const bindings = state.projection.causal_bindings ?? []
const selectedBinding = bindings.find((binding) => binding.id === selectedObjectId)
const selectedScope = scopes.find((scope) => (
  scope.id === selectedObjectId
  || scope.lineage_root_id === selectedObjectId
  || scope.id === selectedBinding?.current_scope_id
))
const bindingsByScope = new Map<string, CausalGeoBinding[]>()
for (const binding of bindings) {
  const list = bindingsByScope.get(binding.current_scope_id) ?? []
  list.push(binding)
  bindingsByScope.set(binding.current_scope_id, list)
}
```

Pass `selectedScope?.id ?? null` to WorldView. Pass selection and bindings into `OnTheMapGroup`. Put `aria-current={selected ? 'true' : undefined}` on the scope button and render a visible `Selected` chip so selection is not color-only.

Under each scope row, render `CausalBindingList` for that scope. In World mode, also render one `.world-causal-overlay` immediately below the globe for the selected scope or selected Field mark. It reuses the same component and never receives coordinates for the target.

Render global truth below the list when incomplete:

```tsx
{!state.projection.causal_bindings_complete && (
  <p className="world-note">
    {(state.projection.causal_bindings_omitted ?? 0).toLocaleString()} more causal bindings omitted.
  </p>
)}
```

- [ ] **Step 6: Highlight only the real geometry in Cesium**

Export `addScope` and add a boolean parameter:

```typescript
export function addScope(
  viewer: Cesium.Viewer, scope: GeoScope, selected = false,
): void {
```

Add `properties: { worldScope: true, selected }` to every entity base. Use larger point size, wider line, and stronger outline when selected. In the redraw effect:

```typescript
for (const scope of scopes) addScope(viewer, scope, scope.id === selectedScopeId)
```

Add `selectedScopeId?: string | null` to props, default it to `null` in the
function destructure, and add it to redraw dependencies. The optional default
keeps direct no-selection consumers and the WebGL-failure test source
compatible. Do not call `viewer.selectedEntity`, add a second Cesium data
source, or create a target line.

- [ ] **Step 7: Style the semantic ray without pretending it is geographic**

Use Dark Roast tokens in `World.css` and `AtlasScene.css`:

```css
.world-scope-row .atlas-row-open[aria-current="true"] {
  box-shadow: inset 3px 0 0 var(--color-amber);
  background: color-mix(in srgb, var(--color-amber) 10%, transparent);
}

.world-selected-chip,
.world-causal-review {
  font-size: 0.75rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.world-causal-list {
  list-style: none;
  margin: 0;
  padding: 0.5rem 0.75rem 0.75rem;
}

.world-causal-binding {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.45rem;
  color: var(--color-cream);
}

.world-causal-overlay {
  border-left: 2px solid var(--color-teal);
  background: var(--color-obsidian);
}
```

Use existing CSS variables verified in `theme.css`; if a listed variable does not exist, replace it with the nearest existing Dark Roast token rather than inventing a new token.

- [ ] **Step 8: Run the rendering slice**

Run:

```bash
cd dialectic/frontend/app
npm test -- src/components/workspace/scenes/AtlasScene.test.tsx \
  src/components/workspace/world/WorldView.test.ts \
  src/components/workspace/world/WorldView.failure.test.tsx \
  src/components/workspace/world/CausalBindingList.test.tsx
```

Expected: all tests pass; failed WebGL still leaves the same complete list and causal text usable.

- [ ] **Step 9: Commit the honest causal rendering**

```bash
git add dialectic/frontend/app/src/types/atlas.ts \
  dialectic/frontend/app/src/components/workspace/scenes/AtlasScene.tsx \
  dialectic/frontend/app/src/components/workspace/scenes/AtlasScene.css \
  dialectic/frontend/app/src/components/workspace/scenes/AtlasScene.test.tsx \
  dialectic/frontend/app/src/components/workspace/world/WorldView.tsx \
  dialectic/frontend/app/src/components/workspace/world/WorldView.test.ts \
  dialectic/frontend/app/src/components/workspace/world/World.css \
  dialectic/frontend/app/src/components/workspace/world/CausalBindingList.tsx \
  dialectic/frontend/app/src/components/workspace/world/CausalBindingList.test.tsx
git commit -m "feat(world): render selected causal evidence honestly"
```

## Task 6: Make Field and Focus open the same World evidence

**Files:**

- Modify: `dialectic/frontend/app/src/components/workspace/scenes/FieldScene.tsx`
- Modify: `dialectic/frontend/app/src/components/workspace/scenes/FieldScene.test.tsx`
- Modify: `dialectic/frontend/app/src/components/workspace/focus/FocusSurface.tsx`
- Modify: `dialectic/frontend/app/src/components/workspace/focus/FocusSurface.test.tsx`
- Modify: `dialectic/frontend/app/src/components/workspace/focus/ScopeReview.tsx`
- Create: `dialectic/frontend/app/src/components/workspace/focus/ScopeReview.test.tsx`
- Modify: `dialectic/frontend/app/src/App.tsx`

- [ ] **Step 1: Write Field and Focus destination tests first**

Use one `CausalGeoBinding` fixture whose mark names an old evidence revision and whose `current_scope_id` names the live redraw.

In `FieldScene.test.tsx`, assert a causal row renders `Open World evidence`; clicking it calls:

```typescript
expect(onOpenWorld).toHaveBeenCalledWith(
  'geo_scope:current', 'field_mark:causal',
)
```

In `FocusSurface.test.tsx`, assert the same for selected `field_mark:causal`.

In `ScopeReview.test.tsx`, pass the shared binding array and assert the exact scope/relation/node/review words render through `CausalBindingList`; clicking the relation selects `field_mark:causal` into Focus.

- [ ] **Step 2: Run the red Focus/Field slice**

Run:

```bash
cd dialectic/frontend/app
npm test -- src/components/workspace/scenes/FieldScene.test.tsx \
  src/components/workspace/focus/FocusSurface.test.tsx \
  src/components/workspace/focus/ScopeReview.test.tsx
```

Expected: missing prop and action failures.

- [ ] **Step 3: Consume the Atlas DTO in Field**

Add props:

```typescript
worldBindings?: CausalGeoBinding[]
onOpenWorld?: (scopeObjectId: string, selectedObject?: string) => void
```

In `MarkRow`, resolve only by the canonical Field mark ID:

```typescript
const worldBinding = worldBindings?.find((binding) => binding.id === mark.id)
```

Render beside Builder:

```tsx
{worldBinding && onOpenWorld && (
  <button
    type="button"
    className="field-mark-world"
    onClick={() => onOpenWorld(worldBinding.current_scope_id, mark.id)}
  >
    Open World evidence
  </button>
)}
```

The World action uses the server-owned current lineage mapping, never the stale
bare evidence subject parsed by the client. It keeps the Field mark itself as
the selected object, so Focus does not change identity merely because the
underlay changes from Field to World.

- [ ] **Step 4: Consume the same DTO in both Focus kinds**

Add to `FocusSurfaceProps`:

```typescript
worldBindings?: CausalGeoBinding[]
onOpenWorld?: (scopeObjectId: string, selectedObject?: string) => void
```

For a selected Field mark, find by `binding.id` and render `Open World evidence`. Pass `selectedMark.id` as the selected object so World opens with the same Field mark in Focus while highlighting its current scope.

For `ScopeReview`, pass all same-room bindings. Inside `ScopeReview`, filter after review loads:

```typescript
const scopeBindings = worldBindings.filter((binding) => (
  binding.current_scope_id === review.current.id
  || review.lineage.some((scope) => scope.id === binding.evidence_scope_id)
))
```

Render `CausalBindingList` and wire its action to `onNavigate({object: binding.id})`. This changes selection only; it does not change scene, room, or view.

- [ ] **Step 5: Wire App once**

Derive:

```typescript
const causalBindings = atlas.status === 'ready'
  ? (atlas.projection.causal_bindings ?? [])
  : []
```

Pass it to `AtlasScene`, `FieldScene`, and `FocusSurface`. Pass the same `openWorldEvidence` callback to Field and Focus. Do not add a fetch to any component.

- [ ] **Step 6: Run all Field/Focus tests**

Run:

```bash
cd dialectic/frontend/app
npm test -- src/components/workspace/scenes/FieldScene.test.tsx \
  src/components/workspace/focus/FocusSurface.test.tsx \
  src/components/workspace/focus/ScopeReview.test.tsx \
  src/components/workspace/fieldDisplay.test.ts
```

Expected: all tests pass. Existing Builder URLs and review actions remain unchanged.

- [ ] **Step 7: Commit the twin doors**

```bash
git add dialectic/frontend/app/src/components/workspace/scenes/FieldScene.tsx \
  dialectic/frontend/app/src/components/workspace/scenes/FieldScene.test.tsx \
  dialectic/frontend/app/src/components/workspace/focus/FocusSurface.tsx \
  dialectic/frontend/app/src/components/workspace/focus/FocusSurface.test.tsx \
  dialectic/frontend/app/src/components/workspace/focus/ScopeReview.tsx \
  dialectic/frontend/app/src/components/workspace/focus/ScopeReview.test.tsx \
  dialectic/frontend/app/src/App.tsx
git commit -m "feat(world): join Field and Focus to World evidence"
```

## Task 7: Prove the fused organism in a disposable browser

**Files:**

- Modify: `docs/superpowers/acceptance/2026-08-25-world-lens-truth-acceptance.py`
- Modify: `dialectic/CLAUDE.md`
- Modify: `JOURNAL.md`
- Create: `docs/superpowers/qualification/2026-08-25-phase-3-world-synapse.md`

- [ ] **Step 1: Add Synapse checks to the existing acceptance harness**

Do not create a second harness. Extend the disposable database/browser flow after the existing visible Field bind and Confirm, before the existing scope Supersede action.

Through visible controls only:

1. From Field, click `Open World evidence`.
2. Assert URL has the ordinary `room`, `scene=atlas`, `view=world;room=<same room>`, and selected object.
3. Assert the current scope row has `aria-current=true` even though the Field mark named an older revision.
4. Assert visible overlay text names the scope, `Supports`, thesis-node label, and `Confirmed`.
5. Assert the Cesium entity for the current scope has `properties.selected=true` through the existing `window.__dialecticWorld` acceptance probe.
6. Toggle House and assert room/object/Focus survive while only `view` changes.
7. Toggle World and assert the same current scope re-highlights.
8. Click the causal relation and assert the exact Field mark opens in Focus while World stays rendered.
9. Use Back and Forward; assert room, scene, view, object, and highlight restore exactly.
10. Copy the URL into the no-WebGL context; assert Focus, selected row, causal text, and full keyboard list remain usable.

Add explicit checks similar to:

```python
check("Field opens World in the same room", query.get("room") == [ROOM_ID])
check("World preserves the same selected Field object", query.get("object") == [mark_id])
check("current lineage scope is selected", current_row.get_attribute("aria-current") == "true")
check("causal overlay names exact semantics", all(
    text in overlay.inner_text()
    for text in ("Supports", "Shipping chokepoint", "Confirmed")
))
check("House and World preserve Focus identity", object_before == object_after == mark_id)
check("failed WebGL preserves Synapse", fallback_row.count() == 1 and fallback_binding.count() == 1)
```

Preserve the harness rule that named writes use visible UI controls. The new Synapse acceptance is read/navigation only.

- [ ] **Step 2: Run targeted source gates before the expensive browser gate**

Run:

```bash
cd dialectic
DIALECTIC_TEST_DATABASE_URL=postgresql://root@localhost/dialectic_test \
  python3 -m pytest tests/test_field_marks_pg.py tests/test_atlas_pg.py \
  tests/test_atlas_api.py tests/test_world_tools.py -q

cd frontend/app
npm test -- src/lib/workspaceRoute.test.ts \
  src/components/workspace/scenes/AtlasScene.test.tsx \
  src/components/workspace/scenes/FieldScene.test.tsx \
  src/components/workspace/focus/FocusSurface.test.tsx \
  src/components/workspace/focus/ScopeReview.test.tsx \
  src/components/workspace/world/WorldView.test.ts \
  src/components/workspace/world/WorldView.failure.test.tsx \
  src/components/workspace/world/CausalBindingList.test.tsx \
  src/App.notification.test.tsx
```

Expected: all tests pass with no skips in the named PostgreSQL tests when the local fixture database is available.

- [ ] **Step 3: Run full source qualification**

Run:

```bash
cd dialectic
DIALECTIC_TEST_DATABASE_URL=postgresql://root@localhost/dialectic_test \
  python3 -m pytest tests/ -q

cd frontend/app
npm test
npm run lint
npm run build
```

Expected: backend, frontend, lint, and production build all pass. Record exact counts from output; do not reuse counts from the pre-Synapse commit.

- [ ] **Step 4: Run the disposable browser acceptance**

Run:

```bash
cd /root/DwoodAmo/.worktrees/world-lens-truth-before-spectacle
python3 docs/superpowers/acceptance/2026-08-25-world-lens-truth-acceptance.py
```

Expected: every prior truth-before-spectacle check and every new Synapse check passes. Preserve the emitted `/tmp/dialectic-world-lens-acceptance-*` path, `results.json`, screenshots, backend log, and preview log in the qualification ledger.

- [ ] **Step 5: Inspect the screenshots, not only the ledger**

Open every generated desktop, 390 px, and no-WebGL screenshot. Reject the build if:

- Focus covers or displaces the World into an unusable sliver;
- selected state relies on color alone;
- the causal sequence wraps into unreadable fragments;
- the complete list is unreachable by keyboard;
- source attribution is hidden;
- House/World toggles lose the selected object;
- a semantic connector can be mistaken for measured geography.

Record screenshot dimensions and the actual visual finding.

- [ ] **Step 6: Write the qualification ledger and current-state docs**

The ledger must separate:

- exact checkout and commit;
- dirty-worktree state;
- backend tests;
- real-Postgres tests and skips;
- frontend tests;
- lint;
- production build;
- disposable browser result and evidence path;
- local migration state;
- production runtime/PID;
- served asset;
- public browser;
- provider configuration;
- activation;
- physical-device proof;
- ordinary-use/human qualification.

Create `docs/superpowers/qualification/` before adding the ledger if the
directory does not yet exist; the ledger itself must be added with
`apply_patch`.

The final six production/user surfaces remain `NOT PERFORMED` unless separately authorized and actually observed.

Update `dialectic/CLAUDE.md` with only durable current architecture: Atlas-in-room, canonical scope lineage identity, shared causal binding projection, and the no-fake-geographic-ray rule. Append one JOURNAL line:

```text
[2026-08-25] fused World and Dialectic through one causal Synapse projection — room, view, object, Focus, Field, and participant sight now preserve canonical scope lineage and exact Field meaning without inventing geography or a second authority
```

- [ ] **Step 7: Run documentation and diff hygiene**

Run:

```bash
git diff --check
rg -n "TODO|TBD|placeholder|Epic EHR|FHIR|SMART on FHIR|Shuttle" \
  dialectic/field_marks.py dialectic/atlas_objects.py dialectic/llm/world.py \
  dialectic/frontend/app/src docs/superpowers/qualification/2026-08-25-phase-3-world-synapse.md
git status --short
```

Expected: `git diff --check` is clean; the forbidden-term scan is empty except any fixture text explicitly asserting absence; status contains only the planned files.

- [ ] **Step 8: Commit the qualified Phase 3 boundary**

```bash
git add docs/superpowers/acceptance/2026-08-25-world-lens-truth-acceptance.py \
  docs/superpowers/qualification/2026-08-25-phase-3-world-synapse.md \
  dialectic/CLAUDE.md JOURNAL.md
git commit -m "test(world): qualify the Phase 3 Synapse"
```

## Final review gate

- [ ] Compare the finished diff against every invariant at the top of this plan.
- [ ] Confirm no schema or migration file changed.
- [ ] Confirm `api/atlas.py` still exposes exactly one GET route.
- [ ] Confirm default Atlas has exactly four top-level keys.
- [ ] Confirm enhanced Atlas counts are exact for bindings over the bounded scopes it projects.
- [ ] Confirm no client derives `current_scope_id` by walking lineage or parsing Field subjects.
- [ ] Confirm every room fence appears in candidates, successors, and reviews.
- [ ] Confirm a root-bound mark follows the current live scope after redraw.
- [ ] Confirm a room change clears the prior object and camera focus.
- [ ] Confirm House/World mode and camera replacements preserve the current object.
- [ ] Confirm selected state is visible, programmatic, and not color-only.
- [ ] Confirm causal meaning is DOM text, not a fabricated geospatial primitive.
- [ ] Confirm Field, Focus, Atlas, and `world_query` consume `CausalGeoBinding` identity.
- [ ] Confirm all write authority remains in existing GeoScope, Field review, and Builder paths.
- [ ] Confirm production, provider, public delivery, activation, physical-device, and human-use claims remain closed.

## Deferred after Phase 3

The following remain outside this implementation even if they are attractive while editing:

- real provider selection or activation;
- animated contacts and render-governor hold owners;
- World Memory and replay retention;
- belief-weather aggregation;
- competing-future signatures;
- falsification watches;
- cross-room causal echoes;
- voice, command deck, spatial computing;
- real geographic arcs between two accepted geographic endpoints.

Those enter only through their gates in `docs/superpowers/specs/2026-08-25-gods-eye-dialectic-fusion-program-design.md`.
