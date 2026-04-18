// InstrumentEditor — instruments tied to a selected node.

import { Plus, X } from "lucide-react";
import type { BuilderInstrument } from "../../lib/types";

interface Props {
  nodeId: string;
  nodeLabel: string;
  instruments: BuilderInstrument[];
  onChange: (instruments: BuilderInstrument[]) => void;
}

function emptyInstrument(): BuilderInstrument {
  return { id: "", monthly: 0, role: "", beta: 0.5, ref: 0, targetLow: null, targetHigh: null, stop: null };
}

export default function InstrumentEditor({ nodeId, nodeLabel, instruments, onChange }: Props) {
  const updateInst = (idx: number, field: keyof BuilderInstrument, value: unknown) => {
    const updated = [...instruments];
    updated[idx] = { ...updated[idx], [field]: value };
    onChange(updated);
  };

  return (
    <div className="space-y-2" data-node-id={nodeId}>
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-mono text-text-muted uppercase">
          Instruments → {nodeLabel}
        </span>
        <button
          onClick={() => onChange([...instruments, emptyInstrument()])}
          className="flex items-center gap-1 text-[11px] font-mono text-amber hover:text-text-primary"
        >
          <Plus size={12} /> Add
        </button>
      </div>

      {instruments.length === 0 && (
        <div className="text-[11px] font-mono text-text-dim py-2">
          No instruments linked to this node yet.
        </div>
      )}

      {instruments.map((inst, i) => (
        <div key={i} className="p-2 bg-surface rounded border border-border space-y-1.5">
          <div className="flex items-center gap-1">
            <input
              value={inst.id}
              onChange={e => updateInst(i, "id", e.target.value.toUpperCase())}
              placeholder="TICKER"
              className="w-20 px-1.5 py-0.5 bg-elevated border border-border rounded text-[12px] text-amber font-mono font-semibold focus:border-amber focus:outline-none"
            />
            <input
              value={inst.role}
              onChange={e => updateInst(i, "role", e.target.value)}
              placeholder="Role description"
              className="flex-1 px-1.5 py-0.5 bg-elevated border border-border rounded text-[12px] text-text-primary font-mono focus:border-amber focus:outline-none"
            />
            <button
              onClick={() => onChange(instruments.filter((_, j) => j !== i))}
              className="p-0.5 text-text-dim hover:text-danger"
            >
              <X size={12} />
            </button>
          </div>
          <div className="grid grid-cols-5 gap-1">
            <div className="flex flex-col">
              <span className="text-[8px] font-mono text-text-dim">$/mo</span>
              <input type="number" value={inst.monthly || ""} onChange={e => updateInst(i, "monthly", parseInt(e.target.value) || 0)}
                className="px-1 py-0.5 bg-elevated border border-border rounded text-[11px] text-text-primary font-mono w-full" />
            </div>
            <div className="flex flex-col">
              <span className="text-[8px] font-mono text-text-dim">Beta</span>
              <input type="number" step="0.1" value={inst.beta || ""} onChange={e => updateInst(i, "beta", parseFloat(e.target.value) || 0)}
                className="px-1 py-0.5 bg-elevated border border-border rounded text-[11px] text-text-primary font-mono w-full" />
            </div>
            <div className="flex flex-col">
              <span className="text-[8px] font-mono text-text-dim">Ref</span>
              <input type="number" step="0.01" value={inst.ref || ""} onChange={e => updateInst(i, "ref", parseFloat(e.target.value) || 0)}
                className="px-1 py-0.5 bg-elevated border border-border rounded text-[11px] text-text-primary font-mono w-full" />
            </div>
            <div className="flex flex-col">
              <span className="text-[8px] font-mono text-text-dim">Target</span>
              <div className="flex gap-0.5">
                <input type="number" step="0.01" value={inst.targetLow ?? ""} onChange={e => updateInst(i, "targetLow", e.target.value ? parseFloat(e.target.value) : null)}
                  placeholder="Lo" className="px-1 py-0.5 bg-elevated border border-border rounded text-[11px] text-text-primary font-mono w-full" />
              </div>
            </div>
            <div className="flex flex-col">
              <span className="text-[8px] font-mono text-text-dim">Stop</span>
              <input type="number" step="0.01" value={inst.stop ?? ""} onChange={e => updateInst(i, "stop", e.target.value ? parseFloat(e.target.value) : null)}
                className="px-1 py-0.5 bg-elevated border border-border rounded text-[11px] text-text-primary font-mono w-full" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
