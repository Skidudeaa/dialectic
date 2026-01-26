/**
 * @dialectic/app - Shared application code
 *
 * ARCHITECTURE: Platform-agnostic code shared across mobile, macOS, and Windows.
 * WHY: Single source of truth for business logic, types, and utilities.
 * TRADEOFF: Must avoid platform-specific imports; platforms provide implementations.
 *
 * This barrel export will be populated in Plan 04 (Shared Code Extraction).
 * Current structure prepared for:
 * - components/  - Shared UI components
 * - hooks/       - Shared hooks
 * - stores/      - Zustand stores
 * - services/    - Platform-agnostic service interfaces
 * - types/       - TypeScript types
 */

// Placeholder export to make module valid
export const VERSION = '1.0.0';
