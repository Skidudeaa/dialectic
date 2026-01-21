# Phase 2: Authentication - Research

**Researched:** 2026-01-20
**Domain:** Mobile authentication with Expo (React Native), FastAPI backend
**Confidence:** HIGH

## Summary

This research covers the complete authentication stack for a React Native/Expo mobile app with an existing FastAPI backend. The phase requires user signup/login with email verification, session persistence across app restarts, biometric unlock for quick re-entry, and multi-device session management.

The Expo ecosystem provides mature, well-documented libraries for secure token storage (`expo-secure-store`) and biometric authentication (`expo-local-authentication`). Expo Router v3+ offers built-in `Stack.Protected` for declarative route protection. The backend uses FastAPI's standard JWT pattern with Argon2 password hashing via `pwdlib`.

**Primary recommendation:** Use `expo-secure-store` for encrypted token storage, `expo-local-authentication` for biometrics, JWT access/refresh token pattern with 15-minute access tokens and 90-day refresh tokens (matching the session duration requirement), and FastAPI's official `pwdlib` + `pyjwt` stack.

## Standard Stack

The established libraries for mobile authentication in Expo:

### Core (Mobile)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `expo-secure-store` | ~15.0.x | Encrypted token storage | Official Expo library, uses iOS Keychain/Android Keystore |
| `expo-local-authentication` | ~17.0.x | Biometric auth (Face ID, fingerprint) | Official Expo library, handles hardware abstraction |
| `expo-router` | ~6.0.x | Navigation with protected routes | Already installed, provides `Stack.Protected` API |
| `react-hook-form` | ^7.54.x | Form state management | Lightweight, performant, TS-first |
| `@hookform/resolvers` | ^3.9.x | Zod integration for react-hook-form | Official resolver package |
| `zod` | ^3.23.x | Schema validation | TypeScript-first, excellent inference |

### Core (Backend)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `pyjwt` | ^2.9.x | JWT encoding/decoding | Official FastAPI recommendation |
| `pwdlib[argon2]` | ^0.2.x | Password hashing | Modern replacement for passlib, Argon2 default |
| `pyotp` | ^2.9.x | 6-digit OTP generation | RFC 6238 compliant, configurable expiration |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `@tanstack/react-query` | ^5.x | Server state management | Auth state sync, token refresh |
| `axios` | ^1.7.x | HTTP client | Interceptor pattern for token refresh |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `expo-secure-store` | `react-native-keychain` | More features but not Expo-native |
| `react-hook-form` | `formik` | Formik heavier, more re-renders |
| `pyjwt` | `python-jose` | jose has more features but heavier |
| `pwdlib` | `passlib` | passlib unmaintained, pwdlib is modern |

**Installation (Mobile):**
```bash
cd mobile
npx expo install expo-secure-store expo-local-authentication
npm install react-hook-form @hookform/resolvers zod axios
```

**Installation (Backend):**
```bash
pip install pyjwt "pwdlib[argon2]" pyotp
```

## Architecture Patterns

### Recommended Project Structure

```
mobile/
├── app/
│   ├── _layout.tsx           # Root layout with SessionProvider
│   ├── (auth)/               # Auth screens (unprotected)
│   │   ├── _layout.tsx
│   │   ├── sign-in.tsx
│   │   ├── sign-up.tsx
│   │   ├── verify-email.tsx
│   │   ├── forgot-password.tsx
│   │   └── reset-password.tsx
│   ├── (app)/                # Protected screens
│   │   ├── _layout.tsx
│   │   └── ...
│   └── index.tsx             # Entry redirect
├── contexts/
│   └── session-context.tsx   # Auth context + provider
├── hooks/
│   ├── use-session.ts        # Session hook
│   ├── use-biometric.ts      # Biometric state
│   └── use-storage-state.ts  # SecureStore abstraction
├── services/
│   ├── auth.ts               # Auth API calls
│   └── api.ts                # Axios instance with interceptors
└── lib/
    └── secure-storage.ts     # SecureStore wrapper

dialectic/
├── api/
│   ├── main.py               # Existing FastAPI app
│   └── auth/                 # New auth module
│       ├── __init__.py
│       ├── routes.py         # Auth endpoints
│       ├── dependencies.py   # Auth dependencies
│       ├── schemas.py        # Pydantic models
│       └── utils.py          # JWT, password helpers
└── schema.sql                # Add auth tables
```

### Pattern 1: Session Context with SecureStore

**What:** React Context that manages auth state with persistence via SecureStore
**When to use:** Always - this is the foundation of the auth system

```typescript
// Source: https://docs.expo.dev/router/advanced/authentication/
// contexts/session-context.tsx
import { createContext, useContext, useEffect, useState } from 'react';
import * as SecureStore from 'expo-secure-store';

interface Session {
  accessToken: string;
  refreshToken: string;
  userId: string;
}

interface SessionContextType {
  session: Session | null;
  isLoading: boolean;
  signIn: (session: Session) => Promise<void>;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<SessionContextType | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    loadSession();
  }, []);

  async function loadSession() {
    try {
      const stored = await SecureStore.getItemAsync('session');
      if (stored) {
        setSession(JSON.parse(stored));
      }
    } finally {
      setIsLoading(false);
    }
  }

  async function signIn(newSession: Session) {
    await SecureStore.setItemAsync('session', JSON.stringify(newSession));
    setSession(newSession);
  }

  async function signOut() {
    await SecureStore.deleteItemAsync('session');
    setSession(null);
  }

  return (
    <SessionContext.Provider value={{ session, isLoading, signIn, signOut }}>
      {children}
    </SessionContext.Provider>
  );
}

export function useSession() {
  const context = useContext(SessionContext);
  if (!context) {
    throw new Error('useSession must be used within SessionProvider');
  }
  return context;
}
```

### Pattern 2: Stack.Protected Route Guards

**What:** Declarative route protection based on auth state
**When to use:** Root layout to control access to auth vs app screens

```typescript
// Source: https://docs.expo.dev/router/advanced/protected/
// app/_layout.tsx
import { Stack } from 'expo-router';
import { SessionProvider, useSession } from '@/contexts/session-context';

function RootLayoutNav() {
  const { session, isLoading } = useSession();

  if (isLoading) {
    return <SplashScreen />;
  }

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Protected guard={!session}>
        <Stack.Screen name="(auth)" />
      </Stack.Protected>
      <Stack.Protected guard={!!session}>
        <Stack.Screen name="(app)" />
      </Stack.Protected>
    </Stack>
  );
}

export default function RootLayout() {
  return (
    <SessionProvider>
      <RootLayoutNav />
    </SessionProvider>
  );
}
```

### Pattern 3: Biometric Unlock Flow

**What:** Biometric authentication for quick re-entry after background
**When to use:** When app returns from background after 15+ minutes

```typescript
// Source: https://docs.expo.dev/versions/latest/sdk/local-authentication/
// hooks/use-biometric.ts
import * as LocalAuthentication from 'expo-local-authentication';
import * as SecureStore from 'expo-secure-store';

export function useBiometric() {
  const [isEnabled, setIsEnabled] = useState(false);
  const [isAvailable, setIsAvailable] = useState(false);

  useEffect(() => {
    checkAvailability();
    loadPreference();
  }, []);

  async function checkAvailability() {
    const hasHardware = await LocalAuthentication.hasHardwareAsync();
    const isEnrolled = await LocalAuthentication.isEnrolledAsync();
    setIsAvailable(hasHardware && isEnrolled);
  }

  async function loadPreference() {
    const enabled = await SecureStore.getItemAsync('biometric_enabled');
    setIsEnabled(enabled === 'true');
  }

  async function authenticate(): Promise<boolean> {
    const result = await LocalAuthentication.authenticateAsync({
      promptMessage: 'Unlock Dialectic',
      fallbackLabel: 'Use password',
      disableDeviceFallback: false,
    });
    return result.success;
  }

  async function enable() {
    await SecureStore.setItemAsync('biometric_enabled', 'true');
    setIsEnabled(true);
  }

  async function disable() {
    await SecureStore.setItemAsync('biometric_enabled', 'false');
    setIsEnabled(false);
  }

  return { isEnabled, isAvailable, authenticate, enable, disable };
}
```

### Pattern 4: FastAPI JWT Authentication

**What:** Backend JWT authentication with access/refresh token pattern
**When to use:** All auth endpoints

```python
# Source: https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
# dialectic/api/auth/utils.py
from datetime import datetime, timedelta, timezone
from typing import Optional
import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from pydantic import BaseModel

SECRET_KEY = os.environ.get("JWT_SECRET_KEY")  # Generate with: openssl rand -hex 32
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 90

password_hash = PasswordHash.recommended()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    return password_hash.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
```

### Pattern 5: Token Refresh with Axios Interceptor

**What:** Automatic token refresh on 401 responses
**When to use:** API client setup

```typescript
// Source: https://blog.logrocket.com/react-native-jwt-authentication-using-axios-interceptors/
// services/api.ts
import axios, { AxiosError } from 'axios';
import * as SecureStore from 'expo-secure-store';

const api = axios.create({
  baseURL: 'https://api.dialectic.app',
});

let isRefreshing = false;
let failedQueue: Array<{
  resolve: (token: string) => void;
  reject: (error: Error) => void;
}> = [];

const processQueue = (error: Error | null, token: string | null) => {
  failedQueue.forEach(prom => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token!);
    }
  });
  failedQueue = [];
};

api.interceptors.request.use(async (config) => {
  const session = await SecureStore.getItemAsync('session');
  if (session) {
    const { accessToken } = JSON.parse(session);
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config;

    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        }).then((token) => {
          originalRequest.headers.Authorization = `Bearer ${token}`;
          return api(originalRequest);
        });
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        const session = await SecureStore.getItemAsync('session');
        if (!session) throw new Error('No session');

        const { refreshToken } = JSON.parse(session);
        const { data } = await axios.post('/auth/refresh', { refresh_token: refreshToken });

        await SecureStore.setItemAsync('session', JSON.stringify(data));
        processQueue(null, data.accessToken);

        originalRequest.headers.Authorization = `Bearer ${data.accessToken}`;
        return api(originalRequest);
      } catch (err) {
        processQueue(err as Error, null);
        await SecureStore.deleteItemAsync('session');
        // Navigate to sign-in handled by session context
        throw err;
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  }
);

export default api;
```

### Anti-Patterns to Avoid

- **Storing tokens in AsyncStorage:** AsyncStorage is unencrypted. Always use SecureStore for tokens.
- **Long-lived access tokens:** Access tokens should be short-lived (15-30 min). Use refresh tokens for longevity.
- **Checking auth in every screen:** Use Stack.Protected at the layout level, not individual screens.
- **Biometric as primary auth:** Biometric is for local unlock only, not server authentication.
- **Storing passwords locally:** Never store the user's password, only tokens.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Token encryption | Custom encryption | `expo-secure-store` | Uses platform keychain, handles key management |
| Biometric prompts | Native module wrapper | `expo-local-authentication` | Handles iOS/Android differences, permissions |
| Password hashing | Custom hash function | `pwdlib` with Argon2 | Secure defaults, actively maintained |
| JWT encoding | Manual JSON + base64 | `pyjwt` | Handles claims, expiration, signatures |
| Form validation | Manual state + errors | `react-hook-form` + `zod` | Performant, type-safe, well-tested |
| Route protection | Manual redirects | `Stack.Protected` | Handles edge cases, deep links |
| OTP generation | `random.randint()` | `pyotp` | RFC compliant, configurable, secure |

**Key insight:** Authentication has many edge cases (token refresh race conditions, biometric enrollment changes, keychain migrations). Libraries handle these; custom code won't.

## Common Pitfalls

### Pitfall 1: Token Refresh Race Condition

**What goes wrong:** Multiple concurrent requests trigger multiple refresh attempts, invalidating tokens mid-flight
**Why it happens:** Naive implementation refreshes on every 401 without coordination
**How to avoid:** Use mutex pattern (see Axios interceptor pattern above) - queue requests while refreshing
**Warning signs:** Intermittent 401 errors, users randomly logged out

### Pitfall 2: Biometric Enrollment Changes

**What goes wrong:** User adds new fingerprint, SecureStore data with `requireAuthentication` becomes inaccessible
**Why it happens:** iOS/Android invalidate biometric-protected data when biometric settings change
**How to avoid:** Don't use `requireAuthentication` for session tokens. Use biometric as a gate, not as storage protection.
**Warning signs:** Users locked out after adding new biometrics

### Pitfall 3: FaceID Testing in Expo Go

**What goes wrong:** FaceID authentication fails in development
**Why it happens:** FaceID requires NSFaceIDUsageDescription which Expo Go doesn't have
**How to avoid:** Use development builds (`npx expo run:ios`) for FaceID testing
**Warning signs:** Works in simulator with TouchID, fails on device with FaceID

### Pitfall 4: Session Invalidation Without Feedback

**What goes wrong:** User confused when silently redirected to login
**Why it happens:** Per CONTEXT.md requirement: "silent redirect to login screen (no explanation modal)"
**How to avoid:** This is intentional per decisions, but ensure the login screen is clearly the login screen
**Warning signs:** User support tickets about "being logged out for no reason"

### Pitfall 5: Email Verification Code Timing

**What goes wrong:** Users report codes "not working" even when entered correctly
**Why it happens:** Clock skew between server and user's perception, or code already used
**How to avoid:** Use absolute expiration timestamps, allow one-time use, show clear "code expired" message
**Warning signs:** High rate of verification code failures

### Pitfall 6: Multi-Device Session Overflow

**What goes wrong:** User can't log in because they're at device limit
**Why it happens:** Per CONTEXT.md: "limited to 3-5 devices (oldest session logged out if exceeded)"
**How to avoid:** Implement automatic oldest-session logout when limit reached, not login denial
**Warning signs:** Users reporting they can't log in from new devices

### Pitfall 7: iOS Keychain Persistence

**What goes wrong:** User reinstalls app and is still logged in unexpectedly
**Why it happens:** iOS Keychain persists data across app reinstalls with same bundle ID
**How to avoid:** This can be desirable (UX) or undesirable (security). Document expected behavior.
**Warning signs:** "Why am I logged in after reinstalling?"

## Code Examples

### Email Verification OTP (Backend)

```python
# Source: https://pyauth.github.io/pyotp/
# dialectic/api/auth/routes.py
import pyotp
import secrets
from datetime import datetime, timedelta

# Generate OTP for email verification
def generate_verification_code() -> tuple[str, str]:
    """Generate 6-digit OTP valid for 30 minutes."""
    # Use random base32 secret for each code
    secret = pyotp.random_base32()
    # interval=1800 = 30 minutes
    totp = pyotp.TOTP(secret, digits=6, interval=1800)
    code = totp.now()
    return code, secret

def verify_code(code: str, secret: str) -> bool:
    """Verify OTP is valid and not expired."""
    totp = pyotp.TOTP(secret, digits=6, interval=1800)
    return totp.verify(code)

# Alternative: simpler approach with database storage
def generate_simple_code() -> str:
    """Generate 6-digit code (store expiry in DB)."""
    return ''.join(secrets.choice('0123456789') for _ in range(6))
```

### PIN Fallback for Biometric (Mobile)

```typescript
// hooks/use-unlock.ts
import { useState } from 'react';
import * as LocalAuthentication from 'expo-local-authentication';
import * as SecureStore from 'expo-secure-store';

const MAX_BIOMETRIC_ATTEMPTS = 3;

export function useUnlock() {
  const [attempts, setAttempts] = useState(0);
  const [showPinFallback, setShowPinFallback] = useState(false);

  async function attemptBiometric(): Promise<boolean> {
    if (attempts >= MAX_BIOMETRIC_ATTEMPTS) {
      setShowPinFallback(true);
      return false;
    }

    const result = await LocalAuthentication.authenticateAsync({
      promptMessage: 'Unlock Dialectic',
      fallbackLabel: 'Use PIN',
      cancelLabel: 'Cancel',
    });

    if (result.success) {
      setAttempts(0);
      return true;
    }

    // Handle specific errors
    if (result.error === 'user_fallback') {
      setShowPinFallback(true);
      return false;
    }

    setAttempts(prev => prev + 1);
    if (attempts + 1 >= MAX_BIOMETRIC_ATTEMPTS) {
      setShowPinFallback(true);
    }
    return false;
  }

  async function verifyPin(pin: string): Promise<boolean> {
    const storedHash = await SecureStore.getItemAsync('pin_hash');
    // In practice, use proper hash comparison
    // This is simplified - actual implementation should hash the input
    return storedHash === pin; // Replace with proper hash verification
  }

  return { attemptBiometric, verifyPin, showPinFallback, setShowPinFallback };
}
```

### Form Validation with Zod

```typescript
// Source: https://react-hook-form.com/docs/useform
// screens/sign-up.tsx
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';

const signUpSchema = z.object({
  email: z.string().email('Invalid email address'),
  password: z.string().min(8, 'Password must be at least 8 characters'),
  confirmPassword: z.string(),
}).refine(data => data.password === data.confirmPassword, {
  message: 'Passwords do not match',
  path: ['confirmPassword'],
});

type SignUpForm = z.infer<typeof signUpSchema>;

export function SignUpScreen() {
  const { control, handleSubmit, formState: { errors } } = useForm<SignUpForm>({
    resolver: zodResolver(signUpSchema),
  });

  const onSubmit = async (data: SignUpForm) => {
    // API call
  };

  return (
    <View>
      <Controller
        control={control}
        name="email"
        render={({ field: { onChange, value } }) => (
          <>
            <TextInput
              placeholder="Email"
              value={value}
              onChangeText={onChange}
              autoCapitalize="none"
              keyboardType="email-address"
            />
            {errors.email && <Text style={styles.error}>{errors.email.message}</Text>}
          </>
        )}
      />
      {/* Similar for password fields */}
    </View>
  );
}
```

### Database Schema Updates

```sql
-- Add to dialectic/schema.sql

-- User credentials (separate from existing users table)
CREATE TABLE user_credentials (
    user_id UUID PRIMARY KEY REFERENCES users(id),
    email TEXT UNIQUE NOT NULL,
    email_verified BOOLEAN NOT NULL DEFAULT FALSE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_user_credentials_email ON user_credentials(email);

-- Email verification codes
CREATE TABLE verification_codes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    code TEXT NOT NULL,
    code_secret TEXT NOT NULL,  -- For TOTP verification
    purpose TEXT NOT NULL,  -- 'email_verification' | 'password_reset'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ
);

CREATE INDEX idx_verification_codes_user ON verification_codes(user_id);

-- User sessions (for multi-device management)
CREATE TABLE user_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    refresh_token_hash TEXT NOT NULL,
    device_info JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ
);

CREATE INDEX idx_user_sessions_user ON user_sessions(user_id);
CREATE INDEX idx_user_sessions_token ON user_sessions(refresh_token_hash);

-- User PIN hashes (for biometric fallback)
CREATE TABLE user_pins (
    user_id UUID PRIMARY KEY REFERENCES users(id),
    pin_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `passlib` for hashing | `pwdlib` with Argon2 | 2024 | passlib unmaintained, pwdlib is modern |
| Manual redirect auth | `Stack.Protected` | Expo Router v3 (2024) | Declarative route protection |
| HS256 for JWT | RS256 for larger systems | Ongoing | Asymmetric keys for distributed verification |
| bcrypt default | Argon2 default | 2023+ | Argon2 more resistant to GPU attacks |
| 24-hour refresh tokens | Long-lived (90 days) with rotation | Best practice | Balance UX with security |

**Deprecated/outdated:**
- `passlib`: Unmaintained, use `pwdlib` instead
- Implicit OAuth flow: Use PKCE instead
- `ALWAYS` keychain accessibility: Deprecated by Apple, use `AFTER_FIRST_UNLOCK`

## Open Questions

Things that couldn't be fully resolved:

1. **PIN length (4-6 digits)**
   - What we know: Both are common, 6 is more secure
   - What's unclear: User preference for this app
   - Recommendation: Use 6-digit PIN (matches OTP format, more secure)

2. **Exact device limit (3-5)**
   - What we know: CONTEXT.md specifies 3-5 range
   - What's unclear: Optimal number for Dialectic's use case
   - Recommendation: Start with 5, can tighten later if abuse detected

3. **Email delivery service**
   - What we know: Need to send verification codes
   - What's unclear: Which email service to use (SendGrid, Postmark, etc.)
   - Recommendation: Use environment variable for SMTP config, keep service-agnostic

4. **Refresh token rotation**
   - What we know: Best practice is to rotate refresh tokens on use
   - What's unclear: Single-use vs multi-use rotation
   - Recommendation: Implement single-use rotation (each refresh gives new refresh token)

## Sources

### Primary (HIGH confidence)
- [Expo SecureStore Documentation](https://docs.expo.dev/versions/latest/sdk/securestore/) - API reference, platform behavior
- [Expo LocalAuthentication Documentation](https://docs.expo.dev/versions/latest/sdk/local-authentication/) - Biometric API, permissions
- [Expo Router Authentication](https://docs.expo.dev/router/advanced/authentication/) - Session pattern, Stack.Protected
- [Expo Router Protected Routes](https://docs.expo.dev/router/advanced/protected/) - Guard API, route protection
- [FastAPI JWT Documentation](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/) - Official JWT pattern

### Secondary (MEDIUM confidence)
- [LogRocket - Axios Interceptors](https://blog.logrocket.com/react-native-jwt-authentication-using-axios-interceptors/) - Token refresh pattern
- [Brains & Beards - Token Renewal Mutex](https://brainsandbeards.com/blog/2024-token-renewal-mutex/) - Race condition handling
- [PyOTP Documentation](https://pyauth.github.io/pyotp/) - OTP generation

### Tertiary (LOW confidence)
- WebSearch results for best practices - General guidance, needs validation in implementation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Official Expo libraries, FastAPI docs
- Architecture: HIGH - Official Expo Router patterns
- Pitfalls: MEDIUM - Combination of docs and community reports

**Research date:** 2026-01-20
**Valid until:** 2026-02-20 (30 days - stable ecosystem)
