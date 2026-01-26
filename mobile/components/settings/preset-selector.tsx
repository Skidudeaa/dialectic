/**
 * ARCHITECTURE: Preset button group for LLM behavior selection.
 * WHY: Simple three-way toggle for quick configuration without sliders.
 * TRADEOFF: Less granular than sliders, but covers 90% of use cases.
 */

import React from 'react';
import { View, Pressable, Text, StyleSheet } from 'react-native';
import type { HeuristicPreset } from '@/stores/settings-store';
import { PRESET_DESCRIPTIONS } from '@/stores/settings-store';

interface PresetSelectorProps {
  selected: HeuristicPreset;
  onSelect: (preset: Exclude<HeuristicPreset, 'custom'>) => void;
}

const PRESET_OPTIONS: Exclude<HeuristicPreset, 'custom'>[] = [
  'quiet',
  'balanced',
  'active',
];

export function PresetSelector({ selected, onSelect }: PresetSelectorProps) {
  return (
    <View>
      <View style={styles.presetsContainer}>
        {PRESET_OPTIONS.map((preset) => (
          <Pressable
            key={preset}
            style={[
              styles.presetButton,
              selected === preset && styles.presetButtonActive,
            ]}
            onPress={() => onSelect(preset)}
          >
            <Text
              style={[
                styles.presetButtonText,
                selected === preset && styles.presetButtonTextActive,
              ]}
            >
              {preset.charAt(0).toUpperCase() + preset.slice(1)}
            </Text>
          </Pressable>
        ))}
      </View>
      <Text style={styles.presetDescription}>
        {PRESET_DESCRIPTIONS[selected]}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  presetsContainer: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 8,
  },
  presetButton: {
    flex: 1,
    paddingVertical: 12,
    paddingHorizontal: 16,
    borderRadius: 8,
    backgroundColor: '#f1f5f9',
    alignItems: 'center',
  },
  presetButtonActive: {
    backgroundColor: '#6366f1',
  },
  presetButtonText: {
    fontSize: 14,
    fontWeight: '600',
    color: '#64748b',
  },
  presetButtonTextActive: {
    color: '#ffffff',
  },
  presetDescription: {
    fontSize: 13,
    color: '#64748b',
    fontStyle: 'italic',
  },
});
