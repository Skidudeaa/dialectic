// OnboardingTour — modal controller.
//
// Reads state from OnboardingProvider, renders the current step inside a
// center-stage card on a dimmed backdrop. Handles global keyboard shortcuts
// (Arrow keys, Enter, Esc), focus trap, and step-change animation.
//
// Not a coachmark — the underlying panels aren't visible while this is up, so
// pretending to "point at" them with a translucent highlight would mislead.
// We teach with illustrations instead.

import { useEffect, useRef } from "react";

import { useOnboarding } from "./useOnboarding";
import { STEPS } from "./steps";

export default function OnboardingTour() {
  const { tour, next, prev, dismissTour, closeTour } = useOnboarding();
  const dialogRef = useRef<HTMLDivElement | null>(null);

  // Animate step transitions — we use the index itself as a React key on the
  // animated wrapper. Changing the key re-mounts the subtree, which re-runs
  // the fade-in CSS animation. No setState-in-effect needed. CSS animations
  // are globally neutralized under `prefers-reduced-motion` (see index.css).

  // Lock body scroll while tour is open so the modal feels modal.
  useEffect(() => {
    if (!tour.open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [tour.open]);

  // Global keybinds (scoped to the open modal).
  useEffect(() => {
    if (!tour.open) return;

    function onKey(e: KeyboardEvent) {
      // Don't hijack typing inside inputs (none today, but future-proof).
      const t = e.target as HTMLElement | null;
      const typing =
        t?.tagName === "INPUT" ||
        t?.tagName === "TEXTAREA" ||
        t?.isContentEditable;
      if (typing) return;

      if (e.key === "Escape") {
        e.preventDefault();
        dismissTour();
      } else if (e.key === "ArrowRight" || e.key === "PageDown") {
        e.preventDefault();
        next();
      } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
        e.preventDefault();
        prev();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [tour.open, next, prev, dismissTour]);

  // Simple focus trap — on open, focus the dialog; Tab/Shift+Tab cycles
  // within. A full trap (with sentinel nodes) is overkill for a tour with a
  // handful of buttons; we rely on the native tab order + a wrap handler.
  useEffect(() => {
    if (!tour.open) return;
    dialogRef.current?.focus();
  }, [tour.open, tour.index]);

  function onTrapKey(e: React.KeyboardEvent) {
    if (e.key !== "Tab") return;
    const root = dialogRef.current;
    if (!root) return;
    const focusables = root.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    if (focusables.length === 0) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  if (!tour.open) return null;

  const Step = STEPS[tour.index]?.Component;
  if (!Step) return null;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-4"
      role="presentation"
      onClick={closeTour}
    >
      {/* Dimmed backdrop with a faint amber glow — the only place in the app
          we allow chrome this warm. Announces "this is a special moment". */}
      <div
        className="absolute inset-0 bg-void/80"
        aria-hidden="true"
        style={{
          backgroundImage:
            "radial-gradient(circle at 50% 35%, rgba(212,168,67,0.08), transparent 60%)",
        }}
      />

      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboarding-title"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        onKeyDown={onTrapKey}
        className="relative bg-surface border border-border rounded-md shadow-2xl w-full max-w-lg max-h-[90vh] flex flex-col animate-fade-in focus:outline-none"
      >
        <div key={tour.index} className="animate-fade-in flex-1 flex flex-col min-h-0">
          <Step />
        </div>
      </div>
    </div>
  );
}
