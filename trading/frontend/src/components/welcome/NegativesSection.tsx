import { Ban } from "lucide-react";
import { NEGATIVES } from "../../lib/welcome";

// NegativesSection — "What this isn't". Five tight scope-setting lines.
// Icon + bold + dim continuation, no prose. The point is to be ignorable
// for the user who already knows, and clarifying for the user who
// doesn't.

export default function NegativesSection() {
  return (
    <section id="isnt" aria-labelledby="isnt-title">
      <div className="flex items-center gap-2 mb-2">
        <Ban size={16} className="text-text-dim" aria-hidden="true" />
        <h2 id="isnt-title" className="font-mono text-2xl text-text-primary">
          What it isn't
        </h2>
      </div>
      <p className="text-sm text-text-muted max-w-2xl mb-4">
        Sets scope. Saves an argument later.
      </p>
      <ul className="border border-border rounded-md bg-surface divide-y divide-border">
        {NEGATIVES.map((n) => (
          <li key={n.id} className="flex items-start gap-3 p-3">
            <Ban
              size={12}
              className="text-text-dim shrink-0 mt-1"
              aria-hidden="true"
            />
            <div className="min-w-0">
              <span className="text-sm font-semibold text-text-primary mr-2">
                {n.title}
              </span>
              <span className="text-xs text-text-muted">— {n.detail}</span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
