/**
 * ARCHITECTURE: Hook for fetching and updating per-room LLM settings.
 * WHY: Room settings override global defaults; API sync keeps server in sync.
 * TRADEOFF: Simple useState vs react-query, but follows codebase patterns.
 */

import { useState, useEffect, useCallback } from 'react';
import { api } from '@/services/api';
import type { HeuristicSettings, HeuristicPreset } from '@/stores/settings-store';
import { PRESETS, useSettingsStore } from '@/stores/settings-store';

interface RoomSettings {
  interjection_turn_threshold: number;
  semantic_novelty_threshold: number;
  auto_interjection_enabled: boolean;
}

// Convert API format to our HeuristicSettings format
function toHeuristicSettings(apiSettings: RoomSettings): HeuristicSettings {
  // Detect which preset matches, or custom
  let preset: HeuristicPreset = 'custom';
  for (const [key, values] of Object.entries(PRESETS)) {
    if (
      values.turnThreshold === apiSettings.interjection_turn_threshold &&
      values.semanticNoveltyThreshold === apiSettings.semantic_novelty_threshold
    ) {
      preset = key as Exclude<HeuristicPreset, 'custom'>;
      break;
    }
  }

  return {
    preset,
    turnThreshold: apiSettings.interjection_turn_threshold,
    semanticNoveltyThreshold: apiSettings.semantic_novelty_threshold,
    stagnationEnabled: apiSettings.auto_interjection_enabled,
  };
}

// Convert our format to API format
function toApiSettings(settings: HeuristicSettings): Partial<RoomSettings> {
  return {
    interjection_turn_threshold: settings.turnThreshold,
    semantic_novelty_threshold: settings.semanticNoveltyThreshold,
    auto_interjection_enabled: settings.stagnationEnabled,
  };
}

interface UseRoomSettingsReturn {
  settings: HeuristicSettings;
  isLoading: boolean;
  error: Error | null;
  refetch: () => Promise<void>;
}

export function useRoomSettings(
  roomId: string | undefined
): UseRoomSettingsReturn {
  const globalSettings = useSettingsStore((s) => s.globalSettings);
  const [settings, setSettings] = useState<HeuristicSettings>(globalSettings);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const fetchSettings = useCallback(async () => {
    if (!roomId) return;

    setIsLoading(true);
    setError(null);

    try {
      const response = await api.get<RoomSettings>(`/rooms/${roomId}/settings`);
      setSettings(toHeuristicSettings(response.data));
    } catch (err) {
      const errorObj = err instanceof Error ? err : new Error('Failed to fetch settings');
      setError(errorObj);
      console.error('[useRoomSettings] Fetch error:', err);
      // Fall back to global settings on error
      setSettings(globalSettings);
    } finally {
      setIsLoading(false);
    }
  }, [roomId, globalSettings]);

  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  return {
    settings,
    isLoading,
    error,
    refetch: fetchSettings,
  };
}

interface UseUpdateRoomSettingsReturn {
  updateSettings: (settings: HeuristicSettings) => Promise<boolean>;
  isUpdating: boolean;
  error: Error | null;
}

export function useUpdateRoomSettings(roomId: string): UseUpdateRoomSettingsReturn {
  const [isUpdating, setIsUpdating] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const updateSettings = useCallback(
    async (settings: HeuristicSettings): Promise<boolean> => {
      setIsUpdating(true);
      setError(null);

      try {
        const apiSettings = toApiSettings(settings);
        await api.patch(`/rooms/${roomId}/settings`, apiSettings);
        return true;
      } catch (err) {
        const errorObj = err instanceof Error ? err : new Error('Failed to update settings');
        setError(errorObj);
        console.error('[useUpdateRoomSettings] Update error:', err);
        return false;
      } finally {
        setIsUpdating(false);
      }
    },
    [roomId]
  );

  return {
    updateSettings,
    isUpdating,
    error,
  };
}
