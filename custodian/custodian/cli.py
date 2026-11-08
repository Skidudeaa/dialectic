"""Explicit CLI contracts; hook payloads are deliberately not guessed."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

from .engine import CustodianError, Engine


def argv_json(value):
    try:
        parsed = json.loads(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    if not isinstance(parsed, list) or not parsed or not all(isinstance(a, str) for a in parsed):
        raise argparse.ArgumentTypeError("Expected a nonempty JSON array of strings")
    return parsed


def git_busy(engine):
    directory = Path(engine.source_git(engine.repo, "rev-parse", "--absolute-git-dir").decode().strip())
    return any((directory / path).exists() for path in
               ("index.lock", "MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD"))


def watch(engine, checks, quiet, interval, timeout, mode="isolated"):
    """Observation-only until quiet; registered foreground sessions take precedence."""
    if quiet < 0 or interval <= 0:
        raise CustodianError("Quiet must be nonnegative and interval positive")
    previous = None
    changed_at = time.monotonic()
    # Coalesce identical trees across daemon restarts; failed attempts need an explicit retry.
    done = {a["tree"] for a in engine.events("watch_checked") if a.get("policy") == checks}
    observed = {o["tree"] for o in engine.events("observation")}
    with (engine.state / "watch.lock").open("a") as singleton:
        try:
            fcntl.flock(singleton, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CustodianError("A watcher already owns this repository") from exc
        while True:
            try:
                with (engine.state / "foreground.lock").open("a") as foreground:
                    try:
                        fcntl.flock(foreground, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        changed_at = time.monotonic()
                    else:
                        # Only a dispatch check. Foreground launches never wait for a running worker.
                        fcntl.flock(foreground, fcntl.LOCK_UN)
                        if git_busy(engine):
                            changed_at = time.monotonic()
                        else:
                            with engine.lease():
                                tree = engine._tree(engine.repo)
                            if tree != previous:
                                previous, changed_at = tree, time.monotonic()
                            if time.monotonic() - changed_at >= quiet:
                                if checks and tree not in done:
                                    result = engine.run("Scheduled verification of observed draft", None,
                                                        checks, timeout=timeout, mode=mode)
                                    # Scheduling event is separate from immutable attempt evidence.
                                    engine.event("watch_checked", dict(tree=result["input_tree"], policy=checks,
                                                                      attempt=result["id"]))
                                    done.add(result["input_tree"])
                                    print(json.dumps(result), flush=True)
                                elif not checks and tree not in observed:
                                    snapshot = engine.capture()
                                    observed.add(snapshot["tree"])
                                    print(json.dumps(snapshot), flush=True)
            except (CustodianError, OSError) as exc:
                print(f"custodian: deferred: {exc}", file=sys.stderr, flush=True)
            time.sleep(interval)


def session(engine, command):
    """Print a fresh view and hold a shared foreground lease for the child lifetime."""
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise CustodianError("session requires a command after --")
    session_id = uuid.uuid4().hex
    # The watcher holds EX only for its dispatch handshake, never during work.
    # Always register: skipping this lock would hide the entire foreground session.
    with (engine.state / "foreground.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        engine.event("session_started", dict(id=session_id, argv=command))
        try:
            try:
                print(engine.state_markdown(blocking=False), flush=True)
            except BlockingIOError:
                print("Custodian has an active attempt; current evidence is not yet available.", flush=True)
            result = subprocess.run(command, cwd=engine.repo)
            return result.returncode
        finally:
            engine.event("session_ended", dict(id=session_id))


def main():
    parser = argparse.ArgumentParser(description="Revision-bound maintenance evidence")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--state-dir", type=Path)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("capture", help="Import a candidate without modifying the source")
    status = sub.add_parser("state", help="Render a disposable context view to stdout")
    status.add_argument("--json", action="store_true")
    sub.add_parser("events", help="Read the append-only event history")
    blob = sub.add_parser("log", help="Read an evidence stdout/stderr object")
    blob.add_argument("object")
    run = sub.add_parser("run", help="Construct and check an isolated candidate")
    run.add_argument("--intent", required=True)
    run.add_argument("--command", type=argv_json, help="Trusted executable argv as JSON; no shell implied")
    run.add_argument("--check", type=argv_json, action="append", default=[])
    run.add_argument("--protect", action="append", default=[])
    run.add_argument("--timeout", type=float, default=60)
    run.add_argument("--config", type=Path)
    run.add_argument("--mode", choices=["isolated", "trusted"], default="isolated")
    run.add_argument("--runtime-path", action="append", default=[])
    run.add_argument("--runtime-root", type=Path)
    watcher = sub.add_parser("watch", help="Continuously capture or check settled candidates; no model calls")
    watcher.add_argument("--quiet", type=float, default=600)
    watcher.add_argument("--interval", type=float, default=5)
    watcher.add_argument("--check", type=argv_json, action="append", default=[])
    watcher.add_argument("--timeout", type=float, default=60)
    watcher.add_argument("--mode", choices=["isolated", "trusted"], default="isolated")
    foreground = sub.add_parser("session", help="Run a foreground tool with a session lease")
    foreground.add_argument("command", nargs=argparse.REMAINDER)
    daemon = sub.add_parser("daemon", help="Run durable policy-driven maintenance with foreground preemption")
    daemon.add_argument("--config", type=Path, required=True)
    daemon.add_argument("--once", action="store_true")
    for name in ("doctor", "budget", "model"):
        option = sub.add_parser(name)
        option.add_argument("--config", type=Path, required=name != "doctor")
        if name == "model":
            option.add_argument("--intent", required=True)
        if name == "doctor":
            option.add_argument("--scope", choices=["user", "system"], default="user",
                                help="Which service manager to probe (default: the per-user manager)")
    service = sub.add_parser("service", help="Render or manage the native service (per-user or system scope)")
    service.add_argument("operation", choices=["render", "install", "start", "stop", "status", "uninstall"])
    service.add_argument("--config", type=Path)
    service.add_argument("--start", action="store_true")
    service.add_argument("--scope", choices=["user", "system"], default="user",
                         help="user: systemd --user unit or launchd agent; system: /etc/systemd/system unit (root)")
    service.add_argument("--environment-file", type=Path,
                         help="systemd EnvironmentFile= with KEY=VALUE lines (e.g. the provider credential); never embedded")
    sub.add_parser("mcp", help="Read-only evidence tools over stdio MCP")
    ctx = sub.add_parser("context", help="Bounded session context derived from retained evidence")
    ctx.add_argument("--max-bytes", type=int, default=16384)
    sub.add_parser("map", help="Python symbol signatures from the captured candidate")
    hook = sub.add_parser("hook", help="Claude lifecycle adapter; reads documented JSON on stdin")
    hook.add_argument("kind", choices=["SessionStart", "Stop", "PreCompact"])
    proposal = sub.add_parser("proposals", help="List proposals or record human disposition")
    proposal.add_argument("--attempt")
    proposal.add_argument("--disposition", choices=["accepted", "rejected", "withdrawn"])
    proposal.add_argument("--reason", default="")
    diff = sub.add_parser("diff")
    diff.add_argument("attempt")
    diff.add_argument("--full", action="store_true")
    for name in ("recover", "audit"):
        sub.add_parser(name)
    decision = sub.add_parser("decision", help="Record explicit rationale against an attempt")
    decision.add_argument("attempt")
    decision.add_argument("--decision", required=True)
    decision.add_argument("--reason", required=True)
    decision.add_argument("--rejected", action="append", default=[])
    runtime = sub.add_parser("runtime", help="Freeze an execution runtime into a verified content snapshot")
    runtime.add_argument("operation", choices=["freeze"])
    runtime.add_argument("--destination", type=Path, required=True)
    runtime.add_argument("--source", type=Path, action="append", required=True)
    args = parser.parse_args()
    try:
        if args.action == "runtime":
            from .runtime import freeze_runtime
            print(json.dumps(freeze_runtime(args.destination, args.source), indent=2))
            return 0
        engine = Engine(args.repo, args.state_dir)
        from .config import Config
        config = Config.load(args.config, repo=engine.repo) if getattr(args, "config", None) else None
        if args.action == "capture":
            print(json.dumps(engine.capture(), indent=2))
        elif args.action == "state":
            print(json.dumps(engine.status(), indent=2) if args.json else engine.state_markdown())
        elif args.action == "events":
            print(json.dumps(engine.events(), indent=2))
        elif args.action == "log":
            # Type check and disallow option injection through a purported object ID.
            if len(args.object) not in (40, 64) or any(c not in "0123456789abcdef" for c in args.object):
                raise CustodianError("Expected a full hexadecimal blob ID")
            sys.stdout.buffer.write(subprocess.check_output(
                ["git", "--git-dir", str(engine.archive), "cat-file", "blob", args.object]))
        elif args.action == "run":
            result = engine.run(args.intent, args.command, config.checks if config else args.check,
                                config.protected if config else args.protect, config.timeout_seconds if config else args.timeout,
                                mode=config.execution_mode if config else args.mode,
                                runtime_paths=config.runtime_paths if config else args.runtime_path,
                                runtime_root=config.runtime_root if config else args.runtime_root)
            print(json.dumps(result, indent=2))
            return 0 if result["status"] == "PASSED" else 1
        elif args.action == "watch":
            watch(engine, args.check, args.quiet, args.interval, args.timeout, args.mode)
        elif args.action == "session":
            return session(engine, args.command)
        elif args.action == "daemon":
            from .daemon import run as run_daemon
            from .maintenance import on_failure
            stopping = [False]
            def stop(signum, frame):
                stopping[0] = True
            signal.signal(signal.SIGTERM, stop)
            signal.signal(signal.SIGINT, stop)
            result = run_daemon(engine, config, once=args.once, stop=lambda: stopping[0], on_failure=on_failure)
            return 0 if not result or result.get("status") not in ("FAILED", "REJECTED", "ERROR") else 1
        elif args.action == "model":
            from .maintenance import propose
            from .daemon import foreground_active, git_busy, fingerprint
            original = fingerprint(engine)
            cancel = lambda: foreground_active(engine) or git_busy(engine) or fingerprint(engine) != original
            result = propose(engine, config, args.intent, cancel=cancel)
            print(json.dumps(result, indent=2))
            return 0 if result["status"] in ("PASSED", "NO_CHANGE") else 1
        elif args.action == "budget":
            from .provider import Provider
            print(json.dumps(Provider(engine.state, config.model).budget_status(), indent=2))
        elif args.action == "doctor":
            from .service import health
            from .sandbox import Sandbox
            report = health(engine, scope=args.scope)
            try:
                report["sandbox"] = Sandbox(mode=config.execution_mode if config else "isolated",
                                             runtime_paths=config.runtime_paths if config else [],
                                             runtime_root=config.runtime_root if config else None).probe()
            except RuntimeError as exc:
                report["sandbox"] = dict(available=False, error=str(exc))
            report["evidence"] = engine.audit()
            report["provider_credentials_configured"] = bool(config and config.model and
                os.environ.get(config.model.get("api_key_env", "ANTHROPIC_API_KEY")))
            print(json.dumps(report, indent=2))
            return 0 if report["sandbox"].get("available") and report["evidence"]["ok"] else 1
        elif args.action == "service":
            from . import service as services
            if args.operation in ("render", "install") and not args.config:
                raise CustodianError("service render/install requires --config")
            if args.operation == "render":
                print(services.render(engine, args.config, scope=args.scope,
                                      environment_file=args.environment_file))
            elif args.operation == "install":
                print(json.dumps(services.install(engine, args.config, start=args.start, scope=args.scope,
                                                  environment_file=args.environment_file), indent=2))
            else:
                print(json.dumps(getattr(services, args.operation)(engine, scope=args.scope), indent=2))
        elif args.action in ("context", "map", "hook", "decision"):
            from . import context
            if args.action == "context":
                result = context.state(engine, max_bytes=args.max_bytes)
            elif args.action == "map":
                result = context.repo_map(engine)
            elif args.action == "hook":
                raw = sys.stdin.read(65537)
                if len(raw.encode()) > 65536:
                    raise CustodianError("Hook payload exceeds 64 KiB")
                result = context.hook_payload(engine, args.kind, json.loads(raw or "{}"))
            else:
                result = context.record_decision(engine, args.attempt, args.decision, args.reason, args.rejected)
            if result:
                print(json.dumps(result, indent=2))
        elif args.action == "mcp":
            from .mcp import serve
            serve(engine)
        elif args.action == "proposals":
            if args.attempt or args.disposition:
                if not args.attempt or not args.disposition:
                    raise CustodianError("Both --attempt and --disposition are required")
                result = engine.dispose(args.attempt, args.disposition, args.reason)
            else:
                result = engine.proposals()
            print(json.dumps(result, indent=2))
        elif args.action == "diff":
            print(engine.diff(args.attempt, full=args.full))
        elif args.action == "recover":
            print(json.dumps(engine.recover(), indent=2))
        elif args.action == "audit":
            result = engine.audit()
            print(json.dumps(result, indent=2))
            return 0 if result["ok"] else 1
        return 0
    except KeyboardInterrupt:
        return 130
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"custodian: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
