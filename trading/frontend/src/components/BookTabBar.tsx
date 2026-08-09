// BookTabBar — persistent horizontal book tabs across the cockpit top.
//
// Why a tab bar (rather than the legacy <select>): with five live books,
// the analyst needs the worst-state book to be visible *before* they pick.
// Each tab carries a colored state dot (red=any node fired, amber=any
// approaching, teal=otherwise stable) so the eye lands on the hottest
// book without an extra click.
//
// State is supplied by the parent — this component pulls nothing on its
// own. That keeps it cheap to render in the header and lets the cross-book
// matrix share the same data.

import type { ThesisBook, ThesisState } from "../lib/types";
import { bookShortId, worstStateColor } from "../lib/bookState";

interface Props {
  books: ThesisBook[];
  activeBookId: string | null;
  bookStates: Record<string, ThesisState | null | undefined>;
  onSelect: (id: string) => void;
}

export default function BookTabBar({
  books,
  activeBookId,
  bookStates,
  onSelect,
}: Props) {
  if (!books.length) return null;

  return (
    <div
      className="flex items-stretch overflow-x-auto bg-surface border-b border-border shrink-0"
      role="tablist"
      aria-label="Thesis books"
    >
      {books.map((book, idx) => {
        const isActive = book.id === activeBookId;
        const dot = worstStateColor(bookStates[book.id]);
        const short = bookShortId(book.id);
        return (
          <button
            key={book.id}
            role="tab"
            aria-selected={isActive}
            aria-controls={`book-tab-panel-${book.id}`}
            tabIndex={isActive ? 0 : -1}
            onClick={() => onSelect(book.id)}
            title={`${book.title} (${dot.label})`}
            className={`group flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-mono whitespace-nowrap border-r border-border transition-colors ${
              isActive
                ? "text-amber bg-elevated border-b-2 border-b-teal -mb-px"
                : "text-text-muted hover:text-text-primary hover:bg-elevated/60"
            }`}
            data-testid={`book-tab-${book.id}`}
          >
            <span
              className={`inline-block w-1.5 h-1.5 rounded-full ${dot.cls}`}
              aria-hidden="true"
            />
            <span>{short}</span>
            {idx < 9 && (
              <span
                className="text-[8px] text-text-dim font-mono ml-0.5 hidden md:inline"
                aria-hidden="true"
              >
                {idx + 1}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
