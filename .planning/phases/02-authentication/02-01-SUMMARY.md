---
phase: 02-authentication
plan: 01
subsystem: backend-auth
tags: [fastapi, jwt, argon2, authentication, postgresql]
dependency-graph:
  requires: [01-project-foundation]
  provides: [auth-endpoints, user-credentials-schema, jwt-tokens]
  affects: [02-02-mobile-auth-screens, 02-03-session-management]
tech-stack:
  added: [pyjwt, pwdlib, argon2-cffi]
  patterns: [jwt-access-refresh, argon2-password-hash, multi-device-sessions]
key-files:
  created:
    - dialectic/api/auth/__init__.py
    - dialectic/api/auth/utils.py
    - dialectic/api/auth/schemas.py
    - dialectic/api/auth/dependencies.py
    - dialectic/api/auth/routes.py
  modified:
    - dialectic/schema.sql
    - dialectic/api/main.py
    - dialectic/requirements.txt
decisions:
  - id: auth-01
    decision: "6-digit verification codes (not 4)"
    rationale: "Matches OTP standard, more secure, consistent with TOTP patterns"
  - id: auth-02
    decision: "5 device limit per user"
    rationale: "Per CONTEXT.md range (3-5), chose upper bound for better UX"
  - id: auth-03
    decision: "No refresh token rotation"
    rationale: "Simpler implementation, can add rotation later if needed"
metrics:
  duration: 6 min
  completed: 2026-01-21
---

# Phase 02 Plan 01: Backend Auth API Summary

**One-liner:** JWT auth with Argon2 hashing, 15min access/90day refresh tokens via FastAPI

## What Was Built

### Database Schema
Added four authentication tables to `dialectic/schema.sql`:

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `user_credentials` | Email/password storage | email (unique), password_hash, email_verified |
| `verification_codes` | 6-digit codes for email/password reset | code, purpose, expires_at, used_at |
| `user_sessions` | Multi-device session tracking | refresh_token_hash, last_used_at, revoked_at |
| `user_pins` | PIN hashes for biometric fallback | pin_hash |

### Auth Module (`dialectic/api/auth/`)
Created complete authentication package:

- **utils.py**: JWT creation/decode, Argon2 password hashing, verification code generation
- **schemas.py**: Pydantic models for all request/response types
- **dependencies.py**: `get_current_user`, `get_current_verified_user` FastAPI dependencies
- **routes.py**: All auth endpoints with session management

### Endpoints Implemented

| Endpoint | Method | Purpose | Status Code (Success/Error) |
|----------|--------|---------|----------------------------|
| `/auth/signup` | POST | Create account, return tokens | 200/409 (email exists) |
| `/auth/login` | POST | Authenticate, return tokens | 200/401 (invalid) |
| `/auth/refresh` | POST | Get new access token | 200/401 (expired/revoked) |
| `/auth/logout` | POST | Revoke session | 200 |
| `/auth/verify-email` | POST | Verify with 6-digit code | 200/400 (invalid code) |
| `/auth/forgot-password` | POST | Request reset code | 200/404 (no account) |
| `/auth/reset-password` | POST | Reset password, auto-login | 200/400 (invalid code) |

### Security Features
- **Argon2 password hashing** via pwdlib (GPU-resistant)
- **15-minute access tokens** (short-lived for security)
- **90-day refresh tokens** (per CONTEXT.md session duration)
- **Multi-device limit**: 5 sessions per user (oldest auto-revoked)
- **Verification codes**: 6 digits, 30-minute expiry, one-time use

## Decisions Made

1. **6-digit verification codes** instead of 4
   - More secure, matches TOTP standard
   - Consistent with password reset codes

2. **5 device limit** (upper bound of 3-5 range)
   - Better UX for users with multiple devices
   - Can tighten later if abuse detected

3. **No refresh token rotation** in this iteration
   - Simpler implementation
   - Same refresh token returned on /refresh
   - Can add rotation later if security audit requires

4. **Explicit error on forgot-password** when no account exists
   - Per CONTEXT.md requirement
   - Returns 404 instead of generic success

## Deviations from Plan

None - plan executed exactly as written.

## Test Results

All endpoints verified working:
- Signup creates user and returns tokens
- Login validates credentials and returns tokens
- Refresh exchanges refresh token for new access token
- Logout revokes session
- Invalid credentials return 401
- Duplicate email returns 409

## Commits

| Hash | Message |
|------|---------|
| `32ffab9` | feat(02-01): add authentication database schema |
| `bafdb44` | feat(02-01): implement FastAPI authentication module |

## Next Phase Readiness

Ready for 02-02 (Mobile Auth Screens). Backend provides:
- All auth endpoints needed for mobile
- JWT tokens for SecureStore storage
- Session management for multi-device

**Dependencies satisfied:**
- Email/password signup and login
- Token refresh for session persistence
- Logout for session revocation

**Note:** Email sending is not implemented (logged for now). Will need email service integration in a future phase.
