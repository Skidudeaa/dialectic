/**
 * ARCHITECTURE: MMKV-backed store for LLM behavior settings.
 * WHY: Global settings persist locally; instant access without API calls.
 * TRADEOFF: Duplicates room-level settings on server, but enables offline defaults.
 */

import { create } from 'zustand';
import { createMMKV, type MMKV } from 'react-native-mmkv';

// Separate MMKV instance for settings data
const storage: MMKV = createMMKV({ id: 'settings-storage' });

export type HeuristicPreset = 'quiet' | 'balanced' | 'active' | 'custom';

export interface HeuristicSettings {
  preset: HeuristicPreset;
  turnThreshold: number;
  semanticNoveltyThreshold: number;
  stagnationEnabled: boolean;
}

// Preset definitions per CONTEXT.md
export const PRESETS: Record<
  Exclude<HeuristicPreset, 'custom'>,
  Omit<HeuristicSettings, 'preset'>
> = {
  quiet: {
    turnThreshold: 8,
    semanticNoveltyThreshold: 0.85,
    stagnationEnabled: false,
  },
  balanced: {
    turnThreshold: 4,
    semanticNoveltyThreshold: 0.7,
    stagnationEnabled: true,
  },
  active: {
    turnThreshold: 2,
    semanticNoveltyThreshold: 0.5,
    stagnationEnabled: true,
  },
};

export const PRESET_DESCRIPTIONS: Record<HeuristicPreset, string> = {
  quiet: 'Claude joins less often, only on clear questions or long pauses',
  balanced: 'Claude joins when natural, about every 4-5 messages',
  active: 'Claude joins frequently, eager to contribute',
  custom: 'Custom thresholds set via advanced options',
};

const DEFAULT_SETTINGS: HeuristicSettings = {
  preset: 'balanced',
  ...PRESETS.balanced,
};

interface SettingsState {
  globalSettings: HeuristicSettings;
  setGlobalSettings: (settings: HeuristicSettings) => void;
  applyPreset: (preset: Exclude<HeuristicPreset, 'custom'>) => void;
  updateThreshold: (
    key: keyof Omit<HeuristicSettings, 'preset'>,
    value: number | boolean
  ) => void;
}

// Load initial state from MMKV
function loadInitialSettings(): HeuristicSettings {
  const stored = storage.getString('llm-settings');
  if (stored) {
    try {
      return JSON.parse(stored) as HeuristicSettings;
    } catch {
      // Invalid JSON, use defaults
      return DEFAULT_SETTINGS;
    }
  }
  return DEFAULT_SETTINGS;
}

export const useSettingsStore = create<SettingsState>((set) => ({
  globalSettings: loadInitialSettings(),

  setGlobalSettings: (settings) => {
    storage.set('llm-settings', JSON.stringify(settings));
    set({ globalSettings: settings });
  },

  applyPreset: (preset) => {
    const newSettings: HeuristicSettings = {
      preset,
      ...PRESETS[preset],
    };
    storage.set('llm-settings', JSON.stringify(newSettings));
    set({ globalSettings: newSettings });
  },

  updateThreshold: (key, value) => {
    set((state) => {
      const newSettings: HeuristicSettings = {
        ...state.globalSettings,
        [key]: value,
        preset: 'custom' as HeuristicPreset, // Custom when manually adjusted
      };
      storage.set('llm-settings', JSON.stringify(newSettings));
      return { globalSettings: newSettings };
    });
  },
}));
