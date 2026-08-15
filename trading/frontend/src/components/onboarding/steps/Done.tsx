// Step 6 — Done.
//
// Closure step. We folded the "Tuesday morning" 4-action walkthrough into
// this step instead of adding another — a tour with a punchy closer reads
// better than one that pads itself out with a dedicated summary step.
// (Was step 7 of 7 when the Chat step still existed; the C4 cull dropped
// that step and the tour's own tests along with it — see
// OnboardingTour.test.tsx for the current "step N of 6" invariant.)
//
// The TryThis footer is the load-bearing addition: three concrete starter
// actions with copyable artifacts (slash command, book-pick rule, journal
// click target) instead of generic encouragement.

import StepFrame from "../StepFrame";
import TryThis from "../TryThis";

interface MorningStep {
  time: string;
  action: string;
  detail: string;
}

const MORNING: MorningStep[] = [
  {
    time: "08:02",
    action: "/brief",
    detail: "Open dashboard. Connection dot green. Drop /brief in your active room. Read the overnight delta.",
  },
  {
    time: "08:07",
    action: "Glance Cascade",
    detail: "Iran/Hormuz at Phase 3 (Amplification). Two nodes near firing. That's where the day's risk lives.",
  },
  {
    time: "08:11",
    action: "@claude",
    detail: "\"any TV alerts I should arm before market open?\" — Claude flags brent-persistence-close-above-115 if it isn't already armed.",
  },
  {
    time: "08:14",
    action: "Trade Journal",
    detail: "Log yesterday's exits. Link each entry to its thesis node. Done in <15 minutes, fully calibrated.",
  },
];

function MorningTimeline() {
  return (
    <div className="space-y-1.5">
      <div className="text-[9px] uppercase tracking-widest text-text-dim font-mono mb-1">
        A Tuesday morning, in 12 minutes
      </div>
      {MORNING.map((m) => (
        <div
          key={m.time}
          className="flex items-start gap-2 font-mono text-[10px] leading-snug"
        >
          <span className="text-amber w-10 shrink-0 pt-0.5">{m.time}</span>
          <span className="w-px self-stretch bg-amber/30 shrink-0" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <div className="text-text-primary">{m.action}</div>
            <div className="text-text-muted text-[10px] leading-snug">
              {m.detail}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function DoneStep() {
  return (
    <StepFrame
      title="You're set. The desk is yours."
      lede={
        <>
          Here's what a real morning looks like — four actions, twelve
          minutes, and you're calibrated to every thesis on the desk.
          Then disagree with the model: log predictions, journal trades,
          fork a book. That's what compounds.
        </>
      }
      illustration={<MorningTimeline />}
      bullets={[
        {
          title: "Hit ? for the cheat sheet",
          body: (
            <>
              Keyboard shortcuts overlay — <span className="kbd">Ctrl+K</span>{" "}
              command palette, <span className="kbd">Ctrl+B</span> sidebar,{" "}
              <span className="kbd">Esc</span> to unwind.
            </>
          ),
        },
        {
          title: "Visit /welcome anytime",
          body: "The deep-dive evergreen guide — install steps, troubleshooting, the full vocabulary of the engine.",
        },
        {
          title: "Replay this tour later",
          body: "There's a help button in the top bar that re-runs this onboarding when you want a refresher.",
        },
      ]}
      primaryLabel="Open the desk"
      tryThis={
        <TryThis
          intro={
            <>
              Three concrete starter actions for your first week. Don't
              read past these — pick one and do it before market open
              tomorrow.
            </>
          }
          snippets={[
            {
              label: "Tomorrow morning",
              text: "/brief",
              caption: "Drop this in your active room before you check anything else. See what the desk learned overnight.",
              ariaLabel: "Copy /brief for tomorrow morning routine",
            },
            {
              label: "This week — pick the book closest to your real conviction",
              text: "japan-rate-shock-graph (FX trader)\nai-capex-unwind-graph (equity sector trader)\nchina-property-cascade-graph (cross-asset)\niran-hormuz-graph (commodity trader)\ntrump-tariffs-graph (macro)",
              multiline: true,
              caption: "Open it in the Builder, adjust the thresholds against your priors. The thesis is yours when the numbers feel honest.",
              ariaLabel: "Copy book selector guide for first week",
            },
            {
              label: "First trade you log",
              text: "Open Trade Journal → New entry → Link to thesis node",
              caption: "Pick the node that justified the trade. That linkage is how the desk learns your calibration over months.",
              ariaLabel: "Copy first trade journal action",
            },
          ]}
        />
      }
    />
  );
}
