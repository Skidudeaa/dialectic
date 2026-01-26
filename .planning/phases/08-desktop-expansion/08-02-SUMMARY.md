---
phase: 08-desktop-expansion
plan: 02
subsystem: desktop
tags: [macos, react-native-macos, xcode, bare-workflow, metro]

# Dependency graph
requires:
  - phase: 08-01
    provides: Monorepo structure with packages/
provides:
  - macOS workspace at packages/macos
  - Native Xcode project for macOS builds
  - Metro configuration for monorepo resolution
  - @dialectic/app workspace dependency
affects: [08-04, 08-05, macos-builds, desktop-features]

# Tech tracking
tech-stack:
  added: [react-native-macos@0.81.1, @react-native-community/cli@20.1.0]
  patterns: [bare workflow for macOS, Podfile for CocoaPods, monorepo Metro resolution]

key-files:
  created:
    - packages/macos/package.json (@dialectic/macos workspace)
    - packages/macos/app.json (app name configuration)
    - packages/macos/index.js (AppRegistry entry point)
    - packages/macos/App.tsx (minimal React Native app)
    - packages/macos/tsconfig.json (TypeScript with @dialectic/app paths)
    - packages/macos/metro.config.js (monorepo-aware bundler config)
    - packages/macos/babel.config.js (module-resolver for workspace imports)
    - packages/macos/.gitignore (Pods, build artifacts)
    - packages/macos/macos/Podfile (CocoaPods configuration)
    - packages/macos/macos/.xcode.env (node binary path)
    - packages/macos/macos/DialecticMac.xcodeproj/project.pbxproj (Xcode project)
    - packages/macos/macos/DialecticMac.xcodeproj/xcshareddata/xcschemes/DialecticMac-macOS.xcscheme
    - packages/macos/macos/DialecticMac-macOS/AppDelegate.h
    - packages/macos/macos/DialecticMac-macOS/AppDelegate.mm
    - packages/macos/macos/DialecticMac-macOS/main.m
    - packages/macos/macos/DialecticMac-macOS/Info.plist
    - packages/macos/macos/DialecticMac-macOS/LaunchScreen.storyboard
  modified:
    - package.json (added "macos" workspace script)
    - yarn.lock (added macos workspace dependencies)

key-decisions:
  - "react-native-macos 0.81.1: Latest version matching mobile RN 0.81.x"
  - "Bare workflow over Expo: macOS not supported by Expo"
  - "Manual Xcode project: react-native-macos-init requires macOS, created manually"
  - "macOS 10.15 deployment target: Minimum for modern React Native"
  - "Standalone tsconfig: Extended config had incompatible moduleResolution"

patterns-established:
  - "macOS bare workflow: AppDelegate + RCTBridge pattern for native macOS"
  - "Podfile for macOS: Different from iOS pods, uses react-native-macos scripts"
  - "Window configuration via storyboard: 1200x800 default window size"

# Metrics
duration: 4min
completed: 2026-01-26
---

# Phase 8 Plan 2: macOS Workspace Summary

**React Native macOS workspace with bare workflow and Xcode project for native macOS builds**

## Performance

- **Duration:** 4 min
- **Started:** 2026-01-26T06:44:00Z
- **Completed:** 2026-01-26T06:48:54Z
- **Tasks:** 3
- **Files created:** 17
- **Files modified:** 2

## Accomplishments

- Created packages/macos workspace with react-native-macos 0.81.1
- Generated native Xcode project structure (manually, since on Linux)
- Configured Metro for monorepo dependency resolution
- Metro bundler starts successfully on port 8081
- TypeScript configuration passes
- Workspace recognized by yarn workspaces

## Task Commits

Each task was committed atomically:

1. **Task 1: Initialize macOS workspace with react-native-macos** - `9f0db34` (feat)
2. **Task 2: Generate native macOS Xcode project** - `23541d0` (feat)
3. **Task 3: Configure Metro for monorepo and test build** - `00dc832` (feat)

## Files Created/Modified

**Created:**
- `packages/macos/package.json` - @dialectic/macos workspace with react-native-macos
- `packages/macos/app.json` - App name "DialecticMac" / display "Dialectic"
- `packages/macos/index.js` - AppRegistry.registerComponent entry point
- `packages/macos/App.tsx` - Minimal app showing "Dialectic for macOS"
- `packages/macos/tsconfig.json` - TypeScript with @dialectic/app path mapping
- `packages/macos/metro.config.js` - Monorepo watchFolders, workspace resolution
- `packages/macos/babel.config.js` - module-resolver for @dialectic/app
- `packages/macos/.gitignore` - Excludes Pods, build artifacts, xcuserdata
- `packages/macos/macos/Podfile` - CocoaPods config for react-native-macos
- `packages/macos/macos/.xcode.env` - Node binary path for Xcode scripts
- `packages/macos/macos/DialecticMac.xcodeproj/project.pbxproj` - Full Xcode project
- `packages/macos/macos/DialecticMac.xcodeproj/xcshareddata/xcschemes/DialecticMac-macOS.xcscheme` - Build scheme
- `packages/macos/macos/DialecticMac-macOS/AppDelegate.h` - Objective-C header
- `packages/macos/macos/DialecticMac-macOS/AppDelegate.mm` - RCTAppDelegate implementation
- `packages/macos/macos/DialecticMac-macOS/main.m` - NSApplicationMain entry
- `packages/macos/macos/DialecticMac-macOS/Info.plist` - App bundle configuration
- `packages/macos/macos/DialecticMac-macOS/LaunchScreen.storyboard` - Window controller

**Modified:**
- `package.json` - Added "macos" workspace script
- `yarn.lock` - Added macos workspace dependencies

## Decisions Made

1. **react-native-macos 0.81.1:** Chose latest version (0.81.1) which aligns with mobile React Native 0.81.5 for maximum compatibility
2. **Manual Xcode project creation:** Since executing on Linux, `react-native-macos-init` cannot run. Created full Xcode project structure manually following official template
3. **macOS 10.15 deployment target:** Matches React Native macOS requirements and covers most macOS users
4. **Standalone tsconfig:** Removed `extends: "@react-native/typescript-config/tsconfig.json"` due to incompatible `moduleResolution: bundler` setting
5. **1200x800 window size:** Reasonable default for desktop messaging app; resizable with 800x600 minimum

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] react-native-macos template not available**
- **Found during:** Task 1
- **Issue:** `npx @react-native-community/cli init --template @nicornk/react-native-template-macos` failed - template not found on npm
- **Fix:** Manually created all workspace files following official react-native-macos structure
- **Impact:** None - achieved same result

**2. [Rule 3 - Blocking] Cannot run react-native-macos-init on Linux**
- **Found during:** Task 2
- **Issue:** `npx react-native-macos-init` requires macOS (Xcode, CocoaPods)
- **Fix:** Manually created full Xcode project structure following official template
- **Files created:** 9 native files (project.pbxproj, AppDelegate, Info.plist, etc.)
- **Impact:** User must run `pod install` on macOS before first build

**3. [Rule 3 - Blocking] @react-native-community/cli missing**
- **Found during:** Task 3
- **Issue:** `yarn start` failed - react-native depends on @react-native-community/cli
- **Fix:** Added `@react-native-community/cli` and `@react-native-community/cli-platform-ios` to devDependencies
- **Verification:** Metro now starts successfully

---

**Total deviations:** 3 auto-fixed (3 blocking)
**Impact on plan:** All resolved. Xcode project created manually; requires pod install on macOS.

## Issues Encountered

- Template package `@nicornk/react-native-template-macos` does not exist - manual creation required
- react-native-macos-init requires macOS environment - created Xcode project manually
- Metro requires @react-native-community/cli - added to devDependencies

## User Setup Required

**On macOS (before first build):**
```bash
cd packages/macos/macos
pod install
```

This will:
1. Install CocoaPods dependencies
2. Create `DialecticMac.xcworkspace`
3. Enable building from Xcode or via `yarn macos`

## Verification Results

- [x] packages/macos/package.json has react-native-macos dependency
- [x] packages/macos/macos/ directory contains Xcode project
- [x] metro.config.js resolves @dialectic/app from workspace
- [ ] (Deferred) App builds and shows "Dialectic for macOS" text - requires macOS

## Next Phase Readiness

- macOS workspace complete with native project structure
- Ready for Plan 03 (Windows workspace) - can proceed in parallel
- Ready for Plan 04 (platform service abstractions) - can import from @dialectic/app
- User must run `pod install` on macOS before building

---
*Phase: 08-desktop-expansion*
*Completed: 2026-01-26*
