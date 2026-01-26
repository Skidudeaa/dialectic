/**
 * ARCHITECTURE: Platform detection utilities for cross-platform code.
 * WHY: Business logic needs to know platform for conditional behavior.
 * TRADEOFF: React Native's Platform API required as peer dependency.
 */

import { Platform } from 'react-native';

export type PlatformType = 'ios' | 'android' | 'macos' | 'windows' | 'web';

export const currentPlatform: PlatformType = Platform.OS as PlatformType;

export const isMobile = currentPlatform === 'ios' || currentPlatform === 'android';
export const isDesktop = currentPlatform === 'macos' || currentPlatform === 'windows';
export const isWeb = currentPlatform === 'web';

// Modifier key for keyboard shortcuts
export const modifierKey = Platform.select({
  macos: 'Cmd',
  windows: 'Ctrl',
  ios: 'Cmd',
  android: 'Ctrl',
  default: 'Ctrl',
}) as string;
