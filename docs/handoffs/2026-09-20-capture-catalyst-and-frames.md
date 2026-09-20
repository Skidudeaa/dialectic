# Handoff 2026-09-20 — Somacura Capture: Mac Catalyst + embedded-frame fix

Self-contained. Read this before touching `capture-ios/`. Every claim below was
observed this session unless marked UNVERIFIED.

**Where it lives:** `~/somacura-capture` → `/Users/thomasamosson/jan25/dialectic/capture-ios/`
(symlink, 2026-09-20). Open the app project with
`open ~/somacura-capture/SomacuraCapture/SomacuraCapture/SomacuraCapture.xcodeproj`.

## 0. Resume here (state at 2026-09-20 09:09Z)

The single blocking item is an OWNER action nobody can do from a terminal:
**set a destination room in the Mac app.** Until then nothing files and the
last unproven Mac path (§4.1) cannot run. 5 captures on disk, all
`pending / no_room`, attempts 0; shared `Library/Preferences/` is empty.

Click path (from `CaptureViews.swift`): open SomacuraCapture (window title
"Reading Rail") → top of the sidebar, first tile **Destination**, value
"Choose room" → sheet "Destination" lists the account's Dialectic rooms (Home
room is labelled "Home") → click one (teal checkmark) → back on the main
screen, retry the "Queued / needs attention" captures → then capture one page
from Safari. Empty list: press **Refresh** in the sheet; still empty with no
banner = the rooms API returned none for this account (backend/membership, not
Mac). Launch the registered build with:
`open "$HOME/Library/Developer/Xcode/DerivedData/SomacuraCapture-cznjzffdlbddrmfuxdaaivsexqys/Build/Products/Debug-maccatalyst/SomacuraCapture.app"`

First thing a new session should run to see whether that happened:

```bash
G="$HOME/Library/Group Containers/group.com.example.unconfigured.SomacuraCapture"
ls "$G/Library/Preferences/"                       # non-empty = a room was chosen
for d in "$G/Captures"/*/; do python3 -c "import json,sys;s=json.load(open(sys.argv[1]+'state.json'));print(s.get('status'),s.get('error_category'),s.get('last_error'))" "$d"; done
```

`status=filed` on a capture made from Safari AFTER the room was set = Mac done.
`Sign in to file this capture` / an auth category = extension cannot read the
app's keychain item → add `keychain-access-groups` to both entitlements files.

## 1. What this is

`capture-ios/` = iOS app + Safari Web Extension ("Somacura Capture"). Toolbar
button → `content.js` extracts the rendered page to Markdown (Defuddle 0.19.3
article path; Turndown for selection/fallback) → `background.js`
`sendNativeMessage` → `SafariWebExtensionHandler` → `CaptureDeliveryService`
commits `Captures/<uuid>/{capture.json,content.md,state.json}` in the App Group
container BEFORE any network, then files to a Dialectic room
(`https://dialectic.somacura.org`). Credentials: Keychain, access group = the
App Group id. Default room: App Group `UserDefaults`.

Paths: Xcode project `capture-ios/SomacuraCapture/SomacuraCapture/`; extension
TypeScript `capture-ios/web-extension/` (tracked `dist/` is copied into
`SomacuraCapture Extension/Resources/`).

## 2. State of the branch

Branch `feat/ipad-reading-rail`, 5 ahead of origin, NOT pushed. Working tree
clean except untracked `.omc/`, `xcuserdata/`, `.DS_Store`, and this file.

| Commit | What |
|---|---|
| `6c0bd7e` | Mac Catalyst destination: xcconfig solely owns `IPHONEOS_DEPLOYMENT_TARGET = 17.0` (8 pbxproj overrides removed), `SUPPORTS_MACCATALYST = YES`, `DERIVE_MACCATALYST_PRODUCT_BUNDLE_IDENTIFIER = NO`, `DEVELOPMENT_TEAM = U4GLQGFNT3`, both entitlements gain `app-sandbox` + `network.client`. Adds `capture-ios/scripts/accept-catalyst.sh`. |
| `00ad25b` | `iframe, object, embed` stripped from the cloned document before Defuddle and added to `UNSAFE_REMOVALS`. Regenerated `dist/content.js` + `Resources/content.js`. Adds `tests/acceptance-embedded-frames.test.ts` and `capture-ios/scripts/accept-embedded-frames.sh`. Behavior change: video embeds inside an article are dropped too. |

## 3. Proven

- `bash capture-ios/scripts/accept-catalyst.sh` → 15/15 (17.0 resolves for all 3
  targets × 2 configs; entitlements; Catalyst unit tests 17/17; iOS Simulator
  `build-for-testing`). ~90 s. Writes only to a temp dir.
- `bash capture-ios/scripts/accept-embedded-frames.sh` → vitest 21/21, typecheck,
  `dist/` == `Resources/` == fresh build. ~3 s. Needs existing `node_modules`.
- Development-signed Catalyst build succeeds (`-allowProvisioningUpdates`; Apple
  issued "Mac Catalyst Team Provisioning Profile"s for both bundle IDs). Signed
  entitlements carry sandbox, network client, app group; macOS floor 14.0.
- On the owner's Mac: app launches, App Group container created, sign-in works
  (keychain add + network from the sandbox), Safari lists and runs the
  extension, four captures committed to disk.
- Frame fix on real pages: gomerblog 07:37Z capture has a raw ad `<iframe>`;
  every capture after the fix has no raw HTML (incl. gomerblog 08:10Z).
- iOS/iPadOS development profiles for the placeholder IDs exist, include the
  App Group, 8 devices, expire 2027-08-29. `com.example.unconfigured` therefore
  WORKS for development signing on both platforms; changing it is cosmetic
  until TestFlight/App Store.
- The file-protection check (`CaptureCore.swift` ~873, `.complete` required
  off-simulator) passes on this Mac, sandboxed. An earlier suspicion that it
  would fail on Catalyst was refuted.

## 4. NOT proven / open

1. **Extension-side keychain read on Mac.** No default room has ever been set
   (`…/Group Containers/group.com.example.unconfigured.SomacuraCapture/Library/Preferences/`
   is empty), so all 5 captures are `pending / no_room`, attempts 0.
   `CaptureDelivery.swift:60` checks the room BEFORE credentials, so that path
   has never executed. Owner action: app → Destination ("Choose room") → pick →
   retry pending → capture once from Safari. If the toolbar says "Sign in to
   file this capture" while the app is signed in, add `keychain-access-groups`
   to both entitlements files (signed bundles currently have none). If the room
   list is empty after Refresh with no banner, it is a backend/membership
   question, not a Mac one.
2. **iPhone/iPad on hardware.** Not run this session. Only the simulator build.
3. **CSS-styled code blocks flatten.** Repro:
   `https://studio.24hourwallpaper.com/build/guide.html` — the JSON example is
   `<div class="format-block">` with `white-space: pre` + monospace, no `<pre>`,
   so Defuddle collapses it to one escaped line. Proposed fix: before Defuddle,
   find block elements whose COMPUTED `white-space` is `pre`/`pre-wrap` with a
   monospace font and rewrite them in the clone as `<pre><code>`. Computed style
   exists only on the live document → map live↔clone by position, never mutate
   the live page. UNVERIFIED whether jsdom's `getComputedStyle` resolves
   `white-space` from a `<style>` block; settle that before writing the test.
   Not started.
4. Deliberately NOT fixing: that page's section titles are `<div class="card-title">`
   (not headings) — promoting styled divs to `##` is font-size guessing. The
   stray "Health" category line on gomerblog is site chrome Defuddle kept.
5. No independent review of either commit. Nothing pushed, nothing deployed.

## 5. Traps found (do not re-derive)

- **OMC is DOWN.** Homebrew auto-upgraded `python@3.14` 3.14.4_1 → 3.14.7 at
  01:57 CDT and removed the old Cellar dir. `~/.local/bin/omc`, `omc-pair`,
  `codex`, and the B runtime's `bin/omc-pair-runtime` all hard-code
  `/opt/homebrew/Cellar/python@3.14/3.14.4_1/…`. Repair with the saved kit's
  `kit.py doctor` → `install` in a terminal with no agent sessions open; then
  `brew pin python@3.14`. Commit `00ad25b` was made directly by the lead with
  the owner's explicit authorization because of this.
- **Codex worker sandbox cannot run `xcodebuild`** (DerivedData/CoreSimulator
  denied; swift macro plugin traps). Workers can edit Xcode projects; the lead
  must run every build/test check outside the sandbox.
- **Codex trust is per exact path.** Trusting the repo root does not cover a
  worktree under `.worktrees/`. `codex` needs a real TTY (`! codex` fails).
- **`/opt/homebrew/opt/node@22` is a stale link to node 25.2.1.** Real Node 22 =
  `~/.nvm/versions/node/v22.19.0`. `build-extension.sh` requires 22 and also
  runs `npm ci` (network; deletes `node_modules`). Minimal rebuild:
  `SOMACURA_NATIVE_APPLICATION_IDENTIFIER=com.example.unconfigured.SomacuraCapture npm run build`
  under Node 22, then copy `dist/{content.js,background.js,manifest.json}` to
  `Resources/`.
- **`pluginkit -m -i <bundle id>` returns "(no matches)" on this machine even
  when registered.** Use `pluginkit -m -A -D -vv | grep -A3 -i somacura`.
- **Any build product with the same bundle ID registers as a second Safari
  extension** (duplicate "0.1.0" entries). Never leave signed/ad-hoc builds in
  temp dirs; build into Xcode's DerivedData. Registered copy now:
  `~/Library/Developer/Xcode/DerivedData/SomacuraCapture-cznjzffdlbddrmfuxdaaivsexqys/Build/Products/Debug-maccatalyst/`.
- Ad-hoc Catalyst unit tests need `CODE_SIGN_ENTITLEMENTS=` cleared (app-group
  entitlement requires a profile); see `accept-catalyst.sh`.
- Captures are immutable: the 07:37Z gomerblog capture keeps its iframe forever.

## 6. Cleanup owed (agent was denied `rm`/kill in this mode; owner runs)

```bash
cd /Users/thomasamosson/jan25/dialectic
git worktree remove --force .worktrees/capture-catalyst   # also removes the preserved worker worktree under it
git branch -D omc/capture-catalyst-baseline omc-team/work-id-capture-catalyst-a-att/worker-1
rm .worktrees/capture-catalyst-a.patch
```

Everything on those branches is already on `feat/ipad-reading-rail`. Add
`xcuserdata/` to a `.gitignore`. OMC ledger record: work_id `capture-catalyst-a`,
attempt 1, completed, profile `omc-pair`, effective effort medium (observed in
worker argv), baseline `e11d6d3`, no strikes.

## 7. Commands

```bash
# Mac build + register (stable path)
cd capture-ios/SomacuraCapture/SomacuraCapture
xcodebuild -project SomacuraCapture.xcodeproj -scheme SomacuraCapture -configuration Debug \
  -destination 'platform=macOS,variant=Mac Catalyst' -allowProvisioningUpdates build

# Gates
bash capture-ios/scripts/accept-catalyst.sh
bash capture-ios/scripts/accept-embedded-frames.sh

# Inspect captures
ls "$HOME/Library/Group Containers/group.com.example.unconfigured.SomacuraCapture/Captures"
```

## 8. Next, in order

1. Owner: pick a room, retry, capture from Safari → closes §4.1 (or triggers the
   `keychain-access-groups` fix).
2. Owner: Run to iPad from Xcode → closes §4.2.
3. Code-block fix (§4.3): acceptance test first, then fix, rebuild under Node 22,
   rebuild the Mac app.
4. Repair the OMC kit; pin python.
5. Before TestFlight: replace `SOMACURA_BUNDLE_PREFIX` (one xcconfig line) and
   rebuild the extension so `background.js` carries the new identifier.
