// Book presentation helpers shared by BookTabBar and CrossBookMatrix.
// Lives outside the component files so fast-refresh sees pure-component
// modules (react-refresh/only-export-components).

import type { ThesisState } from "./types";

/** Last segment of a kebab-cased id, with `-graph` stripped if present. */
export function bookShortId(id: string): string {
  const trimmed = id.replace(/-graph$/, "");
  const parts = trimmed.split("-").filter(Boolean);
  if (parts.length === 0) return id;
  return parts[parts.length - 1];
}

/** Worst node state across the snapshot dictates the dot color. */
export function worstStateColor(state: ThesisState | null | undefined): {
  cls: string;
  label: string;
} {
  if (!state || !state.nodeStates) {
    return { cls: "bg-text-dim/40", label: "no data" };
  }
  const values = Object.values(state.nodeStates);
  if (values.some((s) => s === "fired")) {
    return { cls: "bg-danger", label: "fired" };
  }
  if (values.some((s) => s === "approaching")) {
    return { cls: "bg-amber", label: "approaching" };
  }
  return { cls: "bg-teal", label: "stable" };
}
