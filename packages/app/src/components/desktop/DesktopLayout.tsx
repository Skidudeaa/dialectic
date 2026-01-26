/**
 * Desktop layout components for Dialectic.
 *
 * ARCHITECTURE: Wrapper components that handle desktop-specific layout concerns.
 * WHY: Desktop screens are much wider than mobile - content should be centered.
 * TRADEOFF: Extra wrapper vs inline styles - cleaner component boundaries.
 */

import React, { ReactNode } from 'react';
import { View, StyleSheet, ScrollView, useWindowDimensions } from 'react-native';
import { DESKTOP, isDesktopPlatform } from '../../styles/desktop';

interface DesktopLayoutProps {
  children: ReactNode;
  /** Whether to center content with max-width */
  centered?: boolean;
  /** Custom max width (defaults to DESKTOP.maxContentWidth) */
  maxWidth?: number;
  /** Whether content is scrollable */
  scrollable?: boolean;
  /** Background color */
  backgroundColor?: string;
}

/**
 * Desktop layout wrapper that handles:
 * - Centered max-width content on wide screens
 * - Thin overlay scrollbars
 * - Platform-appropriate styling
 *
 * On mobile, renders children directly without modifications.
 *
 * @example
 * <DesktopLayout centered scrollable>
 *   <ChatContent />
 * </DesktopLayout>
 */
export function DesktopLayout({
  children,
  centered = true,
  maxWidth = DESKTOP.maxContentWidth,
  scrollable = false,
  backgroundColor = '#ffffff',
}: DesktopLayoutProps) {
  const { width: windowWidth } = useWindowDimensions();

  // On mobile, just render children
  if (!isDesktopPlatform) {
    return <>{children}</>;
  }

  // Calculate whether we need centering
  const needsCentering = centered && windowWidth > maxWidth + DESKTOP.padding * 2;

  const content = needsCentering ? (
    <View style={[styles.centeredWrapper, { maxWidth }]}>
      {children}
    </View>
  ) : (
    children
  );

  if (scrollable) {
    return (
      <ScrollView
        style={[styles.container, { backgroundColor }]}
        contentContainerStyle={styles.scrollContent}
        showsVerticalScrollIndicator={true}
        // These props help with thin scrollbars on some platforms
        indicatorStyle="black"
      >
        {content}
      </ScrollView>
    );
  }

  return (
    <View style={[styles.container, { backgroundColor }]}>
      {content}
    </View>
  );
}

/**
 * Chat-specific layout that centers messages on wide screens.
 */
export function ChatLayout({ children }: { children: ReactNode }) {
  return (
    <DesktopLayout centered maxWidth={DESKTOP.maxContentWidth}>
      <View style={styles.chatContainer}>{children}</View>
    </DesktopLayout>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
  },
  scrollContent: {
    flexGrow: 1,
  },
  centeredWrapper: {
    width: '100%',
    alignSelf: 'center',
  },
  chatContainer: {
    flex: 1,
    paddingHorizontal: isDesktopPlatform ? DESKTOP.padding : 0,
  },
});
