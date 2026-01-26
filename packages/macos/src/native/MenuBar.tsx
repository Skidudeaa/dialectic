/**
 * macOS Menu Bar component for Dialectic.
 *
 * ARCHITECTURE: Uses react-native-menubar-extra for NSMenu integration.
 * WHY: Provides native system tray experience expected on macOS.
 * TRADEOFF: Limited to SF Symbols for icons; requires macOS 11+ for full symbol support.
 */

import React from 'react';
import {
  MenubarExtraView,
  MenuBarExtraItem,
  MenuBarExtraSeparator,
} from 'react-native-menubar-extra';

interface Room {
  id: string;
  name: string;
  hasUnread: boolean;
}

interface MenuBarProps {
  /** Number of rooms with unread messages */
  unreadCount: number;
  /** Callback when New Room is selected */
  onNewRoom: () => void;
  /** Callback when Search is selected */
  onSearch: () => void;
  /** Callback when Preferences is selected */
  onPreferences: () => void;
  /** Callback when Quit is selected */
  onQuit: () => void;
  /** List of recent rooms for quick access */
  rooms?: Room[];
  /** Callback when a room is selected from the menu */
  onSelectRoom?: (roomId: string) => void;
}

/**
 * macOS Menu Bar component for Dialectic.
 *
 * Provides:
 * - System tray icon with unread indicator
 * - Quick actions (New Room, Search)
 * - Room quick-switch list (top 5)
 * - Preferences and Quit
 *
 * Uses SF Symbols for icons (macOS 11+):
 * - message.circle: Default icon
 * - message.badge.filled: Unread indicator
 */
export function MenuBar({
  unreadCount,
  onNewRoom,
  onSearch,
  onPreferences,
  onQuit,
  rooms = [],
  onSelectRoom,
}: MenuBarProps) {
  // SF Symbol: message.circle or message.badge.filled for unread
  const iconName = unreadCount > 0 ? 'message.badge.filled' : 'message.circle';

  // Show unread count in title if any
  const title = unreadCount > 0 ? `${unreadCount}` : undefined;

  return (
    <MenubarExtraView icon={iconName} title={title}>
      <MenuBarExtraItem
        title="New Room"
        icon="plus.circle"
        keyEquivalent="n"
        onItemPress={onNewRoom}
      />
      <MenuBarExtraItem
        title="Search"
        icon="magnifyingglass"
        keyEquivalent="f"
        onItemPress={onSearch}
      />
      <MenuBarExtraSeparator />

      {rooms.length > 0 && (
        <>
          {rooms.slice(0, 5).map((room) => (
            <MenuBarExtraItem
              key={room.id}
              title={room.hasUnread ? `* ${room.name}` : room.name}
              icon={room.hasUnread ? 'circle.fill' : 'circle'}
              onItemPress={() => onSelectRoom?.(room.id)}
            />
          ))}
          <MenuBarExtraSeparator />
        </>
      )}

      <MenuBarExtraItem
        title="Preferences..."
        icon="gearshape"
        keyEquivalent=","
        onItemPress={onPreferences}
      />
      <MenuBarExtraSeparator />
      <MenuBarExtraItem
        title="Quit Dialectic"
        keyEquivalent="q"
        onItemPress={onQuit}
      />
    </MenubarExtraView>
  );
}
