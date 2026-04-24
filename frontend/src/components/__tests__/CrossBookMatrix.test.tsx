// CrossBookMatrix tests — shape coverage:
//   1. renders a row per book
//   2. dot color reflects worst node state across the snapshot
//   3. clicking a row calls onSelect with that book id
//   4. empty bookStates dict does not crash (graceful degrade)

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

import CrossBookMatrix from "../CrossBookMatrix";
import * as api from "../../lib/api";
import type { ThesisBook, ThesisState } from "../../lib/types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const sampleBooks: ThesisBook[] = [
  { id: "iran-hormuz-graph", filename: "iran-hormuz-graph.json", title: "Iran/Hormuz", nodes: 16, edges: 14 },
  { id: "trump-tariffs-graph", filename: "trump-tariffs-graph.json", title: "Trump tariffs", nodes: 15, edges: 18 },
  { id: "ai-capex-unwind-graph", filename: "ai-capex-unwind-graph.json", title: "AI capex unwind", nodes: 12, edges: 10 },
];

function makeState(
  partial: Partial<ThesisState> & { nodeStates: Record<string, string> },
): ThesisState {
  return {
    v: 2,
    timestamp: new Date().toISOString(),
    title: "Test",
    nodeStates: partial.nodeStates,
    confluenceScores: partial.confluenceScores ?? {},
    cascadePhase: partial.cascadePhase ?? { number: 1, key: "shock", status: "MONITORING" },
    countdowns: partial.countdowns ?? [],
    marketSnapshot: partial.marketSnapshot ?? {},
    scenarioImpacts: partial.scenarioImpacts ?? {},
    portfolioSummary: partial.portfolioSummary ?? {},
  };
}

function mockEmptyTrades() {
  return vi.spyOn(api, "apiFetch").mockResolvedValue([]);
}

describe("CrossBookMatrix", () => {
  it("renders one row per book", async () => {
    mockEmptyTrades();
    render(
      <CrossBookMatrix
        books={sampleBooks}
        bookStates={{}}
        activeBookId={null}
        onSelect={() => {}}
      />,
    );

    // Wait for the trades fetch to settle and the table to render.
    await waitFor(() => {
      for (const b of sampleBooks) {
        expect(screen.getByTestId(`matrix-row-${b.id}`)).toBeTruthy();
      }
    });
  });

  it("dot color reflects worst node state across the snapshot", async () => {
    mockEmptyTrades();
    const states: Record<string, ThesisState> = {
      "iran-hormuz-graph": makeState({
        nodeStates: { hormuz: "fired", brent: "stable" },
      }),
      "trump-tariffs-graph": makeState({
        nodeStates: { tariff: "approaching", spy: "stable" },
      }),
      "ai-capex-unwind-graph": makeState({
        nodeStates: { nvda: "stable", capex: "stable" },
      }),
    };

    render(
      <CrossBookMatrix
        books={sampleBooks}
        bookStates={states}
        activeBookId={null}
        onSelect={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("matrix-row-iran-hormuz-graph")).toBeTruthy();
    });

    const firedRow = screen.getByTestId("matrix-row-iran-hormuz-graph");
    const approachingRow = screen.getByTestId("matrix-row-trump-tariffs-graph");
    const stableRow = screen.getByTestId("matrix-row-ai-capex-unwind-graph");

    // The state dot is the first child <span> with the bg-* color class.
    expect(firedRow.innerHTML).toContain("bg-danger");
    expect(approachingRow.innerHTML).toContain("bg-amber");
    expect(stableRow.innerHTML).toContain("bg-teal");
  });

  it("clicking a row calls onSelect with that book id", async () => {
    mockEmptyTrades();
    const onSelect = vi.fn();
    render(
      <CrossBookMatrix
        books={sampleBooks}
        bookStates={{}}
        activeBookId={null}
        onSelect={onSelect}
      />,
    );

    const row = await screen.findByTestId("matrix-row-trump-tariffs-graph");
    fireEvent.click(row);
    expect(onSelect).toHaveBeenCalledWith("trump-tariffs-graph");
  });

  it("empty bookStates does not crash and renders no-data dots", async () => {
    mockEmptyTrades();
    const { container } = render(
      <CrossBookMatrix
        books={sampleBooks}
        bookStates={{}}
        activeBookId={null}
        onSelect={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("cross-book-matrix")).toBeTruthy();
    });
    // All three rows still rendered, with the muted no-data dot color.
    expect(container.querySelectorAll('[data-testid^="matrix-row-"]').length).toBe(3);
    expect(container.innerHTML).toContain("bg-text-dim/40");
  });

  it("highlights the active book row", async () => {
    mockEmptyTrades();
    render(
      <CrossBookMatrix
        books={sampleBooks}
        bookStates={{}}
        activeBookId="trump-tariffs-graph"
        onSelect={() => {}}
      />,
    );

    const activeRow = await screen.findByTestId("matrix-row-trump-tariffs-graph");
    expect(activeRow.className).toContain("text-amber");
  });
});
