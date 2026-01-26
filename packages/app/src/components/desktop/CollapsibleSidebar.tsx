import React, { useState, ReactNode, useCallback, useRef, useEffect } from 'react';
import { View, StyleSheet, Animated, Pressable, Platform } from 'react-native';

interface CollapsibleSidebarProps {
  children: ReactNode;
  /** Sidebar content */
  sidebar: ReactNode;
  /** Width when expanded */
  sidebarWidth?: number;
  /** Initial collapsed state */
  initiallyCollapsed?: boolean;
  /** Callback when collapse state changes */
  onCollapseChange?: (collapsed: boolean) => void;
}

/**
 * VS Code-style collapsible sidebar.
 *
 * ARCHITECTURE: Animated sidebar for desktop screen space optimization.
 * WHY: Desktop users want to maximize chat area; sidebar can be hidden.
 * TRADEOFF: Animation complexity; state could persist to storage.
 *
 * Sidebar slides in/out with smooth animation.
 * State persists across renders (could add MMKV persistence).
 *
 * @example
 * <CollapsibleSidebar
 *   sidebar={<RoomList />}
 *   onCollapseChange={setCollapsed}
 * >
 *   <ChatView />
 * </CollapsibleSidebar>
 */
export function CollapsibleSidebar({
  children,
  sidebar,
  sidebarWidth = 280,
  initiallyCollapsed = false,
  onCollapseChange,
}: CollapsibleSidebarProps) {
  const [collapsed, setCollapsed] = useState(initiallyCollapsed);
  const animatedWidth = useRef(new Animated.Value(initiallyCollapsed ? 0 : sidebarWidth)).current;

  useEffect(() => {
    Animated.spring(animatedWidth, {
      toValue: collapsed ? 0 : sidebarWidth,
      useNativeDriver: false,
      tension: 100,
      friction: 15,
    }).start();
  }, [collapsed, sidebarWidth, animatedWidth]);

  const toggleCollapsed = useCallback(() => {
    const newValue = !collapsed;
    setCollapsed(newValue);
    onCollapseChange?.(newValue);
  }, [collapsed, onCollapseChange]);

  const isDesktop = Platform.OS === 'macos' || Platform.OS === 'windows';

  return (
    <View style={styles.container}>
      {/* Sidebar */}
      <Animated.View style={[styles.sidebar, { width: animatedWidth }]}>
        <View style={[styles.sidebarContent, { width: sidebarWidth }]}>
          {sidebar}
        </View>
      </Animated.View>

      {/* Toggle button */}
      {isDesktop && (
        <Pressable
          style={[
            styles.toggleButton,
            collapsed && styles.toggleButtonCollapsed,
          ]}
          onPress={toggleCollapsed}
          accessibilityLabel={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <View style={styles.toggleIndicator}>
            <View
              style={[
                styles.toggleArrow,
                collapsed ? styles.arrowRight : styles.arrowLeft,
              ]}
            />
          </View>
        </Pressable>
      )}

      {/* Main content */}
      <View style={styles.content}>{children}</View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    flexDirection: 'row',
  },
  sidebar: {
    overflow: 'hidden',
    borderRightWidth: 1,
    borderRightColor: '#e5e7eb',
  },
  sidebarContent: {
    flex: 1,
  },
  toggleButton: {
    width: 12,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#f9fafb',
    borderRightWidth: 1,
    borderRightColor: '#e5e7eb',
  },
  toggleButtonCollapsed: {
    backgroundColor: '#f3f4f6',
  },
  toggleIndicator: {
    width: 8,
    height: 24,
    justifyContent: 'center',
    alignItems: 'center',
  },
  toggleArrow: {
    width: 0,
    height: 0,
    borderTopWidth: 5,
    borderBottomWidth: 5,
    borderTopColor: 'transparent',
    borderBottomColor: 'transparent',
  },
  arrowLeft: {
    borderRightWidth: 6,
    borderRightColor: '#9ca3af',
  },
  arrowRight: {
    borderLeftWidth: 6,
    borderLeftColor: '#9ca3af',
  },
  content: {
    flex: 1,
  },
});
