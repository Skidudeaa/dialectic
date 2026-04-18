// EdgeEditor — property panel for the selected edge.

import { Trash2 } from "lucide-react";
import type { BuilderEdge } from "../../lib/types";

interface Props {
  edge: BuilderEdge;
  sourceLabel: string;
  targetLabel: string;
  onChange: (updated: BuilderEdge) => void;
  onDelete: () => void;
}

export default function EdgeEditor({ edge, sourceLabel, targetLabel, onChange, onDelete }: Props) {
  const update = <K extends keyof BuilderEdge>(key: K, value: BuilderEdge[K]) =>
    onChange({ ...edge, [key]: value });

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <span className="text-[12px] font-mono text-text-primary">
          <span className="text-amber">{sourceLabel}</span>
          <span className="text-text-dim"> → </span>
          <span className="text-teal">{targetLabel}</span>
        </span>
        <button onClick={onDelete} className="p-1 text-text-dim hover:text-danger rounded" title="Delete edge">
          <Trash2 size={13} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
        {/* Mechanism */}
        <div className="flex flex-col gap-0.5">
          <label className="text-[10px] font-mono text-text-dim uppercase">Mechanism</label>
          <textarea
            value={edge.mechanism}
            onChange={e => update("mechanism", e.target.value)}
            placeholder="How does the source cause the target? e.g. 'crack spread transmission'"
            rows={3}
            className="px-2 py-1 bg-elevated border border-border rounded text-[12px] text-text-primary font-mono focus:border-amber focus:outline-none resize-y"
          />
        </div>

        {/* Lag */}
        <div className="flex flex-col gap-0.5">
          <label className="text-[10px] font-mono text-text-dim uppercase">Lag</label>
          <input
            value={edge.lag}
            onChange={e => update("lag", e.target.value)}
            placeholder="e.g. '1-2 weeks', 'immediate'"
            className="px-2 py-1 bg-elevated border border-border rounded text-[12px] text-text-primary font-mono focus:border-amber focus:outline-none"
          />
        </div>

        {/* Strength */}
        <div className="flex flex-col gap-0.5">
          <label className="text-[10px] font-mono text-text-dim uppercase">
            Strength: {edge.strength.toFixed(2)}
          </label>
          <input
            type="range"
            min="0" max="1" step="0.05"
            value={edge.strength}
            onChange={e => update("strength", parseFloat(e.target.value))}
            className="w-full accent-amber"
          />
          <div className="flex justify-between text-[9px] font-mono text-text-dim">
            <span>Weak (0)</span>
            <span>Strong (1)</span>
          </div>
        </div>

        {/* Strength visual hint */}
        <div className="p-2 bg-surface rounded border border-border">
          <div className="text-[10px] font-mono text-text-dim mb-1">Edge rendering</div>
          <div className="flex items-center gap-2">
            <div className="flex-1 h-px" style={{
              borderTop: edge.strength < 0.5 ? "2px dashed #525252" : `2px solid #525252`,
              opacity: 0.4 + edge.strength * 0.6,
            }} />
            <span className="text-[10px] font-mono text-text-muted">
              {edge.strength < 0.3 ? "weak" : edge.strength < 0.7 ? "moderate" : "strong"}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
