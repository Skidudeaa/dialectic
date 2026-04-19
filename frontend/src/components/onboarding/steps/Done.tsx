// Step 7 — Done.
//
// Closure step. Tells the user where to go next (welcome page deep dive,
// command palette, "?" replay) and lets them dismiss to land on the dashboard
// proper. The primary CTA writes the localStorage timestamp via completeTour.

import StepFrame from "../StepFrame";
import { CheckCircle2 } from "lucide-react";

function DoneIllustration() {
  return (
    <div className="flex flex-col items-center justify-center py-3 gap-2">
      <CheckCircle2 size={42} className="text-amber" strokeWidth={1.5} />
      <div className="text-[11px] font-mono text-text-muted text-center max-w-[28ch]">
        First room, first @claude question, first /brief — that's a good
        opening hour.
      </div>
    </div>
  );
}

export default function DoneStep() {
  return (
    <StepFrame
      title="You're set. The desk is yours."
      lede={
        <>
          The model only gets sharper the more you argue with it. Disagree
          with confluence scores, log predictions, journal every trade — that
          calibration is what compounds.
        </>
      }
      illustration={<DoneIllustration />}
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
    />
  );
}
