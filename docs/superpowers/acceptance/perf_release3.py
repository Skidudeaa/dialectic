"""
perf_release3.py — Release 3 performance measurement against the seed-scale
database (PLAN.md §5.7 / §7.5 / TG-G).

Runs END TO END: starts an isolated backend on :8014 against `dialectic_seed`
(never `dialectic`, never `dialectic_browser` — sibling TG-F has exclusive use
of that fixture while this build is in flight), waits for it to actually
answer (not just "unit active" — §7.2's warm-up trap), warms it up, times
four endpoints across two full passes, writes
`perf_release3_results.md`, and stops the backend BY PID after confirming
`/proc/<pid>/cwd` is this worktree's `dialectic/` — never a bare `pkill`,
which would just as happily hit the production unit (same script name).

Run with the SAME interpreter production uses (CLAUDE.md's documented trap:
a bare `python3` on this box resolves into an unrelated project's venv):

    cd /root/DwoodAmo/dialectic
    /usr/bin/python3 ../docs/superpowers/acceptance/perf_release3.py

Requires `docs/superpowers/acceptance/seed_release3.py` to have already been
run against the same SEED_DATABASE_URL.
"""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

import asyncpg

_ACCEPTANCE_DIR = os.path.dirname(os.path.abspath(__file__))
if _ACCEPTANCE_DIR not in sys.path:
    sys.path.insert(0, _ACCEPTANCE_DIR)

# Reuses the seed script's own constants — one definition of the fixture
# credentials, not two copies that can drift (CLAUDE.md's "prompt exists in
# several copies" trap, applied to test fixtures).
from seed_release3 import (  # noqa: E402
    SEED_DATABASE_URL,
    USER_A_EMAIL,
    USER_A_PASSWORD,
    USER_B_EMAIL,
    USER_B_PASSWORD,
)

DIALECTIC_DIR = os.path.abspath(os.path.join(_ACCEPTANCE_DIR, "..", "..", "..", "dialectic"))
RESULTS_PATH = os.path.join(_ACCEPTANCE_DIR, "perf_release3_results.md")
BACKEND_LOG_PATH = "/tmp/perf_release3_backend.log"

PORT = int(os.environ.get("PERF_RELEASE3_PORT", "8014"))
BASE = f"http://localhost:{PORT}"
TARGET_MS = 150.0
WARMUP_N = 20
SAMPLE_N = 100

CREDS = {USER_A_EMAIL: USER_A_PASSWORD, USER_B_EMAIL: USER_B_PASSWORD}


# ------------------------------------------------------------------ HTTP ---

def _http(method, url, headers=None, body=None, timeout=10):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            status = resp.status
    except urllib.error.HTTPError as e:
        payload = e.read()
        status = e.code
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return status, payload, elapsed_ms


def wait_for_health(timeout_s=60):
    deadline = time.time() + timeout_s
    last_err = None
    while time.time() < deadline:
        try:
            status, payload, _ = _http("GET", f"{BASE}/health", timeout=3)
            if status == 200:
                body = json.loads(payload or b"{}")
                if body.get("status") == "ok":
                    return True
            last_err = f"status={status} body={payload[:200]!r}"
        except Exception as e:  # noqa: BLE001 — polling loop, any failure just retries
            last_err = repr(e)
        time.sleep(0.5)
    raise RuntimeError(f"backend never became healthy on {BASE}: {last_err}")


def login(email, password):
    status, payload, _ = _http(
        "POST", f"{BASE}/auth/login",
        headers={"Content-Type": "application/json"},
        body={"email": email, "password": password},
    )
    if status != 200:
        raise RuntimeError(f"login failed for {email}: {status} {payload[:300]!r}")
    return json.loads(payload)["access_token"]


def percentile(sorted_vals, p):
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f, c = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def measure(label, url, headers, n):
    latencies = []
    errors = []
    for i in range(n):
        status, payload, ms = _http("GET", url, headers=headers)
        if status != 200:
            errors.append((i, status, payload[:200]))
        latencies.append(ms)
    latencies.sort()
    return {
        "label": label,
        "n": n,
        "errors": errors,
        "p50": percentile(latencies, 50),
        "p95": percentile(latencies, 95),
        "max": latencies[-1] if latencies else float("nan"),
        "min": latencies[0] if latencies else float("nan"),
    }


# --------------------------------------------------------------- backend ---

def start_backend():
    env = os.environ.copy()
    env.update({
        "DATABASE_URL": SEED_DATABASE_URL,
        "PORT": str(PORT),
        "HOST": "127.0.0.1",
        "SCHEDULER_ENABLED": "0",
        "ANTHROPIC_API_KEY": "seed-fixture-dummy-key",
        "JWT_SECRET_KEY": "browser-scene-kernel-secret-32-bytes-minimum",
        "SIGNUPS_ENABLED": "1",
    })
    log_file = open(BACKEND_LOG_PATH, "w")
    proc = subprocess.Popen(
        ["/usr/bin/python3", "run.py"],
        cwd=DIALECTIC_DIR, env=env, stdout=log_file, stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return proc, log_file


def stop_backend(proc, log_file):
    """PID-safe teardown (§7.1/§7.2): confirm /proc/<pid>/cwd is THIS
    worktree's dialectic/ before sending any signal — never a bare pkill,
    which matches the production unit's `python3 run.py` just as well."""
    pid = proc.pid
    try:
        real_cwd = os.readlink(f"/proc/{pid}/cwd")
    except OSError as e:
        print(f"teardown: cannot read /proc/{pid}/cwd ({e}); leaving process alone")
        return False
    if os.path.normpath(real_cwd) != os.path.normpath(DIALECTIC_DIR):
        print(
            f"REFUSING to stop pid {pid}: cwd={real_cwd!r} != {DIALECTIC_DIR!r} "
            f"— this is not the process we started"
        )
        return False
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, signal.SIGTERM)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(pgid, signal.SIGKILL)
            proc.wait(timeout=5)
    except ProcessLookupError:
        pass
    finally:
        log_file.close()
    return True


def port_is_free(port):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) != 0


# --------------------------------------------------------------- diagnostics

async def _diagnostics():
    """Everything that reads dialectic_seed directly (never through HTTP):
    picks the heaviest room + the user with the most memberships, snapshots
    row counts for the results file's "seed parameters" section, and profiles
    the specific prior suspect flagged at build time — atlas_objects.py's
    "unresolved work" loop, which calls FieldMarkService.build() once PER
    ELIGIBLE ROOM rather than one UNIONed statement. This times that loop
    directly against the same connection AtlasService would use, so the
    finding is a real measurement, not a guess from reading the code.
    """
    conn = await asyncpg.connect(SEED_DATABASE_URL)
    for typename in ("jsonb", "json"):
        await conn.set_type_codec(
            typename, encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
        )
    try:
        room = await conn.fetchrow(
            """
            WITH weighted AS (
                SELECT r.id, r.token,
                       (SELECT count(*) FROM messages m JOIN threads t ON t.id = m.thread_id
                         WHERE t.room_id = r.id) AS msgs,
                       (SELECT count(*) FROM field_marks fm WHERE fm.room_id = r.id) AS marks
                FROM rooms r WHERE NOT r.is_home
            )
            SELECT id, token, msgs, marks FROM weighted
            ORDER BY msgs + marks DESC LIMIT 1
            """
        )
        top_user = await conn.fetchrow(
            """
            SELECT rm.user_id, count(*) AS c
            FROM room_memberships rm JOIN rooms r ON r.id = rm.room_id
            WHERE NOT r.is_home
            GROUP BY rm.user_id ORDER BY c DESC LIMIT 1
            """
        )
        email_row = await conn.fetchrow(
            "SELECT email FROM user_credentials WHERE user_id = $1", top_user["user_id"],
        )

        counts = {}
        for tbl in (
            "rooms", "threads", "messages", "memories", "reading_items",
            "field_marks", "commitments", "memory_references", "room_memberships",
            "events",
        ):
            counts[tbl] = await conn.fetchval(f"SELECT count(*) FROM {tbl}")

        # --- the flagged suspect: atlas_objects.AtlasService's per-room
        # FieldMarkService.build() loop for "unresolved work" -------------
        from atlas_objects import _ELIGIBLE_ROOMS_SQL, _ATLAS_ROOM_CAP, AtlasService
        from field_marks import FieldMarkService

        eligible = await conn.fetch(_ELIGIBLE_ROOMS_SQL, top_user["user_id"], _ATLAS_ROOM_CAP)
        eligible_room_ids = [r["room_id"] for r in eligible]

        t0 = time.perf_counter()
        async with conn.transaction():
            await AtlasService(conn)._build(top_user["user_id"])  # noqa: SLF001 — profiling, not production code
        atlas_total_ms = (time.perf_counter() - t0) * 1000.0

        loop_start = time.perf_counter()
        for room_id in eligible_room_ids:
            await FieldMarkService(conn).build(room_id)
        loop_ms = (time.perf_counter() - loop_start) * 1000.0

        diag = {
            "eligible_rooms": len(eligible_room_ids),
            "atlas_build_direct_ms": atlas_total_ms,
            "unresolved_work_loop_ms": loop_ms,
            "unresolved_work_loop_pct": (
                (loop_ms / atlas_total_ms * 100.0) if atlas_total_ms else float("nan")
            ),
            "per_room_avg_ms": (loop_ms / len(eligible_room_ids)) if eligible_room_ids else 0.0,
        }

        return {
            "heavy_room_id": str(room["id"]),
            "heavy_room_token": room["token"],
            "heavy_room_msgs": room["msgs"],
            "heavy_room_marks": room["marks"],
            "top_user_id": str(top_user["user_id"]),
            "top_user_email": email_row["email"],
            "top_user_memberships": top_user["c"],
            "counts": counts,
            "diag": diag,
        }
    finally:
        await conn.close()


def run_diagnostics():
    return asyncio.run(_diagnostics())


# --------------------------------------------------------------- reporting

def fmt(ms):
    return f"{ms:.1f}" if ms == ms else "n/a"  # NaN != NaN


def write_results(meta, endpoints_by_pass, warmup_stats, load_before, load_after):
    lines = []
    lines.append("# Release 3 performance — TG-G reference run")
    lines.append("")
    lines.append(f"Recorded {datetime.now(timezone.utc).isoformat()} against a dedicated "
                  f"`dialectic_seed` database (never `dialectic`, never `dialectic_browser`), "
                  f"backend on :{PORT}, `SCHEDULER_ENABLED=0`. Interpreter: `/usr/bin/python3` "
                  f"(the same one `dialectic.service`'s `ExecStart` uses — a bare `python3` on "
                  f"this box resolves into an unrelated project's venv).")
    lines.append("")
    lines.append("## Seed parameters (§5.7)")
    lines.append("")
    lines.append("Generated by `seed_release3.py`, re-observed from the database at "
                  "measurement time (not the script's own claimed counts):")
    lines.append("")
    lines.append("| table | rows |")
    lines.append("|---|---:|")
    for tbl, n in meta["counts"].items():
        lines.append(f"| {tbl} | {n} |")
    lines.append("")
    lines.append(
        f"- Deterministic UUIDs / frozen timestamps: the `_uid(n)`/`_d(days)` idiom from "
        f"`tests/test_workspace_objects_pg.py`, relative to a fixed `BASE` "
        f"(2026-08-12 12:00 UTC).\n"
        f"- Two users, overlapping-but-different memberships: Amo (rooms 0-39, 40 total) "
        f"and Dan (rooms 20-49, 30 total); 20 rooms shared.\n"
        f"- Heaviest seeded room (used for the two room-scoped endpoints below): "
        f"`{meta['heavy_room_id']}` — {meta['heavy_room_msgs']} messages, "
        f"{meta['heavy_room_marks']} field_marks.\n"
        f"- User with the most memberships (used for Atlas + Home activity below): "
        f"`{meta['top_user_email']}` — {meta['top_user_memberships']} memberships."
    )
    lines.append("")
    lines.append("## Warm-up protocol (§7.2's trap)")
    lines.append("")
    lines.append(
        f"1. Backend started, polled `/health` to a real 200 (`status=\"ok\"`), not just "
        f"`systemctl`-style liveness.\n"
        f"2. {WARMUP_N} throwaway requests per endpoint, discarded (pool warm-up, uvicorn "
        f"reload-mode JIT, OS file cache).\n"
        f"3. Two full {SAMPLE_N}-request timed passes per endpoint. Pass 1 is reported for "
        f"comparison; **pass 2 is the reference reading** (§7.2: \"a performance probe right "
        f"after process start measures warm-up, not code — prefer the second reading\")."
    )
    lines.append("")
    lines.append(f"Box load average (1-min) before measurement: {load_before:.2f}; "
                  f"after: {load_after:.2f}. CPUs: {os.cpu_count()}.")
    lines.append("")
    lines.append(f"## Results — p50 / p95 / max vs the {TARGET_MS:.0f} ms design target")
    lines.append("")
    lines.append("House measured p95 ~= 51 ms at Release 1 seed scale (reference point; "
                  "not to be regressed blindly).")
    lines.append("")
    for pass_idx, results in enumerate(endpoints_by_pass, start=1):
        lines.append(f"### Pass {pass_idx}{' (reference)' if pass_idx == len(endpoints_by_pass) else ''}")
        lines.append("")
        lines.append("| endpoint | n | p50 (ms) | p95 (ms) | max (ms) | min (ms) | errors | vs target |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---|")
        for r in results:
            verdict = "OK" if r["p95"] <= TARGET_MS else "MISS"
            lines.append(
                f"| {r['label']} | {r['n']} | {fmt(r['p50'])} | {fmt(r['p95'])} | "
                f"{fmt(r['max'])} | {fmt(r['min'])} | {len(r['errors'])} | {verdict} |"
            )
        lines.append("")

    misses = [r for r in endpoints_by_pass[-1] if r["p95"] > TARGET_MS]
    lines.append("## Analysis")
    lines.append("")
    if not misses:
        lines.append("All four endpoints meet the 150 ms p95 target on the reference pass "
                      "at this seed scale.")
    else:
        lines.append("Missed the target on the reference pass: "
                      + ", ".join(f"**{r['label']}** (p95 {fmt(r['p95'])} ms)" for r in misses))
    lines.append("")
    diag = meta["diag"]
    lines.append("### Profiling the flagged prior suspect")
    lines.append("")
    lines.append(
        "`atlas_objects.AtlasService._build()`'s \"unresolved work\" section builds one "
        "`FieldMarkService.build(room_id)` call **per eligible room** rather than a single "
        "UNIONed statement (`atlas_objects.py`, module docstring + the loop around line 511). "
        "Timed directly against the same seed-scale connection AtlasService itself uses "
        "(not through HTTP, so this isolates DB + Python cost from network/uvicorn overhead):"
    )
    lines.append("")
    lines.append(f"- Eligible rooms for `{meta['top_user_email']}`: **{diag['eligible_rooms']}**")
    lines.append(f"- Full `AtlasService._build()` (direct DB call): **{fmt(diag['atlas_build_direct_ms'])} ms**")
    lines.append(
        f"- The per-room `FieldMarkService.build()` loop alone: "
        f"**{fmt(diag['unresolved_work_loop_ms'])} ms** "
        f"({diag['unresolved_work_loop_pct']:.1f}% of the total), "
        f"~{fmt(diag['per_room_avg_ms'])} ms/room"
    )
    lines.append("")
    if diag["unresolved_work_loop_pct"] > 30:
        lines.append(
            "That loop is a substantial share of Atlas's own cost at this membership scale "
            "(40 eligible rooms for the heaviest-membership user) — each iteration is a full "
            "`field_marks` fetch capped at 500 rows, fenced and re-derived from scratch, for "
            "every room the caller belongs to, on every Atlas load. It does not, on its own, "
            "explain a target miss if Atlas otherwise meets the target (see the pass-2 table "
            "above), but it is the mechanism to revisit first if Atlas's p95 regresses as "
            "membership counts grow — a single UNIONed, per-partition-capped statement (the "
            "house pattern §1.6 already uses everywhere else in this module) would turn N "
            "round trips into one."
        )
    else:
        lines.append(
            "At this seed scale the loop is a minor share of Atlas's total cost — not the "
            "dominant factor in the numbers above. It remains a structural N+1 (round trips "
            "scale with the caller's membership count, not with a bounded page size) and is "
            "worth flagging forward rather than tuning blind against today's numbers."
        )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- Sequential requests, single client, localhost — measures server-side latency, "
        "not concurrent load.\n"
        "- The heaviest room and the top-membership user are picked dynamically by querying "
        "the seeded database at measurement time, not hardcoded — reruns after reseeding "
        "stay correct.\n"
        f"- Backend log: `{BACKEND_LOG_PATH}`."
    )
    with open(RESULTS_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")
    return RESULTS_PATH


def main():
    print(f"[perf_release3] diagnostics against {SEED_DATABASE_URL} ...")
    meta = run_diagnostics()
    print(f"[perf_release3] heavy room={meta['heavy_room_id']} "
          f"({meta['heavy_room_msgs']} msgs, {meta['heavy_room_marks']} marks)")
    print(f"[perf_release3] top-membership user={meta['top_user_email']} "
          f"({meta['top_user_memberships']} memberships)")

    load_before = os.getloadavg()[0]
    proc, log_file = start_backend()
    try:
        print(f"[perf_release3] backend pid={proc.pid}, waiting for /health ...")
        wait_for_health()
        real_cwd = os.readlink(f"/proc/{proc.pid}/cwd")
        assert os.path.normpath(real_cwd) == os.path.normpath(DIALECTIC_DIR), (
            f"backend cwd {real_cwd!r} != {DIALECTIC_DIR!r} — refusing to proceed"
        )
        print(f"[perf_release3] healthy, cwd confirmed: {real_cwd}")

        token = login(meta["top_user_email"], CREDS[meta["top_user_email"]])
        headers_jwt = {"Authorization": f"Bearer {token}"}
        headers_room = {**headers_jwt, "X-Room-Token": meta["heavy_room_token"]}
        room_id = meta["heavy_room_id"]

        endpoints = [
            ("GET /rooms/{id}/workspace/objects",
             f"{BASE}/rooms/{room_id}/workspace/objects", headers_room),
            ("GET /rooms/{id}/field",
             f"{BASE}/rooms/{room_id}/field", headers_room),
            ("GET /users/me/atlas",
             f"{BASE}/users/me/atlas", headers_jwt),
            ("GET /users/me/home/activity",
             f"{BASE}/users/me/home/activity", headers_jwt),
        ]

        print("[perf_release3] settling 3s before warm-up ...")
        time.sleep(3)
        print(f"[perf_release3] warm-up: {WARMUP_N} requests/endpoint ...")
        for label, url, headers in endpoints:
            measure(label, url, headers, WARMUP_N)
        time.sleep(2)

        passes = []
        for pass_idx in (1, 2):
            print(f"[perf_release3] pass {pass_idx}: {SAMPLE_N} requests/endpoint ...")
            results = [measure(label, url, headers, SAMPLE_N) for label, url, headers in endpoints]
            for r in results:
                print(f"    {r['label']}: p50={fmt(r['p50'])}ms p95={fmt(r['p95'])}ms "
                      f"max={fmt(r['max'])}ms errors={len(r['errors'])}")
            passes.append(results)
            if pass_idx == 1:
                time.sleep(1)

        load_after = os.getloadavg()[0]
        path = write_results(meta, passes, None, load_before, load_after)
        print(f"[perf_release3] wrote {path}")
    finally:
        stopped = stop_backend(proc, log_file)
        print(f"[perf_release3] backend stopped: {stopped}")
        time.sleep(1)
        print(f"[perf_release3] port {PORT} free: {port_is_free(PORT)}")


if __name__ == "__main__":
    main()
