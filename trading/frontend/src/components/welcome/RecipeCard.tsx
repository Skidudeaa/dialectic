import { useState } from "react";
import { Check, Copy } from "lucide-react";
import type { RecipeDef, RecipeSurface } from "../../lib/welcome";
import { useToast } from "../toast";

// RecipeCard — small dense card with title, surface badge, copyable
// snippet, and a one-line "why it matters". Designed to scan.
//
// Snippets are preserved verbatim with whitespace; the click target for
// copy is the icon button, but the whole code block is also tappable.

interface Props {
  recipe: RecipeDef;
}

// Surface → token color. Mirrors the existing badge palette so the page
// stays cohesive with the rest of the dashboard's color language.
const SURFACE_STYLES: Record<RecipeSurface, string> = {
  CHAT: "bg-amber/15 text-amber",
  THESIS: "bg-teal/15 text-teal",
  TV: "bg-purple/15 text-purple",
  BUILDER: "bg-blue/15 text-blue",
  OUTCOMES: "bg-green/15 text-green",
};

export default function RecipeCard({ recipe }: Props) {
  const [copied, setCopied] = useState(false);
  const { toast } = useToast();

  const onCopy = async () => {
    try {
      await navigator.clipboard.writeText(recipe.snippet);
      setCopied(true);
      toast("Copied to clipboard", "success");
      // Brief visual confirm; the toast does the heavy lifting.
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      toast("Copy failed — select the text manually", "error");
    }
  };

  const lang = recipe.lang ?? "text";

  return (
    <article className="bg-surface border border-border rounded-md p-3 flex flex-col gap-2 hover:border-text-dim transition-colors">
      <header className="flex items-center justify-between gap-2">
        <h3 className="font-mono text-[13px] text-text-primary truncate">
          {recipe.title}
        </h3>
        <span
          className={`badge shrink-0 ${SURFACE_STYLES[recipe.surface]}`}
          aria-label={`Surface: ${recipe.surface}`}
        >
          {recipe.surface}
        </span>
      </header>

      <div className="relative group">
        <pre
          className="bg-void border border-border rounded text-[11px] leading-relaxed font-mono text-text-primary p-2 pr-9 overflow-x-auto whitespace-pre"
          aria-label={`${lang} snippet`}
        >
          <code>{recipe.snippet}</code>
        </pre>
        <button
          type="button"
          onClick={onCopy}
          aria-label={`Copy ${recipe.title} snippet`}
          className="absolute top-1.5 right-1.5 p-1 rounded text-text-muted hover:text-amber hover:bg-elevated transition-colors"
        >
          {copied ? (
            <Check size={12} aria-hidden="true" />
          ) : (
            <Copy size={12} aria-hidden="true" />
          )}
        </button>
      </div>

      <p className="text-[11px] text-text-muted leading-relaxed">{recipe.why}</p>
    </article>
  );
}
