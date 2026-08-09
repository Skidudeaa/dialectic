// OnboardingProvider — context wrapper exposing tour state + actions.
//
// Mount this once near the root (above Dashboard). It auto-opens the tour on
// first mount when localStorage has no `td_onboarded` flag. Any descendant can
// call `useOnboarding()` to read state or trigger startTour() (replay) /
// dismissTour() (mark done from elsewhere).
//
// The provider deliberately does NOT render the tour UI — that's
// OnboardingTour's job. This split lets the Dashboard "?" replay button
// trigger the tour without OnboardingTour being mounted as a hard dependency
// of every screen.

import {
  useCallback,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  type AdvanceReason,
  type OnboardingApi,
  type OnboardingState,
  readOnboardedAt,
  writeOnboardedNow,
} from "../../lib/onboarding";
import { STEPS } from "./steps";
import OnboardingTour from "./OnboardingTour";
import { OnboardingContext } from "./OnboardingContext";

interface ProviderProps {
  children: ReactNode;
  /** Set to false in tests / Storybook to disable auto-open on first mount. */
  autoStart?: boolean;
}

export function OnboardingProvider({
  children,
  autoStart = true,
}: ProviderProps) {
  // Initialize state lazily so the first-mount decision happens *during*
  // render (not in an effect). This avoids the setState-in-effect anti-pattern
  // and the resulting one-frame flicker. `autoStart=false` skips the
  // localStorage check entirely (used by tests / Storybook).
  const [tour, setTour] = useState<OnboardingState>(() => {
    const shouldOpen = autoStart && !readOnboardedAt();
    return { open: shouldOpen, index: 0, forced: false };
  });

  const startTour = useCallback(() => {
    setTour({ open: true, index: 0, forced: true });
  }, []);

  const closeTour = useCallback(() => {
    setTour((prev) => ({ ...prev, open: false }));
  }, []);

  const dismissTour = useCallback(() => {
    writeOnboardedNow();
    setTour((prev) => ({ ...prev, open: false }));
  }, []);

  const completeTour = useCallback(() => {
    writeOnboardedNow();
    setTour((prev) => ({ ...prev, open: false }));
  }, []);

  const goTo = useCallback((index: number, _reason?: AdvanceReason) => {
    void _reason; // reserved for telemetry
    setTour((prev) => ({
      ...prev,
      index: Math.max(0, Math.min(STEPS.length - 1, index)),
    }));
  }, []);

  const next = useCallback(() => {
    setTour((prev) => ({
      ...prev,
      index: Math.min(STEPS.length - 1, prev.index + 1),
    }));
  }, []);

  const prev = useCallback(() => {
    setTour((prev) => ({ ...prev, index: Math.max(0, prev.index - 1) }));
  }, []);

  const api = useMemo<OnboardingApi>(
    () => ({
      tour,
      startTour,
      closeTour,
      dismissTour,
      completeTour,
      goTo,
      next,
      prev,
    }),
    [tour, startTour, closeTour, dismissTour, completeTour, goTo, next, prev],
  );

  return (
    <OnboardingContext.Provider value={api}>
      {children}
      <OnboardingTour />
    </OnboardingContext.Provider>
  );
}
