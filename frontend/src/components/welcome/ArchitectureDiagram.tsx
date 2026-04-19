import { useState } from "react";

// ArchitectureDiagram — annotated SVG stack. Hovering or focusing a layer
// updates the side legend with where that piece lives in the repo and
// what owns it. No fake screenshots; pure CSS/SVG.

interface Layer {
  id: string;
  label: string;
  sub: string;
  where: string;
  detail: string;
}

const LAYERS: readonly Layer[] = [
  {
    id: "engine",
    label: "Causal Engine",
    sub: "Python · stdlib · 2200 LOC",
    where: "tools/thesis_graph/thesisgraph.py",
    detail:
      "Loads books/*.json, runs Kahn's topological sort, evaluates thresholds, computes confluence, exports snapshots. Same logic powers HTML generation and the live runtime.",
  },
  {
    id: "fastapi",
    label: "FastAPI Backend",
    sub: "uvicorn · WebSocket · JWT",
    where: "web/main.py + web/routes/* + web/adapters/*",
    detail:
      "REST + WebSocket fan-out. Path validation, scrypt-hashed JWT auth, blocking I/O wrapped in asyncio.to_thread, 60s thesis state cache, concurrent LLM compare via asyncio.gather.",
  },
  {
    id: "react",
    label: "React SPA",
    sub: "Vite · Tailwind 4 · Router 7",
    where: "frontend/src/",
    detail:
      "Five-panel operator console. Auto-reconnecting WebSocket, command palette, XSS-safe markdown, toast notifications, lazy-loaded Builder route.",
  },
  {
    id: "dialectic",
    label: "Dialectic",
    sub: "Postgres · pgvector · LLM",
    where: "/root/DwoodAmo/dialectic",
    detail:
      "Separate service. Receives signed snapshot pushes, embeds them as room memories, surfaces them in LLM prompts, drops curator alerts when triggers fire and you're offline.",
  },
  {
    id: "droplet",
    label: "DigitalOcean Droplet",
    sub: "systemd · nginx · 167.99.113.232",
    where: "deploy/tradingdesk.service",
    detail:
      "Single host. Backend on uvicorn behind nginx, frontend served as built static, SQLite on persistent disk under data/, daily backup with WAL checkpoint.",
  },
];

export default function ArchitectureDiagram() {
  const [active, setActive] = useState<string>(LAYERS[0].id);
  const layer = LAYERS.find((l) => l.id === active) ?? LAYERS[0];

  return (
    <div className="grid lg:grid-cols-[1fr_1fr] gap-4 items-stretch">
      {/* Stack */}
      <div className="bg-void border border-border rounded-md p-4">
        <div className="flex flex-col gap-2">
          {LAYERS.map((l, i) => {
            const isActive = l.id === active;
            return (
              <button
                key={l.id}
                type="button"
                onMouseEnter={() => setActive(l.id)}
                onFocus={() => setActive(l.id)}
                onClick={() => setActive(l.id)}
                aria-pressed={isActive}
                className={[
                  "text-left rounded border px-3 py-2.5 transition-colors cursor-pointer flex items-center justify-between",
                  isActive
                    ? "border-amber/50 bg-amber/5"
                    : "border-border bg-surface hover:border-text-dim",
                ].join(" ")}
              >
                <div>
                  <div
                    className={[
                      "text-xs font-mono uppercase tracking-widest",
                      isActive ? "text-amber" : "text-text-primary",
                    ].join(" ")}
                  >
                    {l.label}
                  </div>
                  <div className="text-[10px] font-mono text-text-muted mt-0.5">
                    {l.sub}
                  </div>
                </div>
                <span className="text-[10px] font-mono text-text-dim">
                  {String(i + 1).padStart(2, "0")}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Legend */}
      <aside
        className="bg-surface border border-border rounded-md p-4 flex flex-col"
        aria-live="polite"
      >
        <div className="text-[11px] uppercase tracking-widest font-mono text-amber mb-1">
          {layer.label}
        </div>
        <div className="text-[10px] font-mono text-text-dim mb-3">{layer.where}</div>
        <p className="text-xs text-text-primary leading-relaxed">{layer.detail}</p>
        <div className="mt-auto pt-4 text-[10px] font-mono text-text-dim border-t border-border mt-4">
          Hover a layer to inspect.
        </div>
      </aside>
    </div>
  );
}
