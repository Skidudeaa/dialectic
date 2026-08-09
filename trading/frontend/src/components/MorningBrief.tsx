import { useState, useEffect, useMemo, type ReactNode } from "react";
import { RefreshCw, Sunrise, Copy, Check } from "lucide-react";
import { apiFetch } from "../lib/api";

const FIRED = /\b(fired|breach(?:ed)?|triggered|crisis|recession|shock)\b/i;
const APPROACHING = /\b(approaching|elevated|rising|warning|near|imminent)\b/i;
const STALE = /\b(stale|stable|monitoring|baseline|quiet|nominal)\b/i;

function colorize(text: string): ReactNode {
  // Highlight the canonical keywords without restructuring the line.
  const tokens = text.split(/(\s+)/);
  return tokens.map((tok, i) => {
    if (FIRED.test(tok)) return <span key={i} className="text-danger font-bold">{tok}</span>;
    if (APPROACHING.test(tok)) return <span key={i} className="text-amber font-bold">{tok}</span>;
    if (STALE.test(tok)) return <span key={i} className="text-teal">{tok}</span>;
    return <span key={i}>{tok}</span>;
  });
}

interface Block {
  kind: "header" | "subheader" | "bullet" | "blank" | "rule" | "text";
  raw: string;
}

function parseBrief(text: string): Block[] {
  return text.split(/\r?\n/).map<Block>((raw) => {
    const trimmed = raw.trim();
    if (trimmed === "") return { kind: "blank", raw };
    if (/^[=─-]{4,}$/.test(trimmed)) return { kind: "rule", raw };
    // ALL-CAPS standalone lines = headers (e.g. "MORNING BRIEF", "CROSS-BOOK FLAGS")
    if (
      /^[A-Z0-9][A-Z0-9 \-/&·:()]+$/.test(trimmed) &&
      trimmed.length >= 3 &&
      trimmed.length <= 60 &&
      !trimmed.endsWith(":")
    ) {
      return { kind: "header", raw };
    }
    // "Title:" lines as subheaders
    if (/^[A-Za-z][A-Za-z0-9 \-/]+:$/.test(trimmed) && trimmed.length <= 50) {
      return { kind: "subheader", raw };
    }
    if (/^[-*•·]\s+/.test(trimmed) || /^\d+[.)]\s+/.test(trimmed)) {
      return { kind: "bullet", raw };
    }
    return { kind: "text", raw };
  });
}

export default function MorningBrief() {
  const [brief, setBrief] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [generatedAt, setGeneratedAt] = useState<Date | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    loadBrief();
  }, []);

  async function loadBrief() {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch<{ brief: string }>("/api/outcomes/brief");
      setBrief(data.brief || "");
      setGeneratedAt(new Date());
    } catch {
      setError("Failed to load brief.");
      setBrief("");
    } finally {
      setLoading(false);
    }
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(brief);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* ignore */
    }
  }

  const blocks = useMemo(() => parseBrief(brief), [brief]);
  const isEmpty = !loading && !error && brief.trim().length === 0;

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between mb-1 shrink-0">
        <span className="text-[10px] text-text-dim font-medium uppercase tracking-widest">
          Morning Brief
        </span>
        <div className="flex items-center gap-1">
          {generatedAt && !error && (
            <span
              className="text-[9px] text-text-dim font-mono"
              title={generatedAt.toLocaleString()}
            >
              {generatedAt.toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
          )}
          <button
            onClick={copy}
            className="text-text-dim hover:text-amber p-0.5 disabled:opacity-30"
            disabled={!brief || loading}
            title="Copy brief"
            aria-label="Copy brief"
          >
            {copied ? <Check size={11} className="text-teal" /> : <Copy size={11} />}
          </button>
          <button
            onClick={loadBrief}
            className="text-text-dim hover:text-amber p-0.5"
            disabled={loading}
            title="Regenerate brief"
            aria-label="Regenerate brief"
          >
            <RefreshCw size={11} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      <div className="bg-elevated rounded p-2 overflow-y-auto flex-1 max-h-[calc(100vh-120px)]">
        {loading && !brief && (
          <div className="space-y-1.5 animate-pulse">
            <div className="h-3 w-32 bg-border rounded" />
            <div className="h-2 w-full bg-border/60 rounded" />
            <div className="h-2 w-5/6 bg-border/60 rounded" />
            <div className="h-2 w-full bg-border/60 rounded" />
            <div className="h-3 w-24 bg-border rounded mt-3" />
            <div className="h-2 w-full bg-border/60 rounded" />
            <div className="h-2 w-4/6 bg-border/60 rounded" />
          </div>
        )}

        {error && (
          <div className="text-[11px] text-danger font-mono">
            {error}{" "}
            <button onClick={loadBrief} className="underline ml-1 hover:text-amber">
              retry
            </button>
          </div>
        )}

        {isEmpty && (
          <div className="flex flex-col items-center text-center py-4 gap-1.5">
            <Sunrise size={20} className="text-text-dim" />
            <p className="text-[11px] text-text-primary leading-tight">
              No brief yet.
            </p>
            <p className="text-[10px] text-text-dim leading-tight max-w-[220px]">
              Generate a structured snapshot of today's thesis state, cross-book flags, and
              open trades to start your session.
            </p>
            <button onClick={loadBrief} className="btn-primary text-[10px] mt-1">
              Generate brief
            </button>
          </div>
        )}

        {!loading && !error && brief && (
          <div className="text-[11px] font-mono text-text-primary leading-snug">
            {blocks.map((b, i) => {
              if (b.kind === "blank")
                return <div key={i} className="h-1.5" aria-hidden />;
              if (b.kind === "rule")
                return <hr key={i} className="border-border my-1" />;
              if (b.kind === "header")
                return (
                  <div
                    key={i}
                    className="text-amber text-[10px] font-bold uppercase tracking-widest mt-2 first:mt-0 mb-0.5"
                  >
                    {b.raw.trim()}
                  </div>
                );
              if (b.kind === "subheader")
                return (
                  <div
                    key={i}
                    className="text-text-primary text-[11px] font-semibold mt-1.5 mb-0.5"
                  >
                    {colorize(b.raw)}
                  </div>
                );
              if (b.kind === "bullet")
                return (
                  <div key={i} className="flex gap-1 pl-1">
                    <span className="text-text-dim shrink-0">·</span>
                    <span className="flex-1">{colorize(b.raw.replace(/^[-*•·]\s+|^\d+[.)]\s+/, ""))}</span>
                  </div>
                );
              return (
                <div key={i} className="whitespace-pre-wrap">
                  {colorize(b.raw)}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
