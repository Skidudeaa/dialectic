// StepFrame — shared layout for every onboarding step.
//
// Steps render their title, lede, and a body slot. StepFrame handles the
// chrome around them: progress dot ribbon, "step N of M" counter, est. read
// time, and the prev/next/skip control bar at the bottom. This keeps each
// individual Step component focused purely on the *content* it teaches.

import { type ReactNode } from "react";
import { ChevronLeft, ChevronRight, X } from "lucide-react";

import { useOnboarding } from "./useOnboarding";
import { STEPS } from "./steps";

interface Props {
  /** One short, declarative sentence — the headline of the step. */
  title: string;
  /** 1-2 sentence value prop. Sets up the why before the what. */
  lede: ReactNode;
  /** The illustration / mini-mockup. Required — content without a visual
   *  anchor reads as a wall of text. */
  illustration: ReactNode;
  /** "What you can do here" — keep to 2-3 short items. */
  bullets: Array<{ title: string; body: ReactNode }>;
  /** Optional kbd hint shown in the footer (e.g. "Ctrl+K"). */
  shortcut?: ReactNode;
  /** Optional override for the primary action label (e.g. "Get started" on
   *  the last step). */
  primaryLabel?: string;
  /** Optional "Try this" footer block — concrete copyable example(s) the
   *  user can paste into chat / Pine / curl right now. Renders below the
   *  bullets with its own styling (see TryThis component). */
  tryThis?: ReactNode;
}

export default function StepFrame({
  title,
  lede,
  illustration,
  bullets,
  shortcut,
  primaryLabel,
  tryThis,
}: Props) {
  const { tour, next, prev, dismissTour, completeTour, goTo } = useOnboarding();

  const isLast = tour.index >= STEPS.length - 1;
  const isFirst = tour.index <= 0;
  const meta = STEPS[tour.index];

  return (
    <div className="flex flex-col h-full">
      {/* Header — title row + meta */}
      <div className="px-6 pt-5 pb-3 border-b border-border/60">
        <div className="flex items-center justify-between text-[10px] font-mono uppercase tracking-widest text-text-dim">
          <span>
            <span className="text-amber">{meta.title}</span>
            <span className="text-text-dim/70">
              {" · "}step {tour.index + 1} of {STEPS.length}
            </span>
          </span>
          <span className="flex items-center gap-2">
            <span className="hidden sm:inline">~{meta.est}</span>
            <button
              onClick={dismissTour}
              className="text-text-dim hover:text-text-primary transition-colors"
              aria-label="Skip tour"
              title="Skip tour"
            >
              <X size={13} />
            </button>
          </span>
        </div>

        <h2
          id="onboarding-title"
          className="mt-2 text-lg font-semibold leading-tight bg-gradient-to-r from-amber via-amber to-text-primary bg-clip-text text-transparent"
        >
          {title}
        </h2>
        <p className="mt-1.5 text-text-muted text-[12px] leading-relaxed max-w-prose">
          {lede}
        </p>
      </div>

      {/* Body — illustration on top, bullets below. Single column keeps the
          modal narrow & scannable on narrow viewports. */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        <div className="rounded border border-border/60 bg-elevated/50 p-3">
          {illustration}
        </div>

        <ul className="space-y-2.5">
          {bullets.map((b, i) => (
            <li key={i} className="flex gap-2.5">
              <span
                aria-hidden="true"
                className="mt-[3px] inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-sm bg-amber/15 text-amber text-[9px] font-mono font-semibold"
              >
                {i + 1}
              </span>
              <div className="text-[12px] leading-relaxed">
                <div className="text-text-primary font-medium">{b.title}</div>
                <div className="text-text-muted">{b.body}</div>
              </div>
            </li>
          ))}
        </ul>

        {shortcut && (
          <div className="text-[10px] font-mono text-text-dim flex items-center gap-1.5 pt-1">
            <span className="uppercase tracking-widest">Try it:</span>
            <span>{shortcut}</span>
          </div>
        )}

        {tryThis}
      </div>

      {/* Footer — progress dots + nav. Sticks to the bottom of the modal. */}
      <div className="border-t border-border/60 px-6 py-3 flex items-center justify-between gap-3">
        <div
          className="flex items-center gap-1.5"
          role="tablist"
          aria-label="Onboarding progress"
        >
          {STEPS.map((s, i) => (
            <button
              key={s.id}
              role="tab"
              aria-selected={i === tour.index}
              aria-label={`Go to step ${i + 1}: ${s.title}`}
              title={s.title}
              onClick={() => goTo(i, "jump")}
              className={`h-1.5 rounded-full transition-all ${
                i === tour.index
                  ? "w-6 bg-amber"
                  : i < tour.index
                  ? "w-1.5 bg-amber/50"
                  : "w-1.5 bg-border hover:bg-text-dim"
              }`}
            />
          ))}
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={dismissTour}
            className="btn-ghost text-text-dim"
            aria-label="Skip the tour"
          >
            Skip
          </button>
          <button
            onClick={prev}
            disabled={isFirst}
            className="btn-secondary inline-flex items-center gap-1"
            aria-label="Previous step"
          >
            <ChevronLeft size={11} />
            Back
          </button>
          {isLast ? (
            <button
              onClick={completeTour}
              className="btn-primary inline-flex items-center gap-1"
              autoFocus
            >
              {primaryLabel ?? "Get started"}
            </button>
          ) : (
            <button
              onClick={next}
              className="btn-primary inline-flex items-center gap-1"
              autoFocus
            >
              {primaryLabel ?? "Next"}
              <ChevronRight size={11} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
