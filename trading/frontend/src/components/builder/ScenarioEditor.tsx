// ScenarioEditor — manage thesis scenarios (what-if branches).

import { useState } from "react";
import { Plus, X, ChevronDown, ChevronRight } from "lucide-react";
import type { BuilderScenario } from "../../lib/types";

interface Props {
  scenarios: BuilderScenario[];
  nodeIds: string[];
  onChange: (scenarios: BuilderScenario[]) => void;
}

function emptyScenario(): BuilderScenario {
  return {
    id: `scenario-${Date.now()}`,
    name: "",
    probability: 0.25,
    notes: "",
    overrides: {},
    portfolioImpact: {},
  };
}

export default function ScenarioEditor({ scenarios, nodeIds, onChange }: Props) {
  const [expanded, setExpanded] = useState<number | null>(null);

  const updateScenario = (idx: number, updates: Partial<BuilderScenario>) => {
    const updated = [...scenarios];
    updated[idx] = { ...updated[idx], ...updates };
    onChange(updated);
  };

  const totalProb = scenarios.reduce((sum, s) => sum + s.probability, 0);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-mono text-text-muted uppercase">Scenarios</span>
          <span className={`text-[10px] font-mono ${Math.abs(totalProb - 1.0) < 0.01 ? "text-green" : "text-danger"}`}>
            Σ = {(totalProb * 100).toFixed(0)}%
          </span>
        </div>
        <button
          onClick={() => {
            onChange([...scenarios, emptyScenario()]);
            setExpanded(scenarios.length);
          }}
          className="flex items-center gap-1 text-[11px] font-mono text-amber hover:text-text-primary"
        >
          <Plus size={12} /> Add
        </button>
      </div>

      {scenarios.map((s, i) => (
        <div key={s.id} className="bg-surface rounded border border-border">
          {/* Scenario header */}
          <div
            className="flex items-center gap-2 px-2 py-1.5 cursor-pointer hover:bg-elevated"
            onClick={() => setExpanded(expanded === i ? null : i)}
          >
            {expanded === i ? <ChevronDown size={12} className="text-text-dim" /> : <ChevronRight size={12} className="text-text-dim" />}
            <span className="flex-1 text-[12px] font-mono text-text-primary">
              {s.name || "Unnamed scenario"}
            </span>
            <span className="text-[10px] font-mono text-amber">
              {(s.probability * 100).toFixed(0)}%
            </span>
            <button
              onClick={e => { e.stopPropagation(); onChange(scenarios.filter((_, j) => j !== i)); }}
              className="p-0.5 text-text-dim hover:text-danger"
            >
              <X size={12} />
            </button>
          </div>

          {/* Expanded body */}
          {expanded === i && (
            <div className="px-2 pb-2 space-y-2 border-t border-border">
              <div className="grid grid-cols-2 gap-2 pt-2">
                <div className="flex flex-col gap-0.5">
                  <label className="text-[10px] font-mono text-text-dim">ID</label>
                  <input
                    value={s.id}
                    onChange={e => updateScenario(i, { id: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-") })}
                    className="px-2 py-1 bg-elevated border border-border rounded text-[12px] text-text-primary font-mono"
                  />
                </div>
                <div className="flex flex-col gap-0.5">
                  <label className="text-[10px] font-mono text-text-dim">Name</label>
                  <input
                    value={s.name}
                    onChange={e => updateScenario(i, { name: e.target.value })}
                    className="px-2 py-1 bg-elevated border border-border rounded text-[12px] text-text-primary font-mono"
                  />
                </div>
              </div>

              <div className="flex flex-col gap-0.5">
                <label className="text-[10px] font-mono text-text-dim">
                  Probability: {(s.probability * 100).toFixed(0)}%
                </label>
                <input
                  type="range" min="0" max="1" step="0.05"
                  value={s.probability}
                  onChange={e => updateScenario(i, { probability: parseFloat(e.target.value) })}
                  className="w-full accent-amber"
                />
              </div>

              <div className="flex flex-col gap-0.5">
                <label className="text-[10px] font-mono text-text-dim">Notes</label>
                <textarea
                  value={s.notes}
                  onChange={e => updateScenario(i, { notes: e.target.value })}
                  rows={2}
                  className="px-2 py-1 bg-elevated border border-border rounded text-[12px] text-text-primary font-mono resize-y"
                  placeholder="What does this scenario imply?"
                />
              </div>

              {/* Overrides */}
              <div className="flex flex-col gap-1">
                <label className="text-[10px] font-mono text-text-dim uppercase">Node Overrides</label>
                {Object.entries(s.overrides).map(([nodeId, value]) => (
                  <div key={nodeId} className="flex items-center gap-1">
                    <select
                      value={nodeId}
                      onChange={e => {
                        const newOverrides = { ...s.overrides };
                        delete newOverrides[nodeId];
                        newOverrides[e.target.value] = value;
                        updateScenario(i, { overrides: newOverrides });
                      }}
                      className="flex-1 px-1 py-0.5 bg-elevated border border-border rounded text-[11px] font-mono"
                    >
                      {nodeIds.map(id => <option key={id} value={id}>{id}</option>)}
                    </select>
                    <input
                      value={String(value)}
                      onChange={e => {
                        const newOverrides = { ...s.overrides };
                        // Try to parse as number, otherwise keep as string
                        const v = e.target.value;
                        newOverrides[nodeId] = !isNaN(Number(v)) && v !== "" ? Number(v) : v;
                        updateScenario(i, { overrides: newOverrides });
                      }}
                      className="w-24 px-1 py-0.5 bg-elevated border border-border rounded text-[11px] font-mono"
                      placeholder="value"
                    />
                    <button
                      onClick={() => {
                        const newOverrides = { ...s.overrides };
                        delete newOverrides[nodeId];
                        updateScenario(i, { overrides: newOverrides });
                      }}
                      className="p-0.5 text-text-dim hover:text-danger"
                    >
                      <X size={10} />
                    </button>
                  </div>
                ))}
                <button
                  onClick={() => {
                    const firstUnused = nodeIds.find(id => !(id in s.overrides)) || nodeIds[0] || "node";
                    updateScenario(i, { overrides: { ...s.overrides, [firstUnused]: "" } });
                  }}
                  className="flex items-center gap-1 text-[10px] font-mono text-amber hover:text-text-primary"
                >
                  <Plus size={10} /> Override
                </button>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
