/**
 * ARCHITECTURE: Full LLM settings UI with presets and advanced sliders.
 * WHY: Presets cover most users; advanced mode for power users tweaking thresholds.
 * TRADEOFF: Advanced mode adds complexity but enables fine-grained control.
 */

import React, { useState } from 'react';
import { View, Text, StyleSheet, Pressable, Switch } from 'react-native';
import Slider from '@react-native-community/slider';
import { PresetSelector } from './preset-selector';
import type { HeuristicSettings, HeuristicPreset } from '@/stores/settings-store';
import { PRESETS } from '@/stores/settings-store';

interface LLMSettingsProps {
  settings: HeuristicSettings;
  onSettingsChange: (settings: HeuristicSettings) => void;
  isRoomOverride?: boolean;
}

export function LLMSettings({
  settings,
  onSettingsChange,
  isRoomOverride = false,
}: LLMSettingsProps) {
  const [showAdvanced, setShowAdvanced] = useState(settings.preset === 'custom');

  const handlePresetSelect = (preset: Exclude<HeuristicPreset, 'custom'>) => {
    onSettingsChange({
      preset,
      ...PRESETS[preset],
    });
  };

  const handleAdvancedChange = (
    key: keyof Omit<HeuristicSettings, 'preset'>,
    value: number | boolean
  ) => {
    onSettingsChange({
      ...settings,
      preset: 'custom',
      [key]: value,
    });
  };

  return (
    <View style={styles.container}>
      {isRoomOverride && (
        <Text style={styles.overrideLabel}>
          Room Override (overrides global settings)
        </Text>
      )}

      <Text style={styles.sectionTitle}>Claude Behavior</Text>

      <PresetSelector selected={settings.preset} onSelect={handlePresetSelect} />

      <Pressable
        style={styles.advancedToggle}
        onPress={() => setShowAdvanced(!showAdvanced)}
      >
        <Text style={styles.advancedToggleText}>
          {showAdvanced ? 'Hide Advanced' : 'Show Advanced'}
        </Text>
      </Pressable>

      {showAdvanced && (
        <View style={styles.advancedContainer}>
          {/* Turn Threshold */}
          <View style={styles.sliderContainer}>
            <Text style={styles.sliderLabel}>
              Turn Threshold: {settings.turnThreshold}
            </Text>
            <Text style={styles.sliderDescription}>
              Claude joins after this many human messages
            </Text>
            <Slider
              style={styles.slider}
              minimumValue={2}
              maximumValue={12}
              step={1}
              value={settings.turnThreshold}
              onSlidingComplete={(v) => handleAdvancedChange('turnThreshold', v)}
              minimumTrackTintColor="#6366f1"
              maximumTrackTintColor="#e2e8f0"
              thumbTintColor="#6366f1"
            />
          </View>

          {/* Semantic Novelty Threshold */}
          <View style={styles.sliderContainer}>
            <Text style={styles.sliderLabel}>
              Novelty Sensitivity:{' '}
              {Math.round(settings.semanticNoveltyThreshold * 100)}%
            </Text>
            <Text style={styles.sliderDescription}>
              How different a message must be to trigger response
            </Text>
            <Slider
              style={styles.slider}
              minimumValue={0.3}
              maximumValue={0.95}
              step={0.05}
              value={settings.semanticNoveltyThreshold}
              onSlidingComplete={(v) =>
                handleAdvancedChange('semanticNoveltyThreshold', v)
              }
              minimumTrackTintColor="#6366f1"
              maximumTrackTintColor="#e2e8f0"
              thumbTintColor="#6366f1"
            />
          </View>

          {/* Stagnation Detection */}
          <View style={styles.switchContainer}>
            <View style={styles.switchTextContainer}>
              <Text style={styles.sliderLabel}>Stagnation Detection</Text>
              <Text style={styles.sliderDescription}>
                Claude nudges when conversation gets stuck
              </Text>
            </View>
            <Switch
              value={settings.stagnationEnabled}
              onValueChange={(v) => handleAdvancedChange('stagnationEnabled', v)}
              trackColor={{ false: '#e2e8f0', true: '#c7d2fe' }}
              thumbColor={settings.stagnationEnabled ? '#6366f1' : '#f4f4f5'}
            />
          </View>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    padding: 16,
  },
  overrideLabel: {
    fontSize: 12,
    color: '#6366f1',
    fontWeight: '500',
    marginBottom: 12,
    fontStyle: 'italic',
  },
  sectionTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: '#1e293b',
    marginBottom: 16,
  },
  advancedToggle: {
    paddingVertical: 12,
    marginTop: 8,
  },
  advancedToggleText: {
    fontSize: 14,
    color: '#6366f1',
    fontWeight: '500',
  },
  advancedContainer: {
    marginTop: 8,
    paddingTop: 16,
    borderTopWidth: 1,
    borderTopColor: '#e2e8f0',
  },
  sliderContainer: {
    marginBottom: 24,
  },
  sliderLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: '#1e293b',
    marginBottom: 2,
  },
  sliderDescription: {
    fontSize: 12,
    color: '#64748b',
    marginBottom: 8,
  },
  slider: {
    width: '100%',
    height: 40,
  },
  switchContainer: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  switchTextContainer: {
    flex: 1,
    marginRight: 16,
  },
});
