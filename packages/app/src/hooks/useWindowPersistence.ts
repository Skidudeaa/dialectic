/**
 * Window persistence hook for desktop apps.
 *
 * ARCHITECTURE: Remembers window size/position across app sessions.
 * WHY: Desktop users expect windows to reopen where they left them.
 * TRADEOFF: Requires MMKV; actual window resize needs native module.
 */

import { useEffect, useRef } from 'react';
import { Platform, useWindowDimensions } from 'react-native';
import { MMKV } from 'react-native-mmkv';

const STORAGE_KEY = 'window-state';

interface WindowState {
  width: number;
  height: number;
  x?: number;
  y?: number;
}

// Storage for window state (platform-specific initialization)
let storage: MMKV | null = null;

function getStorage(): MMKV | null {
  if (storage) return storage;

  try {
    storage = new MMKV({ id: 'dialectic-window' });
    return storage;
  } catch {
    console.warn('MMKV not available for window persistence');
    return null;
  }
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
