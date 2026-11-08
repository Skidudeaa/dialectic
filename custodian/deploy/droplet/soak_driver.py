#!/usr/bin/env python3
"""Fault-injection soak of the live Custodian daemon against the real dialectic clone.

Scenario (every expectation asserted against the append-only event ledger):
  1. daemon starts; after the quiet interval it captures and verifies         -> attempt 1 starts
  2. a foreground edit lands while the check runs                            -> attempt 1 CANCELLED
  3. quiet again -> the edited draft is verified                             -> attempt 2 PASSED
  4. the alias tuple is broken -> verify FAILED, one bounded retry, then stop -> attempts 3,4 FAILED, no 5th
  5. the tuple is restored; the daemon is SIGKILLed while the check runs     -> attempt 5 abandoned
  6. daemon restarts: recovery marks 5 INTERRUPTED; a fresh attempt passes    -> attempt 6 PASSED
  7. a registered foreground session defers dispatch; after it exits, verify  -> attempt 7 PASSED
  8. audit ok; every PASSED outcome names the exact tree it checked
"""
import json, os, signal, sqlite3, subprocess, sys, time

REPO = "/home/user/dialectic"
STATE = "/opt/custodian-trial/soak-state"
POLICY = "/opt/custodian-trial/etc/dialectic-soak.toml"
CWD = "/home/user/dialectic/custodian"
CUST = ["/usr/bin/python3", "-m", "custodian", "--repo", REPO, "--state-dir", STATE]
LOG = open("/opt/custodian-trial/soak-daemon.log", "ab")
PRESENCE = f"{REPO}/dialectic/presence.py"
MENTIONS = f"{REPO}/dialectic/llm/mentions.py"
timeline = []


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    timeline.append(line)


def events():
    path = f"{STATE}/events.sqlite3"
    if not os.path.exists(path):
        return []
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = db.execute("select kind, payload from events order by seq").fetchall()
    finally:
        db.close()
    return [dict(kind=k, **json.loads(p)) for k, p in rows]


def count(kind):
    return sum(1 for e in events() if e["kind"] == kind)


def finished():
    return [e for e in events() if e["kind"] == "attempt_finished"]


def wait(desc, pred, timeout=300):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            log(f"{desc} (+{time.time() - t0:.0f}s)")
            return True
        time.sleep(1)
    log(f"TIMEOUT after {timeout}s waiting for: {desc}")
    return False


def start_daemon():
    p = subprocess.Popen(CUST + ["daemon", "--config", POLICY], cwd=CWD, stdout=LOG, stderr=LOG,
                         start_new_session=True)
    log(f"daemon started pid {p.pid}")
    return p


def git(*args):
    return subprocess.check_output(["git", "-C", REPO, *args]).decode()


def sandbox_children():
    out = subprocess.run(["pgrep", "-f", "pytest.main"], capture_output=True, text=True).stdout.split()
    return out


ok = True
def check(cond, msg):
    global ok
    log(("PASS " if cond else "FAIL ") + msg)
    ok = ok and bool(cond)


subprocess.run(["rm", "-rf", STATE], check=True)
git("checkout", "--", "dialectic/presence.py", "dialectic/llm/mentions.py")
daemon = start_daemon()
try:
    # 1-2. first attempt starts after quiet; an edit mid-check cancels it
    assert wait("attempt 1 started", lambda: count("attempt_started") >= 1)
    time.sleep(6)  # the check is now running inside the sandbox
    check(bool(sandbox_children()), "a sandboxed pytest is running during attempt 1")
    with open(PRESENCE, "a") as f:
        f.write("\n# soak: foreground edit during a running check\n")
    log("edited dialectic/presence.py while attempt 1's check was running")
    assert wait("attempt 1 finished", lambda: len(finished()) >= 1)
    a1 = finished()[0]
    check(a1["status"] == "CANCELLED", f"attempt 1 is {a1['status']} ({a1.get('reason')})")
    check(a1.get("branch") is None and not a1.get("checks") or all(c.get("cancelled") for c in a1.get("checks", [])),
          "attempt 1 minted no branch and its check evidence is marked cancelled")
    # 3. the edited draft is verified after quiet
    assert wait("attempt 2 finished", lambda: len(finished()) >= 2)
    a2 = finished()[1]
    check(a2["status"] == "PASSED", f"attempt 2 is {a2['status']} on tree {a2['input_tree'][:12]}")
    check(a2["input_tree"] != a1["input_tree"], "attempt 2 verified a different tree than the cancelled attempt")
    # 4. break the contract-pinned tuple: FAILED, one bounded retry, then the daemon stops retrying
    src = open(MENTIONS).read()
    assert '_LLM_ALIAS_PREFIXES = ("dialectic", "claude", "llm")' in src
    open(MENTIONS, "w").write(src.replace('_LLM_ALIAS_PREFIXES = ("dialectic", "claude", "llm")',
                                          '_LLM_ALIAS_PREFIXES = ("dialectic", "claude")'))
    log("broke the alias tuple in dialectic/llm/mentions.py")
    assert wait("attempt 3 finished", lambda: len(finished()) >= 3)
    a3 = finished()[2]
    check(a3["status"] == "FAILED", f"attempt 3 is {a3['status']} ({a3.get('reason')})")
    assert wait("attempt 4 (the one bounded retry) finished", lambda: len(finished()) >= 4, timeout=200)
    a4 = finished()[3]
    check(a4["status"] == "FAILED" and a4["input_tree"] == a3["input_tree"], "retry re-verified the same broken tree and FAILED")
    time.sleep(50)
    check(count("attempt_started") == 4, f"no further retry after max_retries (attempts started: {count('attempt_started')})")
    # 5a. restoring the tuple reproduces attempt 2's exact tree: the scheduler is keyed by
    #     candidate identity, so an already-PASSED tree must NOT be verified again.
    open(MENTIONS, "w").write(src)
    log("restored the alias tuple (tree now identical to attempt 2's)")
    time.sleep(45)
    check(count("attempt_started") == 4, f"an already-verified tree is not re-verified (started: {count('attempt_started')})")
    # 5b. a genuinely new draft, then SIGKILL the controller mid-check
    with open(PRESENCE, "a") as f:
        f.write("# soak: a new draft so the kill lands on a fresh attempt\n")
    log("new edit to presence.py -> a tree never seen before")
    assert wait("attempt 5 started", lambda: count("attempt_started") >= 5)
    time.sleep(6)
    check(bool(sandbox_children()), "a sandboxed pytest is running during attempt 5")
    os.killpg(daemon.pid, signal.SIGKILL)
    daemon.wait()
    log(f"SIGKILLed the daemon process group (pid {daemon.pid}) mid-check")
    time.sleep(3)
    check(not sandbox_children(), "the sandboxed check died with its controller (die-with-parent)")
    check(len(finished()) == 4, f"attempt 5 has no finish record after the kill ({len(finished())} finished)")
    work_dirs = os.listdir(f"{STATE}/work") if os.path.isdir(f"{STATE}/work") else []
    log(f"abandoned workspaces on disk: {work_dirs}")
    # 6. restart: recovery closes attempt 5 as INTERRUPTED; a fresh attempt passes
    daemon = start_daemon()
    assert wait("recovery recorded attempt 5", lambda: len(finished()) >= 5)
    a5 = finished()[4]
    check(a5["status"] == "INTERRUPTED" and a5.get("branch") is None, f"attempt 5 is {a5['status']}: {a5.get('reason')}")
    check(count("recovery") == 1, "one recovery event")
    assert wait("attempt 6 finished", lambda: len(finished()) >= 6, timeout=240)
    a6 = finished()[5]
    check(a6["status"] == "PASSED" and a6["input_tree"] == a5["input_tree"],
          f"attempt 6 re-verified the interrupted tree and is {a6['status']}")
    check(not os.listdir(f"{STATE}/work"), "abandoned workspaces were removed by recovery")
    # 7. a registered foreground session defers dispatch
    session = subprocess.Popen(CUST + ["session", "--", "sleep", "40"], cwd=CWD, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    with open(PRESENCE, "a") as f:
        f.write("# soak: edit under a registered foreground session\n")
    log("edited presence.py under `custodian session -- sleep 40`")
    time.sleep(32)
    check(count("attempt_started") == 6, f"no attempt dispatched while the session lease was held (started: {count('attempt_started')})")
    session.wait()
    log("foreground session exited")
    assert wait("attempt 7 finished", lambda: len(finished()) >= 7, timeout=240)
    a7 = finished()[6]
    check(a7["status"] == "PASSED", f"attempt 7 is {a7['status']} after the lease was released")
    check(count("session_started") == 1 and count("session_ended") == 1, "session start/end recorded once each")
finally:
    if daemon.poll() is None:
        os.killpg(daemon.pid, signal.SIGTERM)
        try:
            daemon.wait(timeout=30)
            log("daemon stopped cleanly on SIGTERM")
        except subprocess.TimeoutExpired:
            os.killpg(daemon.pid, signal.SIGKILL)
            log("daemon needed SIGKILL on shutdown")
    git("checkout", "--", "dialectic/presence.py", "dialectic/llm/mentions.py")
    log("foreground restored with git checkout")

# 8. invariants over the whole ledger
audit = json.loads(subprocess.check_output(CUST + ["audit"], cwd=CWD))
check(audit["ok"], f"audit ok with {audit['events']} events")
observed = {e["tree"] for e in events() if e["kind"] == "observation"}
rows = []
for a in finished():
    rows.append(dict(id=a["id"][:12], status=a["status"], input_tree=a["input_tree"][:12],
                     output_tree=(a.get("output_tree") or "")[:12], reason=a.get("reason")))
    if a["status"] == "PASSED":
        check(a["output_tree"] == a["input_tree"] and a["input_tree"] in observed,
              f"PASSED {a['id'][:12]} names a captured tree and changed nothing (no mutator in this soak)")
    if a["status"] in ("CANCELLED", "INTERRUPTED", "FAILED"):
        check(a.get("branch") is None, f"{a['status']} {a['id'][:12]} minted no proposal branch")
print(json.dumps(rows, indent=1))
summary = dict(ok=ok, attempts=rows, timeline=timeline, audit=audit,
               event_kinds={k: count(k) for k in sorted({e['kind'] for e in events()})})
json.dump(summary, open("/opt/custodian-trial/soak-summary.json", "w"), indent=2)
print("SOAK", "OK" if ok else "FAILED")
sys.exit(0 if ok else 1)
