import { useState, useId } from "react";
import {
  Activity,
  GitBranch,
  Webhook,
  PenTool,
  MessagesSquare,
  Inbox,
  Bot,
  ChevronDown,
  type LucideIcon,
} from "lucide-react";
import type { FeatureDef } from "../../lib/welcome";

const ICONS: Record<string, LucideIcon> = {
  Activity,
  GitBranch,
  Webhook,
  PenTool,
  MessagesSquare,
  Inbox,
  Bot,
};

// FeatureCard — expandable card. Click the header (or the chevron) to
// reveal the bulleted detail; collapsed by default to keep the section
// scannable. Uses aria-expanded so screen readers announce the state.

interface Props {
  feature: FeatureDef;
}

export default function FeatureCard({ feature }: Props) {
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  const Icon = ICONS[feature.icon] ?? Activity;
  const isLive = feature.status === "live";

  return (
    <div
      className={[
        "bg-surface border rounded-md transition-colors",
        open ? "border-amber/40" : "border-border hover:border-text-dim",
      ].join(" ")}
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={detailsId}
        className="w-full text-left p-4 flex gap-3 items-start cursor-pointer"
      >
        <div
          className={[
            "shrink-0 w-9 h-9 rounded grid place-items-center",
            isLive ? "bg-amber/10 text-amber" : "bg-elevated text-text-muted",
          ].join(" ")}
          aria-hidden="true"
        >
          <Icon size={18} strokeWidth={1.5} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-sm font-semibold text-text-primary">{feature.title}</h3>
            <span
              className={
                isLive
                  ? "badge bg-green/15 text-green"
                  : "badge bg-elevated text-text-muted"
              }
            >
              {isLive ? "live" : "soon"}
            </span>
          </div>
          <p className="text-xs text-text-muted leading-relaxed">{feature.summary}</p>
        </div>
        <ChevronDown
          size={16}
          className={[
            "shrink-0 text-text-muted transition-transform mt-1",
            open ? "rotate-180" : "",
          ].join(" ")}
          aria-hidden="true"
        />
      </button>
      {open && (
        <div
          id={detailsId}
          className="px-4 pb-4 pl-16 -mt-1 animate-fade-in"
        >
          <ul className="space-y-1.5 text-xs text-text-primary border-l border-border pl-3">
            {feature.details.map((d) => (
              <li key={d} className="leading-relaxed">
                {d}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
