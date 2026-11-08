#!/usr/bin/env bash
# Custodian on the droplet -- one idempotent command, run as root on the host.
#
# What it does, in order (each step echoes, each step is safe to repeat):
#   1. preflight     python >= 3.11 with tomllib, git, bubblewrap, systemd, the target repo
#   2. home repo     /root/custodian: a standalone git repository holding Custodian's own
#                    code, synced from the monorepo checkout's custodian/ directory. The
#                    daemon never runs from inside the repository it maintains.
#   3. policy+state  /etc/custodian/dialectic.toml (outside the repo, validated),
#                    /etc/custodian/dialectic.env (0600, the provider credential goes here),
#                    /var/lib/custodian/dialectic (the evidence archive + ledgers)
#   4. doctor        the sandbox must actually create its namespaces here, or we stop
#   5. trial         one foreground attempt against the live draft: PASSED or FAILED is
#                    evidence; only a controller error aborts the install
#   6. service       a SYSTEM-scope systemd unit, enabled and started; status printed
#
# Nothing here touches the dialectic working tree, index, branches or services.
set -euo pipefail

TARGET_REPO=${CUSTODIAN_TARGET_REPO:-/root/DwoodAmo/dialectic}
SOURCE_DIR=${CUSTODIAN_SOURCE_DIR:-$TARGET_REPO/custodian}
HOME_REPO=${CUSTODIAN_HOME:-/root/custodian}
STATE_DIR=${CUSTODIAN_STATE_DIR:-/var/lib/custodian/dialectic}
POLICY=${CUSTODIAN_POLICY:-/etc/custodian/dialectic.toml}
ENV_FILE=${CUSTODIAN_ENV_FILE:-/etc/custodian/dialectic.env}
PYTHON=${CUSTODIAN_PYTHON:-/usr/bin/python3}
INSTALL_SERVICE=${CUSTODIAN_INSTALL_SERVICE:-1}

step() { printf '\n==> %s\n' "$*"; }
die()  { printf 'custodian install: %s\n' "$*" >&2; exit 2; }

[ "$(id -u)" = 0 ] || die "run as root (the system unit and /var/lib/custodian need it)"

step "1/6 preflight"
"$PYTHON" - <<'PY' || die "python >= 3.11 with tomllib is required (CUSTODIAN_PYTHON=$PYTHON)"
import sys, tomllib
assert sys.version_info >= (3, 11), sys.version
print("python", sys.version.split()[0], sys.executable)
PY
git --version
bwrap --version || die "bubblewrap is required (apt-get install bubblewrap)"
systemctl --version | head -1 || die "systemd is required for the system-scope service"
git -C "$TARGET_REPO" rev-parse --show-toplevel >/dev/null || die "target repository not found: $TARGET_REPO"
[ -f "$SOURCE_DIR/custodian/engine.py" ] || die "Custodian source not found at $SOURCE_DIR (pull the branch that carries custodian/ first)"
SOURCE_COMMIT=$(git -C "$TARGET_REPO" rev-parse --short HEAD)
echo "target repo $TARGET_REPO @ $SOURCE_COMMIT"

step "2/6 home repository $HOME_REPO"
if [ ! -d "$HOME_REPO/.git" ]; then
  mkdir -p "$HOME_REPO"
  git -C "$HOME_REPO" init -q -b main
fi
if [ -n "$(git -C "$HOME_REPO" status --porcelain)" ]; then
  die "$HOME_REPO has uncommitted changes; commit or discard them before syncing"
fi
# Mirror the source tree exactly (files the source dropped disappear too) with
# tools every host has: clear the tracked tree, copy, then let `git add -A`
# compute the difference. No rsync dependency.
if git -C "$HOME_REPO" rev-parse --verify -q HEAD >/dev/null; then
  git -C "$HOME_REPO" rm -r -q --quiet . >/dev/null 2>&1 || true
fi
(cd "$SOURCE_DIR" && tar --exclude='./.git' --exclude='__pycache__' --exclude='*.pyc' -cf - .) | (cd "$HOME_REPO" && tar -xf -)
git -C "$HOME_REPO" add -A
if git -C "$HOME_REPO" diff --cached --quiet; then
  echo "home repository already matches $SOURCE_DIR"
else
  git -C "$HOME_REPO" -c user.name=Custodian -c user.email=custodian@localhost \
    commit -q -m "sync: custodian/ from dialectic@$SOURCE_COMMIT"
  echo "committed sync from dialectic@$SOURCE_COMMIT"
fi
git -C "$HOME_REPO" log --oneline -1

step "3/6 policy, credential file and state directory"
install -d -m 0700 "$(dirname "$POLICY")" "$(dirname "$ENV_FILE")" "$STATE_DIR"
if [ ! -f "$POLICY" ]; then
  install -m 0600 "$SOURCE_DIR/deploy/droplet/dialectic.toml" "$POLICY"
  echo "installed policy $POLICY from the kit"
else
  echo "keeping existing policy $POLICY (kit copy: $SOURCE_DIR/deploy/droplet/dialectic.toml)"
fi
if [ ! -f "$ENV_FILE" ]; then
  umask 077
  cat > "$ENV_FILE" <<'EOF'
# Read by systemd (EnvironmentFile=) for the Custodian daemon only.
# Model maintenance stays off until the policy carries a [model] table AND this
# variable holds a real key. Never commit this file; it is root-only (0600).
ANTHROPIC_API_KEY=
EOF
  umask 022
  echo "created $ENV_FILE (credential empty: model maintenance disabled)"
else
  echo "keeping existing $ENV_FILE"
fi
chmod 0600 "$ENV_FILE"

CUSTODIAN=("$PYTHON" -m custodian --repo "$TARGET_REPO" --state-dir "$STATE_DIR")
cd "$HOME_REPO"

step "4/6 doctor (sandbox probe + evidence audit)"
"${CUSTODIAN[@]}" doctor --config "$POLICY" --scope system || die "doctor failed: isolation or evidence integrity is not available on this host"

step "5/6 foreground trial attempt against the live draft"
set +e
"${CUSTODIAN[@]}" run --config "$POLICY" --intent "Install trial: verify the current draft" \
  > "$STATE_DIR/install-trial.json"
trial=$?
set -e
case $trial in
  0) echo "trial outcome: PASSED (configured checks exited zero against the captured draft)";;
  1) echo "trial outcome: FAILED/REJECTED/UNVERIFIED -- that is evidence, not an install error";;
  *) die "trial could not execute (exit $trial); see $STATE_DIR/install-trial.json";;
esac
"$PYTHON" - "$STATE_DIR/install-trial.json" <<'PY'
import json, sys
a = json.load(open(sys.argv[1]))
print("attempt", a["id"], a["status"], "-", a.get("reason", ""))
print("input tree", a["input_tree"], "base", a["base"][:12])
for c in a.get("checks", []):
    print("check", c["argv"][:2], "exit", c["exit_code"], "stdout blob", c["stdout_blob"], "stderr blob", c["stderr_blob"])
PY

if [ "$INSTALL_SERVICE" != 1 ]; then
  step "6/6 service install skipped (CUSTODIAN_INSTALL_SERVICE=$INSTALL_SERVICE)"
  exit 0
fi

step "6/6 system-scope service"
"${CUSTODIAN[@]}" service install --config "$POLICY" --scope system --environment-file "$ENV_FILE" --start
"${CUSTODIAN[@]}" service status --scope system

cat <<EOF

Custodian is installed.
  daemon logs      journalctl -u custodian-\$(printf %s "$TARGET_REPO" | sha256sum | cut -c1-24) -f
  state            ${CUSTODIAN[*]} state
  proposals        ${CUSTODIAN[*]} proposals
  diff             ${CUSTODIAN[*]} diff ATTEMPT_ID --full
  dispose          ${CUSTODIAN[*]} proposals --attempt ATTEMPT_ID --disposition rejected --reason '...'
  stop/uninstall   ${CUSTODIAN[*]} service stop --scope system
                   ${CUSTODIAN[*]} service uninstall --scope system

Claude Code SessionStart hook (per-repository settings, keep it out of git):
  $TARGET_REPO/.claude/settings.local.json
  {"hooks": {"SessionStart": [{"hooks": [{"type": "command",
     "command": "cd $HOME_REPO && ${CUSTODIAN[*]} hook SessionStart"}]}]}}

Codex MCP (read-only evidence tools):
  codex mcp add custodian -- $PYTHON -m custodian --repo $TARGET_REPO --state-dir $STATE_DIR mcp
  (run from $HOME_REPO, or install the package: $PYTHON -m pip install $HOME_REPO)
EOF
