// TryThis — the "drop a concrete copyable thing in front of the user"
// footer block that every onboarding step uses.
//
// The original tour explained what each surface IS. This component is the
// fix for "explain what to actually PUT IN" — every step gets one (or more)
// snippets the user can copy with one click and paste into chat / a Pine
// alert / curl / etc.
//
// Visual treatment is intentionally distinct from the bullets above it:
// darker tint, mono font, amber TRY THIS label, per-snippet copy button.
// Multi-snippet steps stack vertically with thin dividers; each entry is
// independently copyable with its own toast.

import { useState, type ReactNode } from "react";
import { Copy, Check } from "lucide-react";

import { useToast } from "../toast";

export interface TryThisSnippet {
  /** The literal text to copy. Multi-line is fine. */
  text: string;
  /** Optional caption shown below the snippet (italic, muted). */
  caption?: ReactNode;
  /** Optional label above the snippet (e.g. "Pine alert recipe"). */
  label?: string;
  /** Aria label override for the copy button. */
  ariaLabel?: string;
  /** If true, render with `whitespace-pre` to preserve formatting. */
  multiline?: boolean;
}

interface Props {
  /** A single snippet, or a stack of snippets with thin dividers between. */
  snippets: TryThisSnippet[];
  /** Optional intro line shown above the snippets, inside the block. */
  intro?: ReactNode;
}

export default function TryThis({ snippets, intro }: Props) {
  return (
    <div
      className="mt-3 rounded border border-amber/20 bg-elevated/60 p-3"
      data-testid="onboarding-try-this"
    >
      <div className="text-amber font-mono text-[10px] tracking-widest uppercase">
        Try this
      </div>
      {intro && (
        <div className="mt-1.5 text-[11px] leading-relaxed text-text-muted">
          {intro}
        </div>
      )}
      <div className="mt-2 space-y-2">
        {snippets.map((s, i) => (
          <div
            key={i}
            className={
              i > 0
                ? "pt-2 border-t border-border/40"
                : ""
            }
          >
            <SnippetRow snippet={s} index={i} />
          </div>
        ))}
      </div>
    </div>
  );
}

function SnippetRow({ snippet, index }: { snippet: TryThisSnippet; index: number }) {
  const { toast } = useToast();
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    const text = snippet.text;
    let ok = false;
    try {
      // navigator.clipboard requires secure context — fall back if missing.
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        ok = true;
      } else {
        ok = legacyCopy(text);
      }
    } catch {
      ok = legacyCopy(text);
    }

    if (ok) {
      setCopied(true);
      toast("Copied to clipboard", "success");
      window.setTimeout(() => setCopied(false), 1000);
    } else {
      toast("Copy failed — select and copy manually", "error");
    }
  }

  const Icon = copied ? Check : Copy;
  const label = snippet.ariaLabel ?? `Copy snippet ${index + 1} to clipboard`;

  return (
    <div>
      {snippet.label && (
        <div className="mb-1 text-[9px] font-mono uppercase tracking-widest text-text-dim">
          {snippet.label}
        </div>
      )}
      <div className="flex items-start gap-1.5">
        <pre
          className={`flex-1 m-0 rounded bg-surface/80 border border-amber/20 px-2 py-1.5 font-mono text-[11px] leading-snug text-text-primary ${
            snippet.multiline ? "whitespace-pre overflow-x-auto" : "whitespace-pre-wrap break-words"
          }`}
        >
{snippet.text}
        </pre>
        <button
          type="button"
          onClick={handleCopy}
          aria-label={label}
          title={copied ? "Copied" : "Copy to clipboard"}
          className={`shrink-0 inline-flex items-center justify-center h-6 w-6 rounded border transition-colors ${
            copied
              ? "border-teal/40 bg-teal/10 text-teal"
              : "border-border bg-elevated/80 text-text-dim hover:text-amber hover:border-amber/40"
          }`}
        >
          <Icon size={11} aria-hidden="true" />
        </button>
      </div>
      {snippet.caption && (
        <div className="mt-1 text-[10px] italic text-text-muted leading-snug">
          {snippet.caption}
        </div>
      )}
    </div>
  );
}

/** execCommand fallback for non-secure-context / older browsers. */
function legacyCopy(text: string): boolean {
  try {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}
