import React, { useState, ReactNode, useCallback } from 'react';
import { View, Text, StyleSheet, Platform, Pressable, Modal } from 'react-native';

export interface ContextMenuItem {
  id: string;
  label: string;
  icon?: string;
  shortcut?: string;
  onPress: () => void;
  destructive?: boolean;
  disabled?: boolean;
}

interface ContextMenuProps {
  children: ReactNode;
  items: ContextMenuItem[];
  /** Disable context menu */
  disabled?: boolean;
}

interface MenuPosition {
  x: number;
  y: number;
}

/**
 * Right-click context menu for desktop.
 *
 * ARCHITECTURE: Native-feel context menus for desktop platforms.
 * WHY: Right-click is a core desktop interaction pattern.
 * TRADEOFF: Modal overlay may not feel fully native; future native module possible.
 *
 * On desktop: right-click shows native-styled dropdown menu.
 * On mobile: does nothing (use long-press hold menu instead).
 *
 * @example
 * <ContextMenu
 *   items={[
 *     { id: 'fork', label: 'Fork from here', onPress: handleFork },
 *     { id: 'copy', label: 'Copy', shortcut: '⌘C', onPress: handleCopy },
 *     { id: 'quote', label: 'Quote', onPress: handleQuote },
 *   ]}
 * >
 *   <MessageBubble message={message} />
 * </ContextMenu>
 */
export function ContextMenu({ children, items, disabled }: ContextMenuProps) {
  const [visible, setVisible] = useState(false);
  const [position, setPosition] = useState<MenuPosition>({ x: 0, y: 0 });

  const isDesktop = Platform.OS === 'macos' || Platform.OS === 'windows';

  const handleContextMenu = useCallback(
    (event: any) => {
      if (disabled || !isDesktop) return;

      event.preventDefault?.();
      event.stopPropagation?.();

      // Get click position
      const x = event.nativeEvent?.pageX ?? event.pageX ?? 0;
      const y = event.nativeEvent?.pageY ?? event.pageY ?? 0;

      setPosition({ x, y });
      setVisible(true);
    },
    [disabled, isDesktop]
  );

  const handleItemPress = useCallback(
    (item: ContextMenuItem) => {
      setVisible(false);
      if (!item.disabled) {
        item.onPress();
      }
    },
    []
  );

  if (!isDesktop) {
    return <>{children}</>;
  }

  return (
    <>
      <Pressable
        // @ts-ignore - onContextMenu exists on desktop
        onContextMenu={handleContextMenu}
      >
        {children}
      </Pressable>

      <Modal
        visible={visible}
        transparent
        animationType="none"
        onRequestClose={() => setVisible(false)}
      >
        <Pressable
          style={styles.overlay}
          onPress={() => setVisible(false)}
        >
          <View
            style={[
              styles.menu,
              { left: position.x, top: position.y },
            ]}
          >
            {items.map((item) => (
              <Pressable
                key={item.id}
                style={[
                  styles.menuItem,
                  item.disabled && styles.menuItemDisabled,
                  item.destructive && styles.menuItemDestructive,
                ]}
                onPress={() => handleItemPress(item)}
                disabled={item.disabled}
              >
                <Text
                  style={[
                    styles.menuItemText,
                    item.destructive && styles.menuItemTextDestructive,
                    item.disabled && styles.menuItemTextDisabled,
                  ]}
                >
                  {item.label}
                </Text>
                {item.shortcut && (
                  <Text style={styles.shortcut}>{item.shortcut}</Text>
                )}
              </Pressable>
            ))}
          </View>
        </Pressable>
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
  },
  menu: {
    position: 'absolute',
    backgroundColor: 'white',
    borderRadius: 8,
    paddingVertical: 4,
    minWidth: 180,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.15,
    shadowRadius: 12,
    elevation: 8,
  },
  menuItem: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  menuItemDisabled: {
    opacity: 0.5,
  },
  menuItemDestructive: {},
  menuItemText: {
    fontSize: 14,
    color: '#1f2937',
  },
  menuItemTextDestructive: {
    color: '#ef4444',
  },
  menuItemTextDisabled: {
    color: '#9ca3af',
  },
  shortcut: {
    fontSize: 12,
    color: '#9ca3af',
    marginLeft: 16,
  },
});
