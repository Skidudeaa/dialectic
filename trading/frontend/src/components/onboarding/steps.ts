// Step registry — single source of truth for the tour's structure.
//
// The order here IS the order users see. Adding a step = append a row;
// reordering = move a row. The OnboardingTour controller renders STEPS[index]
// directly, so there's no other map to keep in sync.
//
// `est` is human reading-time guidance (informational only — we don't gate
// advancement on it). `anchor` names the surface the step describes; not used
// for positioning today (the tour is modal, not a coachmark) but kept for the
// day someone wants to upgrade to anchored hints.

import type { ComponentType } from "react";

import WelcomeStep from "./steps/Welcome";
import ChatPanelStep from "./steps/ChatPanel";
import ThesisViewerStep from "./steps/ThesisViewer";
import TradingViewStep from "./steps/TradingView";
import BuilderStep from "./steps/Builder";
import IntegrationsStep from "./steps/Integrations";
import DoneStep from "./steps/Done";

export interface StepMeta {
  id: string;
  /** Short label shown in the progress dot tooltip and (small caps) header. */
  title: string;
  /** Surface the step is about — useful if we ever pin this near a panel. */
  anchor: "global" | "chat" | "thesis" | "tradingview" | "builder" | "integrations";
  /** Reading time hint, e.g. "20s". Surfaced in the corner of the modal. */
  est: string;
  Component: ComponentType;
}

export const STEPS: StepMeta[] = [
  {
    id: "welcome",
    title: "Welcome",
    anchor: "global",
    est: "20s",
    Component: WelcomeStep,
  },
  {
    id: "chat",
    title: "Chat",
    anchor: "chat",
    est: "30s",
    Component: ChatPanelStep,
  },
  {
    id: "thesis",
    title: "Thesis",
    anchor: "thesis",
    est: "45s",
    Component: ThesisViewerStep,
  },
  {
    id: "tradingview",
    title: "TradingView",
    anchor: "tradingview",
    est: "30s",
    Component: TradingViewStep,
  },
  {
    id: "builder",
    title: "Builder",
    anchor: "builder",
    est: "25s",
    Component: BuilderStep,
  },
  {
    id: "integrations",
    title: "Integrations",
    anchor: "integrations",
    est: "20s",
    Component: IntegrationsStep,
  },
  {
    id: "done",
    title: "Ready",
    anchor: "global",
    est: "10s",
    Component: DoneStep,
  },
];
