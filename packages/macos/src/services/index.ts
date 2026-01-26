/**
 * Barrel export for macOS service implementations.
 *
 * ARCHITECTURE: Single import point for all macOS-specific service implementations.
 * WHY: Clean import path for platform-init.ts registration.
 */

export { secureStorage } from './secure-storage';
export { database } from './database';
export { notificationService } from './notifications';
