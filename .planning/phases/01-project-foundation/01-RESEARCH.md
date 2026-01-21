# Phase 1: Project Foundation - Research

**Researched:** 2026-01-20
**Domain:** React Native / Expo scaffolding, CI/CD, TypeScript tooling
**Confidence:** HIGH

## Summary

Phase 1 establishes the cross-platform mobile development infrastructure for Dialectic using React Native with Expo SDK 52. The research confirms that the locked decisions (managed workflow, Expo Router, EAS Build, TypeScript) align with current best practices. SDK 52 ships with React Native 0.76 and has the New Architecture enabled by default, eliminating historical performance concerns.

The standard approach is straightforward: use `create-expo-app` with the default template (includes Expo Router and TypeScript), configure ESLint/Prettier via `npx expo lint`, add Jest with `jest-expo`, and set up GitHub Actions to trigger EAS Build on main branch pushes. Development uses Expo Go initially, with development builds created via EAS for testing native features.

**Primary recommendation:** Initialize with `npx create-expo-app@latest` (default template), configure linting/testing on day one, and establish CI with lint/type-check/test on PRs and EAS Build on main branch only.

## Standard Stack

The established libraries/tools for this phase:

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Expo SDK | 52 | Development toolchain, managed services | Latest stable, includes RN 0.76, New Architecture default, longer support runway |
| React Native | 0.76 | Cross-platform mobile framework | Bundled with SDK 52, New Architecture mandatory, no bridge |
| TypeScript | 5.x | Type safety | First-class Expo support, type-safe JSI modules |
| Expo Router | 4.x | File-based navigation | Bundled with default template, built on React Navigation, typed routes |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| expo-dev-client | latest | Development build support | When testing native features not in Expo Go |
| eslint-config-expo | latest | Expo-optimized ESLint | Always - run `npx expo lint` to install |
| prettier | 3.x | Code formatting | Always - integrates with ESLint |
| jest-expo | latest | Jest preset for Expo | Always - testing infrastructure |
| @testing-library/react-native | 12.x | Component testing utilities | Always - replaces deprecated react-test-renderer |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Expo Router | React Navigation directly | More control, but lose file-based routing and typed routes |
| jest-expo | plain Jest | jest-expo handles RN/Expo transforms automatically |
| EAS Build | Local builds | Full control, but requires Xcode/Android Studio setup |

**Installation:**

```bash
# Create new project with default template (includes Expo Router + TypeScript)
npx create-expo-app@latest dialectic-mobile

# Navigate to project
cd dialectic-mobile

# Initialize ESLint with Expo config (auto-installs deps)
npx expo lint

# Add Prettier integration
npx expo install prettier eslint-config-prettier eslint-plugin-prettier --dev

# Add Jest and Testing Library
npx expo install jest-expo jest @types/jest @testing-library/react-native --dev

# Initialize EAS (creates eas.json)
npx eas-cli@latest build:configure
```

## Architecture Patterns

### Recommended Project Structure

The user decided on feature-folder organization with mobile code in `/mobile`:

```
mobile/
├── app/                    # Expo Router routes (file-based)
│   ├── _layout.tsx         # Root layout (providers, fonts)
│   ├── index.tsx           # Home screen (matches /)
│   ├── (tabs)/             # Tab group (route group)
│   │   ├── _layout.tsx     # Tab navigator configuration
│   │   ├── index.tsx       # Default tab
│   │   └── settings.tsx    # Settings tab
│   └── +not-found.tsx      # 404 handler
├── features/               # Feature modules (per user decision)
│   ├── auth/
│   │   ├── components/
│   │   ├── hooks/
│   │   └── screens/        # Non-route screens if needed
│   └── chat/
│       ├── components/
│       └── hooks/
├── components/             # Shared UI components
├── hooks/                  # Shared hooks
├── utils/                  # Shared utilities
├── constants/              # App constants
├── __tests__/              # Test files (NOT in app/)
├── app.config.js           # Dynamic Expo config
├── eas.json                # EAS Build profiles
├── eslint.config.js        # ESLint flat config
├── .prettierrc             # Prettier config
├── jest.config.js          # Jest configuration
├── tsconfig.json           # TypeScript config
├── .env                    # Default env vars (can commit)
├── .env.local              # Local overrides (gitignored)
└── package.json
```

### Pattern 1: Expo Router File-Based Routing

**What:** Files in `app/` directory automatically become routes. Directories define navigation structure.

**When to use:** Always - this is the locked decision.

**Example:**

```typescript
// Source: https://docs.expo.dev/router/basics/core-concepts/
// app/_layout.tsx - Root layout, wraps all routes
import { Stack } from 'expo-router';

export default function RootLayout() {
  return (
    <Stack>
      <Stack.Screen name="index" options={{ title: 'Home' }} />
      <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
    </Stack>
  );
}

// app/index.tsx - Home screen at /
export default function HomeScreen() {
  return <View><Text>Welcome!</Text></View>;
}

// app/(tabs)/_layout.tsx - Tab navigator
import { Tabs } from 'expo-router';

export default function TabLayout() {
  return (
    <Tabs>
      <Tabs.Screen name="index" options={{ title: 'Chat' }} />
      <Tabs.Screen name="settings" options={{ title: 'Settings' }} />
    </Tabs>
  );
}
```

### Pattern 2: Environment Variables with EXPO_PUBLIC_ Prefix

**What:** Environment variables prefixed with `EXPO_PUBLIC_` are automatically loaded and accessible in code.

**When to use:** For any client-side configuration that varies by environment.

**Example:**

```typescript
// Source: https://docs.expo.dev/guides/environment-variables/
// .env
EXPO_PUBLIC_API_URL=http://localhost:8000

// .env.local (gitignored)
EXPO_PUBLIC_API_URL=https://staging.api.dialectic.app

// In code - MUST use static dot notation
const apiUrl = process.env.EXPO_PUBLIC_API_URL;

// WRONG - these do NOT work:
// process.env['EXPO_PUBLIC_API_URL']
// const { EXPO_PUBLIC_API_URL } = process.env
```

### Pattern 3: EAS Build Profiles

**What:** eas.json defines build configurations for different purposes.

**When to use:** Always - required for native builds.

**Example:**

```json
// Source: https://docs.expo.dev/build/eas-json/
{
  "cli": {
    "version": ">= 12.0.0"
  },
  "build": {
    "development": {
      "developmentClient": true,
      "distribution": "internal",
      "ios": {
        "simulator": true
      },
      "android": {
        "buildType": "apk"
      }
    },
    "preview": {
      "distribution": "internal",
      "android": {
        "buildType": "apk"
      }
    },
    "production": {}
  }
}
```

### Anti-Patterns to Avoid

- **Test files in app/ directory:** All files in `app/` become routes. Put tests in `__tests__/` instead.
- **Dynamic env var access:** `process.env[varName]` does not work with Expo's bundler. Use static `process.env.EXPO_PUBLIC_X`.
- **Committing .env.local:** Contains machine-specific or sensitive values. Always gitignore.
- **Skipping dual-platform testing:** Test on both iOS and Android from day one to catch platform differences early.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Project scaffolding | Manual setup | `create-expo-app` | Correct defaults, TypeScript, Expo Router pre-configured |
| ESLint config | Custom rules | `eslint-config-expo` | Handles multi-environment (Node, Hermes, web) correctly |
| Jest transforms | Manual babel/metro config | `jest-expo` preset | Handles RN transforms, Expo modules, async storage mocking |
| Build pipeline | Local Xcode/Android Studio | EAS Build | Cloud-based, credential management, no local toolchain needed |
| Navigation | Custom router | Expo Router | File-based, typed, deep linking, React Navigation underneath |

**Key insight:** Expo's toolchain is highly integrated. Using the official tools (expo lint, jest-expo, EAS) avoids configuration mismatches that cause subtle bugs.

## Common Pitfalls

### Pitfall 1: SDK 52 TypeScript Source Issue

**What goes wrong:** expo-modules-core may install as TypeScript source (.ts) instead of compiled JS, causing prebuild errors.

**Why it happens:** Known issue in SDK 52 with certain npm configurations.

**How to avoid:** If you see `ERR_UNKNOWN_FILE_EXTENSION .ts` errors during prebuild:
1. Delete `node_modules` and `package-lock.json`
2. Run `npm install` fresh
3. If persists, check [expo/expo#38332](https://github.com/expo/expo/issues/38332) for workarounds

**Warning signs:** `Unknown file extension '.ts'` error during `npx expo prebuild`

### Pitfall 2: Test Files in app/ Directory

**What goes wrong:** Jest test files placed in `app/` become actual routes, causing navigation errors.

**Why it happens:** Expo Router treats ALL files in `app/` as routes (except `_layout.tsx` and special files).

**How to avoid:** Keep all test files in `__tests__/` directory at project root.

**Warning signs:** 404 errors or unexpected routes appearing in navigation.

### Pitfall 3: Environment Variable Access Syntax

**What goes wrong:** Environment variables return `undefined` despite being set in `.env`.

**Why it happens:** Expo's bundler only supports static dot notation for env vars.

**How to avoid:**
- Always use `process.env.EXPO_PUBLIC_VARNAME`
- Never use `process.env['EXPO_PUBLIC_VARNAME']`
- Never use destructuring: `const { EXPO_PUBLIC_X } = process.env`

**Warning signs:** `undefined` values at runtime despite correct `.env` configuration.

### Pitfall 4: Expo Go Limitations

**What goes wrong:** App works in development but crashes when testing features requiring native modules not in Expo Go.

**Why it happens:** Expo Go has a fixed set of native modules. Custom native code requires a development build.

**How to avoid:**
- For Phase 1 scaffolding: Expo Go is fine
- When adding native features: Create development build with `eas build --profile development`
- Use `npx expo-doctor` to check library compatibility

**Warning signs:** "Native module X is not available" errors in Expo Go.

### Pitfall 5: Cross-Platform Testing Gaps

**What goes wrong:** App works on iOS but crashes on Android (or vice versa).

**Why it happens:** Testing only on one platform during development.

**How to avoid:**
- Run on both iOS Simulator and Android Emulator from day one
- Set up CI to run tests on both platforms (jest-expo/universal)
- Budget time for platform-specific fixes

**Warning signs:** Bug reports clustering on one platform.

## Code Examples

Verified patterns from official sources:

### Project Initialization

```bash
# Source: https://docs.expo.dev/more/create-expo/
# Create new project with default template (Expo Router + TypeScript)
npx create-expo-app@latest dialectic-mobile

cd dialectic-mobile

# Start development server
npx expo start
```

### ESLint Configuration (Flat Config)

```javascript
// Source: https://docs.expo.dev/guides/using-eslint/
// eslint.config.js
const { defineConfig, globalIgnores } = require('eslint/config');
const expoConfig = require('eslint-config-expo/flat');
const eslintPluginPrettierRecommended = require('eslint-plugin-prettier/recommended');

module.exports = defineConfig([
  globalIgnores(['dist/*', 'node_modules/*', '.expo/*']),
  expoConfig,
  eslintPluginPrettierRecommended,
]);
```

### Prettier Configuration

```json
// .prettierrc
{
  "semi": true,
  "trailingComma": "es5",
  "singleQuote": true,
  "printWidth": 100,
  "tabWidth": 2,
  "useTabs": false,
  "arrowParens": "always",
  "endOfLine": "lf"
}
```

### Jest Configuration

```json
// Source: https://docs.expo.dev/develop/unit-testing/
// package.json (partial)
{
  "scripts": {
    "test": "jest",
    "test:watch": "jest --watchAll"
  },
  "jest": {
    "preset": "jest-expo",
    "setupFilesAfterEnv": ["./jest-setup.js"]
  }
}
```

```javascript
// jest-setup.js
import '@testing-library/react-native/extend-expect';
```

### Example Test File

```typescript
// Source: https://docs.expo.dev/develop/unit-testing/
// __tests__/HomeScreen-test.tsx
import { render, screen } from '@testing-library/react-native';
import HomeScreen from '../app/index';

describe('<HomeScreen />', () => {
  it('renders welcome text', () => {
    render(<HomeScreen />);
    expect(screen.getByText('Welcome!')).toBeTruthy();
  });
});
```

### GitHub Actions CI Workflow

```yaml
# Source: https://docs.expo.dev/build/building-on-ci/
# .github/workflows/ci.yml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  lint-and-test:
    name: Lint, Type Check, Test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5

      - uses: actions/setup-node@v6
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: mobile/package-lock.json

      - name: Install dependencies
        working-directory: mobile
        run: npm ci

      - name: Lint
        working-directory: mobile
        run: npx expo lint

      - name: Type check
        working-directory: mobile
        run: npx tsc --noEmit

      - name: Test
        working-directory: mobile
        run: npm test -- --ci --coverage

  build:
    name: EAS Build
    needs: lint-and-test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5

      - uses: actions/setup-node@v6
        with:
          node-version: 22
          cache: npm
          cache-dependency-path: mobile/package-lock.json

      - name: Setup Expo and EAS
        uses: expo/expo-github-action@v8
        with:
          eas-version: latest
          token: ${{ secrets.EXPO_TOKEN }}

      - name: Install dependencies
        working-directory: mobile
        run: npm ci

      - name: Build on EAS
        working-directory: mobile
        run: eas build --platform all --non-interactive --no-wait
```

### app.config.js with Environment Variables

```javascript
// Source: https://docs.expo.dev/workflow/configuration/
// app.config.js
export default {
  expo: {
    name: 'Dialectic',
    slug: 'dialectic',
    version: '1.0.0',
    orientation: 'portrait',
    icon: './assets/icon.png',
    userInterfaceStyle: 'automatic',
    newArchEnabled: true,
    splash: {
      image: './assets/splash-icon.png',
      resizeMode: 'contain',
      backgroundColor: '#ffffff',
    },
    ios: {
      supportsTablet: false,
      bundleIdentifier: 'com.dialectic.app',
    },
    android: {
      adaptiveIcon: {
        foregroundImage: './assets/adaptive-icon.png',
        backgroundColor: '#ffffff',
      },
      package: 'com.dialectic.app',
    },
    extra: {
      eas: {
        projectId: 'your-project-id', // Generated by EAS
      },
    },
    plugins: ['expo-router'],
  },
};
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Bridge architecture | New Architecture (JSI, TurboModules, Fabric) | SDK 52 default | 30-40% faster, sync native calls |
| Legacy ESLint config | Flat config format | SDK 53+ | Simpler configuration, modern API |
| react-test-renderer | @testing-library/react-native | React 19+ | RTR deprecated, RNTL actively maintained |
| AsyncStorage | react-native-mmkv | 2023+ | 30x faster, sync API, encryption |
| Manual navigation setup | Expo Router file-based | 2023 | Typed routes, simpler mental model |

**Deprecated/outdated:**

- **react-test-renderer:** Does not support React 19+. Use @testing-library/react-native.
- **Legacy ESLint .eslintrc.js:** Still works but flat config is recommended for new projects.
- **AsyncStorage:** Use react-native-mmkv for new projects (much faster, sync API).

## Open Questions

Things that couldn't be fully resolved:

1. **SDK 52 vs SDK 55**
   - What we know: CONTEXT.md specifies SDK 52, but SDK 55 is now latest stable
   - What's unclear: Whether SDK 52 is a firm requirement or can be updated
   - Recommendation: Use SDK 52 as specified; document upgrade path for future

2. **Monorepo vs Single Package**
   - What we know: User decided single-package with mobile in `/mobile`
   - What's unclear: How this interacts with existing `dialectic/` backend in same repo
   - Recommendation: Keep independent package.json, separate CI workflows

3. **Development Build Timing**
   - What we know: Expo Go works for basic scaffolding
   - What's unclear: When during Phase 1 to create first development build
   - Recommendation: Create development build profile in eas.json but don't build until needed

## Sources

### Primary (HIGH confidence)

- [Expo Documentation - create-expo-app](https://docs.expo.dev/more/create-expo/)
- [Expo Documentation - Expo Router Introduction](https://docs.expo.dev/router/introduction/)
- [Expo Documentation - Expo Router Core Concepts](https://docs.expo.dev/router/basics/core-concepts/)
- [Expo Documentation - Environment Variables](https://docs.expo.dev/guides/environment-variables/)
- [Expo Documentation - Using ESLint and Prettier](https://docs.expo.dev/guides/using-eslint/)
- [Expo Documentation - Unit Testing with Jest](https://docs.expo.dev/develop/unit-testing/)
- [Expo Documentation - EAS Build on CI](https://docs.expo.dev/build/building-on-ci/)
- [Expo Documentation - Configure EAS Build with eas.json](https://docs.expo.dev/build/eas-json/)
- [Expo Documentation - Development Builds Introduction](https://docs.expo.dev/develop/development-builds/introduction/)
- [Expo SDK 52 Changelog](https://expo.dev/changelog/2024-11-12-sdk-52)
- [React Native 0.76 Release](https://reactnative.dev/blog/2024/10/23/release-0.76-new-architecture)

### Secondary (MEDIUM confidence)

- [Expo GitHub Action](https://github.com/expo/expo-github-action)
- [Expo Blog - Expo Go vs Development Builds](https://expo.dev/blog/expo-go-vs-development-builds)

### Tertiary (LOW confidence)

- [GitHub Issue: expo-modules-core TypeScript source issue](https://github.com/expo/expo/issues/38332) - Known issue, may be resolved

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH - All from official Expo documentation
- Architecture: HIGH - Expo Router patterns well-documented
- Pitfalls: MEDIUM - Some from community reports, validated with official docs
- CI/CD: HIGH - expo-github-action is official Expo project

**Research date:** 2026-01-20
**Valid until:** 2026-04-20 (90 days - stable technology, slow-moving)
