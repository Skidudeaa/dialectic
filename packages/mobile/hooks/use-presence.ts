/**
 * ARCHITECTURE: Presence tracking hook with app lifecycle integration.
 * WHY: Automatic Away/Offline transitions based on user activity and app state.
 * TRADEOFF: Uses existing callback-based useAppState API for compatibility.
 *
 * Timers:
 * - Inactivity timer: 5 min in foreground without activity -> Away (auto)
 * - Background timer: 5 min in background -> Offline
 *
 * Lifecycle:
 * - App backgrounds: Immediate Away, starts 5 min timer for Offline
 * - App foregrounds: Cancel timers, return to Online (unless manual away)
 */

import { useEffect, useRef, useCallback } from 'react';
import { usePresenceStore } from '@/stores/presence-store';
import { useAppState } from './use-app-state';

// CONTEXT.md: 5 minutes inactivity -> Away
const INACTIVITY_TIMEOUT_MS = 5 * 60 * 1000;
// CONTEXT.md: 5 minutes in background -> Offline
const BACKGROUND_OFFLINE_TIMEOUT_MS = 5 * 60 * 1000;

export function usePresence() {
  const {
    myStatus,
    isManualAway,
    participants,
    setOnline,
    setAway,
    setOffline,
    recordActivity,
    updateParticipant,
  } = usePresenceStore();

  const inactivityTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const backgroundTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isManualAwayRef = useRef(isManualAway);

  // Keep ref in sync with state for use in callbacks
  useEffect(() => {
    isManualAwayRef.current = isManualAway;
  }, [isManualAway]);

  // Handle app backgrounding - called by useAppState when app goes to background
  const handleBackground = useCallback(() => {
    // CONTEXT.md: Immediate Away when backgrounded
    setAway(false);

    // Start timer for Offline transition after 5 minutes in background
    backgroundTimerRef.current = setTimeout(() => {
      setOffline();
    }, BACKGROUND_OFFLINE_TIMEOUT_MS);
  }, [setAway, setOffline]);

  // Handle app foregrounding - called by useAppState when app comes to foreground
  const handleForeground = useCallback(() => {
    // Clear background timer
    if (backgroundTimerRef.current) {
      clearTimeout(backgroundTimerRef.current);
      backgroundTimerRef.current = null;
    }

    // Return to online (unless manual away)
    if (!isManualAwayRef.current) {
      setOnline();
    }
  }, [setOnline]);

  // Use existing callback-based useAppState hook
  useAppState(handleBackground, handleForeground);

  // Inactivity timer for auto-away
  const resetInactivityTimer = useCallback(() => {
    if (inactivityTimerRef.current) {
      clearTimeout(inactivityTimerRef.current);
    }

    inactivityTimerRef.current = setTimeout(() => {
      if (!isManualAwayRef.current) {
        setAway(false); // Auto away, not manual
      }
    }, INACTIVITY_TIMEOUT_MS);
  }, [setAway]);

  // Record activity and reset timer
  const touch = useCallback(() => {
    recordActivity();
    resetInactivityTimer();
  }, [recordActivity, resetInactivityTimer]);

  // Start inactivity timer on mount
  useEffect(() => {
    resetInactivityTimer();

    return () => {
      if (inactivityTimerRef.current) clearTimeout(inactivityTimerRef.current);
      if (backgroundTimerRef.current) clearTimeout(backgroundTimerRef.current);
    };
  }, [resetInactivityTimer]);

  // Manual away toggle
  const toggleManualAway = useCallback(() => {
    if (isManualAway) {
      setOnline();
    } else {
      setAway(true);
    }
  }, [isManualAway, setOnline, setAway]);

  return {
    myStatus,
    isManualAway,
    participants,
    touch,
    toggleManualAway,
    updateParticipant,
  };
}
