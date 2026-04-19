// Step 6 — Integrations.
//
// Surfaces the parts of the system the user doesn't *touch* but should know
// exist: Dialectic curator, outbox queue, future native clients.

import StepFrame from "../StepFrame";
import TryThis from "../TryThis";
import { Cloud, Inbox, Smartphone, MessageSquare } from "lucide-react";

function IntegrationGrid() {
  const items = [
    {
      icon: <MessageSquare size={14} className="text-amber" />,
      title: "Dialectic",
      body: "Curator alerts when you're offline. pgvector memory across sessions.",
      meta: "localhost:8002",
    },
    {
      icon: <Inbox size={14} className="text-teal" />,
      title: "Outbox",
      body: "Failed pushes queue locally and replay automatically.",
      meta: "/api/bridge/outbox",
    },
    {
      icon: <Cloud size={14} className="text-blue" />,
      title: "Bridge",
      body: "run-all.py orchestrates fetch → diff → push for every book.",
      meta: "cron Mon/Wed/Fri",
    },
    {
      icon: <Smartphone size={14} className="text-purple" />,
      title: "Native clients",
      body: "iOS / Android / macOS / Windows on the roadmap.",
      meta: "soon",
    },
  ];
  return (
    <div className="grid grid-cols-2 gap-2">
      {items.map((it) => (
        <div
          key={it.title}
          className="bg-surface rounded p-2 border border-border/60"
        >
          <div className="flex items-center gap-1.5 mb-1">
            {it.icon}
            <span className="font-mono text-[11px] text-text-primary font-medium">
              {it.title}
            </span>
          </div>
          <p className="text-[10px] text-text-muted leading-snug">{it.body}</p>
          <div className="mt-1 text-[9px] font-mono text-text-dim">{it.meta}</div>
        </div>
      ))}
    </div>
  );
}

export default function IntegrationsStep() {
  return (
    <StepFrame
      title="The plumbing that keeps the desk honest while you sleep."
      lede={
        <>
          Trading Desk doesn't live in isolation. Snapshots flow out to
          Dialectic for asynchronous discussion, the outbox guarantees you
          never lose a push, and the bridge keeps every book current.
        </>
      }
      illustration={<IntegrationGrid />}
      bullets={[
        {
          title: "Dialectic mirrors your thesis",
          body: "Every push lands as structured context in a Dialectic room — the curator can wake you when something material moves.",
        },
        {
          title: "Outbox is your safety net",
          body: "If a push fails, it queues. The badge in the top bar shows queued count; click Drain Now to retry.",
        },
        {
          title: "Bridge runs three days a week",
          body: "Cron at 08:00 Mon/Wed/Fri fetches fresh data, diffs against last snapshot, and pushes only on changes.",
        },
      ]}
      tryThis={
        <TryThis
          intro={
            <>
              When the OutboxBadge in the top bar shows queued pushes,
              click <span className="font-mono text-amber">Drain</span>{" "}
              in its popover — or hit the endpoint directly from a
              terminal.
            </>
          }
          snippets={[
            {
              label: "Drain the outbox queue",
              text: "curl -X POST -H \"Authorization: Bearer $TD_JWT\" http://167.99.113.232:8000/api/bridge/outbox/replay",
              caption: "Retries every queued push; returns the count delivered + the count still failing.",
              ariaLabel: "Copy curl command to drain the outbox",
            },
            {
              label: "Force a full pipeline run for one book",
              text: "DIALECTIC_ROOM_TOKEN=$TOKEN python3 tools/bridge/run-all.py --books books/iran-hormuz-graph.json",
              caption: "Fetch → snapshot → diff → push, end-to-end. Useful right after editing a book.",
              ariaLabel: "Copy run-all command for iran-hormuz",
            },
          ]}
        />
      }
    />
  );
}
