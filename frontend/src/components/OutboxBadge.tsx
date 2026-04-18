// OutboxBadge — top-bar pill showing the count of snapshots queued for retry
// in the dialectic outbox. Hidden when nothing is queued (no information,
// no chrome). Color-graded by severity:
//
//   1..9    queued -> amber-dim (informational backlog, normal during a blip)
//   10..99  queued -> amber       (notable; multi-cron-cycle outage)
//   100+    queued -> danger      (something is wrong; investigate)
//
// Polls every 60s while mounted, pauses while the tab is hidden, and
// immediately refetches on tab refocus to give the operator current data
// the moment they look at the dashboard.

import { useCallback, useEffect, useRef, useState } from "react";
import { Inbox, Loader2 } from "lucide-react";
import { fetchOutboxStatus, replayOutbox } from "../lib/api";
import type { OutboxStatus } from "../lib/outbox";
import { useToast } from "./Toast";

const POLL_MS = 60_000;

type Severity = "info" | "warn" | "danger";

function classify(queued: number): Severity {
  if (queued >= 100) return "danger";
  if (queued >= 10) return "warn";
  return "info";
}

function relativeAge(iso: string | null): string {
  if (!iso) return "—";
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "—";
  const sec = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h ago`;
  return `${Math.round(sec / 86400)}d ago`;
}

export default function OutboxBadge() {
  const [status, setStatus] = useState<OutboxStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [draining, setDraining] = useState(false);
  const popoverRef = useRef<HTMLDivElement | null>(null);
  const { toast } = useToast();

  const load = useCallback(async () => {
    try {
      const data = await fetchOutboxStatus();
      setStatus(data);
    } catch {
      // WHY: silently degrade. The badge is informational; if the endpoint
      // is unreachable the connection dot will already be screaming.
    }
  }, []);

  // WHY: extracted so the warning-toast Retry action can re-fire the same
  // drain without duplicating the success/partial/failure switch-case.
  const drain = useCallback(async () => {
    setDraining(true);
    try {
      const result = await replayOutbox();
      // Refetch immediately so the badge reflects the post-drain count
      // even if the next 60s poll hasn't fired yet.
      await load();
      if (result.remaining === 0 && result.replayed >= 0) {
        const n = result.replayed;
        toast(
          n === 0
            ? "Outbox already empty"
            : `Drained ${n} snapshot${n === 1 ? "" : "s"}`,
          "success",
        );
      } else {
        toast(
          `Drained ${result.replayed}, ${result.remaining} still queued — ${result.dialecticUrl} unreachable?`,
          {
            type: "warning",
            action: { label: "Retry", onClick: () => { void drain(); } },
          },
        );
      }
    } catch {
      toast("Drain failed", "error");
    } finally {
      setDraining(false);
    }
  }, [load, toast]);

  useEffect(() => {
    load();
    const interval = setInterval(() => {
      // Don't poll while the tab is hidden — operators get a fresh fetch
      // immediately on refocus via the visibilitychange handler below.
      if (!document.hidden) load();
    }, POLL_MS);

    function onVisible() {
      if (!document.hidden) load();
    }
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [load]);

  // Click-outside close for the popover.
  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      const node = popoverRef.current;
      if (node && !node.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    window.addEventListener("mousedown", onClick);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onClick);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!status || status.queued === 0) return null;

  const severity = classify(status.queued);
  const palette =
    severity === "danger"
      ? "bg-danger/20 text-danger border-danger/30 animate-pulse-danger"
      : severity === "warn"
      ? "bg-warning/20 text-warning border-warning/30"
      : "bg-amber-dim/15 text-amber-dim border-amber-dim/30";

  const rooms = Object.entries(status.byRoom).sort((a, b) => b[1] - a[1]);
  const oldestLabel = relativeAge(status.oldest);

  return (
    <div className="relative inline-flex" ref={popoverRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label={`${status.queued} snapshot${status.queued === 1 ? "" : "s"} queued for retry`}
        aria-haspopup="dialog"
        aria-expanded={open}
        title={`${status.queued} queued · oldest ${oldestLabel}`}
        className={`inline-flex items-center gap-1 px-1.5 py-px rounded border text-[9px] font-mono uppercase tracking-wide ${palette}`}
      >
        <Inbox size={10} aria-hidden="true" />
        <span>{status.queued}</span>
        <span className="hidden sm:inline">queued</span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Outbox queue detail"
          className="absolute right-0 top-full mt-1 z-40 bg-surface border border-border rounded shadow-2xl w-64 animate-fade-in"
        >
          <div className="px-2 py-1 border-b border-border flex items-center justify-between">
            <span className="font-mono text-[10px] text-amber font-semibold uppercase tracking-widest">
              Outbox
            </span>
            <span className="font-mono text-[9px] text-text-dim">
              cap {status.replayCap}
            </span>
          </div>
          <div className="px-2 py-1.5 text-[10px] font-mono text-text-muted space-y-0.5">
            <div className="flex justify-between">
              <span className="text-text-dim">queued</span>
              <span className="text-text-primary">{status.queued}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-dim">oldest</span>
              <span className="text-text-primary">{oldestLabel}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-dim">newest</span>
              <span className="text-text-primary">{relativeAge(status.newest)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-dim">size</span>
              <span className="text-text-primary">{(status.totalBytes / 1024).toFixed(1)} KiB</span>
            </div>
          </div>
          {rooms.length > 0 && (
            <div className="border-t border-border px-2 py-1">
              <div className="text-[9px] uppercase tracking-widest text-text-dim font-mono mb-0.5">
                By room
              </div>
              <ul className="space-y-px">
                {rooms.map(([room, count]) => (
                  <li
                    key={room}
                    className="flex justify-between text-[10px] font-mono text-text-muted"
                  >
                    <span className="truncate max-w-[18ch]" title={room}>
                      {room.length > 18 ? `${room.slice(0, 8)}…` : room}
                    </span>
                    <span className="text-text-primary">{count}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="px-2 py-1 border-t border-border text-[9px] font-mono text-text-dim">
            Snapshots replay on the next push.
          </div>
          {status.queued > 0 && (
            <div className="px-2 py-1.5 border-t border-border">
              <button
                type="button"
                onClick={() => { void drain(); }}
                disabled={draining}
                aria-label="Drain queued snapshots now"
                aria-disabled={draining}
                className="w-full inline-flex items-center justify-center gap-1.5 px-2 py-1 rounded border border-amber/40 bg-amber/10 text-amber text-[10px] font-mono uppercase tracking-wide hover:bg-amber/20 disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {draining ? (
                  <>
                    <Loader2 size={10} className="animate-spin" aria-hidden="true" />
                    <span>Draining…</span>
                  </>
                ) : (
                  <>
                    <Inbox size={10} aria-hidden="true" />
                    <span>Drain now</span>
                  </>
                )}
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
