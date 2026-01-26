import React, { ReactNode } from 'react';
import { useKeyboardShortcuts, KeyboardShortcut } from '../../hooks/useKeyboardShortcuts';

interface KeyboardShortcutsProviderProps {
  children: ReactNode;
  shortcuts: KeyboardShortcut[];
}

/**
 * Provider component that registers global keyboard shortcuts.
 *
 * ARCHITECTURE: Wrapper component for global keyboard handling.
 * WHY: Shortcuts need to work regardless of focus location.
 * TRADEOFF: Placed at app root, captures all matching keypresses.
 *
 * Place at app root to enable shortcuts everywhere.
 *
 * @example
 * <KeyboardShortcutsProvider shortcuts={[
 *   { key: 'n', withModifier: true, onPress: openNewRoom, description: 'New room' },
 *   { key: 'f', withModifier: true, onPress: openSearch, description: 'Search' },
 * ]}>
 *   <App />
 * </KeyboardShortcutsProvider>
 */
export function KeyboardShortcutsProvider({
  children,
  shortcuts,
}: KeyboardShortcutsProviderProps) {
  useKeyboardShortcuts(shortcuts);
  return <>{children}</>;
}

export { useKeyboardShortcuts, formatShortcut, getModifierKeyDisplay } from '../../hooks/useKeyboardShortcuts';
export type { KeyboardShortcut };
