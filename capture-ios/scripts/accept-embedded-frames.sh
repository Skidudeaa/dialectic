#!/usr/bin/env bash
# Acceptance check for OMC work_id capture-embedded-frames.
# Requires an existing web-extension/node_modules (no install, no network).
#
# Proves: the whole vitest suite (including tests/acceptance-embedded-frames.test.ts)
# passes, types check, and the tracked build outputs are exactly what the current
# source builds to, so the shipped extension carries the fix.
# NOT covered: behaviour inside real Safari on a real ad-laden page.
set -uo pipefail

capture_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
web_root="$capture_root/web-extension"
resource_root="$capture_root/SomacuraCapture/SomacuraCapture/SomacuraCapture Extension/Resources"
# Must equal the app's PRODUCT_BUNDLE_IDENTIFIER; build-extension.sh derives the
# same value from xcodebuild, which the worker sandbox cannot run.
native_identifier="com.example.unconfigured.SomacuraCapture"

# Select by reported version, not by path: on this machine Homebrew's
# opt/node@22 is a stale link to node 25.
for candidate in "$HOME"/.nvm/versions/node/v22.*/bin /opt/homebrew/opt/node@22/bin; do
  if [[ -x "$candidate/node" && "$("$candidate/node" --version 2>/dev/null)" == v22.* ]]; then
    PATH="$candidate:$PATH"
    break
  fi
done
export PATH

failures=0
fail() { echo "ACCEPT FAIL: $*" >&2; failures=$((failures + 1)); }
pass() { echo "ACCEPT PASS: $*"; }

node_major="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null)"
if [[ "$node_major" == "22" ]]; then pass "Node $(node --version)"; else fail "Node 22 required, found '$(node --version 2>/dev/null)'"; fi

cd "$web_root" || { echo "ACCEPT FAIL: $web_root missing" >&2; exit 1; }
[[ -d node_modules ]] || { echo "ACCEPT FAIL: node_modules missing (provisioned by the lead, never installed here)" >&2; exit 1; }

if npm test --silent >"${TMPDIR:-/tmp}/somacura-accept-vitest.$$" 2>&1; then
  pass "vitest: $(grep -E '^\s*Tests ' "${TMPDIR:-/tmp}/somacura-accept-vitest.$$" | tail -1 | sed 's/^[[:space:]]*//')"
else
  fail "vitest failed"
  grep -E "FAIL|AssertionError|Error:|✗|×|Tests " "${TMPDIR:-/tmp}/somacura-accept-vitest.$$" | head -30 >&2
fi
rm -f "${TMPDIR:-/tmp}/somacura-accept-vitest.$$"

if npm run typecheck --silent >/dev/null 2>&1; then pass "typecheck"; else fail "typecheck failed"; fi

# Rebuilding must be a byte-for-byte no-op: the tracked outputs already match source.
before="$(shasum -a 256 dist/content.js dist/background.js dist/manifest.json | shasum -a 256)"
if SOMACURA_NATIVE_APPLICATION_IDENTIFIER="$native_identifier" npm run build --silent >/dev/null 2>&1; then
  after="$(shasum -a 256 dist/content.js dist/background.js dist/manifest.json | shasum -a 256)"
  if [[ "$before" == "$after" ]]; then pass "tracked dist/ already equals a fresh build"; else fail "dist/ was stale: rebuild changed it"; fi
else
  fail "build failed"
fi
for artifact in content.js background.js manifest.json; do
  if cmp -s "dist/$artifact" "$resource_root/$artifact"; then
    pass "Resources/$artifact equals dist/$artifact"
  else
    fail "Resources/$artifact differs from dist/$artifact"
  fi
done

if ((failures > 0)); then
  echo "ACCEPT RESULT: $failures check(s) failed" >&2
  exit 1
fi
echo "ACCEPT RESULT: all checks passed"
