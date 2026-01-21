/**
 * ARCHITECTURE: Hook for tracking React Native AppState transitions.
 * WHY: Needed to detect background/foreground transitions for lock timeout logic.
 * TRADEOFF: Polling-style state vs event-driven, but React Native only supports event listener.
 */

import { useEffect, useRef } from 'react';
import { AppState, type AppStateStatus } from 'react-native';

export function useAppState(
  onBackground?: () => void,
  onForeground?: () => void
) {
  const appState = useRef(AppState.currentState);

  useEffect(() => {
    const subscription = AppState.addEventListener(
      'change',
      (nextAppState: AppStateStatus) => {
        if (
          appState.current.match(/active/) &&
          nextAppState.match(/inactive|background/)
        ) {
          // Going to background
          onBackground?.();
        } else if (
          appState.current.match(/inactive|background/) &&
          nextAppState === 'active'
        ) {
          // Coming to foreground
          onForeground?.();
        }
        appState.current = nextAppState;
      }
    );

    return () => {
      subscription.remove();
    };
  }, [onBackground, onForeground]);

  return appState.current;
}
