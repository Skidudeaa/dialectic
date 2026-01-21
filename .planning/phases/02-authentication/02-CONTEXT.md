# Phase 2: Authentication - Context

**Gathered:** 2026-01-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Users can create accounts, log in, and maintain sessions across app restarts. Includes biometric unlock for quick re-entry after brief absence. This phase covers the full authentication lifecycle for mobile: signup, login, session persistence, background lock/unlock, and password recovery.

</domain>

<decisions>
## Implementation Decisions

### Login/signup flow
- Separate screens for Sign Up and Log In (distinct buttons on landing page)
- Minimal password requirements: 8+ characters, no complexity rules
- Validation errors: inline below fields for specific errors + toast/banner for submission failures
- Email verification required before user can access the app

### Session behavior
- Session duration: 90 days before requiring re-login
- Background lock: require unlock after 15 minutes in background
- Multi-device: yes, limited to 3-5 devices (oldest session logged out if exceeded)
- Session invalidation: silent redirect to login screen (no explanation modal)

### Biometric unlock
- Prompt to enable biometric after first successful login
- On biometric failure: allow 3 retry attempts, then show password fallback
- Biometric also required for password changes and security settings
- For users without biometric: offer PIN as alternative to full password for background unlock

### Account recovery
- Forgot password sends 6-digit code to email (not a link)
- Reset code valid for 30 minutes
- Auto-login after successful password reset
- Explicit error if no account exists for entered email (not a generic message)

### Claude's Discretion
- Specific PIN length (4-6 digits)
- Exact device limit number (3-5 range)
- Loading states and transitions between screens
- Exact retry timing and lockout behavior

</decisions>

<specifics>
## Specific Ideas

No specific product references mentioned — open to standard mobile authentication patterns.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 02-authentication*
*Context gathered: 2026-01-20*
