/**
 * Desktop-specific components for macOS and Windows.
 *
 * ARCHITECTURE: Desktop-only components that no-op on mobile.
 * WHY: Desktop users expect keyboard shortcuts, hover, context menus.
 * TRADEOFF: Platform checks at runtime; tree-shaking won't remove mobile imports.
 *
 * All components in this module:
 * - Work on macOS and Windows
 * - No-op gracefully on iOS and Android
 * - Use platform-appropriate conventions (Cmd vs Ctrl, etc.)
 */

export { KeyboardShortcutsProvider, useKeyboardShortcuts, formatShortcut, getModifierKeyDisplay } from './KeyboardShortcuts';
export type { KeyboardShortcut } from './KeyboardShortcuts';

export { HoverActions } from './HoverActions';
export { ContextMenu } from './ContextMenu';
export type { ContextMenuItem } from './ContextMenu';

export { DropZone } from './DropZone';
export type { DroppedFile } from './DropZone';

export { CollapsibleSidebar } from './CollapsibleSidebar';

// Layout components
export { DesktopLayout, ChatLayout } from './DesktopLayout';
