// The React context object — split out so consumers (useOnboarding hook) can
// import it without dragging the whole provider component into their bundle,
// and so the provider file can satisfy the react-refresh "components only"
// rule.

import { createContext } from "react";
import type { OnboardingApi } from "../../lib/onboarding";

export const OnboardingContext = createContext<OnboardingApi | null>(null);
