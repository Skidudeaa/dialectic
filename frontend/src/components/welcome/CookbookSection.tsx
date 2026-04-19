import { useMemo, useState } from "react";
import { ChefHat } from "lucide-react";
import { RECIPES, type RecipeSurface } from "../../lib/welcome";
import RecipeCard from "./RecipeCard";

// CookbookSection — recipe gallery grouped by surface, with a filter rail
// at the top. The filter is a simple chip row, not a dropdown — five
// options, one click, no hidden state.
//
// We render the chips as buttons with aria-pressed so screen readers
// announce the active filter. "ALL" is always present.

const SURFACES: readonly { key: RecipeSurface | "ALL"; label: string }[] = [
  { key: "ALL", label: "all" },
  { key: "CHAT", label: "chat" },
  { key: "THESIS", label: "thesis" },
  { key: "TV", label: "tv" },
  { key: "BUILDER", label: "builder" },
  { key: "OUTCOMES", label: "outcomes" },
] as const;

export default function CookbookSection() {
  const [filter, setFilter] = useState<RecipeSurface | "ALL">("ALL");

  const visible = useMemo(
    () =>
      filter === "ALL" ? RECIPES : RECIPES.filter((r) => r.surface === filter),
    [filter],
  );

  // Per-surface counts feed the chip labels, so the user knows what's
  // about to be filtered before they click.
  const counts = useMemo(() => {
    const c: Record<string, number> = { ALL: RECIPES.length };
    for (const r of RECIPES) c[r.surface] = (c[r.surface] ?? 0) + 1;
    return c;
  }, []);

  return (
    <section id="cookbook" aria-labelledby="cookbook-title">
      <div className="flex items-center gap-2 mb-2">
        <ChefHat size={16} className="text-amber" aria-hidden="true" />
        <h2 id="cookbook-title" className="font-mono text-2xl text-text-primary">
          Cookbook
        </h2>
      </div>
      <p className="text-sm text-text-muted max-w-2xl mb-4">
        Recipes the desk eats well. Lift the snippet, paste it into the right
        surface, watch it work. All examples use real books, real bindings,
        real slash commands.
      </p>

      {/* Filter chips — keyboard accessible, aria-pressed, no JS framework
          beyond useState. */}
      <div
        role="group"
        aria-label="Filter recipes by surface"
        className="flex flex-wrap gap-1.5 mb-4"
      >
        {SURFACES.map((s) => {
          const active = s.key === filter;
          return (
            <button
              key={s.key}
              type="button"
              onClick={() => setFilter(s.key)}
              aria-pressed={active}
              className={[
                "px-2 py-0.5 rounded text-[11px] font-mono uppercase tracking-wider border transition-colors",
                active
                  ? "border-amber/60 bg-amber/15 text-amber"
                  : "border-border bg-surface text-text-muted hover:text-text-primary hover:border-text-dim",
              ].join(" ")}
            >
              {s.label}
              <span className="ml-1 text-text-dim">{counts[s.key] ?? 0}</span>
            </button>
          );
        })}
      </div>

      <div className="grid md:grid-cols-2 gap-3">
        {visible.map((r) => (
          <RecipeCard key={r.id} recipe={r} />
        ))}
      </div>
    </section>
  );
}
