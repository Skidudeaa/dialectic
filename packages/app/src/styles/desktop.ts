/**
 * Desktop-specific style utilities for Dialectic.
 *
 * ARCHITECTURE: Centralized desktop styling constants and helpers.
 * WHY: Desktop screens need different treatment than mobile (wider, mouse-first).
 * TRADEOFF: Platform checks at runtime vs build-time - simpler but slight overhead.
 */

import { StyleSheet, Platform, ViewStyle, TextStyle } from 'react-native';

export const isDesktop = Platform.OS === 'macos' || Platform.OS === 'windows';
export const isMacOS = Platform.OS === 'macos';
export const isWindows = Platform.OS === 'windows';

/**
 * Desktop-specific style constants.
 */
export const DESKTOP = {
  /** Max width for main content area */
  maxContentWidth: 800,
  /** Default sidebar width */
  sidebarWidth: 280,
  /** Minimum window width */
  minWindowWidth: 720,
  /** Minimum window height */
  minWindowHeight: 480,
  /** Standard padding for desktop */
  padding: 16,
  /** Larger font sizes for desktop readability */
  fontSize: {
    small: 13,
    normal: 14,
    large: 16,
    title: 20,
  },
};

/**
 * Thin overlay scrollbar styles.
 *
 * Applied via CSS injection on desktop (requires native module)
 * or via ScrollView props where supported.
 */
export const scrollbarStyles = {
  // These would be applied via CSS on web/desktop
  // For RN, we rely on platform defaults or native customization
  width: 6,
  borderRadius: 3,
  backgroundColor: 'rgba(0, 0, 0, 0.2)',
  hoverBackgroundColor: 'rgba(0, 0, 0, 0.4)',
};

/**
 * Base desktop styles.
 */
export const desktopStyles = StyleSheet.create({
  // Centered content container
  centeredContent: {
    maxWidth: DESKTOP.maxContentWidth,
    width: '100%',
    alignSelf: 'center',
  },

  // Full-width with padding
  paddedContainer: {
    paddingHorizontal: DESKTOP.padding,
  },

  // Desktop window container
  windowContainer: {
    flex: 1,
    backgroundColor: '#ffffff',
  },

  // Desktop-appropriate shadows
  cardShadow: {
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.08,
    shadowRadius: 8,
    elevation: 4,
  },

  // Subtle hover background (use with HoverActions)
  hoverBackground: {
    backgroundColor: '#f9fafb',
  },
});

/**
 * Helper to conditionally apply desktop styles.
 *
 * @example
 * <View style={withDesktopStyles(styles.container, desktopStyles.centeredContent)}>
 */
export function withDesktopStyles<T extends ViewStyle | TextStyle>(
  baseStyle: T,
  desktopStyle: T
): T {
  if (!isDesktop) return baseStyle;
  return { ...baseStyle, ...desktopStyle } as T;
}

/**
 * Get platform-appropriate border radius.
 * macOS uses more rounded corners, Windows uses sharper ones.
 */
export function getPlatformBorderRadius(size: 'small' | 'medium' | 'large'): number {
  const radii = {
    macos: { small: 6, medium: 10, large: 14 },
    windows: { small: 4, medium: 6, large: 8 },
    default: { small: 4, medium: 8, large: 12 },
  };

  const platform = isMacOS ? 'macos' : isWindows ? 'windows' : 'default';
  return radii[platform][size];
}
