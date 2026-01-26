/**
 * @dialectic/app - Shared application code
 *
 * ARCHITECTURE: Platform-agnostic code shared across mobile, macOS, and Windows.
 * WHY: Single source of truth for business logic, types, and utilities.
 * TRADEOFF: Must avoid platform-specific imports; platforms provide implementations.
 *
 * Current structure:
 * - services/    - Platform service abstractions (storage, database, notifications)
 * - components/  - Shared UI components (desktop/, chat/)
 * - hooks/       - Shared hooks (keyboard shortcuts, window persistence)
 * - styles/      - Desktop style utilities
 *
 * Future additions (as shared code is extracted):
 * - stores/      - Zustand stores
 * - types/       - TypeScript types
 */

// Services (platform abstractions)
export * from './services';

// Desktop components (only render on desktop platforms)
export * from './components/desktop';

// Chat components (cross-platform)
export * from './components/chat';

// Hooks
export * from './hooks';

// Styles
export * from './styles/desktop';

// Version for debugging
export const VERSION = '1.0.0';
