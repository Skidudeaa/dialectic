/**
 * ARCHITECTURE: Global Claude behavior settings screen.
 * WHY: Central place to configure LLM interjection defaults for all rooms.
 * TRADEOFF: Global settings may not fit all conversations, but per-room overrides handle that.
 */

import React from 'react';
import { ScrollView, StyleSheet } from 'react-native';
import { Stack } from 'expo-router';
import { LLMSettings } from '@/components/settings/llm-settings';
import { useSettingsStore } from '@/stores/settings-store';

export default function ClaudeBehaviorScreen() {
  const globalSettings = useSettingsStore((s) => s.globalSettings);
  const setGlobalSettings = useSettingsStore((s) => s.setGlobalSettings);

  return (
    <>
      <Stack.Screen
        options={{
          title: 'Claude Behavior',
          headerBackTitle: 'Settings',
        }}
      />
      <ScrollView style={styles.container}>
        <LLMSettings
          settings={globalSettings}
          onSettingsChange={setGlobalSettings}
        />
      </ScrollView>
    </>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#ffffff',
  },
});
