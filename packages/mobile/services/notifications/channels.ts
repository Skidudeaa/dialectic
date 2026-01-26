/**
 * ARCHITECTURE: Android notification channel configuration.
 * WHY: Android 8.0+ requires channels; distinct sounds for human vs LLM.
 * TRADEOFF: More setup complexity but enables per-type sound customization.
 */

import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

// Sound filenames (without path - bundled by expo-notifications plugin)
const HUMAN_SOUND = 'human_notification.wav';
const LLM_SOUND = 'llm_notification.wav';

/**
 * Set up Android notification channels for human and LLM messages.
 * Per CONTEXT.md: Custom sound for Dialectic, distinct for Claude vs human.
 */
export async function setupNotificationChannels(): Promise<void> {
  if (Platform.OS !== 'android') {
    return;
  }

  // Human messages channel - bright chime
  await Notifications.setNotificationChannelAsync('human_messages', {
    name: 'Messages from Humans',
    importance: Notifications.AndroidImportance.HIGH,
    sound: HUMAN_SOUND,
    vibrationPattern: [0, 250, 250, 250],
    lightColor: '#3b82f6', // Blue for human messages
  });

  // LLM messages channel - softer, distinct tone
  // Per CONTEXT.md: LLM having a distinct sound reinforces Claude as participant
  await Notifications.setNotificationChannelAsync('llm_messages', {
    name: 'Messages from Claude',
    importance: Notifications.AndroidImportance.HIGH,
    sound: LLM_SOUND,
    vibrationPattern: [0, 100, 100, 100, 100, 100], // Different pattern for distinction
    lightColor: '#8b5cf6', // Purple for LLM messages (matches Claude brand)
  });
}

/**
 * Create a notification channel for a specific room.
 * Enables per-room mute via Android channel settings (per CONTEXT.md requirement).
 */
export async function createRoomChannel(
  roomId: string,
  roomName: string
): Promise<void> {
  if (Platform.OS !== 'android') {
    return;
  }

  await Notifications.setNotificationChannelAsync(`room_${roomId}`, {
    name: `${roomName} Notifications`,
    importance: Notifications.AndroidImportance.HIGH,
    sound: HUMAN_SOUND, // Default to human sound; server specifies channel per message
  });
}
