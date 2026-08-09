// Step 3 — Thesis Viewer.
//
// The right panel where the actual model state lives. Mini cascade ribbon +
// node list + confluence bars in a single visual so a glance teaches the
// reader what the panel will look like in real life.

import StepFrame from "../StepFrame";
import TryThis from "../TryThis";

function CascadeRibbon() {
  // 5 phase boxes: 1 fired, 2 fired, 3 starting, 4-5 untouched.
  const phases = [
    { label: "Shock", status: "done" },
    { label: "Transmission", status: "done" },
    { label: "Amplification", status: "active" },
    { label: "Policy", status: "idle" },
    { label: "Resolution", status: "idle" },
  ] as const;

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className="text-[9px] uppercase tracking-widest text-text-dim font-mono">
          Cascade
        </span>
        <span className="text-[9px] font-mono text-amber uppercase tracking-widest">
          Approaching
        </span>
      </div>
      <div className="flex gap-1">
        {phases.map((p) => (
          <div
            key={p.label}
            className={`flex-1 h-2 rounded-sm ${
              p.status === "done"
                ? "bg-danger/70"
                : p.status === "active"
                ? "bg-amber animate-pulse-amber"
                : "bg-elevated border border-border"
            }`}
            title={p.label}
          />
        ))}
      </div>
      <div className="text-[10px] font-mono text-text-muted mt-1">
        3. Amplification — real PnL risk starts here
      </div>
    </div>
  );
}

interface NodeRow {
  id: string;
  state: string;
  color: "danger" | "amber" | "muted";
  aux?: string;
}

function NodeList() {
  const rows: NodeRow[] = [
    { id: "hormuz", state: "fired", color: "danger" },
    { id: "brent", state: "approaching", color: "amber", aux: "RSI:64" },
    { id: "em-stress", state: "fired", color: "danger" },
    { id: "earnings", state: "stable", color: "muted" },
  ];
  return (
    <div className="space-y-0.5">
      {rows.map((r) => (
        <div
          key={r.id}
          className="flex items-center justify-between font-mono text-[11px]"
        >
          <span className="text-text-primary">{r.id}</span>
          <span className="flex items-center gap-1.5">
            {r.aux && <span className="text-text-dim text-[10px]">{r.aux}</span>}
            <span
              className={
                r.color === "danger"
                  ? "badge-fired"
                  : r.color === "amber"
                  ? "badge-approaching"
                  : "badge-monitoring"
              }
            >
              {r.state}
            </span>
          </span>
        </div>
      ))}
    </div>
  );
}

function ConfluenceBars() {
  // em-stress mirrors the live iran-hormuz snapshot (fired, confluence 2.05).
  // earnings-compression is the approaching foil — below the 2.0 trade bar.
  const rows = [
    { id: "em-stress", score: 2.05, w: 92 },
    { id: "earnings-compression", score: 1.67, w: 75 },
  ];
  return (
    <div className="space-y-1">
      <div className="text-[9px] uppercase tracking-widest text-text-dim font-mono">
        Confluence
      </div>
      {rows.map((r) => (
        <div key={r.id} className="flex items-center gap-2">
          <span className="font-mono text-[10px] text-text-muted w-32 truncate">
            {r.id}
          </span>
          <div className="flex-1 h-1.5 bg-elevated rounded-sm overflow-hidden">
            <div
              className="h-full bg-amber"
              style={{ width: `${r.w}%` }}
              aria-hidden="true"
            />
          </div>
          <span className="font-mono text-[10px] text-amber w-9 text-right">
            {r.score.toFixed(2)}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function ThesisViewerStep() {
  return (
    <StepFrame
      title="Where you read the model — and where the model reads you."
      lede={
        <>
          The right panel is your situational awareness. Every node, every
          deadline, every cascade phase your thesis has crossed. Click the
          refresh button to pull fresh Yahoo + Polymarket data.
        </>
      }
      illustration={
        <div className="space-y-3">
          <CascadeRibbon />
          <div className="border-t border-border/40 pt-3">
            <NodeList />
          </div>
          <div className="border-t border-border/40 pt-3">
            <ConfluenceBars />
          </div>
        </div>
      }
      bullets={[
        {
          title: "5-phase cascade tracker",
          body: "Shock → Transmission → Amplification → Policy → Resolution. Amplification is where money is at risk.",
        },
        {
          title: "Node states colored by severity",
          body: "fired (red), approaching (amber), stable (grey), gated (purple). Sort the worst to the top.",
        },
        {
          title: "Confluence ≥ 2.0 = trade setup",
          body: "Three or more independent causal paths firing on one node. That's the conviction signal.",
        },
      ]}
      tryThis={
        <TryThis
          intro={
            <>
              Click <span className="font-mono text-amber">em-stress</span>{" "}
              in the iran-hormuz right panel — see why three independent
              paths (oil price, dollar strength, EM credit spreads) all
              converge on one node. Trades on em-stress are
              conviction-weighted higher than any single-path signal.
            </>
          }
          snippets={[
            {
              label: "Ask the LLM to walk the edges",
              text: "@claude open iran-hormuz, list every upstream node feeding em-stress and tell me which path is currently the strongest contributor to its 2.05 score.",
              ariaLabel: "Copy prompt to walk em-stress confluence",
            },
          ]}
        />
      }
    />
  );
}
