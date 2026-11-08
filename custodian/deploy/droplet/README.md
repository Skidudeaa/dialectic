# Custodian on the droplet — runbook

One root shell on `167.99.113.232`, one command, and the dialectic monorepo at
`/root/DwoodAmo/dialectic` has a maintenance daemon whose durable unit is an
**attempted change**: captured draft bytes → isolated verification → an
append-only outcome a later edit can never inherit. This directory is the
whole kit: `install.sh` (idempotent, root), `dialectic.toml` (the execution
policy for this repository) and this runbook.

```
/root/custodian                 the NEW repository on the host: Custodian's own code,
                                synced from <monorepo>/custodian by install.sh; the
                                daemon never runs from inside the repo it maintains
/etc/custodian/dialectic.toml   execution policy (checks, protected paths, schedule) — outside the repo
/etc/custodian/dialectic.env    root-only EnvironmentFile; ANTHROPIC_API_KEY lives here or nowhere
/var/lib/custodian/dialectic    evidence: objects.git (candidates, logs, proposal branches),
                                events.sqlite3 (append-only), provider.sqlite3 (budget ledger)
/etc/systemd/system/custodian-<sha256(repo)[:24]>.service   system-scope unit, WantedBy=multi-user.target
```

## 0. Before you run anything — what was and was not verified

Built and proven on 2026-11-08 in a Linux x86-64 container (kernel 6.18,
bubblewrap 0.9.0 from Ubuntu noble, Python 3.11/3.12/3.13 present), **not on
the droplet** — this session had no SSH path to it (port 22 is refused from
the build network and no key is available). Everything below that names the
droplet is therefore a prediction from the repository's own records
(`CLAUDE.md`: `/root/DwoodAmo/dialectic`, `/usr/bin/python3` runs
`dialectic.service`, bubblewrap backs the Workshop) and is marked where it
matters:

| Claim | Status |
|---|---|
| 110/110 Custodian tests pass with real bubblewrap namespaces as root | **executed here** |
| Capture + verify of the real dialectic checkout (1,571 files) inside the sandbox | **executed here** (see `custodian/validation/2026-11-08-droplet-build/`) |
| `install.sh` steps 1–5 against the real dialectic clone | **executed here** with `CUSTODIAN_INSTALL_SERVICE=0` |
| System-scope unit render/install/start/status/uninstall | **executed against a fake `systemctl`** (no systemd in the build container) |
| Droplet Python is ≥ 3.11 (`tomllib`) | UNVERIFIED — docs say 3.12; `install.sh` aborts otherwise |
| Droplet bubblewrap accepts `--disable-userns` (needs ≥ 0.6) | UNVERIFIED — `doctor` creates the namespaces before anything runs |
| A live paid Anthropic request through the provider adapter | **not executed** anywhere yet; model maintenance ships OFF |

## 1. Get the kit onto the host

Until the pull request carrying `custodian/` is merged, do not switch the
production working tree's branch (both services run their checkouts). Clone
the branch beside it instead:

```sh
git clone --depth 1 -b claude/amazing-lamport-qbaxnw https://github.com/Skidudeaa/dialectic /root/dialectic-custodian-src
export CUSTODIAN_SOURCE_DIR=/root/dialectic-custodian-src/custodian
```

After the merge, a normal `git -C /root/DwoodAmo/dialectic pull` puts
`custodian/` on disk and the variable is unnecessary (the default source is
`<target repo>/custodian`).

## 2. Install

```sh
sudo bash "${CUSTODIAN_SOURCE_DIR:-/root/DwoodAmo/dialectic/custodian}/deploy/droplet/install.sh"
```

What you will see, step by step, and what each proves:

1. **preflight** — interpreter, git, bubblewrap and systemd are present; the
   target is a Git repository. A missing `tomllib` stops here (Python < 3.11).
2. **home repository** — `/root/custodian` is created (or fast-forwarded by
   one `sync:` commit) from the kit source. Uncommitted edits there abort.
3. **policy, credential file, state** — the kit's `dialectic.toml` is copied
   only if `/etc/custodian/dialectic.toml` does not exist; an existing policy
   is never overwritten. The env file is created 0600 with an EMPTY key.
4. **doctor** — bubblewrap really creates user/mount/pid/net namespaces here;
   the evidence archive audits clean. Non-zero exit aborts the install. Expect
   `"sandbox": {"available": true, "enforced": true}` and `"evidence": {"ok": true}`.
5. **trial** — one foreground attempt: the live draft (tracked + untracked
   files, the dirty CSS pass included) is captured, checked read-only in the
   sandbox, and the outcome is written to `/var/lib/custodian/dialectic/install-trial.json`.
   `PASSED` or `FAILED` are both success for the install: the point is that the
   outcome is bound to a tree id, not that the tree is green.
6. **service** — the system unit is written, `daemon-reload`, `enable --now`,
   then `status`. `ActiveState=active` is the only acceptable reading.

Set `CUSTODIAN_INSTALL_SERVICE=0` to stop after the trial (how the build
container rehearsed this script).

## 3. Verify it is really running

```sh
systemctl status "custodian-$(printf %s /root/DwoodAmo/dialectic | sha256sum | cut -c1-24)"
journalctl -u "custodian-$(printf %s /root/DwoodAmo/dialectic | sha256sum | cut -c1-24)" -f
cd /root/custodian
/usr/bin/python3 -m custodian --repo /root/DwoodAmo/dialectic --state-dir /var/lib/custodian/dialectic state
/usr/bin/python3 -m custodian --repo /root/DwoodAmo/dialectic --state-dir /var/lib/custodian/dialectic events | tail -40
/usr/bin/python3 -m custodian --repo /root/DwoodAmo/dialectic --state-dir /var/lib/custodian/dialectic audit
```

The daemon logs one JSON line per scheduler decision that is not
`DEFERRED`/`IDLE`. With `quiet_seconds = 900` the first `verify` attempt lands
fifteen minutes after the last edit; until then `daemon --once` honestly
reports deferral. `state` must show `Matches observed bytes: true` only while
the working tree is byte-identical to the checked candidate — edit one file
and watch it flip to `false` without the recorded PASSED changing.

## 4. The checks, and why they are what they are

`dialectic.toml` runs dialectic's **Postgres-free pytest modules**
(`--ignore-glob=*_pg.py`) with the system `/usr/bin/python3` — the interpreter
`dialectic.service` itself runs, whose dist-packages live under `/usr` and are
therefore visible inside the sandbox without any extra mount. The 34 `*_pg.py`
modules need `dialectic_test` over TCP, which the sandbox cannot and must not
reach: a verdict that depended on a shared mutable database is exactly the
"unrecordable external state" the architecture refuses to launder. Frontend
`vitest` is excluded structurally: `node_modules` is gitignored, so it is
never part of a candidate, and the repository's own directory may not be
mounted as a runtime. Both remain the operator's hand-run gates (CLAUDE.md
Quick Start), and `UNVERIFIED` is what Custodian records when a policy has no
checks — never a quiet pass.

If the trial reports `FAILED`, read the evidence before changing anything:

```sh
/usr/bin/python3 -m custodian --repo /root/DwoodAmo/dialectic --state-dir /var/lib/custodian/dialectic log <stderr_blob from install-trial.json>
```

A test that needs an environment variable or a network service inside the
sandbox is a real finding about that test, and the right fix is a
`--deselect` in the policy with the reason written beside it — not a wider
mount.

## 5. Enabling model maintenance (optional, off by default)

1. Put the key in `/etc/custodian/dialectic.env` (`ANTHROPIC_API_KEY=sk-ant-...`), keep 0600.
2. Uncomment the `[model]` table in `/etc/custodian/dialectic.toml`; confirm
   the two prices against the current Anthropic price list — the budget ledger
   is accounting at the rates you write, not an invoice cap.
3. `systemctl restart custodian-<id>` so the unit re-reads the EnvironmentFile.
4. Make one explicit request before trusting `auto_on_failure`:

```sh
cd /root/custodian && /usr/bin/python3 -m custodian --repo /root/DwoodAmo/dialectic --state-dir /var/lib/custodian/dialectic \
  model --config /etc/custodian/dialectic.toml --intent 'Repair the observed check failure while preserving the public API'
/usr/bin/python3 -m custodian --repo /root/DwoodAmo/dialectic --state-dir /var/lib/custodian/dialectic budget --config /etc/custodian/dialectic.toml
```

No live paid request has been made through this adapter in any build so far;
the contract (count_tokens → atomic reservation → Messages API → settle) is
proven only against the loopback fixture in `tests/test_provider.py`. The
first real request is the moment that closes.

## 6. Connect the foreground tools

The daemon is useless to a Claude Code or Codex session that cannot see its
evidence. Two read-only doors, neither of which can run checks or change
source:

**Claude Code SessionStart hook** — `/root/DwoodAmo/dialectic/.claude/settings.local.json`
(machine-local; the root `.gitignore` already excludes `.claude/settings.json`):

```json
{"hooks": {"SessionStart": [{"hooks": [{"type": "command",
  "command": "cd /root/custodian && /usr/bin/python3 -m custodian --repo /root/DwoodAmo/dialectic --state-dir /var/lib/custodian/dialectic hook SessionStart"}]}]}}
```

**Codex MCP** — `codex mcp add custodian -- /usr/bin/python3 -m custodian --repo /root/DwoodAmo/dialectic --state-dir /var/lib/custodian/dialectic mcp`
(run from `/root/custodian`, or `pip install /root/custodian` once so the
module resolves from anywhere).

Interactive sessions that should DEFER the daemon start through the lease:
`custodian --repo … --state-dir … session -- claude`.

## 7. Reviewing what it proposes

```sh
custodian proposals
custodian diff ATTEMPT_ID --full
git -C /root/DwoodAmo/dialectic fetch /var/lib/custodian/dialectic/objects.git refs/heads/custodian/XXXX:refs/heads/custodian/XXXX
custodian proposals --attempt ATTEMPT_ID --disposition accepted --reason '...'
```

Nothing merges, pushes or restarts on its own. A `custodian/*` branch is a
candidate with evidence attached; integration stays a human act, and the
dialectic deploy ritual (migration → restart → release flip) is untouched.

## 8. Rollback

```sh
cd /root/custodian && /usr/bin/python3 -m custodian --repo /root/DwoodAmo/dialectic --state-dir /var/lib/custodian/dialectic service uninstall --scope system
rm -rf /root/custodian /etc/custodian            # code + policy + credential file
# /var/lib/custodian/dialectic is evidence; delete it only when you mean to.
```

The dialectic working tree, index, refs and services were never written to,
so there is nothing to roll back there.

## 9. Publishing the new repository to GitHub (when you want it)

`/root/custodian` already has `main` with one commit per sync. To publish:

```sh
cd /root/custodian && git remote add origin git@github.com:Skidudeaa/custodian.git && git push -u origin main
```

Or, for the full per-file history from the monorepo instead of sync commits:
`git -C /root/DwoodAmo/dialectic subtree split --prefix=custodian -b custodian-standalone`
and push that branch to the new remote.
