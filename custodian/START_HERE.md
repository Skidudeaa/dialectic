# Custodian 0.2.0 — start here

This bundle contains the complete source, an installable Python wheel, all project documentation, the integration tests, original test output, and the validation record. Nothing starts automatically when you extract or install it.

## Read in this order

1. **START_HERE.md** — install and first run.
2. **README.md** — full operating guide: policies, isolation, scheduling, models, MCP, hooks, services, and recovery.
3. **ARCHITECTURE.md** — the structural bet, implemented mechanisms, evidence, and operational limits.
4. **VALIDATION.json** and **TEST_RESULTS.txt** — the recorded 105-test pass and end-to-end trial; external checks not performed are named.
5. **examples/custodian.toml** — model-disabled policy template to copy outside your target repository.
6. **PACKAGE_CONTENTS.md** and **SHA256SUMS** — inventory and integrity verification.

## Requirements

Python 3.11 or newer, Git, Linux, and Bubblewrap with working user namespaces. Bubblewrap 0.12.0 was exercised; the code requires flags including `--disable-userns`, so an older distribution package may not work. Check with `doctor` instead of assuming binary presence is sufficient.

Your target must be a Git repository with at least one commit. Its test tools, libraries, and service fixtures must be available in the configured execution runtime. The bundle does not include Python, Git, Bubblewrap, project dependencies, credentials, or a running daemon state database.

The default execution boundary requires Linux. macOS service generation is implemented, but Linux isolation does not run on macOS. Explicit `trusted` mode is a compatibility option for operator-controlled commands and is prohibited for model-produced edits.

## Install the bundled wheel

From this extracted directory:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --no-index --no-deps dist/custodian_change_store-0.2.0-py3-none-any.whl
.venv/bin/custodian --help
```

The application has no third-party Python runtime dependencies. Creating a virtualenv may require your operating system's Python venv package. The wheel installation above does not fetch packages from the network.

For development, use `python3 -m pip install -e .` in a virtualenv. That route may require build dependencies. To run directly without installation, invoke `python3 -m custodian` from the extracted directory.

## Configure the first repository

Copy `examples/custodian.toml` to a location outside the repository you want to maintain. Replace its check command with that project's real verification command. Set absolute paths:

```sh
custodian_repo=/absolute/path/to/your/project
custodian_state=/absolute/path/outside/project/custodian-state
custodian_policy=/absolute/path/outside/project/custodian.toml

.venv/bin/custodian --repo "$custodian_repo" --state-dir "$custodian_state" doctor --config "$custodian_policy"
.venv/bin/custodian --repo "$custodian_repo" --state-dir "$custodian_state" run --config "$custodian_policy" --intent 'Verify the current draft'
.venv/bin/custodian --repo "$custodian_repo" --state-dir "$custodian_state" daemon --config "$custodian_policy"
```

Policy and state must stay outside the target repository. Use an interpreter visible inside the sandbox: `/usr/bin/python3` works for the standard-library trial, while a custom virtualenv may require an explicit dependency mount through `runtime_paths`. A virtualenv within the target is not allowed as that dependency mount because it would expose foreground files.

The sample policy makes no model calls. Optional model use requires explicit source-disclosure patterns, a model identifier, rates, and a credential environment variable; see README.md. Credentials are never included in this bundle.

## Enable a service only after the foreground trial

```sh
.venv/bin/custodian --repo "$custodian_repo" --state-dir "$custodian_state" service render --config "$custodian_policy"
.venv/bin/custodian --repo "$custodian_repo" --state-dir "$custodian_state" service install --config "$custodian_policy" --start
.venv/bin/custodian --repo "$custodian_repo" --state-dir "$custodian_state" service status
```

Keep the installation at a stable path after activation. On Linux this uses a user systemd manager; the package does not create a login bus or enable lingering automatically. Native service activation was not exercised in the build environment because that manager was unavailable. No service was installed on your droplet.

## Verify the bundle and implementation

```sh
sha256sum -c SHA256SUMS
python3 -m unittest discover -s tests -v
```

The full tests exercise actual Linux isolation and require the tools above. The original validation records report the executed environment; they do not establish compatibility with an arbitrary host. Provider tests use a local test server and do not incur paid model calls.

## Amendment 2026-11-08 — this is now a co-project of the dialectic monorepo (amend-beside)

The bundle above was imported as `custodian/` in `Skidudeaa/dialectic`, the
repository it was built to maintain. Prefer what follows over the bundle-era
lines about wheels, `SHA256SUMS` and the user systemd manager:

- **Run it from the checkout.** `cd custodian && python3 -m unittest discover -s tests`
  (110 tests, bubblewrap required) and `python3 -m custodian --help`. There is no
  wheel in the tree; `pip install -e .` or `pip install /path/to/custodian` still
  works because `pyproject.toml` is unchanged. The 0.2.0 bundle's own records
  live under `validation/0.2.0-bundle/`; this build's under
  `validation/2026-11-08-droplet-build/`.
- **Servers use `--scope system`.** `custodian service install --scope system
  --environment-file /etc/custodian/<repo>.env --config … --start` writes
  `/etc/systemd/system/custodian-<id>.service` (`WantedBy=multi-user.target`)
  and drives plain `systemctl`. The per-user manager the text above describes
  is still the default (`--scope user`) and is right for a laptop; on a
  headless root host it does not exist until someone logs in.
- **The droplet is one command**: `deploy/droplet/install.sh`, with
  `deploy/droplet/README.md` as the runbook and `deploy/droplet/dialectic.toml`
  as the measured policy for this repository. It creates the standalone
  repository `/root/custodian` on the host, never runs the daemon from inside
  the repository it maintains, and leaves the dialectic working tree, index,
  refs and services untouched.
- **Debian-family hosts work now.** `/usr/bin/python3 -> /etc/alternatives/python3`
  used to be a dangling link inside the sandbox (every check: `execvp … No such
  file`); `/etc/alternatives` is now the one `/etc` entry mounted, read-only.
- **A scan is sub-second.** Blob ids are computed in-process in the archive's
  object format; see README.md's same-day amendment for the measurements.
