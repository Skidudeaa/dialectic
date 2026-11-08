# Custodian

Custodian is a local maintenance daemon whose durable unit is an attempted change. Each attempt retains its input files, candidate files, executed checks, output logs, and outcome. Status is a view of that evidence: a later edit cannot inherit a passing result for different bytes.

The daemon captures edits outside Git commits, waits for quiet, verifies candidates, and runs configured maintenance jobs in isolated workspaces. Optional model requests return bounded edits to the controller; the model receives no shell, credentials, ledger authority, or integration authority. Passing changes become private proposal branches for review. The foreground checkout is never automatically changed, merged, or pushed.

The [architectural contract](ARCHITECTURE.md) explains the representation change. This README describes the executable implementation.

## Install and inspect the execution boundary

Requirements:

- Python 3.11+, Git, and a repository with at least one commit.
- Linux with Bubblewrap and usable user namespaces for default isolated execution.
- Policy and state directories outside the foreground repository.
- Check dependencies available in the selected runtime. A repository's ignored virtual environment is not copied into candidates.

There are no Python runtime dependencies. Install from this checkout:

```sh
python3 -m pip install -e .
custodian --help
python3 -m unittest discover -s tests -v
```

Without installation, use `python3 -m custodian` from this checkout. All examples below use the installed command. Choose absolute paths:

```sh
custodian_repo=/absolute/path/to/project
custodian_state=/absolute/path/outside/project/custodian-state
custodian_policy=/absolute/path/outside/project/custodian.toml
```

Then inspect actual capabilities:

```sh
custodian --repo "$custodian_repo" --state-dir "$custodian_state" doctor
```

Default execution fails closed if isolation is unavailable. `trusted` mode is an explicit compatibility escape for operator-controlled commands; it is not permitted for model-produced changes. macOS service rendering is supported, but Linux namespace isolation is not available there.

In isolated mode, workers receive a writable candidate at `/work`; verifiers receive the candidate read-only. Neither receives the foreground checkout, state archive, home directory, controller credentials, or host network. Git administrative files are masked. Environment variables are allowlisted. Process namespaces, timeout, cancellation, and output limits bound execution. Check tools must put generated files under `/tmp` rather than changing source; for example, run pytest with its cache provider disabled and a temporary `--basetemp` if your project requires it.

A read-only source mount establishes which source bytes were available. It does not make weak or dishonest tests prove program correctness. External-service equivalence and host-runtime reproducibility remain separate facts.

## Configure an external policy

Create `$custodian_policy` outside the source repository:

```toml
checks = [["python3", "-m", "unittest", "discover", "-s", "tests"]]
protected = ["SPEC.md", "AGENTS.md", "CLAUDE.md", "tests"]
execution_mode = "isolated"
quiet_seconds = 600
poll_seconds = 5
timeout_seconds = 120
max_retries = 2
retry_backoff_seconds = 60
runtime_paths = []

# Optional: your project must actually contain this command.
# [[jobs]]
# name = "maintenance"
# command = ["python3", "tools/maintenance.py"]
# interval_seconds = 86400
# enabled = true
```

Commands are arrays of arguments, never implicitly shell strings. Replace the example checks with your repository's real independent checks. Enabled maintenance jobs require checks. Protected paths match exact repository-relative paths or directory prefixes. They constrain changes introduced by maintenance relative to its imported input, including deletions; they do not erase pre-existing human edits.

`runtime_paths` explicitly exposes additional dependency directories read-only. It must not expose the source repository or Custodian state. These mounts are a deliberate disclosure boundary: do not include directories containing credentials. Policy files are validated and reject unknown fields; candidates cannot replace the external execution policy.

For a content-pinned userspace, freeze selected executables and their complete library closure into a separate artifact. This tested Linux x86-64 smoke example contains only `/usr/bin/true` and its loader/libc dependencies; it cannot run a project's Python or Node checks:

```sh
custodian runtime freeze --destination /absolute/path/to/runtimes/true-smoke \
  --source /usr/bin/true \
  --source /lib/x86_64-linux-gnu/libc.so.6 \
  --source /lib64/ld-linux-x86-64.so.2
```

For that smoke test, set `runtime_root = "/absolute/path/to/runtimes/true-smoke"`, `runtime_paths = []`, and `checks = [["/usr/bin/true"]]`. A real project needs a separate artifact containing its actual interpreter, libraries, and test dependencies. Copying all of `/usr` is not a portable shortcut: distribution symlinks into `/etc/alternatives` are deliberately rejected.

Frozen execution validates the inventory, content hashes, modes, and symlinks before use and records the runtime identity. The snapshot cannot be modified by its sandbox workers. It pins userspace files, not the host kernel or external services; the owning operator can deliberately replace artifacts. Without `runtime_root`, evidence identifies the host runtime as unpinned rather than promising reproducibility.

## Run the daemon

```sh
custodian --repo "$custodian_repo" --state-dir "$custodian_state" daemon \
  --config "$custodian_policy"
```

The scheduler uses cheap filesystem metadata observations while waiting and captures source bytes after the quiet interval. No model is called merely because time passes. Each scheduling decision is keyed to the input, base commit, and execution policy. Repeated failures have bounded exponential retries; a changed policy or candidate creates new work. Cancellation is retained as cancellation, not failure or success.

Registered foreground sessions, source activity, and detected Git operations defer new work. They also cancel in-flight background execution. Start cooperating interactive tools through the wrapper:

```sh
custodian --repo "$custodian_repo" --state-dir "$custodian_state" session -- codex
custodian --repo "$custodian_repo" --state-dir "$custodian_state" session -- claude
```

The wrapper records session start/end and holds a foreground lease. It prints context, but printing alone does not inject context into a model; use MCP or the documented hook below. Unregistered interactive processes are not all discoverable. File changes still trigger deferral, and isolation remains the correctness boundary.

`daemon --once` performs a scheduler tick and reports whether it ran or deferred. With a nonzero quiet interval, an initial tick can correctly report deferral. `watch` remains available as the simpler capture/check interface; use `daemon --config` for configured jobs and operational recovery.

## Native service lifecycle

Review the actual generated unit before installation:

```sh
custodian --repo "$custodian_repo" --state-dir "$custodian_state" service render \
  --config "$custodian_policy"
```

Install and start only when ready:

```sh
custodian --repo "$custodian_repo" --state-dir "$custodian_state" service install \
  --config "$custodian_policy" --start
custodian --repo "$custodian_repo" --state-dir "$custodian_state" service status
custodian --repo "$custodian_repo" --state-dir "$custodian_state" service stop
custodian --repo "$custodian_repo" --state-dir "$custodian_state" service start
```

Omit `--start` to install without activation. `service uninstall` stops and removes only the managed service file; it retains source, evidence, and policy. On Linux, services use the per-user systemd manager; on macOS, they use a LaunchAgent. Unit paths and names are deterministic per repository, existing unrelated files are never overwritten, and native supervisor errors are reported. A generated or installed file is not evidence that a service is running.

The service uses an absolute Python interpreter and source/package working directory. Do not move or remove that installation while the service uses it. Provider credentials, if enabled, must be available to the service manager's environment; an interactive shell's environment is not automatically inherited. Secrets are never embedded in generated service files.

## Inspect, verify, and propose

```sh
custodian --repo "$custodian_repo" --state-dir "$custodian_state" capture
custodian --repo "$custodian_repo" --state-dir "$custodian_state" state --json
custodian --repo "$custodian_repo" --state-dir "$custodian_state" context --max-bytes 16384
custodian --repo "$custodian_repo" --state-dir "$custodian_state" map
custodian --repo "$custodian_repo" --state-dir "$custodian_state" run \
  --config "$custodian_policy" --intent 'Verify the current draft'
```

Capture includes tracked and nonignored untracked files, deletions, executable modes, and symlink contents. Imported intent starts as `UNKNOWN`. A scan constructs a candidate; even two equal scans do not prove the live directory contained those bytes atomically. Unsupported file types and submodules are refused. Escaping symlinks are refused before execution.

For a maintenance attempt, add `--command '["python3", "tools/maintenance.py"]'` using an actual command in your project. Candidate creation and verification occur in separate workspaces. Each completed attempt retains its own outcome:

| Outcome | Meaning |
|---|---|
| `PASSED` | Configured checks exited zero against the identified candidate under the recorded execution conditions. |
| `FAILED` | A command failed, timed out, exceeded a limit, or could not execute normally. |
| `REJECTED` | Maintenance changed a protected path. |
| `UNVERIFIED` | No checks were configured. |
| `CANCELLED` | Foreground activity or controller shutdown preempted work. |
| `INTERRUPTED` | Execution was interrupted or recovered without a trustworthy completed outcome. |

A pass is not a global repository certificate. Context reports which candidate it concerns and whether the currently observed bytes match. In trusted mode, only before/after source comparisons are available; isolated mode additionally enforces a read-only verifier input. Missing external-state equivalence remains explicit.

## Review private proposals

```sh
custodian --repo "$custodian_repo" --state-dir "$custodian_state" proposals
custodian --repo "$custodian_repo" --state-dir "$custodian_state" diff ATTEMPT_ID
custodian --repo "$custodian_repo" --state-dir "$custodian_state" diff ATTEMPT_ID --full
```

The ordinary diff shows maintenance changes relative to imported input; `--full` includes imported uncommitted changes relative to the captured base. Review the full diff before integration. At most three private proposal branches wait at once.

A branch such as `custodian/012345abcdef` lives in `$custodian_state/objects.git`. Explicitly import it yourself if you decide to integrate:

```sh
git -C "$custodian_repo" fetch "$custodian_state/objects.git" \
  refs/heads/custodian/012345abcdef:refs/heads/custodian/012345abcdef
```

Record your disposition and release its waiting slot:

```sh
custodian --repo "$custodian_repo" --state-dir "$custodian_state" proposals \
  --attempt ATTEMPT_ID --disposition rejected --reason 'The proposed change does not preserve behavior'
```

`accepted`, `rejected`, and `withdrawn` record the operator's disposition; none performs a merge. Evidence survives disposal. Record rationale explicitly instead of asking the daemon to invent it from chat:

```sh
custodian --repo "$custodian_repo" --state-dir "$custodian_state" decision ATTEMPT_ID \
  --decision 'Keep the existing API' --reason 'The proposed call signature breaks consumers' \
  --rejected 'Rename the public entry point'
```

## Optional bounded model maintenance

Model use is off by default. The built-in adapter calls the Anthropic Messages API directly; it does not use a Claude subscription or execute `claude -p`. Configure the exact model identifier and current input/output prices yourself. No current price is guessed by the code.

Add a `[model]` table to your external policy with these fields:

- `model`: the provider model identifier.
- `input_usd_per_million` and `output_usd_per_million`: explicit positive decimal prices.
- `daily_budget_usd`: the local daily admission allowance; defaults to `"5"`.
- `api_key_env`: the credential environment-variable name; defaults to `"ANTHROPIC_API_KEY"`.
- `include`: explicit source-disclosure patterns, for example `["src/**/*.py"]`.
- `exclude`: optional exclusions; defaults exclude common environment/key/credential/secret names.
- `allow_new`: explicitly allowed new-file patterns; defaults to no new files.
- `max_input_tokens`, `max_output_tokens`, `max_input_bytes`: request bounds.
- `auto_on_failure = true`: optional automatic requests after independently observed verification failure.

Do not put the credential itself in TOML. Then invoke an explicit request:

```sh
custodian --repo "$custodian_repo" --state-dir "$custodian_state" model \
  --config "$custodian_policy" --intent 'Repair the observed failure while preserving the public API'
custodian --repo "$custodian_repo" --state-dir "$custodian_state" budget --config "$custodian_policy"
```

Only allowlisted snapshot files and bounded check evidence are disclosed. Review your policy: exclusion patterns are not a secret scanner. Responses contain edit operations with exact original-content hashes. The controller rejects unsupported paths, stale hashes, protected changes, and undisclosed files before independent isolated verification. The model cannot choose verification commands or grade its own output.

An empty edit response is recorded as `NO_CHANGE`: model abstention creates no maintenance attempt or proposal branch. Its request and accounting evidence are retained.

Budget admission uses atomic SQLite reservations before paid generation. It reserves the configured input allowance plus maximum output, retains reservations for uncertain requests or crashes, and locks out new requests if reported usage breaches the allowance. This is accounting at your configured rates, not a guarantee about a provider invoice: token counting is an estimate, prices are supplied by you, and remote processing may finish after local cancellation. There is no automatic retry of uncertain paid requests and no integration with an external governor ledger.

## Connect foreground tools to evidence

The read-only MCP server exposes `custodian_state`, `custodian_attempt`, `custodian_history`, `custodian_decisions`, and `custodian_repo_map`, plus corresponding resources. Views have byte limits and distinguish stale or unavailable current observations. The map extracts Python declaration signatures from captured input, not from executing the repository.

For Codex, register the installed executable:

```sh
codex mcp add custodian -- /absolute/path/to/venv/bin/custodian \
  --repo /absolute/path/to/project \
  --state-dir /absolute/path/outside/project/custodian-state mcp
```

Other MCP clients can launch the same command over stdio. MCP registration provides tools; it does not guarantee a model will call them without instruction.

The Claude hook adapter accepts native hook JSON on stdin:

```sh
custodian --repo "$custodian_repo" --state-dir "$custodian_state" hook SessionStart
```

Use that command as a Claude `SessionStart` command hook, following the [documented command-hook format](https://code.claude.com/docs/en/hooks#add-context-for-claude). It validates the supplied `cwd` and `session_id`, records the event, and returns `hookSpecificOutput.additionalContext` containing bounded evidence. `hook Stop` and `hook PreCompact` record lifecycle observations and intentionally emit no model instructions. They are not session locks; use the `session` wrapper for cooperating foreground leases. Vendor configuration files are never silently overwritten, and Codex hook payloads are not assumed.

## Recovery and retained evidence

```sh
custodian --repo "$custodian_repo" --state-dir "$custodian_state" recover
custodian --repo "$custodian_repo" --state-dir "$custodian_state" audit
custodian --repo "$custodian_repo" --state-dir "$custodian_state" events
custodian --repo "$custodian_repo" --state-dir "$custodian_state" log FULL_HEXADECIMAL_BLOB_ID
```

Recovery records abandoned attempts as interrupted and removes their disposable workspaces. It does not invent a success from a partial run. Audit verifies retained references. Raw stdout/stderr are stored as evidence objects; private refs preserve them through Git garbage collection. The event ledger rejects row updates and deletions through triggers, but the owning user can still alter local storage. Back up the entire external state directory together, including the Git archive and both SQLite databases. There is no automatic evidence pruning; monitor disk use.

## What this release does not claim

The daemon is not an autonomous proof of semantic correctness, a universal cross-language dead-code oracle, or a complete transcript-derived memory system. Missing rationale stays unknown. It does not auto-merge, push, install a service on import, provide a provider invoice guarantee, or silently downgrade failed isolation to trusted execution. Check environments and external services must be represented honestly; unsupported conditions remain explicit rather than becoming a repository-wide “verified” flag.

## Amendment 2026-11-08 — the droplet build (amend-beside; prefer this where it differs)

Four changes landed when Custodian was bound to the dialectic monorepo for
real, each proven failing before it was fixed. Everything above remains true
except where this section says otherwise.

### Services have a scope

```sh
custodian --repo "$custodian_repo" --state-dir "$custodian_state" service render \
  --config "$custodian_policy" --scope system --environment-file /etc/custodian/project.env
custodian --repo "$custodian_repo" --state-dir "$custodian_state" service install \
  --config "$custodian_policy" --scope system --environment-file /etc/custodian/project.env --start
custodian --repo "$custodian_repo" --state-dir "$custodian_state" service status --scope system
custodian --repo "$custodian_repo" --state-dir "$custodian_state" doctor --config "$custodian_policy" --scope system
```

`--scope user` (the default, and everything the "Native service lifecycle"
section describes) renders `~/.config/systemd/user/…` or a LaunchAgent and
needs a login session or lingering. `--scope system` renders
`/etc/systemd/system/custodian-<id>.service` with `WantedBy=multi-user.target`
and `After=network-online.target`, and drives `systemctl` without `--user`; it
is systemd-only and needs root. `--environment-file` emits `EnvironmentFile=`
pointing at an existing root-only `KEY=VALUE` file outside the repository —
the provider credential's home on a server, since an interactive shell's
environment is never inherited by a unit. The file's contents never enter the
unit; `status`/`uninstall` take the same `--scope`. **Why:** on a headless root
host the user manager does not exist until someone logs in, so a daemon
"activated" there dies with the SSH session; the earlier text's "does not
create a login bus or enable lingering" was describing exactly that trap.

### The sandbox mounts `/etc/alternatives`, read-only

Debian-family hosts route `/usr/bin/python3` (and `pytest`, `node`, …) through
`/etc/alternatives` symlinks. With only `/usr` mounted the interpreter named in
every check was a dangling link inside the namespace, and all 21 isolation
tests failed with `bwrap: execvp /usr/bin/python3: No such file or directory`
on a host whose `/usr/bin/python3 -> /etc/alternatives/python3`. That one
directory (distribution symlinks and a README, no account/DNS/secret data) is
now the only `/etc` entry mounted. Frozen runtimes are unaffected and still
reject alternatives indirection by design.

### Blob ids are computed in-process; a scan is sub-second

`engine._tree` used to spawn `git hash-object -w --stdin` once per file. On
dialectic (1,571 tracked files, 39 MB) a single scan took ~7 s, an attempt runs
five scans, and `status()` — the SessionStart hook and every MCP read — paid
the same 7 s. Blob ids are now computed with `hashlib` in the archive's own
object format (`sha1` or `sha256`, read from `rev-parse --show-object-format`),
one `cat-file --batch-check` answers which of the N ids already exist, and only
missing blobs are written; `_capture` fetches the base commit *before*
scanning so an unmodified tracked file never costs a process. Measured on the
same checkout: capture 7.1 s → 0.33 s warm (0.82 s cold including the history
fetch), `state` 7 s → 0.23 s, and the tree id is byte-for-byte the one the old
engine produced (`2abcc77d…` from both, back-to-back). `tests/test_engine.py`
pins identity against git-native hashing on CRLF, NUL-bearing, empty, executable,
symlinked and duplicate-content files in both sha1 and sha256 repositories, and
asserts a second scan spawns no `hash-object` at all.

### Provider defaults

`max_output_tokens` now defaults to **16384** (was 4096): on current models
thinking is always on and shares `max_tokens` with the answer, so the old
ceiling turned a correct repair into `stop_reason=max_tokens` — a paid request
with no edit. The reservation grows accordingly; lower it in policy
deliberately. The authentication header was re-checked against the API
overview on 2026-11-08: `Authorization: Bearer <api key>` is the documented
primary header, `x-api-key` the legacy fallback — the adapter is unchanged.
Still true: no live paid request has been made through this adapter.

### Binding a real repository: the dialectic policy

`deploy/droplet/dialectic.toml` is the first measured policy. Its one check is
the repository's documented test invocation written as a single argv — a
`python -c` that `chdir`s into `dialectic/` and calls `pytest.main`, because
the project's own tests open files relative to that directory — with the 34
Postgres-backed modules ignored by glob (the sandbox has no network and must
not launder a shared mutable database into a verdict) and five tests
deselected by name because each reaches for a host resource the sandbox does
not provide (`/etc/passwd`, headless Chrome, a `/var/lib` venv). Inside the
sandbox, read-only, against the live draft: **1925 passed, 83 skipped, 5
deselected in 27 s**, attempt `PASSED`, candidate bytes unchanged. The
`deploy/droplet/` runbook carries the install, the verification commands and
the rollback.

### The model now sees what failed

`build_context` disclosed the HEAD of a failed check's stderr. On dialectic the
stderr of a 3-failure pytest run was one deprecation warning; the `FAILED`
lines and assertion diffs were on stdout, at the end. `failed_check` now
carries `stdout_tail` and `stderr_tail` (last 8 KiB each). Still not executed:
a live paid request — this build environment authenticates no scripted call
to the Anthropic API (a count_tokens probe with a placeholder key returned
401, which does confirm the `Authorization: Bearer` header is parsed as the
credential).

### The live daemon under fault injection, on the real repository

`deploy/droplet/soak_driver.py` runs the daemon against the dialectic clone
and asserts every expectation against the append-only ledger (record:
`validation/2026-11-08-droplet-build/soak-live-daemon.{json,log}`, 27 of 27
assertions, audit ok over 45 events). What it proved, in order: an edit that
lands while a check runs cancels the attempt (`CANCELLED`, exit −9, no
branch); the edited draft is then verified on its own tree; a broken
contract-pinned tuple is `FAILED`, retried exactly once with backoff, then
left alone; **restoring the tuple reproduced an already-PASSED tree and the
scheduler did not re-verify it** — scheduling is keyed by candidate identity,
so identical bytes cost nothing twice; a `SIGKILL` of the controller mid-check
killed the sandboxed pytest with it (`--die-with-parent`), left no finish
record, and on restart recovery marked that attempt `INTERRUPTED` ("outcome
unknown"), removed its workspaces, and a fresh attempt re-verified the same
tree to `PASSED`; a registered `custodian session` lease deferred dispatch for
its whole lifetime, and the next attempt passed after it exited. Trees are
reproducible across runs: the same draft produced tree `6fa0af73…` in both
soak runs. One lesson is recorded in the driver itself: the first run's
step 5 "failed" because it expected a re-verification the daemon correctly
refused.
