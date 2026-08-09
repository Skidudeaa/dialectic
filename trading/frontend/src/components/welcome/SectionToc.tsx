import { useEffect, useState } from "react";
import { WELCOME_SECTIONS } from "../../lib/welcome";

// SectionToc — sticky left-rail table of contents that highlights the
// current section as the user scrolls. Uses IntersectionObserver against
// the section ids defined in WELCOME_SECTIONS. Falls back to the first
// section if nothing intersects (initial mount).

export default function SectionToc() {
  const [active, setActive] = useState<string>(WELCOME_SECTIONS[0].id);

  useEffect(() => {
    const ids = WELCOME_SECTIONS.map((s) => s.id);
    const elements = ids
      .map((id) => document.getElementById(id))
      .filter((el): el is HTMLElement => el !== null);

    if (elements.length === 0) return;

    // Guard for environments (jsdom in tests) that don't ship an
    // IntersectionObserver. The TOC simply stays anchored on the first
    // section in that case — links still work, no crash.
    if (typeof IntersectionObserver === "undefined") return;

    const observer = new IntersectionObserver(
      (entries) => {
        // Prefer the topmost intersecting section.
        const visible = entries
          .filter((e) => e.isIntersecting)
          .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (visible[0]?.target.id) {
          setActive(visible[0].target.id);
        }
      },
      // rootMargin pulls the activation line ~120px down from the top
      // so a heading that's just scrolled into view becomes "current".
      { rootMargin: "-120px 0px -65% 0px", threshold: 0.01 },
    );

    for (const el of elements) observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <nav
      aria-label="Page sections"
      className="sticky top-6 hidden lg:block w-44 shrink-0"
    >
      <div className="text-[10px] uppercase tracking-widest text-text-dim font-mono mb-2">
        On this page
      </div>
      <ul className="space-y-1 border-l border-border pl-3">
        {WELCOME_SECTIONS.map((s) => {
          const isActive = s.id === active;
          return (
            <li key={s.id}>
              <a
                href={`#${s.id}`}
                aria-current={isActive ? "true" : undefined}
                className={[
                  "block text-xs py-0.5 transition-colors",
                  isActive
                    ? "text-amber font-medium"
                    : "text-text-muted hover:text-text-primary",
                ].join(" ")}
              >
                {s.label}
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
