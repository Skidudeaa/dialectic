#!/usr/bin/env python3
"""
The Long Way house: a bounded end-to-end probe of the longway organ against the real database and the real repo.

    python3 deploy/longway_observe.py [--port 8014] [--keep]

Boots the backend from this tree with /etc/longway/longway.env (scheduler and workshop off, one worker, a spare
port), then as a synthetic house manager: reads /organ, resets a password from a seed-script code, logs in, creates
a room, binds it to ogasawara, reads the chart, the journey and the proposals, and removes every row it made. Writes
OMC_OBSERVATION_RESULT when that variable is set (the omc build observe contract) and prints the same JSON.

WHY a probe and not only tests: the tests prove the organ against fixtures; this proves the deployed shape, the
environment file, the database copied from Dialectic's live schema, migration 029 and the repo path, together.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DIALECTIC = HERE.parent
ENV_FILE = Path("/etc/longway/longway.env")


def load_env(port: int) -> dict:
    env = dict(os.environ)
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k] = v
    env.update(PORT=str(port), WEB_CONCURRENCY="1", SCHEDULER_ENABLED="0", DIALECTIC_WORKSHOP_ENABLED="0")
    env.pop("PRODUCTION", None)
    return env


def call(method: str, url: str, body: dict | None = None, token: str | None = None, room: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if room:
        req.add_header("X-Room-Token", room)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, raw.decode("utf-8", "replace")


async def cleanup(database_url: str, email: str, room_id: str | None) -> None:
    import asyncpg
    conn = await asyncpg.connect(database_url)
    try:
        user_id = await conn.fetchval("SELECT user_id FROM user_credentials WHERE email = $1", email)
        if room_id:
            for sql in ("DELETE FROM events WHERE room_id = $1", "DELETE FROM messages WHERE thread_id IN (SELECT id FROM threads WHERE room_id = $1)",
                        "DELETE FROM threads WHERE room_id = $1", "DELETE FROM room_memberships WHERE room_id = $1",
                        "DELETE FROM longway_evidence_proposals WHERE room_id = $1", "DELETE FROM longway_confirmations WHERE room_id = $1",
                        "DELETE FROM rooms WHERE id = $1"):
                try:
                    await conn.execute(sql, room_id)
                except asyncpg.UndefinedTableError:
                    pass
        if user_id:
            for sql in ("DELETE FROM verification_codes WHERE user_id = $1", "DELETE FROM user_sessions WHERE user_id = $1",
                        "DELETE FROM events WHERE user_id = $1", "DELETE FROM room_memberships WHERE user_id = $1",
                        "DELETE FROM user_credentials WHERE user_id = $1", "DELETE FROM users WHERE id = $1"):
                await conn.execute(sql, user_id)
    finally:
        await conn.close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", type=int, default=8014)
    p.add_argument("--keep", action="store_true", help="leave the probe rows in place")
    args = p.parse_args()
    env = load_env(args.port)
    base = f"http://127.0.0.1:{args.port}"
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, bool(ok), detail))
        print(f"{'ok ' if ok else 'BAD'} {name}{': ' + detail if detail else ''}")

    server = subprocess.Popen([sys.executable, "run.py"], cwd=DIALECTIC, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True)
    email = f"longway-probe-{secrets.token_hex(4)}@example.invalid"
    room_id = None
    try:
        deadline = time.time() + 90
        health = None
        while time.time() < deadline:
            if server.poll() is not None:
                break
            try:
                status, health = call("GET", f"{base}/health")
                if status == 200:
                    break
            except (urllib.error.URLError, ConnectionError):
                pass
            time.sleep(1)
        check("backend answers /health", health is not None and health.get("status") == "ok", json.dumps(health)[:200] if health else "no answer")
        if health is None:
            return finish(checks, env, email, room_id, server, args.keep)

        status, organ = call("GET", f"{base}/organ")
        check("GET /organ is the longway identity", status == 200 and isinstance(organ, dict) and organ.get("organ") == "longway"
              and organ.get("name") == "The Long Way" and organ.get("participant") == "Scout", json.dumps(organ)[:200])

        out = subprocess.run([sys.executable, str(HERE / "longway_seed.py"), "invite", "--email", email, "--name", "Probe", "--manager"],
                             env=env, capture_output=True, text=True, cwd=DIALECTIC)
        code = next((line.rsplit(":", 1)[1].strip() for line in out.stdout.splitlines() if "reset code" in line), None)
        check("seed script invites a house manager", out.returncode == 0 and bool(code), (out.stdout + out.stderr)[-300:] if not code else "code issued")
        password = secrets.token_urlsafe(18)
        status, body = call("POST", f"{base}/auth/reset-password", {"email": email, "code": code or "000000", "new_password": password})
        check("reset-password with the seed code", status == 200, json.dumps(body)[:200])
        token = body.get("access_token") if isinstance(body, dict) else None
        if not token:
            status, body = call("POST", f"{base}/auth/login", {"email": email, "password": password})
            check("login", status == 200 and isinstance(body, dict) and "access_token" in body, json.dumps(body)[:200])
            token = body.get("access_token") if isinstance(body, dict) else None

        status, room = call("POST", f"{base}/rooms", {"name": "Probe: Ogasawara"}, token=token)
        check("create a room", status == 200 and isinstance(room, dict) and "id" in room, json.dumps(room)[:200])
        room_id = room.get("id") if isinstance(room, dict) else None
        room_token = room.get("token") if isinstance(room, dict) else None

        status, bound = call("POST", f"{base}/rooms/{room_id}/longway/bind", {"slug": "ogasawara"}, token=token, room=room_token)
        check("bind the room to ogasawara", status == 200, json.dumps(bound)[:200])

        status, chart = call("GET", f"{base}/rooms/{room_id}/longway/chart", token=token, room=room_token)
        ok = status == 200 and isinstance(chart, dict)
        js = chart.get("journeys", []) if ok else []
        slugs = {j.get("slug"): j for j in js}
        check("chart: 19 journeys with friends-2027 as a trip", ok and len(js) == 19 and slugs.get("friends-2027", {}).get("kind") == "trip",
              f"status {status}, {len(js)} journeys")
        check("chart: the room's journey is ogasawara", ok and chart.get("room", {}).get("linked_journey") == "ogasawara")
        og = slugs.get("ogasawara", {})
        check("chart: ogasawara's leg is dashed on S1", og.get("segments", [{}])[0].get("ink") == "dashed" and og.get("segments", [{}])[0].get("basis") == ["S1"])
        vs = chart.get("vehicles", []) if ok else []
        maru = next((v for v in vs if v.get("name") == "Ogasawara Maru"), None)
        check("chart: Ogasawara Maru is listed with a fix or 'never heard'", maru is not None and "heard" in maru and ("fix" in maru),
              json.dumps({k: maru.get(k) for k in ("heard", "fix")})[:200] if maru else "missing")
        check("chart: fixes_state present", ok and isinstance(chart.get("fixes_state"), dict) and "stale" in chart["fixes_state"],
              json.dumps(chart.get("fixes_state"))[:200] if ok else "")
        blob = json.dumps(chart) if ok else ""
        check("chart: no reservation number from the private trip leaks", "4A8C4A" not in blob and "4A9322" not in blob and "coast-starlight" not in blob)

        status, journey = call("GET", f"{base}/rooms/{room_id}/longway/journey/ogasawara", token=token, room=room_token)
        check("journey: dossier and evidence present", status == 200 and isinstance(journey, dict) and len(journey.get("dossier", "")) > 200
              and len(journey.get("evidence", [])) > 0, f"status {status}")
        status, props = call("GET", f"{base}/rooms/{room_id}/longway/proposals", token=token, room=room_token)
        check("proposals: a list", status == 200 and isinstance(props, list), f"status {status}")
        status, confs = call("GET", f"{base}/rooms/{room_id}/longway/confirmations", token=token, room=room_token)
        check("confirmations: a list", status == 200 and isinstance(confs, list), f"status {status}")
        status, denied = call("GET", f"{base}/rooms/{room_id}/longway/chart", token=None, room=room_token)
        check("chart without a JWT is refused", status in (401, 403), f"status {status}")
    finally:
        return finish(checks, env, email, room_id, server, args.keep)


def finish(checks, env, email, room_id, server, keep) -> int:
    if server.poll() is None:
        os.killpg(server.pid, signal.SIGTERM)
        try:
            server.wait(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(server.pid, signal.SIGKILL)
    log = server.stdout.read() if server.stdout else ""
    if not keep:
        try:
            asyncio.run(cleanup(env["DATABASE_URL"], email, room_id))
        except Exception as exc:  # the probe must still report
            checks.append(("cleanup", False, repr(exc)))
    bad = [c for c in checks if not c[1]]
    result = {
        "finding": "supported" if checks and not bad else "contradicted",
        "observed": "; ".join(f"{n}: {'ok' if ok else 'FAILED ' + d}" for n, ok, d in checks) or "no checks ran",
        "runtime": {"target": f"longway backend from {DIALECTIC} on port {env['PORT']}", "source_tree": str(DIALECTIC)},
    }
    if bad:
        result["server_log_tail"] = log[-3000:]
    out = os.environ.get("OMC_OBSERVATION_RESULT")
    if out:
        Path(out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "server_log_tail"}, indent=1))
    if bad and log:
        print("--- server log tail ---")
        print(log[-3000:])
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
