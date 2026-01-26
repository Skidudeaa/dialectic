/**
 * @dialectic/app - Shared application code
 *
 * ARCHITECTURE: Platform-agnostic code shared across mobile, macOS, and Windows.
 * WHY: Single source of truth for business logic, types, and utilities.
 * TRADEOFF: Must avoid platform-specific imports; platforms provide implementations.
 *
 * Current structure:
 * - services/    - Platform service abstractions (storage, database, notifications)
 *
 * Future additions (as shared code is extracted):
 * - components/  - Shared UI components
 * - hooks/       - Shared hooks
 * - stores/      - Zustand stores
 * - types/       - TypeScript types
 */

// Services (platform abstractions)
export * from './services';

// Version for debugging
export const VERSION = '1.0.0';
