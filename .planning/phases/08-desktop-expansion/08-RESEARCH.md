# Phase 8: Desktop Expansion - Research

**Researched:** 2026-01-26
**Domain:** React Native Desktop (Windows + macOS)
**Confidence:** MEDIUM

## Summary

React Native for Windows and macOS are "out-of-tree" platforms maintained by Microsoft. They enable native desktop apps using the same React paradigm as mobile, but with significant differences from the Expo-managed workflow used in Phases 1-7. The project must transition from Expo managed workflow to a monorepo structure with bare workflows for each desktop platform.

The key challenge is that Expo does not officially support Windows or macOS. While some Expo modules work on macOS (expo-sqlite claims macOS support), Windows support is nonexistent for most Expo packages. This requires replacing or adapting several dependencies from the mobile implementation.

**Primary recommendation:** Structure as a Yarn Workspaces monorepo with separate platform workspaces (mobile, macos, windows) sharing a common app package. Replace Expo-specific dependencies with cross-platform alternatives: react-native-sqlite-2 for SQLite, react-native-keychain for secure storage (macOS only, Windows needs native module), and platform-specific implementations for notifications, system tray, and context menus.

## Standard Stack

The established libraries/tools for React Native desktop development:

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| react-native-windows | 0.81.x | Windows native rendering | Microsoft-maintained, New Architecture default, aligned with RN 0.81 |
| react-native-macos | 0.79.x | macOS native rendering | Microsoft-maintained, AppKit-based, lags behind RN mainline |
| react-native | 0.81.x | Core framework (mobile) | Must align with RN-Windows version |
| Yarn Workspaces | 4.x | Monorepo management | Enables nohoist for version isolation per platform |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| react-native-sqlite-2 | 3.6.x | SQLite for all platforms | Replaces expo-sqlite; supports iOS, Android, Windows, macOS |
| react-native-keychain | 10.x | Secure credential storage | macOS via Catalyst, iOS/Android native; no Windows support |
| react-native-menubar-extra | latest | macOS dock/menu bar | NSMenu integration for macOS menu bar apps |
| react-native-winrt | latest | Windows API access | Direct WinRT API calls from JS (notifications, system features) |
| react-native-mmkv | 3.x | Fast key-value storage | Partial desktop support (macOS yes, Windows experimental branch) |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| expo-sqlite | react-native-sqlite-2 | Cross-platform (Win/Mac), WebSQL API, less type-safe than Drizzle |
| expo-sqlite | OP-SQLite | macOS native support, Windows unknown, faster but less tested |
| expo-secure-store | react-native-keychain | macOS Catalyst support, Windows requires custom native module |
| FlashList | FlatList | FlashList runs JS-only on desktop (untested), FlatList safer |

**Installation (per platform workspace):**
```bash
# Windows workspace
yarn add react-native-windows@^0.81.0 react-native-sqlite-2

# macOS workspace
yarn add react-native-macos@^0.79.0 react-native-sqlite-2 react-native-keychain react-native-menubar-extra
```

## Architecture Patterns

### Recommended Project Structure

```
dialectic/
├── packages/
│   ├── app/                    # Shared JS/TS application code
│   │   ├── src/
│   │   │   ├── components/     # Shared UI components
│   │   │   ├── hooks/          # Shared hooks
│   │   │   ├── stores/         # Zustand stores
│   │   │   ├── services/       # Platform-agnostic services
│   │   │   └── types/          # TypeScript types
│   │   └── package.json
│   │
│   ├── mobile/                 # iOS + Android (existing Expo app)
│   │   ├── android/
│   │   ├── ios/
│   │   ├── app.config.js
│   │   ├── metro.config.js
│   │   └── package.json
│   │
│   ├── macos/                  # macOS bare workflow
│   │   ├── macos/              # Native Xcode project
│   │   ├── index.js
│   │   ├── metro.config.js
│   │   └── package.json
│   │
│   └── windows/                # Windows bare workflow
│       ├── windows/            # Native Visual Studio project
│       ├── index.js
│       ├── metro.config.js
│       └── package.json
│
├── package.json                # Workspaces root
└── yarn.lock
```

### Pattern 1: Platform-Specific Service Abstraction

**What:** Create platform-agnostic interfaces with platform-specific implementations
**When to use:** Dependencies that differ between mobile and desktop (secure storage, notifications, file handling)

```typescript
// packages/app/src/services/secure-storage.ts
export interface SecureStorage {
  set(key: string, value: string): Promise<void>;
  get(key: string): Promise<string | null>;
  delete(key: string): Promise<void>;
}

// packages/mobile/src/services/secure-storage.ts
import * as SecureStore from 'expo-secure-store';
export const secureStorage: SecureStorage = {
  set: (key, value) => SecureStore.setItemAsync(key, value),
  get: (key) => SecureStore.getItemAsync(key),
  delete: (key) => SecureStore.deleteItemAsync(key),
};

// packages/macos/src/services/secure-storage.ts
import * as Keychain from 'react-native-keychain';
export const secureStorage: SecureStorage = {
  set: async (key, value) => {
    await Keychain.setGenericPassword(key, value, { service: key });
  },
  get: async (key) => {
    const result = await Keychain.getGenericPassword({ service: key });
    return result ? result.password : null;
  },
  delete: async (key) => {
    await Keychain.resetGenericPassword({ service: key });
  },
};

// packages/windows/src/services/secure-storage.ts
// Native module required - Windows Credential Manager
import { WindowsCredentialStore } from '../native/CredentialStore';
export const secureStorage: SecureStorage = {
  set: (key, value) => WindowsCredentialStore.set(key, value),
  get: (key) => WindowsCredentialStore.get(key),
  delete: (key) => WindowsCredentialStore.delete(key),
};
```

### Pattern 2: Platform File Extensions

**What:** Use React Native's platform-specific file extensions
**When to use:** Components/hooks with minor platform differences

```
Button.tsx           # Default/shared
Button.macos.tsx     # macOS-specific
Button.windows.tsx   # Windows-specific
Button.ios.tsx       # iOS-specific
Button.android.tsx   # Android-specific
```

Metro resolves the correct file based on platform at build time.

### Pattern 3: Nohoist Configuration

**What:** Prevent hoisting of packages that need platform-specific versions
**When to use:** react-native, platform-specific packages, native-linked modules

```json
// Root package.json
{
  "workspaces": {
    "packages": ["packages/*"],
    "nohoist": [
      "**/react-native",
      "**/react-native/**",
      "**/react-native-windows",
      "**/react-native-windows/**",
      "**/react-native-macos",
      "**/react-native-macos/**",
      "**/@react-native-*",
      "**/@react-native-*/**"
    ]
  }
}
```

### Anti-Patterns to Avoid

- **Assuming Expo modules work on desktop:** Most don't. expo-secure-store, expo-notifications, expo-file-system have no Windows support and limited macOS support.
- **Synchronizing RN versions across platforms:** Use nohoist to allow different versions. macOS lags behind Windows/mobile.
- **Using FlatList without testing:** FlashList runs JS-only on desktop; test thoroughly or fall back to FlatList.
- **Sharing native module code:** Windows uses C++/C# with WinRT, macOS uses Objective-C/Swift with AppKit. They're fundamentally different.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Windows notifications | Custom notification system | react-native-winrt + Windows.UI.Notifications | Toast APIs, Action Center integration, badge support built-in |
| macOS menu bar | Custom NSMenu bindings | react-native-menubar-extra | Already maps JSX to AppKit menu elements |
| Windows keyboard shortcuts | onKeyDown event handlers | IKeyboardProps API / useHotkeys pattern | Platform-aware global shortcuts, modifier key handling |
| macOS drag-drop | Custom native module | Built-in onDragEnter/onDragLeave/onDrop | RN-macOS has native support via View props |
| Windows drag-drop | Custom native module | Sample project pattern (dstaley/react-native-windows-drag-drop-sample) | UWP drag-drop handlers with native module |
| Multi-window management | Window manager from scratch | Native APIs via native modules | Each platform handles windows differently |

**Key insight:** Desktop platforms have mature native APIs. The challenge is bridging them to JS, not reimplementing them. Look for existing native modules or create thin wrappers over WinRT (Windows) and AppKit (macOS) APIs.

## Common Pitfalls

### Pitfall 1: Version Mismatch Between Platforms

**What goes wrong:** react-native-macos (0.79) is behind react-native-windows (0.81) and mainline RN (0.83). Shared packages may have incompatible peer dependencies.
**Why it happens:** macOS support has fewer contributors; updates lag by 2-4 versions.
**How to avoid:** Use Yarn nohoist to isolate versions. Shared app code should avoid RN-version-specific features. Test on lowest common denominator.
**Warning signs:** Peer dependency warnings, "property does not exist" errors, New Architecture incompatibilities.

### Pitfall 2: Expo Module Assumptions

**What goes wrong:** Code assumes expo-* packages exist; crashes on desktop with "module not found."
**Why it happens:** Mobile codebase uses Expo managed workflow; desktop uses bare workflow.
**How to avoid:** Abstract all platform-specific code behind interfaces. Use Platform.select or .platform.tsx files. Create mock implementations for missing modules.
**Warning signs:** Import errors mentioning "expo-*" on desktop builds.

### Pitfall 3: UIKit/AppKit Confusion on macOS

**What goes wrong:** iOS-style components render incorrectly or crash on macOS.
**Why it happens:** react-native-macos provides aliases (UIView -> NSView) but behaviors differ.
**How to avoid:** Test all components on macOS. Use macOS-specific styles where needed. Review Microsoft's macOS documentation for known differences.
**Warning signs:** Scroll behavior issues, touch vs click handling, keyboard navigation broken.

### Pitfall 4: Windows New Architecture Lock-In

**What goes wrong:** App uses Paper-based patterns; doesn't migrate to Fabric.
**Why it happens:** New Architecture is default in RN-Windows 0.80+. Paper deprecated in 0.82.
**How to avoid:** Initialize with `--template cpp-app` (New Architecture). Use Fabric-compatible components only.
**Warning signs:** Deprecation warnings, performance issues, UWP-only APIs failing.

### Pitfall 5: FlashList Desktop Failures

**What goes wrong:** FlashList renders nothing or crashes on Windows/macOS.
**Why it happens:** FlashList runs JS-only mode on desktop; no native optimization. Shopify doesn't test desktop.
**How to avoid:** Test FlashList thoroughly on desktop. Have FlatList fallback ready. Consider using FlatList on desktop if issues arise.
**Warning signs:** Empty lists, scroll performance issues, AutoLayoutView errors.

### Pitfall 6: Missing Windows Secure Storage

**What goes wrong:** No credential storage on Windows; auth tokens stored insecurely.
**Why it happens:** react-native-keychain has no Windows support. expo-secure-store doesn't work.
**How to avoid:** Create native Windows module using Windows Credential Manager (CredentialManager class). Or use encrypted MMKV as fallback (less secure than OS keychain).
**Warning signs:** "Module not found" for keychain packages on Windows.

## Code Examples

Verified patterns from official sources:

### Windows Toast Notifications (React Native WinRT)

```typescript
// Source: https://microsoft.github.io/react-native-windows/blog/2022/02/11/rnwinrt
import { ToastNotificationManager, ToastTemplateType, XmlDocument } from 'react-native-winrt';

function showToast(title: string, message: string) {
  const template = ToastNotificationManager.getTemplateContent(
    ToastTemplateType.toastText02
  );

  const textNodes = template.getElementsByTagName('text');
  textNodes.item(0).appendChild(template.createTextNode(title));
  textNodes.item(1).appendChild(template.createTextNode(message));

  const toast = new ToastNotification(template);
  ToastNotificationManager.createToastNotifier().show(toast);
}
```

### macOS Menu Bar with react-native-menubar-extra

```typescript
// Source: https://github.com/okwasniewski/react-native-menubar-extra
import { MenuBarExtraProvider, MenuBarMenu, MenuBarItem, MenuBarSeparator } from 'react-native-menubar-extra';

function App() {
  return (
    <MenuBarExtraProvider icon="icon-name">
      <MenuBarMenu title="Dialectic">
        <MenuBarItem title="New Room" shortcut="cmd+n" onPress={handleNewRoom} />
        <MenuBarItem title="Search" shortcut="cmd+f" onPress={handleSearch} />
        <MenuBarSeparator />
        <MenuBarItem title="Quit" shortcut="cmd+q" onPress={handleQuit} />
      </MenuBarMenu>
    </MenuBarExtraProvider>
  );
}
```

### Windows Keyboard Shortcuts (IKeyboardProps)

```typescript
// Source: https://microsoft.github.io/react-native-windows/docs/ikeyboardprops-api
import { View } from 'react-native';

function MessageInput() {
  return (
    <View
      supportKeyboard={true}
      onKeyDown={(e) => {
        // Ctrl+Enter to send
        if (e.nativeEvent.key === 'Enter' && e.nativeEvent.ctrlKey) {
          handleSend();
          e.stopPropagation();
        }
      }}
    >
      {/* Input content */}
    </View>
  );
}
```

### macOS Drag-and-Drop Files

```typescript
// Source: https://github.com/microsoft/react-native-macos/issues/842
// react-native-macos supports onDragEnter, onDragLeave, onDrop on Views

function DropZone() {
  const [isDragging, setIsDragging] = useState(false);

  return (
    <View
      style={[styles.dropZone, isDragging && styles.dragging]}
      onDragEnter={() => setIsDragging(true)}
      onDragLeave={() => setIsDragging(false)}
      onDrop={(e) => {
        setIsDragging(false);
        const files = e.nativeEvent.dataTransfer.files;
        // files is array of { uri: string, type: string, name: string }
        handleFileDrop(files);
      }}
    >
      <Text>Drop files here</Text>
    </View>
  );
}
```

### Platform-Conditional Code

```typescript
// Source: React Native Platform documentation
import { Platform } from 'react-native';

const isDesktop = Platform.OS === 'windows' || Platform.OS === 'macos';
const isMobile = Platform.OS === 'ios' || Platform.OS === 'android';

// Keyboard shortcut display
const modifierKey = Platform.select({
  macos: 'Cmd',
  windows: 'Ctrl',
  default: '',
});

// Conditional styling
const styles = StyleSheet.create({
  container: {
    maxWidth: isDesktop ? 800 : undefined, // Centered layout on desktop
    alignSelf: isDesktop ? 'center' : undefined,
  },
});
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| UWP XAML rendering | WinAppSDK/Composition (Fabric) | RN-Windows 0.80 (2025) | Better performance, modern Windows APIs |
| Paper renderer | Fabric renderer | RN-Windows 0.80 default | Cross-platform rendering parity |
| expo eject | Bare workflow from start | Expo SDK 46 (2022) | No ejection needed; start bare for desktop |
| Single RN version | Nohoist per-platform versions | Monorepo pattern established | Allows version divergence |

**Deprecated/outdated:**
- **Paper renderer in RN-Windows**: Not supported from 0.82 onward
- **UWP-only apps**: New Architecture uses Win32/WinAppSDK
- **expo eject command**: Deprecated since SDK 46; use bare workflow or prebuild

## Open Questions

Things that couldn't be fully resolved:

1. **Windows Secure Storage Implementation**
   - What we know: react-native-keychain has no Windows support; need native module for Credential Manager
   - What's unclear: Whether existing community solutions exist or must be built from scratch
   - Recommendation: Plan for native C++/C# module development; budget 1-2 days

2. **MMKV Windows Support Status**
   - What we know: There's a windows-support branch on the MMKV repo; macOS works
   - What's unclear: Whether branch is production-ready or experimental
   - Recommendation: Test MMKV on Windows during implementation; have AsyncStorage fallback

3. **FlashList Desktop Reliability**
   - What we know: Runs in JS-only mode, Shopify doesn't test desktop
   - What's unclear: Specific failure modes, performance characteristics
   - Recommendation: Test early with real message data; prepare FlatList fallback

4. **react-native-controlled-mentions Desktop Compatibility**
   - What we know: Pure JS library, should theoretically work
   - What's unclear: Whether TextInput behaviors differ enough to cause issues
   - Recommendation: Test @Claude mentions on both platforms early

5. **Multi-Window Implementation Approach**
   - What we know: RN-Windows supports multiple root views via native code; RN-macOS similar
   - What's unclear: Shared JS context behavior, state management across windows
   - Recommendation: Start with single-window; add multi-window as enhancement

## Sources

### Primary (HIGH confidence)
- React Native Windows Official Docs: https://microsoft.github.io/react-native-windows/
- React Native macOS Official Docs: https://microsoft.github.io/react-native-macos/
- React Native Windows New Architecture: https://microsoft.github.io/react-native-windows/docs/new-architecture
- React Native WinRT (notifications): https://microsoft.github.io/react-native-windows/blog/2022/02/11/rnwinrt

### Secondary (MEDIUM confidence)
- react-native-menubar-extra: https://github.com/okwasniewski/react-native-menubar-extra
- react-native-universal-monorepo: https://github.com/mmazzarolo/react-native-universal-monorepo
- react-native-sqlite-2: https://github.com/craftzdog/react-native-sqlite-2
- react-native-keychain: https://github.com/oblador/react-native-keychain
- FlashList Windows issue: https://github.com/Shopify/flash-list/issues/482

### Tertiary (LOW confidence)
- MMKV Windows support branch: https://github.com/mrousavy/react-native-mmkv/tree/windows-support
- Windows drag-drop sample: https://github.com/dstaley/react-native-windows-drag-drop-sample
- Expo Windows discussion: https://github.com/expo/expo/discussions/22273

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM - Official docs verified, but desktop RN ecosystem less mature than mobile
- Architecture: MEDIUM - Monorepo pattern well-documented, but Dialectic-specific adaptation untested
- Pitfalls: HIGH - Multiple sources confirm version lag, Expo incompatibility, platform differences
- Dependency replacements: MEDIUM - Alternatives identified but Windows gaps remain (secure storage)

**Research date:** 2026-01-26
**Valid until:** 2026-02-26 (30 days - desktop RN ecosystem evolving but stable)
