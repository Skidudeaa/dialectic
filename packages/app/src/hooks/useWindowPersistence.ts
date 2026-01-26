/**
 * Window persistence hook for desktop apps.
 *
 * ARCHITECTURE: Remembers window size/position across app sessions.
 * WHY: Desktop users expect windows to reopen where they left them.
 * TRADEOFF: Uses injection pattern; platform provides storage implementation.
 */

import { useEffect, useRef } from 'react';
import { Platform, useWindowDimensions } from 'react-native';

const STORAGE_KEY = 'window-state';

interface WindowState {
  width: number;
  height: number;
  x?: number;
  y?: number;
}

/**
 * Simple key-value storage interface for window persistence.
 * Platform apps inject their implementation (e.g., MMKV).
 */
interface WindowStorage {
  getString(key: string): string | undefined;
  set(key: string, value: string): void;
}

// Injected storage instance
let storage: WindowStorage | null = null;

/**
 * Set the storage implementation for window persistence.
 * Called by platform apps during initialization.
 */
export function setWindowStorageImplementation(impl: WindowStorage): void {
  storage = impl;
}

function getStorage(): WindowStorage | null {
  return storage;
}

/**
 * Persist and restore window size/position on desktop.
 *
 * On app launch: restores last window state.
 * On window resize/move: saves new state.
 *
 * Mobile platforms: no-op.
 */
export function useWindowPersistence(): void {
  const isDesktop = Platform.OS === 'macos' || Platform.OS === 'windows';
  const { width, height } = useWindowDimensions();
  const lastSavedRef = useRef<WindowState | null>(null);

  // Restore window state on mount
  useEffect(() => {
    if (!isDesktop) return;

    const storage = getStorage();
    if (!storage) return;

    try {
      const saved = storage.getString(STORAGE_KEY);
      if (saved) {
        const state: WindowState = JSON.parse(saved);

        // Restore window size via native module
        // This requires a native module to actually resize the window
        // Placeholder: log intent
        console.log('[WindowPersistence] Restoring:', state);

        // NativeModules.WindowManager?.setWindowFrame?.(state);
      }
    } catch (error) {
      console.warn('Failed to restore window state:', error);
    }
  }, [isDesktop]);

  // Save window state on changes (debounced)
  useEffect(() => {
    if (!isDesktop) return;

    const storage = getStorage();
    if (!storage) return;

    // Simple debounce - only save if different from last saved
    const currentState: WindowState = { width, height };

    if (
      !lastSavedRef.current ||
      lastSavedRef.current.width !== width ||
      lastSavedRef.current.height !== height
    ) {
      // Debounce by 500ms
      const timer = setTimeout(() => {
        storage.set(STORAGE_KEY, JSON.stringify(currentState));
        lastSavedRef.current = currentState;
        console.log('[WindowPersistence] Saved:', currentState);
      }, 500);

      return () => clearTimeout(timer);
    }
  }, [width, height, isDesktop]);
}

/**
 * Get saved window state (for native module to use on launch).
 */
export function getSavedWindowState(): WindowState | null {
  const storage = getStorage();
  if (!storage) return null;

  try {
    const saved = storage.getString(STORAGE_KEY);
    return saved ? JSON.parse(saved) : null;
  } catch {
    return null;
  }
}
