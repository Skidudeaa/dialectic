import { useState } from "react";
import { PANELS, type PanelDef } from "../../lib/welcome";

// WorkspaceDiagram — a clickable layout map of the 5 dashboard panels.
// Hovering or focusing a tile reveals its tagline + bullets in a side
// caption. Mirrors the actual dashboard geometry: chat dominates center,
// thesis viewer right, predictions/journal/ticker stacked left.

const ACCENTS: Record<PanelDef["accent"], { text: string; bg: string; ring: string }> = {
  amber: { text: "text-amber", bg: "bg-amber/10", ring: "ring-amber/40" },
  teal: { text: "text-teal", bg: "bg-teal/10", ring: "ring-teal/40" },
  purple: { text: "text-purple", bg: "bg-purple/10", ring: "ring-purple/40" },
  blue: { text: "text-blue", bg: "bg-blue/10", ring: "ring-blue/40" },
  green: { text: "text-green", bg: "bg-green/10", ring: "ring-green/40" },
};

export default function WorkspaceDiagram() {
  const [active, setActive] = useState<string>(PANELS[0].id);
  const activePanel = PANELS.find((p) => p.id === active) ?? PANELS[0];

  return (
    <div className="grid lg:grid-cols-[2fr_1fr] gap-4">
      {/* Diagram */}
      <div
        className="bg-void border border-border rounded-md p-3"
        role="group"
        aria-label="Five-panel dashboard layout"
      >
        <div className="grid grid-cols-4 grid-rows-3 gap-1.5 h-[280px]">
          {PANELS.map((p) => {
            const a = ACCENTS[p.accent];
            const isActive = p.id === active;
            return (
              <button
                key={p.id}
                type="button"
                onMouseEnter={() => setActive(p.id)}
                onFocus={() => setActive(p.id)}
                onClick={() => setActive(p.id)}
                aria-pressed={isActive}
                aria-label={`${p.title}: ${p.tagline}`}
                className={[
                  "rounded border text-left p-2 transition-all cursor-pointer flex flex-col justify-between",
                  a.bg,
                  isActive
                    ? `border-transparent ring-2 ${a.ring}`
                    : "border-border hover:border-text-dim",
                ].join(" ")}
                style={{
                  gridColumn: `${p.col[0]} / span ${p.col[1]}`,
                  gridRow: `${p.row[0]} / span ${p.row[1]}`,
                }}
              >
                <span
                  className={`text-[10px] uppercase tracking-widest font-mono ${a.text}`}
                >
                  {p.title}
                </span>
                <span className="text-[10px] font-mono text-text-muted line-clamp-2">
                  {p.tagline}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Caption */}
      <aside
        className="bg-surface border border-border rounded-md p-4"
        aria-live="polite"
      >
        <div
          className={`text-[11px] uppercase tracking-widest font-mono ${ACCENTS[activePanel.accent].text} mb-1`}
        >
          {activePanel.title}
        </div>
        <p className="text-sm text-text-primary mb-3 leading-snug">
          {activePanel.tagline}
        </p>
        <ul className="space-y-1.5 text-xs text-text-muted">
          {activePanel.bullets.map((b) => (
            <li key={b} className="flex gap-2">
              <span className="text-text-dim font-mono mt-px">›</span>
              <span>{b}</span>
            </li>
          ))}
        </ul>
      </aside>
    </div>
  );
}
