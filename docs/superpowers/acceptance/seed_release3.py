"""
seed_release3.py — deterministic scale-seed for the Release 3 gate's
performance measurements (PLAN.md §5.7 / TG-G).

WHAT THIS IS: a seed script, not a probe of write endpoints (§5.7's own
instruction) — every row lands via a direct asyncpg INSERT, the same idiom
`tests/test_workspace_objects_pg.py` and `tests/test_field_marks_pg.py` use
for their fixtures (`_uid(n)` deterministic UUIDs, `_d(days)` frozen
timestamps relative to a fixed BASE). Nothing here calls an HTTP endpoint.

TARGET DATABASE: a DEDICATED database, never `dialectic`, never
`dialectic_browser` (TG-F's fixture, exclusive to sibling TG-F while this
build is in flight), never `dialectic_test` (pytest's). Default
`dialectic_seed` — create it once with:

    createdb dialectic_seed
    psql dialectic_seed -f schema.sql
    for f in migrations/0*.sql; do psql dialectic_seed -f "$f"; done

migration 016 (voyage_embeddings) will report "already exists" / a harmless
no-op-shaped error on a FRESH schema.sql — schema.sql already bakes in its
final shape (`memories.embedding vector(1024)` plus the view that reads it),
because schema.sql is the fresh-DB baseline for everything through 013 and
016 both (014's `reading_items` is the one documented gap — see
dialectic/CLAUDE.md's 2026-08-13 amendment). Apply 014, 015, 017 for real;
016 is redundant on a fresh build. Override with SEED_DATABASE_URL.

IDEMPOTENCY: every seeded row is deleted by deterministic id before being
reinserted (see `_cleanup`), so re-running this script against the same
database reproduces identical row counts without needing a drop/recreate —
and `createdb`/`dropdb` remain free at any time since this database is this
task group's alone. The ONE pre-existing row this script never touches is
the singleton Home room bootstrapped by migration 013's own DO block
(`rooms.is_home`) — it is looked up, never created or deleted here; only the
two membership rows this script adds for its own seeded users are cleaned up.

SCALE (§5.7): ~50 rooms, ~2k messages, ~500 memories with real supersession
chains, ~100 readings with memory twins (written through
`llm.reading._reading_key`, the writer's OWN key function — §2 item 4's twin
rule), ~200+ field_marks with lineage chains (confirm/contest/correct/split/
merge) and reviews, echo references (`memory_references`), commitments.
TWO users with overlapping-but-different memberships so the Atlas fence is
exercised at scale, one holding the most memberships (for
`GET /users/me/atlas`) and both added to the one Home room (for
`GET /users/me/home/activity`).

Run with the SAME interpreter production uses — `/usr/bin/python3`, not a
bare `python3` (CLAUDE.md's documented trap: a bare `python3` on this box
resolves to an unrelated project's venv):

    cd /root/DwoodAmo/dialectic
    /usr/bin/python3 ../docs/superpowers/acceptance/seed_release3.py
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg

# --- make the dialectic package importable (llm.reading._reading_key,
# api.auth.utils.get_password_hash) without installing it -------------------
_DIALECTIC_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "dialectic")
)
if _DIALECTIC_DIR not in sys.path:
    sys.path.insert(0, _DIALECTIC_DIR)

from api.auth.utils import get_password_hash  # noqa: E402
from field_marks import compute_dedup_key  # noqa: E402
from llm.reading import _reading_key  # noqa: E402

SEED_DATABASE_URL = os.environ.get(
    "SEED_DATABASE_URL", "postgresql://root@localhost/dialectic_seed"
)

# --- the _uid/_d idiom (tests/test_workspace_objects_pg.py) ----------------

BASE = datetime(2026, 8, 12, 12, 0, tzinfo=timezone.utc)


def _uid(n: int) -> UUID:
    return UUID(f"00000000-0000-4000-8000-{n:012x}")


def _d(days: float) -> datetime:
    return BASE - timedelta(days=days)


# --- deterministic id namespaces (offset blocks, so every id is a pure
# function of loop indices — no reliance on insertion order or global state,
# which is what makes a rerun byte-for-byte reproducible) -------------------
NS_USER = 0x000000
NS_ROOM = 0x010000
NS_THREAD_MAIN = 0x020000
NS_THREAD_BRANCH = 0x021000
NS_MESSAGE = 0x100000       # + i*1000 + j   (<=1000 messages/room headroom)
NS_MEMORY = 0x300000        # + i*100 + j
NS_READING = 0x400000       # + i*100 + j
NS_READING_TWIN = 0x410000  # + i*100 + j
NS_FIELD = 0x500000         # + i*1000 + k   (shared relation+review counter)
NS_COMMITMENT = 0x600000    # + i*10 + j
NS_ECHO = 0x700000          # + k
NS_EVENT = 0x800000         # + k

N_ROOMS = 50
HEAVY_ROOM_INDEX = 0
# Sentinel rooms for the two-user fence smoke check (mirrors the
# OTHER-ROOM-SENTINEL pattern from tests/test_workspace_objects_pg.py) —
# content only one of the two seeded users can ever see.
AMO_SENTINEL_ROOM_INDEX = 5
DAN_SENTINEL_ROOM_INDEX = 45
AMO_SENTINEL = "AMO-ONLY-SENTINEL"
DAN_SENTINEL = "DAN-ONLY-SENTINEL"

USER_A_ID = _uid(NS_USER + 1)
USER_B_ID = _uid(NS_USER + 2)
USER_A_EMAIL = "amo-seed@fixture.example.com"
USER_A_PASSWORD = "seed-fixture-pw-amo-4f2c"
USER_A_NAME = "Amo (seed)"
USER_B_EMAIL = "dan-seed@fixture.example.com"
USER_B_PASSWORD = "seed-fixture-pw-dan-9b7e"
USER_B_NAME = "Dan (seed)"

SEED_USER_IDS = [USER_A_ID, USER_B_ID]
SEED_ROOM_IDS = [_uid(NS_ROOM + i) for i in range(N_ROOMS)]


def room_members(i: int) -> list[UUID]:
    """0-19: Amo only. 20-39: both (the overlap). 40-49: Dan only.
    Amo ends up with 40 memberships (rooms 0-39) — "the user with the most
    memberships" the perf script measures Atlas against. Dan has 30
    (rooms 20-49), 20 of them shared with Amo."""
    if i < 20:
        return [USER_A_ID]
    if i < 40:
        return [USER_A_ID, USER_B_ID]
    return [USER_B_ID]


def n_messages(i: int) -> int:
    return 220 if i == HEAVY_ROOM_INDEX else 30 + (i % 12)


def n_memories(i: int) -> int:
    return 34 if i == HEAVY_ROOM_INDEX else 6 + (i % 7)


def n_readings(i: int) -> int:
    return 16 if i == HEAVY_ROOM_INDEX else 1 + (i % 3)


def n_commitments(i: int) -> int:
    return 4 if i == HEAVY_ROOM_INDEX else 1 + (i % 2)


def has_branch(i: int) -> bool:
    return i % 5 == 0


def has_brief(i: int) -> bool:
    return i % 5 == 0


# --- SQL (column order matches field_marks.py / api/field.py exactly, so a
# row this script writes is indistinguishable from one the API would have
# written) --------------------------------------------------------------

_RELATION_SQL = """
INSERT INTO field_marks
    (id, room_id, thread_id, mark_kind, relation, origin, provenance,
     subjects, title, payload, supersedes_id, caused_by_id, actor_user_id,
     created_at, dedup_key)
VALUES ($1,$2,$3,'relation',$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
"""

_REVIEW_SQL = """
INSERT INTO field_marks
    (id, room_id, mark_kind, action, target_mark_id, actor_user_id,
     provenance, created_at, payload)
VALUES ($1,$2,'review',$3,$4,$5,'human',$6,$7)
"""


class RoomFieldIds:
    """Deterministic id allocator for one room's field_marks — a pure
    function of (room index, call order within THIS script), so a rerun
    allocates the same ids in the same order."""

    def __init__(self, room_index: int):
        self._base = NS_FIELD + room_index * 1000
        self._k = 0

    def next(self) -> UUID:
        self._k += 1
        return _uid(self._base + self._k)


def _subj(mid: UUID, field: str | None = None) -> dict:
    d = {"entity": "messages", "id": str(mid)}
    if field:
        d["field"] = field
    return d


def build_field_kit(kind, room, thread, subjects, actor, at, ids, title_prefix):
    """One lineage kit, mirroring tests/test_field_marks_pg.py's fixture
    helpers (_relation/_review). Returns (relations, reviews) as lists of
    param tuples matching _RELATION_SQL / _REVIEW_SQL, split by kind so the
    caller can insert in FK-safe phases: every original relation first,
    then every review (which targets an original), then every replacement
    relation (which supersedes an original and is caused_by a review).
    """
    originals, reviews, replacements = [], [], []

    def rel(rid, relation, subj, org, prov, title, supersedes=None, caused_by=None,
             actor_id=None, when=at):
        subj_list = subj if isinstance(subj, list) else [subj]
        return (
            rid, room, thread, relation, org, prov, subj_list, title, {},
            supersedes, caused_by, actor_id, when,
            compute_dedup_key(relation, subj_list),
        )

    def rev(vid, action, target, when, extra=None):
        return (vid, room, action, target, actor, when, extra or {})

    if kind == "confirm":
        mid = ids.next()
        originals.append(rel(mid, "emerging_position", subjects[0], "inferred",
                              "field_inference", f"{title_prefix}: emerging position"))
        reviews.append(rev(ids.next(), "confirm", mid, at - timedelta(days=5)))
        reviews.append(rev(ids.next(), "confirm", mid, at - timedelta(days=3)))
    elif kind == "contest":
        mid = ids.next()
        originals.append(rel(mid, "possible_contradiction",
                              [subjects[0], subjects[1]], "inferred",
                              "field_inference", f"{title_prefix}: possible contradiction"))
        reviews.append(rev(ids.next(), "contest", mid, at - timedelta(days=4)))
    elif kind == "correct":
        mid = ids.next()
        originals.append(rel(mid, "repeated_definition", subjects[0], "inferred",
                              "field_inference", f"{title_prefix}: definition A"))
        rvid = ids.next()
        reviews.append(rev(rvid, "correct", mid, at - timedelta(days=1)))
        replacements.append(rel(
            ids.next(), "repeated_definition", subjects[1], "explicit", "human",
            f"{title_prefix}: definition A, corrected",
            supersedes=mid, caused_by=rvid, actor_id=actor,
            when=at - timedelta(days=1),
        ))
    elif kind == "split":
        mid = ids.next()
        originals.append(rel(mid, "claim_group", subjects[0], "inferred",
                              "field_inference", f"{title_prefix}: combined claim"))
        rvid = ids.next()
        reviews.append(rev(rvid, "split", mid, at - timedelta(days=2)))
        for k, sidx in enumerate((1, 2)):
            replacements.append(rel(
                ids.next(), "claim_group", subjects[sidx], "explicit", "human",
                f"{title_prefix}: claim {chr(65 + k)}",
                supersedes=mid, caused_by=rvid, actor_id=actor,
                when=at - timedelta(days=2),
            ))
    elif kind == "merge":
        m1, m2 = ids.next(), ids.next()
        originals.append(rel(m1, "claim_group", subjects[0], "inferred",
                              "field_inference", f"{title_prefix}: claim 1"))
        originals.append(rel(m2, "claim_group", subjects[1], "inferred",
                              "field_inference", f"{title_prefix}: claim 2"))
        rv1 = ids.next()
        rv2 = ids.next()
        group = str(ids.next())
        reviews.append(rev(rv1, "merge", m1, at - timedelta(days=2),
                            {"merge_group": group}))
        reviews.append(rev(rv2, "merge", m2, at - timedelta(days=2),
                            {"merge_group": group}))
        replacements.append(rel(
            ids.next(), "claim_group", subjects[2], "explicit", "human",
            f"{title_prefix}: merged claim",
            supersedes=m1, caused_by=rv1, actor_id=actor,
            when=at - timedelta(days=2),
        ))
    elif kind == "bare_provisional":
        mid = ids.next()
        originals.append(rel(mid, "unanswered_question", subjects[0], "inferred",
                              "field_inference", f"{title_prefix}: open question"))
    elif kind == "bare_explicit":
        mid = ids.next()
        originals.append(rel(mid, "candidate_synthesis", subjects[0], "explicit",
                              "human", f"{title_prefix}: proposed synthesis",
                              actor_id=actor))
    else:
        raise ValueError(f"unknown kit kind: {kind}")

    return originals, reviews, replacements


KIT_CYCLE = ("confirm", "contest", "correct", "split", "merge")

# How many distinct subject messages each kit consumes — the caller uses
# this to hand every kit a disjoint slice of the room's subject pool.
KIT_SUBJECT_DEMAND = {
    "confirm": 1, "contest": 2, "correct": 2, "split": 3, "merge": 3,
}


async def _cleanup(conn: asyncpg.Connection) -> None:
    """Delete every row this script could have written, by deterministic id,
    child-to-parent. Never touches the Home room, its Main thread or its
    bootstrap events — those are migration 013's, looked up, not owned."""
    room_ids = SEED_ROOM_IDS
    user_ids = SEED_USER_IDS
    await conn.execute("DELETE FROM field_marks WHERE room_id = ANY($1::uuid[])", room_ids)
    await conn.execute(
        "DELETE FROM memory_references WHERE target_room_id = ANY($1::uuid[]) "
        "OR source_memory_id IN (SELECT id FROM memories WHERE room_id = ANY($1::uuid[]))",
        room_ids,
    )
    await conn.execute("DELETE FROM commitments WHERE room_id = ANY($1::uuid[])", room_ids)
    await conn.execute("DELETE FROM reading_items WHERE room_id = ANY($1::uuid[])", room_ids)
    await conn.execute("DELETE FROM memories WHERE room_id = ANY($1::uuid[])", room_ids)
    await conn.execute(
        "DELETE FROM messages WHERE thread_id IN "
        "(SELECT id FROM threads WHERE room_id = ANY($1::uuid[]))",
        room_ids,
    )
    await conn.execute("DELETE FROM threads WHERE room_id = ANY($1::uuid[])", room_ids)
    await conn.execute(
        "DELETE FROM room_memberships WHERE room_id = ANY($1::uuid[]) OR user_id = ANY($2::uuid[])",
        room_ids, user_ids,
    )
    await conn.execute("DELETE FROM rooms WHERE id = ANY($1::uuid[])", room_ids)
    await conn.execute("DELETE FROM events WHERE room_id = ANY($1::uuid[])", room_ids)
    await conn.execute("DELETE FROM user_sessions WHERE user_id = ANY($1::uuid[])", user_ids)
    await conn.execute("DELETE FROM verification_codes WHERE user_id = ANY($1::uuid[])", user_ids)
    await conn.execute("DELETE FROM user_credentials WHERE user_id = ANY($1::uuid[])", user_ids)
    await conn.execute("DELETE FROM users WHERE id = ANY($1::uuid[])", user_ids)


async def seed(conn: asyncpg.Connection) -> dict:
    counts: dict[str, int] = {}
    await _cleanup(conn)

    # --- users -----------------------------------------------------------
    now = datetime.now(timezone.utc)
    for uid, name in ((USER_A_ID, USER_A_NAME), (USER_B_ID, USER_B_NAME)):
        await conn.execute(
            "INSERT INTO users (id, created_at, display_name) VALUES ($1,$2,$3)",
            uid, _d(60), name,
        )
    for uid, email, pw in (
        (USER_A_ID, USER_A_EMAIL, USER_A_PASSWORD),
        (USER_B_ID, USER_B_EMAIL, USER_B_PASSWORD),
    ):
        await conn.execute(
            """INSERT INTO user_credentials
                   (user_id, email, email_verified, password_hash, created_at, updated_at)
               VALUES ($1,$2,TRUE,$3,$4,$4)""",
            uid, email, get_password_hash(pw), now,
        )
    counts["users"] = 2

    # --- Home membership: the one is_home room migration 013 bootstraps --
    home_id = await conn.fetchval("SELECT id FROM rooms WHERE is_home")
    if home_id is None:
        raise RuntimeError(
            "no is_home room found — apply migrations/013_home_base.sql first"
        )
    for uid in SEED_USER_IDS:
        await conn.execute(
            """INSERT INTO room_memberships (room_id, user_id, joined_at, can_manage_home)
               VALUES ($1,$2,$3,TRUE)
               ON CONFLICT (room_id, user_id) DO NOTHING""",
            home_id, uid, _d(60),
        )

    # --- rooms + threads + memberships ------------------------------------
    room_rows, thread_rows, membership_rows = [], [], []
    branch_of: dict[int, UUID] = {}
    main_of: dict[int, UUID] = {}
    for i in range(N_ROOMS):
        room_id = SEED_ROOM_IDS[i]
        name = f"Seed Room {i:03d}"
        if i == AMO_SENTINEL_ROOM_INDEX:
            name = f"{AMO_SENTINEL} Room {i:03d}"
        elif i == DAN_SENTINEL_ROOM_INDEX:
            name = f"{DAN_SENTINEL} Room {i:03d}"
        room_rows.append((room_id, _d(45), f"seed-room-token-{i:03d}", name))
        main_id = _uid(NS_THREAD_MAIN + i)
        main_of[i] = main_id
        thread_rows.append((main_id, room_id, _d(45), None, "Main"))
        if has_branch(i):
            branch_id = _uid(NS_THREAD_BRANCH + i)
            branch_of[i] = branch_id
            thread_rows.append((branch_id, room_id, _d(20), main_id, "A branch"))
        for uid in room_members(i):
            membership_rows.append((room_id, uid, _d(45)))

    await conn.executemany(
        "INSERT INTO rooms (id, created_at, token, name) VALUES ($1,$2,$3,$4)",
        room_rows,
    )
    await conn.executemany(
        "INSERT INTO threads (id, room_id, created_at, parent_thread_id, title) "
        "VALUES ($1,$2,$3,$4,$5)",
        thread_rows,
    )
    await conn.executemany(
        "INSERT INTO room_memberships (room_id, user_id, joined_at) VALUES ($1,$2,$3)",
        membership_rows,
    )
    counts["rooms"] = len(room_rows)
    counts["threads"] = len(thread_rows)
    counts["room_memberships"] = len(membership_rows)

    # --- messages ----------------------------------------------------------
    message_rows = []
    room_message_ids: dict[int, list[UUID]] = {i: [] for i in range(N_ROOMS)}
    main_seq: dict[int, int] = {i: 0 for i in range(N_ROOMS)}
    branch_seq: dict[int, int] = {i: 0 for i in range(N_ROOMS)}
    for i in range(N_ROOMS):
        members = room_members(i)
        count = n_messages(i)
        at0 = _d(40)
        for j in range(count):
            mid = _uid(NS_MESSAGE + i * 1000 + j)
            room_message_ids[i].append(mid)
            speaker_human = (j % 3 != 0)
            if speaker_human:
                speaker_type = "human"
                user_id = members[j % len(members)]
            else:
                speaker_type = "llm_primary"
                user_id = None
            use_branch = i in branch_of and (j % 5 == 4)
            thread_id = branch_of[i] if use_branch else main_of[i]
            if use_branch:
                branch_seq[i] += 1
                seq = branch_seq[i]
            else:
                main_seq[i] += 1
                seq = main_seq[i]
            content = (
                f"Seed message {j} in room {i:03d}: does the evidence still "
                f"support the working position, or has something shifted?"
                if j % 4 == 3 else
                f"Seed message {j} in room {i:03d}: noting a data point worth "
                f"tracking against the thesis."
            )
            mtype = "question" if content.rstrip().endswith("?") else "text"
            created_at = at0 - timedelta(hours=count - j)
            metadata = None
            if has_brief(i) and j == count - 1:
                content = (
                    f"Research brief for room {i:03d}\n\n"
                    f"Findings: the seeded position holds under the tracked evidence."
                )
                mtype = "text"
                metadata = json.dumps({"source": "deep_dive"})
            message_rows.append((
                mid, thread_id, seq, created_at, speaker_type, user_id,
                mtype, content, metadata,
            ))
    await conn.executemany(
        """INSERT INTO messages
               (id, thread_id, sequence, created_at, speaker_type, user_id,
                message_type, content, is_deleted, metadata)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,false,$9::jsonb)""",
        message_rows,
    )
    counts["messages"] = len(message_rows)

    # --- memories, with real supersession chains ---------------------------
    # Two-pass: insert every memory active/unsuperseded first (so no row
    # forward-references one that doesn't exist yet), then a second pass
    # flips the superseded members of each chain — the same reason
    # migrations order DDL before data.
    memory_insert_rows = []
    memory_update_rows = []
    for i in range(N_ROOMS):
        count = n_memories(i)
        chain_ids = [_uid(NS_MEMORY + i * 100 + j) for j in range(count)]
        for j, mid in enumerate(chain_ids):
            at = _d(35) + timedelta(hours=j)
            memory_insert_rows.append((
                mid, SEED_ROOM_IDS[i], at, at, "room",
                f"seed-fact-{i:03d}-{j:03d}",
                f"Seed memory {j} for room {i:03d}: a working fact the room holds.",
                "active",
            ))
        # Chain rule: within each room's list, every run of up to 3
        # consecutive memories forms one supersession chain (oldest first);
        # the chain's non-last members get superseded_by pointing forward.
        for j in range(count):
            if j % 3 != 2 and j + 1 < count and (j + 1) % 3 != 0:
                successor = chain_ids[j + 1]
                superseded_at = _d(35) + timedelta(hours=j + 1)
                reason = (
                    "Seed-marked conflict for the contradiction-proxy edge"
                    if (i + j) % 10 == 0 else None
                )
                memory_update_rows.append(
                    (chain_ids[j], successor, superseded_at, reason, SEED_ROOM_IDS[i])
                )

    await conn.executemany(
        """INSERT INTO memories (id, room_id, created_at, updated_at, scope, key,
               content, status)
           VALUES ($1,$2,$3,$3,$4,$5,$6,$7)""",
        [(r[0], r[1], r[2], r[4], r[5], r[6], r[7]) for r in memory_insert_rows],
    )
    if memory_update_rows:
        await conn.executemany(
            """UPDATE memories SET status = 'superseded', superseded_by_memory_id = $2,
                   superseded_at = $3, invalidation_reason = $4
               WHERE id = $1""",
            [(r[0], r[1], r[2], r[3]) for r in memory_update_rows],
        )
    counts["memories"] = len(memory_insert_rows)
    counts["memories_superseded"] = len(memory_update_rows)

    # --- readings + memory twins (llm.reading._reading_key — §2 item 4) ---
    reading_rows, twin_rows = [], []
    for i in range(N_ROOMS):
        count = n_readings(i)
        msgs = room_message_ids[i]
        for j in range(count):
            rid = _uid(NS_READING + i * 100 + j)
            url = f"https://seed.example.test/room-{i:03d}/article-{j:03d}"
            title = f"Seed Article {j:03d} for Room {i:03d}"
            site = "seed.example.test"
            summary = f"What article {j:03d} said, distilled for room {i:03d}."
            content = f"Full body of seed article {j:03d} for room {i:03d}. " * 8
            at = _d(30) + timedelta(hours=j)
            source_message_id = msgs[j % len(msgs)] if msgs else None
            reading_rows.append((
                rid, SEED_ROOM_IDS[i], url, title, site, content, summary,
                "proposal", source_message_id, at,
            ))
            twin_key = _reading_key({"url": url, "title": title})
            twin_id = _uid(NS_READING_TWIN + i * 100 + j)
            twin_rows.append((
                twin_id, SEED_ROOM_IDS[i], at, at, "llm", twin_key,
                f"{summary} — {site}", "active",
            ))
    await conn.executemany(
        """INSERT INTO reading_items
               (id, room_id, url, title, site, content, summary, source,
                source_message_id, created_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
        reading_rows,
    )
    await conn.executemany(
        """INSERT INTO memories (id, room_id, created_at, updated_at, scope, key,
               content, status)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
        twin_rows,
    )
    counts["reading_items"] = len(reading_rows)
    counts["reading_twins"] = len(twin_rows)

    # --- commitments ---------------------------------------------------
    commitment_rows = []
    for i in range(N_ROOMS):
        count = n_commitments(i)
        for j in range(count):
            cid = _uid(NS_COMMITMENT + i * 10 + j)
            active = (j % 2 == 0)
            status = "active" if active else "resolved"
            deadline = _d(0) + timedelta(hours=(i + j) % 48) - timedelta(days=45)
            resolved_at = None if active else _d(1)
            resolution = None if active else "correct"
            commitment_rows.append((
                cid, SEED_ROOM_IDS[i], main_of[i],
                f"Seed commitment {j} for room {i:03d} resolves by its deadline",
                "flat", "commitment", _d(38), deadline, status,
                resolved_at, resolution,
            ))
    await conn.executemany(
        """INSERT INTO commitments
               (id, room_id, thread_id, claim, resolution_criteria, category,
                created_at, deadline, status, resolved_at, resolution)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""",
        commitment_rows,
    )
    counts["commitments"] = len(commitment_rows)

    # --- field_marks: lineage kits, three FK-safe phases across ALL rooms --
    all_originals, all_reviews, all_replacements = [], [], []
    for i in range(N_ROOMS):
        thread_id = main_of[i]
        msgs = room_message_ids[i]
        pool_size = 24
        subjects = [_subj(msgs[k % len(msgs)]) for k in range(pool_size)] if msgs else [
            _subj(_uid(NS_MESSAGE + i * 1000))
        ] * pool_size
        actor = room_members(i)[0]
        ids = RoomFieldIds(i)
        at = _d(15)
        kinds = list(KIT_CYCLE) if i == HEAVY_ROOM_INDEX else [KIT_CYCLE[i % len(KIT_CYCLE)]]
        # Each kit type draws a DISJOINT slice of the room's subject pool,
        # sized to its own demand — never a shared rotation. Two kit types
        # share a relation name (split/merge both use claim_group), and the
        # dedup unique index is keyed on (room_id, relation, subjects); any
        # overlap there is a UniqueViolation the moment both run in the same
        # room (HEAVY_ROOM runs all five kits at once).
        offset = 0
        for kind in kinds:
            demand = KIT_SUBJECT_DEMAND[kind]
            slice_ = subjects[offset:offset + demand]
            offset += demand
            o, r, p = build_field_kit(kind, SEED_ROOM_IDS[i], thread_id, slice_,
                                       actor, at, ids, f"Room {i:03d}")
            all_originals += o
            all_reviews += r
            all_replacements += p
        extra_provisional = 5 if i == HEAVY_ROOM_INDEX else 1
        for k in range(extra_provisional):
            o, _, _ = build_field_kit(
                "bare_provisional", SEED_ROOM_IDS[i], thread_id,
                [subjects[offset]], actor, at, ids, f"Room {i:03d} #{k}",
            )
            offset += 1
            all_originals += o
        o, _, _ = build_field_kit(
            "bare_explicit", SEED_ROOM_IDS[i], thread_id,
            [subjects[offset]], actor, at, ids, f"Room {i:03d}",
        )
        all_originals += o

    await conn.executemany(_RELATION_SQL, all_originals)
    await conn.executemany(_REVIEW_SQL, all_reviews)
    await conn.executemany(_RELATION_SQL, all_replacements)
    counts["field_marks"] = len(all_originals) + len(all_reviews) + len(all_replacements)
    counts["field_marks_relations"] = len(all_originals) + len(all_replacements)
    counts["field_marks_reviews"] = len(all_reviews)

    # --- echo references (memory_references) — cross-room citations within
    # Amo's own membership set (rooms 0-39), so the edge is visible in his
    # Atlas without also needing to reason about Dan's narrower fence -------
    echo_rows = []
    k = 0
    for i in range(0, 39, 3):
        j = i + 1
        source_memory = _uid(NS_MEMORY + i * 100)  # room i's first memory
        eid = _uid(NS_ECHO + k)
        echo_rows.append((
            eid, source_memory, SEED_ROOM_IDS[j], main_of[j], None,
            _d(10) + timedelta(hours=k), USER_A_ID, True,
            f"Echoed from room {i:03d} while discussing room {j:03d}",
        ))
        k += 1
    await conn.executemany(
        """INSERT INTO memory_references
               (id, source_memory_id, target_room_id, target_thread_id,
                target_message_id, referenced_at, referenced_by_user_id,
                referenced_by_llm, citation_context)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
        echo_rows,
    )
    counts["memory_references"] = len(echo_rows)

    # --- events: room/thread bootstrap + one per supersession + one per
    # commitment, so workspace_objects.py's Record union (messages UNION
    # events) has a real event half to project, not just messages ----------
    event_rows = []
    k = 0
    for i in range(N_ROOMS):
        event_rows.append((_uid(NS_EVENT + k), _d(45), "room_created",
                            SEED_ROOM_IDS[i], None, {"name": f"Seed Room {i:03d}"}))
        k += 1
        event_rows.append((_uid(NS_EVENT + k), _d(45), "thread_created",
                            SEED_ROOM_IDS[i], main_of[i], {"title": "Main"}))
        k += 1
    for row in memory_update_rows:
        original_id, successor_id, superseded_at, _reason, room_id = row
        event_rows.append((
            _uid(NS_EVENT + k), superseded_at, "memory_superseded", room_id, None,
            {"memory_id": str(original_id), "superseded_by": str(successor_id)},
        ))
        k += 1
    for row in commitment_rows:
        cid, room_id = row[0], row[1]
        event_rows.append((
            _uid(NS_EVENT + k), _d(38), "commitment_created", room_id, None,
            {"commitment_id": str(cid)},
        ))
        k += 1
    await conn.executemany(
        """INSERT INTO events (id, timestamp, event_type, room_id, thread_id, payload)
           VALUES ($1,$2,$3,$4,$5,$6::jsonb)""",
        [(e[0], e[1], e[2], e[3], e[4], json.dumps(e[5])) for e in event_rows],
    )
    counts["events"] = len(event_rows)

    return counts


async def verify(conn: asyncpg.Connection) -> list[str]:
    """Post-seed smoke check, run against the real service classes — not a
    second reimplementation of what they should return (§5.7's own
    verification list): field projection of the heaviest room returns marks
    with derived review states, and Atlas fences the two seeded users by
    value (the sentinel pattern), with no cross-fence leakage."""
    findings = []

    from atlas_objects import AtlasService
    from field_marks import FieldMarkService

    heavy_room_id = SEED_ROOM_IDS[HEAVY_ROOM_INDEX]
    field_proj = await FieldMarkService(conn).build(heavy_room_id)
    review_states = {m.review for m in field_proj.marks}
    findings.append(
        f"field projection (heaviest room, {len(field_proj.marks)} marks): "
        f"review states present = {sorted(review_states)}"
    )
    expected = {"provisional", "confirmed", "contested", "superseded"}
    if not expected.issubset(review_states):
        findings.append(f"  MISSING review states: {expected - review_states}")

    async with conn.transaction():
        atlas_a = await AtlasService(conn).build(USER_A_ID)
    async with conn.transaction():
        atlas_b = await AtlasService(conn).build(USER_B_ID)

    titles_a = {n.title for n in atlas_a.nodes}
    titles_b = {n.title for n in atlas_b.nodes}
    a_sees_own = any(AMO_SENTINEL in t for t in titles_a)
    a_sees_other = any(DAN_SENTINEL in t for t in titles_a)
    b_sees_own = any(DAN_SENTINEL in t for t in titles_b)
    b_sees_other = any(AMO_SENTINEL in t for t in titles_b)
    findings.append(
        f"atlas fence — Amo: {len(atlas_a.nodes)} nodes/{len(atlas_a.edges)} edges, "
        f"sees own sentinel={a_sees_own}, sees Dan's sentinel={a_sees_other}"
    )
    findings.append(
        f"atlas fence — Dan: {len(atlas_b.nodes)} nodes/{len(atlas_b.edges)} edges, "
        f"sees own sentinel={b_sees_own}, sees Amo's sentinel={b_sees_other}"
    )
    if not (a_sees_own and b_sees_own):
        findings.append("  FAIL: a user cannot see their own sentinel room")
    if a_sees_other or b_sees_other:
        findings.append("  FAIL: cross-fence leakage — a user sees the other's sentinel")
    return findings


async def main() -> None:
    conn = await asyncpg.connect(SEED_DATABASE_URL)
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
        )
    try:
        counts = await seed(conn)
        print("=== seed_release3: row counts ===")
        for k, v in counts.items():
            print(f"  {k}: {v}")
        print()
        print("=== seed_release3: smoke check ===")
        for line in await verify(conn):
            print(f"  {line}")
        print()
        print(f"users: A={USER_A_EMAIL} ({USER_A_ID}), B={USER_B_EMAIL} ({USER_B_ID})")
        print(f"heavy room: {SEED_ROOM_IDS[HEAVY_ROOM_INDEX]}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
