#!/usr/bin/env bash
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
capture_root="$repo_root/capture-ios"
project_root="$capture_root/SomacuraCapture/SomacuraCapture"
project="$project_root/SomacuraCapture.xcodeproj"
derived_data="${SOMACURA_DERIVED_DATA:-/tmp/SomacuraCaptureDerived}"

"$capture_root/scripts/build-extension.sh"

manifest="$capture_root/web-extension/dist/manifest.json"
test -f "$manifest"
! rg -q '"default_popup"' "$manifest"
rg -q '"nativeMessaging"' "$manifest"
rg -q '"action"' "$manifest"
! rg -i -q 'obsidian://' "$capture_root/web-extension/src"
native_identifier="$({
  xcodebuild \
    -project "$project" \
    -target SomacuraCapture \
    -configuration Debug \
    -showBuildSettings 2>/dev/null
} | awk -F ' = ' '
  $1 ~ /^[[:space:]]*PRODUCT_BUNDLE_IDENTIFIER$/ { value = $2 }
  END { print value }
')"
test -n "$native_identifier"
rg -Fq "\"$native_identifier\"" "$capture_root/web-extension/dist/background.js"
cmp \
  "$capture_root/web-extension/dist/background.js" \
  "$project_root/SomacuraCapture Extension/Resources/background.js"

xcodebuild \
  -project "$project" \
  -scheme SomacuraCapture \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath "$derived_data" \
  CODE_SIGNING_ALLOWED=NO \
  build

ipad_simulator_udid="${IPAD_SIMULATOR_UDID:-}"
if [[ -z "$ipad_simulator_udid" ]]; then
  ipad_simulator_udid="$(
    xcrun simctl list devices available \
      | sed -nE 's/.*iPad.*\(([0-9A-F-]{36})\) \((Booted|Shutdown)\).*/\1/p' \
      | awk 'NR == 1 { value = $0 } END { print value }'
  )"
fi
if [[ -z "$ipad_simulator_udid" ]]; then
  echo "No available iPad Simulator; the native XCTest gate cannot be skipped" >&2
  exit 1
fi
xcodebuild \
  -project "$project" \
  -scheme SomacuraCapture \
  -destination "platform=iOS Simulator,id=$ipad_simulator_udid" \
  -derivedDataPath "$derived_data" \
  -parallel-testing-enabled NO \
  -enableCodeCoverage NO \
  CODE_SIGNING_ALLOWED=NO \
  test

git diff --check
