#!/usr/bin/env bash
set -euo pipefail

capture_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
web_root="$capture_root/web-extension"
resource_root="$capture_root/SomacuraCapture/SomacuraCapture/SomacuraCapture Extension/Resources"
project="$capture_root/SomacuraCapture/SomacuraCapture/SomacuraCapture.xcodeproj"
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
if [[ ! "$native_identifier" =~ ^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$ ]]; then
  echo "Could not resolve SomacuraCapture PRODUCT_BUNDLE_IDENTIFIER" >&2
  exit 1
fi

node_major="$(node -p 'process.versions.node.split(".")[0]')"
if [[ "$node_major" != "22" ]]; then
  echo "Somacura Capture requires Node 22; current Node is $(node --version)" >&2
  exit 1
fi

cd "$web_root"
npm ci
npm test
npm run typecheck
SOMACURA_NATIVE_APPLICATION_IDENTIFIER="$native_identifier" npm run build

mkdir -p "$resource_root"
cp "$web_root/dist/background.js" "$resource_root/background.js"
cp "$web_root/dist/content.js" "$resource_root/content.js"
cp "$web_root/dist/manifest.json" "$resource_root/manifest.json"
rm -rf "$resource_root/icons"
cp -R "$web_root/dist/icons" "$resource_root/icons"

rg -Fq "\"$native_identifier\"" "$web_root/dist/background.js"
cmp "$web_root/dist/background.js" "$resource_root/background.js"
