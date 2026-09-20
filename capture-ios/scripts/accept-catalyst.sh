#!/usr/bin/env bash
# Acceptance check for the Mac Catalyst readiness step (work_id capture-catalyst-a).
# Runs every check and reports all failures; exits non-zero if any failed.
# Build products go to a temporary directory so the source tree is never written.
#
# NOT covered: Safari actually loading the extension, app-group containers and
# keychain sharing. Those need a provisioned, signed run on a real Mac/device.
set -uo pipefail

capture_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project_dir="$capture_root/SomacuraCapture/SomacuraCapture"
project="$project_dir/SomacuraCapture.xcodeproj"
pbxproj="$project/project.pbxproj"
derived="$(mktemp -d "${TMPDIR:-/tmp}/somacura-accept.XXXXXX")"
trap 'rm -rf "$derived"' EXIT

failures=0
fail() { echo "ACCEPT FAIL: $*" >&2; failures=$((failures + 1)); }
pass() { echo "ACCEPT PASS: $*"; }

# 1. One deployment floor, owned by the xcconfig: 17.0 everywhere.
if grep -q "IPHONEOS_DEPLOYMENT_TARGET" "$pbxproj"; then
  fail "project.pbxproj still sets IPHONEOS_DEPLOYMENT_TARGET (the xcconfig must be the only owner)"
else
  pass "project.pbxproj sets no IPHONEOS_DEPLOYMENT_TARGET"
fi
for target in "SomacuraCapture" "SomacuraCapture Extension" "SomacuraCaptureTests"; do
  for configuration in Debug Release; do
    resolved="$(xcodebuild -project "$project" -target "$target" \
      -configuration "$configuration" -showBuildSettings 2>/dev/null |
      awk -F ' = ' '$1 ~ /^[[:space:]]*IPHONEOS_DEPLOYMENT_TARGET$/ { print $2 }')"
    if [[ "$resolved" == "17.0" ]]; then
      pass "$target/$configuration resolves IPHONEOS_DEPLOYMENT_TARGET=17.0"
    else
      fail "$target/$configuration resolves IPHONEOS_DEPLOYMENT_TARGET='$resolved', expected 17.0"
    fi
  done
done

# 2. Both signed bundles are sandboxed with outbound network, and keep the app group.
for entitlements in \
  "$project_dir/SomacuraCapture/SomacuraCapture.entitlements" \
  "$project_dir/SomacuraCapture Extension/SomacuraCaptureExtension.entitlements"; do
  name="$(basename "$entitlements")"
  plutil -lint "$entitlements" >/dev/null || fail "$name is not a valid plist"
  for key in "com.apple.security.app-sandbox" "com.apple.security.network.client"; do
    value="$(/usr/libexec/PlistBuddy -c "Print :$key" "$entitlements" 2>/dev/null)"
    if [[ "$value" == "true" ]]; then
      pass "$name has $key=true"
    else
      fail "$name lacks $key=true (got '$value')"
    fi
  done
  group="$(/usr/libexec/PlistBuddy -c "Print :com.apple.security.application-groups:0" "$entitlements" 2>/dev/null)"
  if [[ "$group" == '$(SOMACURA_APP_GROUP_IDENTIFIER)' ]]; then
    pass "$name keeps the app group"
  else
    fail "$name app group changed (got '$group')"
  fi
done

# 3. Unit tests on Mac Catalyst. Ad-hoc signed with entitlements cleared because
#    the app-group entitlement needs a provisioning profile this check cannot have.
if xcodebuild -project "$project" -scheme SomacuraCapture -configuration Debug \
  -destination 'platform=macOS,variant=Mac Catalyst' \
  -derivedDataPath "$derived/catalyst" \
  CODE_SIGN_IDENTITY=- CODE_SIGN_STYLE=Manual DEVELOPMENT_TEAM= \
  PROVISIONING_PROFILE_SPECIFIER= CODE_SIGN_ENTITLEMENTS= \
  test >"$derived/catalyst.log" 2>&1; then
  pass "Mac Catalyst unit tests: $(grep -E 'Executed [0-9]+ tests' "$derived/catalyst.log" | tail -1 | sed 's/^[[:space:]]*//')"
else
  fail "Mac Catalyst unit tests failed"
  grep -E "error:|Test Case .* failed|Executed [0-9]+ tests" "$derived/catalyst.log" | sort -u | head -30 >&2
fi

# 4. iOS still builds (app + extension + tests) at the unified floor.
if xcodebuild -project "$project" -scheme SomacuraCapture -configuration Debug \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath "$derived/ios" CODE_SIGNING_ALLOWED=NO \
  build-for-testing >"$derived/ios.log" 2>&1; then
  pass "iOS Simulator build-for-testing"
else
  fail "iOS Simulator build-for-testing failed"
  grep -E "error:" "$derived/ios.log" | sort -u | head -30 >&2
fi

if ((failures > 0)); then
  echo "ACCEPT RESULT: $failures check(s) failed" >&2
  exit 1
fi
echo "ACCEPT RESULT: all checks passed"
