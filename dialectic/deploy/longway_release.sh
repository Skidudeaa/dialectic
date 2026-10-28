#!/bin/bash
# The Long Way house: build the frontend with the longway organ from this worktree and release it the way
# Dialectic releases (immutable directory, atomic symlink flip, nginx reload). Run from anywhere as root.
#
#   dialectic/deploy/longway_release.sh            build, release, reload
#   dialectic/deploy/longway_release.sh --dry-run  build only, print where it would go
#
# WHY a separate script and not Dialectic's: the two instances share one codebase and must never share a
# release directory; the symlink names, the organ variable and the worktree are the three things that differ.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP="$HERE/../frontend/app"
RELEASES=/var/www/longway-releases
CURRENT=/var/www/longway-current
COMMIT="$(git -C "$HERE" rev-parse --short HEAD)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
NAME="$STAMP-longway-$COMMIT"

cd "$APP"
if [ ! -d node_modules ]; then npm ci --no-audit --no-fund; fi
VITE_ORGAN=longway npm run build
test -f dist/index.html
test -f dist/manifest.webmanifest
grep -q '"name":"The Long Way"' dist/manifest.webmanifest || { echo "manifest is not The Long Way; refusing to release" >&2; exit 1; }
if ! grep -q "The Long Way" dist/index.html; then echo "index.html does not name The Long Way; refusing to release" >&2; exit 1; fi

if [ "${1:-}" = "--dry-run" ]; then echo "built $NAME in $APP/dist (not released)"; exit 0; fi
mkdir -p "$RELEASES"
cp -r dist "$RELEASES/$NAME"
chmod -R a+rX "$RELEASES/$NAME"
ln -sfn "$RELEASES/$NAME" "$CURRENT.tmp" && mv -Tf "$CURRENT.tmp" "$CURRENT"
nginx -t
systemctl reload nginx
echo "released $NAME -> $CURRENT"
ls -1 "$RELEASES" | tail -3
