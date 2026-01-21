# Technology Stack

**Project:** Dialectic Cross-Platform Clients
**Researched:** 2026-01-20
**Overall Confidence:** HIGH

## Executive Recommendation

**Use React Native with Expo** for the cross-platform mobile/desktop clients.

**Rationale:**
1. **JavaScript/TypeScript alignment**: Existing backends (FastAPI) already serve JSON over WebSocket. React Native's JS-native ecosystem maps directly to your data transport.
2. **Desktop support via Microsoft**: React Native for Windows and macOS are Microsoft-maintained, production-grade, and used by Office. Flutter's desktop is stable but has a smaller enterprise footprint.
3. **WebSocket integration**: Socket.IO and native WebSocket APIs are JavaScript-native; Flutter requires Dart wrappers that add abstraction layers.
4. **Hiring and maintainability**: ~1.4x more React/React Native developers exist compared to Flutter/Dart developers. Your team's JavaScript familiarity reduces ramp-up time.
5. **New Architecture maturity**: React Native 0.82+ runs entirely on the New Architecture with JSI (no bridge), eliminating the historical performance criticism.

---

## Recommended Stack

### Core Framework

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| React Native | 0.83+ | Cross-platform mobile framework | New Architecture (TurboModules, Fabric) is now mandatory and mature. React 19.2 integration provides modern patterns. | HIGH |
| Expo SDK | 55+ | Development toolchain & managed services | Handles builds, OTA updates, push notifications. SDK 55 supports New Architecture and React Native 0.83. | HIGH |
| TypeScript | 5.x | Type safety | Type-safe native modules via JSI. Catches errors at compile time. | HIGH |

### Desktop Targets

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| React Native Windows | 0.79+ | Windows desktop client | Microsoft-maintained, used by Office. WinAppSDK Win32 with Fabric renderer. | HIGH |
| React Native macOS | 0.79+ | macOS desktop client | Microsoft-maintained, same codebase as mobile. Native macOS UI components. | HIGH |

### State Management

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| Zustand | 5.x | Client-side global state | ~3KB bundle, hook-based API, no providers required. 40% market share in 2026. Perfect for small-to-mid apps. | HIGH |
| TanStack Query | 5.x | Server state & caching | Handles WebSocket-fetched data, caching, offline persistence. Industry standard for server state. | HIGH |

### Real-time Communication

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| Native WebSocket API | (built-in) | Primary WebSocket transport | React Native supports WebSocket natively. No library needed for basic connectivity. | HIGH |
| @react-native-community/netinfo | 11.x | Network state detection | Required for reconnection logic on mobile. Detects connectivity changes. | HIGH |

### Local Storage

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| react-native-mmkv | 4.x (V4) | Fast key-value storage | 30x faster than AsyncStorage, synchronous API, encryption support. Now a Nitro Module. | HIGH |
| TanStack Query Persister | 5.x | Query cache persistence | Survives app restart. Uses MMKV as storage backend. | HIGH |

### Push Notifications

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| @react-native-firebase/messaging | 21.x | FCM integration | Cross-platform (iOS via APNs, Android via FCM). Free, reliable, well-documented. | HIGH |
| expo-notifications | 0.29.x | Expo-managed push notifications | If staying in Expo managed workflow. Simpler setup, less configuration. | MEDIUM |

### Navigation

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| React Navigation | 7.x | Screen navigation | De facto standard for React Native. Deep linking, native-like transitions. | HIGH |

### UI Components

| Technology | Version | Purpose | Why | Confidence |
|------------|---------|---------|-----|------------|
| NativeWind | 4.x | Tailwind CSS for React Native | If team knows Tailwind. Cross-platform styling with atomic classes. | MEDIUM |
| Tamagui | 1.x | Cross-platform UI kit | Excellent for desktop+mobile with same components. Type-safe, performant. | MEDIUM |

---

## Installation

```bash
# Create new Expo project with TypeScript
npx create-expo-app@latest dialectic-client --template expo-template-blank-typescript

# Core dependencies
npm install zustand @tanstack/react-query @tanstack/query-async-storage-persister

# Storage (MMKV)
npm install react-native-mmkv

# Network state (for reconnection logic)
npm install @react-native-community/netinfo

# Navigation
npm install @react-navigation/native @react-navigation/native-stack

# Firebase (if using bare workflow or ejecting)
npm install @react-native-firebase/app @react-native-firebase/messaging

# OR Expo notifications (if staying managed)
npx expo install expo-notifications

# UI (choose one)
npm install nativewind tailwindcss  # For NativeWind
# OR
npm install tamagui @tamagui/config  # For Tamagui
```

### Desktop Setup (React Native Windows/macOS)

For Windows and macOS desktop targets, you'll need to eject from Expo managed workflow or use a bare workflow:

```bash
# Windows (run from project root)
npx react-native-windows-init --overwrite

# macOS (run from project root)
npx react-native-macos-init
```

---

## Alternatives Considered

### Framework: Flutter

| Criterion | React Native (Recommended) | Flutter |
|-----------|---------------------------|---------|
| **Desktop maturity** | Microsoft-maintained, used by Office | Stable but smaller enterprise footprint |
| **Developer pool** | ~1.4x larger than Flutter | Growing but smaller |
| **WebSocket native** | JavaScript-native (your backend speaks JSON) | Requires Dart wrappers |
| **Existing team skills** | If JS/TS familiar: immediate | Dart learning curve |
| **New Architecture** | Mandatory in 0.82+, no bridge | Impeller stable on both platforms |
| **Bundle size** | Smaller initial bundle | Larger due to Skia/Impeller engine |

**Verdict:** Flutter is excellent and would work. Choose React Native because:
1. JavaScript/TypeScript aligns with web team skills
2. Microsoft actively maintains desktop targets
3. WebSocket handling is more natural in JS ecosystem

### State: Redux Toolkit vs Zustand vs Jotai

| Criterion | Zustand (Recommended) | Redux Toolkit | Jotai |
|-----------|----------------------|---------------|-------|
| **Bundle size** | ~3KB | ~15KB | ~1.2KB |
| **Learning curve** | Minimal | Moderate | Minimal |
| **Boilerplate** | Almost none | Reduced but still present | None |
| **DevTools** | Excellent (via zustand/middleware) | Best-in-class | Good |
| **Use case** | Small-to-mid apps | Large enterprise | Fine-grained reactivity |

**Verdict:** Zustand. For a 2-human + LLM app, you don't need Redux's ceremony. Zustand's simplicity wins.

### Storage: MMKV vs AsyncStorage

| Criterion | MMKV (Recommended) | AsyncStorage |
|-----------|-------------------|--------------|
| **Performance** | 30x faster | Baseline |
| **API** | Synchronous | Async only |
| **Encryption** | Built-in | Not supported |
| **New Architecture** | Nitro Module (V4) | Bridge-based |

**Verdict:** MMKV. Faster, synchronous, encrypted. No reason to use AsyncStorage for new projects.

### Push Notifications: Firebase vs OneSignal vs Expo

| Criterion | Firebase (Recommended) | OneSignal | Expo Notifications |
|-----------|----------------------|-----------|-------------------|
| **Cost** | Free | Free tier limited | Free |
| **Setup complexity** | Moderate | Easy | Easiest |
| **Bare workflow** | Required | Supported | Not required |
| **Analytics** | Integrated | Separate | Basic |
| **Reliability** | Excellent | Excellent | Good |

**Verdict:** Firebase if you eject for desktop support (which you will). Expo Notifications if you stay managed-only for mobile.

---

## Architecture Decisions

### Expo Managed vs Bare Workflow

**Recommendation: Start with Expo managed, plan to eject for desktop.**

- **Phase 1 (Mobile MVP):** Use Expo managed workflow. Faster iteration, OTA updates, no Xcode/Android Studio needed.
- **Phase 2 (Desktop):** Eject to bare workflow when adding React Native Windows/macOS. Desktop targets require native project access.

Expo's `expo prebuild` generates native projects when you need them. This isn't a one-way door.

### WebSocket Strategy

**Use native WebSocket API, not Socket.IO**, because:

1. Your backend already speaks raw WebSocket (FastAPI + WebSocket handler)
2. Socket.IO adds protocol overhead for features you may not need
3. Native WebSocket + manual reconnection logic gives you more control

```typescript
// WebSocket singleton pattern (recommended)
class WebSocketManager {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;

  connect(roomId: string) {
    this.ws = new WebSocket(`wss://api.dialectic.app/ws/${roomId}`);
    this.ws.onclose = () => this.handleReconnect(roomId);
  }

  private handleReconnect(roomId: string) {
    const delay = Math.min(1000 * 2 ** this.reconnectAttempts, 30000);
    setTimeout(() => this.connect(roomId), delay);
    this.reconnectAttempts++;
  }
}
```

### Offline Persistence Strategy

**Use TanStack Query with MMKV persister:**

```typescript
import { QueryClient } from '@tanstack/react-query';
import { createAsyncStoragePersister } from '@tanstack/query-async-storage-persister';
import { MMKV } from 'react-native-mmkv';

const storage = new MMKV();
const mmkvStorage = {
  setItem: (key: string, value: string) => storage.set(key, value),
  getItem: (key: string) => storage.getString(key) ?? null,
  removeItem: (key: string) => storage.delete(key),
};

const persister = createAsyncStoragePersister({
  storage: mmkvStorage,
});
```

---

## Version Matrix (Verified January 2026)

| Package | Minimum Version | Source |
|---------|-----------------|--------|
| React Native | 0.83 | [reactnative.dev/blog](https://reactnative.dev/blog) |
| Expo SDK | 55 | [expo.dev/changelog](https://expo.dev/changelog/sdk-54) |
| React | 19.2 | Bundled with RN 0.83 |
| React Native Windows | 0.79 | [github.com/microsoft/react-native-windows](https://github.com/microsoft/react-native-windows) |
| React Native macOS | 0.79 | [github.com/microsoft/react-native-macos](https://github.com/microsoft/react-native-macos) |
| Zustand | 5.x | [zustand.docs.pmnd.rs](https://zustand.docs.pmnd.rs) |
| TanStack Query | 5.x | [tanstack.com/query](https://tanstack.com/query/latest) |
| react-native-mmkv | 4.x | [github.com/mrousavy/react-native-mmkv](https://github.com/mrousavy/react-native-mmkv) |
| @react-native-firebase/messaging | 21.x | [rnfirebase.io](https://rnfirebase.io/messaging/usage) |

---

## What NOT to Use

| Technology | Why Avoid |
|------------|-----------|
| **AsyncStorage** | 30x slower than MMKV, no encryption, async-only API |
| **Legacy React Native (<0.82)** | New Architecture is mandatory; legacy support ended |
| **Redux (vanilla)** | Too much boilerplate for this app size. Use Zustand or Redux Toolkit if you insist. |
| **Socket.IO** | Adds protocol overhead when your backend already speaks raw WebSocket |
| **GetX (if considering Flutter)** | Single maintainer, maintenance crisis, avoid for new projects |
| **Realm** | Overkill for key-value storage; use MMKV. Only consider if you need complex queries. |
| **Expo managed-only for desktop** | Doesn't support React Native Windows/macOS; must eject |

---

## Integration with Existing Backends

### Dialectic Backend (FastAPI + WebSocket)

```typescript
// Client connects to existing WebSocket handler
const ws = new WebSocket('wss://dialectic-api/ws/{room_id}');

// Send message (matches existing message types)
ws.send(JSON.stringify({
  type: 'send_message',
  content: '...',
  speaker_type: 'HUMAN'
}));

// Handle events (event sourcing model)
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  // Update local state via Zustand/TanStack Query
};
```

### Cairn Backend (Session Management)

```typescript
// Use fetch/axios for REST endpoints
import { useQuery, useMutation } from '@tanstack/react-query';

const { data: session } = useQuery({
  queryKey: ['session', sessionId],
  queryFn: () => fetch(`https://cairn-api/sessions/${sessionId}`).then(r => r.json()),
});
```

---

## Sources

**Official Documentation:**
- [React Native Blog - Latest Releases](https://reactnative.dev/blog) (Verified 2026-01-20)
- [Expo SDK 54 Changelog](https://expo.dev/changelog/sdk-54)
- [Flutter 3.38 Release Notes](https://docs.flutter.dev/release/release-notes)
- [React Native Windows](https://microsoft.github.io/react-native-windows/)
- [React Native macOS](https://github.com/microsoft/react-native-macos)
- [Firebase Cloud Messaging](https://firebase.google.com/docs/cloud-messaging) (Updated 2026-01-15)
- [TanStack Query React Native](https://tanstack.com/query/latest/docs/framework/react/react-native)

**Comparison Sources:**
- [Flutter vs React Native 2026 - TechAhead](https://www.techaheadcorp.com/blog/flutter-vs-react-native-in-2026-the-ultimate-showdown-for-app-development-dominance/)
- [State Management in 2026 - Nucamp](https://www.nucamp.co/blog/state-management-in-2026-redux-context-api-and-modern-patterns)
- [Zustand vs Redux vs Jotai - BetterStack](https://betterstack.com/community/guides/scaling-nodejs/zustand-vs-redux-toolkit-vs-jotai/)
- [MMKV vs AsyncStorage - GitHub](https://github.com/mrousavy/react-native-mmkv)
- [Push Notification Providers 2026 - Knock](https://knock.app/blog/evaluating-the-best-push-notifications-providers)
