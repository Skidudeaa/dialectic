# Phase 1: Project Foundation - Context

**Gathered:** 2026-01-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Establish cross-platform mobile development infrastructure with working iOS and Android builds from a shared React Native codebase. This phase delivers scaffolding, build pipeline, and dev tooling — no features.

</domain>

<decisions>
## Implementation Decisions

### Expo Configuration
- Managed workflow (not bare) — use Expo Go for development, EAS Build for native builds
- Target SDK 52 (latest stable) with React Native 0.76 and new architecture
- TypeScript for the entire codebase
- Use EAS Build for all native builds (cloud-based, no local Xcode/Android Studio required for CI)

### Project Structure
- Single-package repository (not monorepo)
- Feature-folder organization: `/features/auth/`, `/features/chat/`, etc.
- Each feature contains its own components, hooks, and screens
- Expo Router for file-based navigation (built on React Navigation)
- Mobile app lives in `/mobile` directory, separate from existing `dialectic/` backend
- Expo Router's `app/` folder at `/mobile/app/`

### Dev Environment
- Primary development on iOS Simulator (Mac)
- Environment variables via `app.config.js` + `.env` files (expo-constants with dotenv)
- Different `.env` files per environment (development, staging, production)
- ESLint + Prettier for linting and formatting from day one
- Jest + React Native Testing Library for testing infrastructure

### CI/CD Approach
- GitHub Actions for CI
- PR checks: lint + type check + tests (fast feedback, no native builds)
- Native builds (EAS Build) triggered on main branch and tags only
- Build artifacts stored on EAS servers (download from Expo dashboard)

### Claude's Discretion
- Specific ESLint rule configuration
- Prettier formatting options
- Jest configuration details
- GitHub Actions workflow file structure
- Exact folder layout within `/mobile`

</decisions>

<specifics>
## Specific Ideas

- Keep mobile code cleanly separated from backend — independent CI workflows, READMEs, and dependency management
- SDK 52 chosen for longer support runway and to avoid immediate upgrade cycle

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-project-foundation*
*Context gathered: 2026-01-20*
