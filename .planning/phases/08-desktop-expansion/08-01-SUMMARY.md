---
phase: 08-desktop-expansion
plan: 01
subsystem: infra
tags: [yarn, workspaces, monorepo, react-native, metro]

# Dependency graph
requires:
  - phase: 07-dialectic-differentiators
    provides: Complete mobile app with all features
provides:
  - Yarn workspaces monorepo structure
  - @dialectic/app shared package
  - @dialectic/mobile workspace
  - Metro config for monorepo
  - CI workflow updated for packages/
affects: [08-02, 08-03, 08-04, 08-05, windows, macos, desktop]

# Tech tracking
tech-stack:
  added: [yarn@4.12.0, workspace:* protocol]
  patterns: [monorepo with workspace linking, hoistingLimits for RN isolation]

key-files:
  created:
    - package.json (root workspace config)
    - .yarnrc.yml (Yarn 4 config with node-modules linker)
    - packages/app/package.json (@dialectic/app shared package)
    - packages/app/tsconfig.json (composite TypeScript project)
    - packages/app/src/index.ts (barrel export placeholder)
    - packages/mobile/metro.config.js (monorepo-aware Metro)
    - yarn.lock (workspace dependency resolution)
  modified:
    - packages/mobile/package.json (renamed, added workspace dep)
    - packages/mobile/tsconfig.json (added @dialectic/app paths)
    - .github/workflows/mobile-ci.yml (updated paths, switched to yarn)

key-decisions:
  - "Yarn 4 over Yarn 1: Required for workspace:* protocol support"
  - "hoistingLimits: workspaces instead of deprecated nohoist"
  - "nodeLinker: node-modules for React Native compatibility"
  - "Simplified workspaces array instead of object with nohoist"

patterns-established:
  - "Workspace dependency: workspace:* for monorepo packages"
  - "Metro monorepo: watchFolders includes monorepo root, nodeModulesPaths for resolution"
  - "TypeScript project references: composite: true for shared packages"

# Metrics
duration: 4min
completed: 2026-01-26
---

# Phase 8 Plan 1: Monorepo Setup Summary

**Yarn 4 workspaces monorepo with packages/app shared code and packages/mobile relocated Expo app**

## Performance

- **Duration:** 4 min
- **Started:** 2026-01-26T06:37:47Z
- **Completed:** 2026-01-26T06:42:00Z
- **Tasks:** 3
- **Files created:** 7
- **Files modified:** 4

## Accomplishments
- Converted project to Yarn workspaces monorepo structure
- Created packages/app as @dialectic/app shared code package (ready for extraction in Plan 04)
- Relocated mobile/ to packages/mobile/ with workspace dependency on @dialectic/app
- Updated CI workflow for monorepo paths and yarn
- Mobile tests pass (1/1), TypeScript checks pass

## Task Commits

Each task was committed atomically:

1. **Task 1: Create monorepo root and workspaces structure** - `3f15467` (feat)
2. **Task 2: Relocate mobile app to packages/mobile** - `824adc4` (feat)
3. **Task 3: Install dependencies and verify mobile builds** - `33f4b9a` (chore)

## Files Created/Modified

**Created:**
- `package.json` - Root workspace configuration with scripts for workspace commands
- `.yarnrc.yml` - Yarn 4 config with nodeLinker: node-modules for RN compatibility
- `.yarn/releases/yarn-4.12.0.cjs` - Bundled Yarn for zero-install
- `packages/app/package.json` - Shared package with peer deps on react/react-native
- `packages/app/tsconfig.json` - TypeScript config with composite: true
- `packages/app/src/index.ts` - Barrel export placeholder for Plan 04
- `packages/mobile/metro.config.js` - Metro config with monorepo watchFolders
- `yarn.lock` - Workspace dependency resolution

**Modified:**
- `packages/mobile/package.json` - Renamed to @dialectic/mobile, added @dialectic/app dep, hoistingLimits
- `packages/mobile/tsconfig.json` - Added @dialectic/app path mapping and project reference
- `.github/workflows/mobile-ci.yml` - Updated paths, switched from npm to yarn

## Decisions Made

1. **Yarn 4 upgrade:** Yarn 1 doesn't support `workspace:*` protocol - upgraded to Yarn 4 which is required for proper workspace linking
2. **hoistingLimits over nohoist:** Used `installConfig.hoistingLimits: "workspaces"` per Yarn 4 deprecation of nohoist
3. **nodeLinker: node-modules:** Required for React Native compatibility (RN doesn't support PnP)
4. **Simplified workspaces array:** Used `"workspaces": ["packages/*"]` instead of object form since hoisting is configured per-workspace

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Yarn 1 to Yarn 4 upgrade**
- **Found during:** Task 3 (Install dependencies)
- **Issue:** Yarn 1.22 doesn't support `workspace:*` protocol, install failed
- **Fix:** Upgraded to Yarn 4.12.0 via `yarn set version berry`
- **Files modified:** .yarnrc.yml (yarnPath added), .yarn/releases/yarn-4.12.0.cjs created
- **Verification:** `yarn workspaces list` shows both packages, install succeeds
- **Committed in:** 33f4b9a (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Essential for workspace:* protocol. Yarn 4 is better long-term choice.

## Issues Encountered
- Yarn 1 incompatibility with workspace:* protocol - resolved by upgrading to Yarn 4
- Peer dependency warnings (expo-haptics, @babel/core, etc.) - normal for Expo/RN ecosystem, does not affect functionality

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Monorepo structure complete, ready for Windows workspace (Plan 02)
- packages/app exists as placeholder for shared code extraction (Plan 04)
- Mobile app unchanged in functionality - still builds, tests pass
- CI workflow updated and ready for packages/* changes

---
*Phase: 08-desktop-expansion*
*Completed: 2026-01-26*
