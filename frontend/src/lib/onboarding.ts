// Onboarding tour — shared types + constants.
//
// The localStorage key is the single source of truth for "has this user
// already completed/skipped the first-login tour?". The OnboardingProvider
// reads it on mount; on completion or skip, the tour writes an ISO timestamp
// (not a boolean) so we can audit when each user first finished onboarding
// and possibly re-trigger after major releases by comparing timestamps.

export const ONBOARDED_KEY = "td_onboarded";

/** Reason a step was advanced — fed to telemetry one day. */
export type AdvanceReason = "next" | "prev" | "jump" | "skip" | "complete";

export interface OnboardingState {
  /** True if the modal is currently mounted/visible. */
  open: boolean;
  /** Zero-indexed current step. */
  index: number;
  /** True if the tour was forcibly started via startTour() (replay button)
   *  and should ignore localStorage on next mount-cycle decision. */
  forced: boolean;
}

export interface OnboardingApi {
  tour: OnboardingState;
  /** Open the tour from step 0, ignoring localStorage. Used by the replay
   *  button in Dashboard / "?" overlay. */
  startTour: () => void;
  /** Close without writing localStorage. Use for accidental dismissals
   *  (e.g. modal backdrop click) where we want it to re-open next session. */
  closeTour: () => void;
  /** Close + write localStorage timestamp. Treat the tour as "done". */
  dismissTour: () => void;
  /** Same as dismissTour but semantically "user reached the end". */
  completeTour: () => void;
  /** Programmatic step navigation. Bounds-clamped by the controller. */
  goTo: (index: number, reason?: AdvanceReason) => void;
  next: () => void;
  prev: () => void;
}

/** Returns the ISO timestamp from localStorage, or null if never onboarded. */
export function readOnboardedAt(): string | null {
  try {
    return localStorage.getItem(ONBOARDED_KEY);
  } catch {
    return null;
  }
}

export function writeOnboardedNow(): void {
  try {
    localStorage.setItem(ONBOARDED_KEY, new Date().toISOString());
  } catch {
    /* quota / privacy mode — silently no-op */
  }
}

/** Test seam: clear the onboarded flag. Not used by app code. */
export function clearOnboardedFlag(): void {
  try {
    localStorage.removeItem(ONBOARDED_KEY);
  } catch {
    /* ignore */
  }
}
