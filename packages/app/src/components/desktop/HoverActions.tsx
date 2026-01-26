import React, { useState, ReactNode } from 'react';
import { View, StyleSheet, Platform } from 'react-native';

interface HoverActionsProps {
  children: ReactNode;
  actions: ReactNode;
  /** Position of actions when revealed */
  position?: 'top-right' | 'right' | 'bottom-right';
  /** Only show on desktop */
  desktopOnly?: boolean;
}

/**
 * Wrapper that reveals action buttons on hover (desktop only).
 *
 * ARCHITECTURE: Hover-reveal pattern for contextual actions.
 * WHY: Desktop users expect hover interactions; reduces UI clutter.
 * TRADEOFF: Actions hidden until hover; may hurt discoverability.
 *
 * On mobile, actions are hidden (use long-press menu instead).
 * On desktop, hovering reveals the action buttons.
 *
 * @example
 * <HoverActions
 *   actions={
 *     <>
 *       <IconButton icon="fork" onPress={onFork} />
 *       <IconButton icon="copy" onPress={onCopy} />
 *     </>
 *   }
 * >
 *   <MessageBubble message={message} />
 * </HoverActions>
 */
export function HoverActions({
  children,
  actions,
  position = 'top-right',
  desktopOnly = true,
}: HoverActionsProps) {
  const [isHovered, setIsHovered] = useState(false);

  const isDesktop = Platform.OS === 'macos' || Platform.OS === 'windows';

  if (desktopOnly && !isDesktop) {
    return <>{children}</>;
  }

  const positionStyle = {
    'top-right': styles.positionTopRight,
    'right': styles.positionRight,
    'bottom-right': styles.positionBottomRight,
  }[position];

  return (
    <View
      style={styles.container}
      // @ts-ignore - onMouseEnter/Leave exist on desktop
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      {children}
      {isHovered && (
        <View style={[styles.actionsContainer, positionStyle]}>
          {actions}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: 'relative',
  },
  actionsContainer: {
    position: 'absolute',
    flexDirection: 'row',
    backgroundColor: 'white',
    borderRadius: 6,
    padding: 4,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 4,
    gap: 4,
  },
  positionTopRight: {
    top: 4,
    right: 4,
  },
  positionRight: {
    top: '50%',
    right: 4,
    transform: [{ translateY: -12 }],
  },
  positionBottomRight: {
    bottom: 4,
    right: 4,
  },
});
