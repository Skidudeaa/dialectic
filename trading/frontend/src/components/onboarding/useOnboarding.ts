// Hook accessors for the onboarding context.
//
// Lives in its own file so OnboardingProvider.tsx exports only components
// (react-refresh rule). Importing the context object from the provider would
// create a circular dependency, so we re-export from a tiny shared module.

import { useContext } from "react";

import { OnboardingContext } from "./OnboardingContext";
import type { OnboardingApi } from "../../lib/onboarding";

export function useOnboarding(): OnboardingApi {
  const ctx = useContext(OnboardingContext);
  if (!ctx) {
    throw new Error(
      "useOnboarding() must be used inside <OnboardingProvider>. " +
        "Wrap your app or test root with the provider.",
    );
  }
  return ctx;
}

/** Optional escape hatch for code that may render outside the provider tree
 *  (e.g. a probe in the login screen). Returns null instead of throwing. */
export function useOnboardingOptional(): OnboardingApi | null {
  return useContext(OnboardingContext);
}
