// PredictionTracker tests — Phase 2 deep-surface authoring: the voided
// resolve path, the provenance badge, the server-scored Brier headline
// (replacing the old client-side MAE mislabeled as calibration), and the
// strict resolution_spec shape emitted on create. Mocks apiFetch so no
// real fetch runs.

import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, fireEvent, cleanup } from "@testing-library/react";

import PredictionTracker from "../PredictionTracker";
import * as api from "../../lib/api";
import type { Prediction } from "../../lib/types";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

function pred(overrides: Partial<Prediction> = {}): Prediction {
  return {
    id: "p1",
    user: "amo",
    statement: "XOP crosses 115",
    confidence: 0.7,
    deadline: "2099-01-01",
    resolution: null,
    resolved_at: null,
    resolution_notes: null,
    resolution_spec: null,
    linked_book_id: null,
    tags: [],
    source_type: "human",
    source_label: "amo",
    source_ref: null,
    base_rate: null,
    base_rate_source: null,
    confidence_history: [],
    created_at: "2026-08-17T00:00:00Z",
    ...overrides,
  };
}

function mockApi(predictions: Prediction[], brierScore: number | null = 0.18) {
  return vi.spyOn(api, "apiFetch").mockImplementation((async (
    path: string,
    init?: RequestInit,
  ) => {
    if (path === "/api/predictions/calibration") {
      return {
        calibration: [],
        total_predictions: predictions.length,
        total_correct: 0,
        brier_score: brierScore,
      };
    }
    if (path === "/api/predictions" && !init?.method) {
      return predictions;
    }
    return {};
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
  }) as any);
}

describe("PredictionTracker", () => {
  it("offers the voided resolution and posts it", async () => {
    const spy = mockApi([pred()]);
    render(<PredictionTracker />);
    const voidBtn = await screen.findByRole("button", { name: /mark voided/i });
    fireEvent.click(voidBtn);
    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith(
        "/api/predictions/p1/resolve",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ resolution: "voided" }),
        }),
      );
    });
  });

  it("shows a provenance badge only when the source differs from the user", async () => {
    mockApi([
      pred({ id: "p1", source_label: "Claude", source_type: "llm" }),
      pred({ id: "p2", statement: "own call", source_label: "amo" }),
    ]);
    render(<PredictionTracker />);
    await screen.findByText("XOP crosses 115");
    expect(screen.getByText("Claude")).toBeTruthy();
    // The self-authored row carries no badge (its label is its user).
    expect(screen.queryByText("amo")).toBeNull();
  });

  it("renders the server Brier, not a client-side recomputation", async () => {
    // Client MAE over this row would be |0.9 - 1| = 0.10; the server says
    // 0.42 — the headline must show the server's number.
    mockApi(
      [pred({ resolution: "correct", resolved_at: "2026-08-16T00:00:00Z", confidence: 0.9 })],
      0.42,
    );
    render(<PredictionTracker />);
    await screen.findByText(/Brier 0.42/);
    expect(screen.queryByText(/cal 0.10/)).toBeNull();
  });

  it("excludes voided rows from the accuracy denominator", async () => {
    mockApi([
      pred({ id: "p1", resolution: "correct", resolved_at: "2026-08-16T00:00:00Z" }),
      pred({ id: "p2", resolution: "voided", resolved_at: "2026-08-16T00:00:00Z" }),
    ]);
    render(<PredictionTracker />);
    // 1 correct of 1 scored (the voided row scores nowhere) — not 1 of 2.
    await screen.findByText("(1/1)");
    expect(screen.getByText("100%")).toBeTruthy();
  });

  it("marks spec-carrying open claims with the auto chip", async () => {
    mockApi([
      pred({
        resolution_spec: {
          kind: "price_cross",
          symbol: "XOP",
          comparator: "above",
          threshold: 115,
        },
      }),
    ]);
    render(<PredictionTracker />);
    const chip = await screen.findByText("auto");
    expect(chip.closest("span")?.getAttribute("title")).toContain("XOP above 115");
  });

  it("emits the exact strict price_cross spec shape on create", async () => {
    const spy = mockApi([]);
    render(<PredictionTracker />);
    await waitFor(() => expect(spy).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: /add prediction/i }));
    fireEvent.change(screen.getByPlaceholderText(/USD\/JPY/), {
      target: { value: "XOP closes above 115" },
    });
    fireEvent.change(screen.getByTitle("Deadline"), {
      target: { value: "2099-01-01" },
    });
    fireEvent.click(screen.getByRole("button", { name: "more" }));
    fireEvent.change(screen.getByLabelText("Auto-resolve kind"), {
      target: { value: "price_cross" },
    });
    fireEvent.change(screen.getByLabelText("Symbol"), {
      target: { value: "XOP" },
    });
    fireEvent.change(screen.getByLabelText("Threshold"), {
      target: { value: "115" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => {
      const post = spy.mock.calls.find(
        ([path, init]) => path === "/api/predictions" && init?.method === "POST",
      );
      expect(post).toBeTruthy();
      const body = JSON.parse(String(post![1]!.body));
      expect(body.resolution_spec).toEqual({
        kind: "price_cross",
        symbol: "XOP",
        comparator: "above",
        threshold: 115,
      });
    });
  });

  it("posts no resolution_spec when the kind stays manual", async () => {
    const spy = mockApi([]);
    render(<PredictionTracker />);
    await waitFor(() => expect(spy).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: /add prediction/i }));
    fireEvent.change(screen.getByPlaceholderText(/USD\/JPY/), {
      target: { value: "plain manual call" },
    });
    fireEvent.change(screen.getByTitle("Deadline"), {
      target: { value: "2099-01-01" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => {
      const post = spy.mock.calls.find(
        ([path, init]) => path === "/api/predictions" && init?.method === "POST",
      );
      expect(post).toBeTruthy();
      expect(JSON.parse(String(post![1]!.body))).not.toHaveProperty(
        "resolution_spec",
      );
    });
  });
});
