// MetaEditor — thesis metadata bar (title, claim, budget, date).

import type { BuilderMeta } from "../../lib/types";

interface Props {
  meta: BuilderMeta;
  onChange: (updated: BuilderMeta) => void;
}

export default function MetaEditor({ meta, onChange }: Props) {
  const update = <K extends keyof BuilderMeta>(key: K, value: BuilderMeta[K]) =>
    onChange({ ...meta, [key]: value });

  return (
    <div className="flex items-center gap-3 px-3 py-1.5 bg-surface border-b border-border overflow-x-auto">
      <input
        value={meta.title}
        onChange={e => update("title", e.target.value)}
        placeholder="Thesis title..."
        className="flex-1 min-w-[200px] px-2 py-1 bg-elevated border border-border rounded text-[13px] text-text-primary font-semibold focus:border-amber focus:outline-none"
      />
      <input
        value={meta.claim}
        onChange={e => update("claim", e.target.value)}
        placeholder="Core claim / hypothesis..."
        className="flex-[2] min-w-[300px] px-2 py-1 bg-elevated border border-border rounded text-[12px] text-text-primary font-mono focus:border-amber focus:outline-none"
      />
      <div className="flex items-center gap-1">
        <span className="text-[10px] font-mono text-text-dim">$</span>
        <input
          type="number"
          value={meta.monthlyBudget}
          onChange={e => update("monthlyBudget", parseInt(e.target.value) || 0)}
          className="w-20 px-2 py-1 bg-elevated border border-border rounded text-[12px] text-text-primary font-mono focus:border-amber focus:outline-none"
          placeholder="Budget"
        />
        <span className="text-[10px] font-mono text-text-dim">/mo</span>
      </div>
      <input
        type="date"
        value={meta.asOf}
        onChange={e => update("asOf", e.target.value)}
        className="px-2 py-1 bg-elevated border border-border rounded text-[12px] text-text-primary font-mono focus:border-amber focus:outline-none"
      />
    </div>
  );
}
