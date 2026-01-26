/**
 * ARCHITECTURE: Main settings screen with navigation links.
 * WHY: Central hub for all app settings, organized by category.
 * TRADEOFF: Flat list for now, could add sections/grouping later.
 */

import React from 'react';
import { View, Text, StyleSheet, Pressable, ScrollView } from 'react-native';
import { Stack, useRouter } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';

interface SettingsItemProps {
  icon: keyof typeof Ionicons.glyphMap;
  iconColor: string;
  label: string;
  onPress: () => void;
}

function SettingsItem({ icon, iconColor, label, onPress }: SettingsItemProps) {
  return (
    <Pressable style={styles.settingsItem} onPress={onPress}>
      <Ionicons name={icon} size={24} color={iconColor} />
      <Text style={styles.settingsText}>{label}</Text>
      <Ionicons name="chevron-forward" size={20} color="#94a3b8" />
    </Pressable>
  );
}

export default function SettingsScreen() {
  const router = useRouter();

  return (
    <>
      <Stack.Screen
        options={{
          title: 'Settings',
          headerBackTitle: 'Back',
        }}
      />
      <ScrollView style={styles.container}>
        <View style={styles.section}>
          <Text style={styles.sectionHeader}>LLM</Text>
          <SettingsItem
            icon="sparkles-outline"
            iconColor="#6366f1"
            label="Claude Behavior"
            onPress={() =>
              (router.push as (path: string) => void)('/settings/claude-behavior')
            }
          />
        </View>
      </ScrollView>
    </>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#ffffff',
  },
  section: {
    marginTop: 24,
  },
  sectionHeader: {
    fontSize: 12,
    fontWeight: '600',
    color: '#64748b',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    paddingHorizontal: 16,
    marginBottom: 8,
  },
  settingsItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 14,
    paddingHorizontal: 16,
    backgroundColor: '#ffffff',
    borderBottomWidth: 1,
    borderBottomColor: '#f1f5f9',
  },
  settingsText: {
    flex: 1,
    fontSize: 16,
    color: '#1e293b',
    marginLeft: 12,
  },
});
