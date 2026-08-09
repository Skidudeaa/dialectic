// RulesEditor — edit the trading rules list.

import { Plus, X, GripVertical } from "lucide-react";

interface Props {
  rules: string[];
  onChange: (rules: string[]) => void;
}

export default function RulesEditor({ rules, onChange }: Props) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-mono text-text-muted uppercase">Trading Rules</span>
        <button
          onClick={() => onChange([...rules, ""])}
          className="flex items-center gap-1 text-[11px] font-mono text-amber hover:text-text-primary"
        >
          <Plus size={12} /> Add
        </button>
      </div>

      {rules.length === 0 && (
        <div className="text-[11px] font-mono text-text-dim py-2">
          No rules yet. Add position sizing limits, review cadence, de-escalation protocols.
        </div>
      )}

      {rules.map((rule, i) => (
        <div key={i} className="flex items-start gap-1">
          <GripVertical size={12} className="text-text-dim mt-1.5 shrink-0" />
          <textarea
            value={rule}
            onChange={e => {
              const updated = [...rules];
              updated[i] = e.target.value;
              onChange(updated);
            }}
            rows={2}
            className="flex-1 px-2 py-1 bg-elevated border border-border rounded text-[12px] text-text-primary font-mono focus:border-amber focus:outline-none resize-y"
            placeholder="e.g. Never deploy > 1/3 SGOV on one signal"
          />
          <button
            onClick={() => onChange(rules.filter((_, j) => j !== i))}
            className="p-0.5 text-text-dim hover:text-danger mt-1"
          >
            <X size={12} />
          </button>
        </div>
      ))}
    </div>
  );
}
