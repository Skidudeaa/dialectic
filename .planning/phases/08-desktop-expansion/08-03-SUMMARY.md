---
phase: 08-desktop-expansion
plan: 03
subsystem: infra
tags: [react-native-windows, metro, monorepo, windows, desktop, fabric]

# Dependency graph
requires:
  - phase: 08-01
    provides: Yarn workspaces monorepo structure
provides:
  - @dialectic/windows workspace package
  - Windows Metro config for monorepo
  - Visual Studio project build instructions
  - Platform isolation via blockList
affects: [08-04, 08-05, windows, desktop]

# Tech tracking
tech-stack:
  added: [react-native-windows@0.81, @react-native/babel-preset@0.81, @react-native/metro-config@0.81]
  patterns: [Metro monorepo config for Windows, platform isolation via blockList]

key-files:
  created:
    - packages/windows/package.json
    - packages/windows/index.js
    - packages/windows/App.tsx
    - packages/windows/app.json
    - packages/windows/tsconfig.json
    - packages/windows/metro.config.js
    - packages/windows/babel.config.js
    - packages/windows/windows/BUILD-README.md
    - tsconfig.base.json
  modified:
    - package.json (added windows workspace script)
    - packages/app/package.json (removed outdated @types/react-native)

key-decisions:
  - "cpp-app template for New Architecture (Fabric) support on Windows"
  - "Metro blockList excludes mobile and macos packages for clean Windows builds"
  - "VS project generation documented (requires Windows machine with VS 2022)"

patterns-established:
  - "Platform isolation: blockList in metro.config.js prevents cross-platform pollution"
  - "Desktop workspace structure: index.js entry, App.tsx component, app.json config"

# Metrics
duration: 3min
completed: 2026-01-26
---

# Phase 8 Plan 3: Windows Workspace Summary

**React Native Windows workspace with Fabric/New Architecture support, Metro monorepo config, and VS project build documentation**

## Performance

- **Duration:** 3 min
- **Started:** 2026-01-26T06:44:14Z
- **Completed:** 2026-01-26T06:47:30Z
- **Tasks:** 3
- **Files created:** 9
- **Files modified:** 2

## Accomplishments
- Created @dialectic/windows workspace with react-native-windows 0.81 (aligned with mobile RN version)
- Configured Metro for monorepo resolution with @dialectic/app workspace linking
- Added platform isolation via blockList excluding mobile and macos packages
- Documented VS project generation requirements (must run on Windows with VS 2022)
- Created tsconfig.base.json for shared TypeScript configuration

## Task Commits

Each task was committed atomically:

1. **Task 1: Initialize Windows workspace with react-native-windows** - `d946e74` (feat)
2. **Task 2: Generate native Windows Visual Studio project** - `da2b036` (docs)
3. **Task 3: Configure Metro for monorepo** - `0dbe798` (feat)

## Files Created/Modified

**Created:**
- `packages/windows/package.json` - @dialectic/windows package with RN-Windows 0.81 dependency
- `packages/windows/index.js` - Entry point with AppRegistry.registerComponent
- `packages/windows/App.tsx` - Minimal "Dialectic for Windows" component
- `packages/windows/app.json` - App name configuration (DialecticWin)
- `packages/windows/tsconfig.json` - TypeScript config with @dialectic/app paths
- `packages/windows/metro.config.js` - Monorepo Metro config with watchFolders and blockList
- `packages/windows/babel.config.js` - Babel config with module-resolver
- `packages/windows/windows/BUILD-README.md` - VS project generation documentation
- `packages/windows/windows/.gitkeep` - Placeholder for VS project directory
- `tsconfig.base.json` - Shared TypeScript base configuration

**Modified:**
- `package.json` - Added "windows" workspace script
- `packages/app/package.json` - Removed @types/react-native (RN 0.79+ includes types)

## Decisions Made

1. **cpp-app template:** VS project will use `--template cpp-app` for New Architecture (Fabric) support, as required by RN-Windows 0.80+
2. **Platform isolation via blockList:** Metro excludes `/packages/mobile/` and `/packages/macos/` from Windows builds to prevent cross-platform module conflicts
3. **VS project deferred:** Since running on Linux, VS project generation is documented but not executed - must be done on Windows machine

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Removed outdated @types/react-native**
- **Found during:** Task 3 (yarn install)
- **Issue:** @dialectic/app had @types/react-native@^0.73.0 which conflicts with RN 0.81 (types included in react-native since 0.79)
- **Fix:** Removed @types/react-native from packages/app/package.json
- **Files modified:** packages/app/package.json
- **Verification:** yarn install succeeds, workspaces list shows all packages
- **Committed in:** 0dbe798 (Task 3 commit)

**2. [Rule 3 - Blocking] Created missing tsconfig.base.json**
- **Found during:** Task 1 (tsconfig.json extends missing file)
- **Issue:** Windows tsconfig.json extends "../../tsconfig.base.json" which didn't exist
- **Fix:** Created tsconfig.base.json with standard React Native TypeScript settings
- **Files modified:** tsconfig.base.json (created)
- **Verification:** TypeScript configuration resolves correctly
- **Committed in:** d946e74 (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (2 blocking)
**Impact on plan:** Both fixes necessary for dependency resolution and TypeScript config. No scope creep.

## Issues Encountered
- Running on Linux, VS project cannot be generated - documented build requirements instead
- Peer dependency warnings during yarn install (expo-haptics, react version) - normal for RN ecosystem, does not affect functionality

## User Setup Required

**Windows build requires manual setup on Windows machine:**
1. Install Visual Studio 2022 with C++ and UWP workloads
2. Install Windows SDK 10.0.19041.0+
3. Run `npx react-native-windows-init --overwrite --template cpp-app` from packages/windows/
4. Run `yarn windows` to build and launch

See `packages/windows/windows/BUILD-README.md` for full instructions.

## Next Phase Readiness
- Windows workspace ready for shared code extraction (Plan 04)
- Visual Studio project generation deferred to Windows developer
- Metro configuration verified, @dialectic/app resolution working
- Plan 04 (Shared Code) can extract components to packages/app

---
*Phase: 08-desktop-expansion*
*Completed: 2026-01-26*
