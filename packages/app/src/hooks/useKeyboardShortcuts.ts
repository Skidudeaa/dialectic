import { useEffect, useCallback } from 'react';
import { Platform } from 'react-native';

export interface KeyboardShortcut {
  /** Key code (e.g., 'n', 'f', 'Enter') */
  key: string;
  /** Require modifier key (Cmd on macOS, Ctrl on Windows) */
  withModifier?: boolean;
  /** Require Shift key */
  withShift?: boolean;
  /** Handler function */
  onPress: () => void;
  /** Description for help/accessibility */
  description?: string;
}

/**
 * DOM KeyboardEvent interface for desktop platforms.
 * React Native doesn't include DOM types, but document.addEventListener
 * is available on desktop platforms (macOS, Windows).
 */
interface DOMKeyboardEvent {
  key: string;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  preventDefault(): void;
}

const isModifierPressed = (event: DOMKeyboardEvent): boolean => {
  // macOS uses Cmd (metaKey), Windows uses Ctrl (ctrlKey)
  return Platform.OS === 'macos' ? event.metaKey : event.ctrlKey;
};

/**
 * Hook for registering keyboard shortcuts on desktop.
 *
 * ARCHITECTURE: Cross-platform keyboard shortcut abstraction.
 * WHY: Desktop users expect keyboard shortcuts; mobile has no keyboard.
 * TRADEOFF: Uses document events (web/desktop only), no-ops on mobile.
 *
 * On mobile platforms, this hook does nothing.
 * On desktop, attaches keydown listener to document.
 *
 * @example
 * useKeyboardShortcuts([
 *   { key: 'n', withModifier: true, onPress: openNewRoom },
 *   { key: 'f', withModifier: true, onPress: openSearch },
 *   { key: 'Enter', withModifier: true, onPress: sendMessage },
 * ]);
 */
export function useKeyboardShortcuts(shortcuts: KeyboardShortcut[]): void {
  const handleKeyDown = useCallback(
    (event: DOMKeyboardEvent) => {
      // Find matching shortcut
      const shortcut = shortcuts.find((s) => {
        const keyMatch = s.key.toLowerCase() === event.key.toLowerCase();
        const modifierMatch = s.withModifier ? isModifierPressed(event) : !isModifierPressed(event);
        const shiftMatch = s.withShift ? event.shiftKey : !s.withShift || !event.shiftKey;
        return keyMatch && modifierMatch && shiftMatch;
      });

      if (shortcut) {
        event.preventDefault();
        shortcut.onPress();
      }
    },
    [shortcuts]
  );

  useEffect(() => {
    // Only add listener on desktop platforms
    if (Platform.OS !== 'macos' && Platform.OS !== 'windows') {
      return;
    }

    // document exists in desktop RN but not typed in React Native
    const doc = typeof globalThis !== 'undefined' ? (globalThis as unknown as { document?: { addEventListener: Function; removeEventListener: Function } }).document : undefined;
    if (doc) {
      doc.addEventListener('keydown', handleKeyDown);
      return () => doc.removeEventListener('keydown', handleKeyDown);
    }
  }, [handleKeyDown]);
}

/**
 * Get display string for modifier key.
 */
export function getModifierKeyDisplay(): string {
  return Platform.OS === 'macos' ? '\u2318' : 'Ctrl'; // ⌘ for mac
}

/**
 * Format shortcut for display (e.g., "⌘N" or "Ctrl+N").
 */
export function formatShortcut(key: string, withModifier = false): string {
  const modifier = getModifierKeyDisplay();
  const displayKey = key.length === 1 ? key.toUpperCase() : key;

  if (withModifier) {
    return Platform.OS === 'macos' ? `${modifier}${displayKey}` : `${modifier}+${displayKey}`;
  }
  return displayKey;
}
