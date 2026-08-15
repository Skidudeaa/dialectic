// OnboardingTour tests — exercises the controller end-to-end:
// step 1 visible → Next advances to step 2 → Skip writes localStorage and
// closes the modal. Plus a couple of smaller invariants (replay starts fresh,
// keyboard ArrowRight advances).

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { render, screen, fireEvent, cleanup, act } from "@testing-library/react";

import { OnboardingProvider } from "../onboarding/OnboardingProvider";
import { useOnboarding } from "../onboarding/useOnboarding";
import { ONBOARDED_KEY, clearOnboardedFlag } from "../../lib/onboarding";

beforeEach(() => {
  clearOnboardedFlag();
});

afterEach(() => {
  cleanup();
  clearOnboardedFlag();
});

function ReplayButton() {
  const { startTour } = useOnboarding();
  return <button onClick={startTour}>replay</button>;
}

describe("OnboardingTour", () => {
  it("auto-opens on first mount, advances via Next, and Skip writes localStorage", () => {
    render(
      <OnboardingProvider>
        <div>app</div>
      </OnboardingProvider>,
    );

    // Step 1 — Welcome — should be visible without any user action.
    expect(
      screen.getByText(/turns macro theses into causal graphs/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/step 1 of 6/i)).toBeInTheDocument();

    // Click Next ("Show me how" is the primaryLabel on step 1).
    fireEvent.click(screen.getByRole("button", { name: /show me how/i }));

    // Step 2 — Thesis Viewer — content visible.
    expect(
      screen.getByText(/where you read the model — and where the model reads you/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/step 2 of 6/i)).toBeInTheDocument();

    // localStorage not yet written — we haven't skipped or completed.
    expect(localStorage.getItem(ONBOARDED_KEY)).toBeNull();

    // Skip — should close the modal and write the timestamp.
    fireEvent.click(screen.getByRole("button", { name: /skip the tour/i }));

    expect(
      screen.queryByText(/where you read the model — and where the model reads you/i),
    ).not.toBeInTheDocument();

    const stamp = localStorage.getItem(ONBOARDED_KEY);
    expect(stamp).not.toBeNull();
    // ISO timestamp shape — Date.parse should succeed.
    expect(Number.isNaN(Date.parse(stamp!))).toBe(false);
  });

  it("does NOT auto-open when localStorage flag is already set", () => {
    localStorage.setItem(ONBOARDED_KEY, new Date().toISOString());
    render(
      <OnboardingProvider>
        <div>app</div>
      </OnboardingProvider>,
    );
    expect(
      screen.queryByText(/turns macro theses into causal graphs/i),
    ).not.toBeInTheDocument();
  });

  it("startTour() reopens from step 1 even when the flag is set (replay)", () => {
    localStorage.setItem(ONBOARDED_KEY, new Date().toISOString());
    render(
      <OnboardingProvider>
        <ReplayButton />
      </OnboardingProvider>,
    );
    fireEvent.click(screen.getByText("replay"));
    expect(
      screen.getByText(/turns macro theses into causal graphs/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/step 1 of 6/i)).toBeInTheDocument();
  });

  it("ArrowRight advances the step", () => {
    render(
      <OnboardingProvider>
        <div />
      </OnboardingProvider>,
    );
    expect(screen.getByText(/step 1 of 6/i)).toBeInTheDocument();
    act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight" }));
    });
    expect(screen.getByText(/step 2 of 6/i)).toBeInTheDocument();
  });
});
