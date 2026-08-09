/**
 * Validation tests — pre-save structural checks for builder books.
 *
 * WHY: The backend writes whatever it gets; the engine then rejects
 * invalid books on next --dry-run. These checks catch the common mistakes
 * (orphan edges, dup IDs, bad scenario refs) before they hit disk.
 */

import { describe, it, expect } from "vitest";
import { validateBook, hasErrors } from "./validation";
import type { BuilderBook } from "../../lib/types";

function baseBook(): BuilderBook {
  return {
    meta: { title: "Test", claim: "", monthlyBudget: 1000, asOf: "2026-01-01" },
    nodes: [
      {
        id: "a", label: "A", type: "event", phase: 1, state: "monitoring",
        context: "", x: 0, y: 0, feeds: [], thresholds: [], indicators: [],
        countdown: false, irreversible: false, gatedBy: [],
      },
      {
        id: "b", label: "B", type: "price", phase: 2, state: "monitoring",
        context: "", x: 200, y: 0, feeds: [], thresholds: [], indicators: [],
        countdown: false, irreversible: false, gatedBy: [],
      },
    ],
    edges: [{ source: "a", target: "b", mechanism: "", lag: "", strength: 0.7 }],
    instruments: {},
    scenarios: [],
    cascadePhases: {},
    rules: [],
  };
}

describe("validateBook", () => {
  it("clean book yields no errors", () => {
    const issues = validateBook(baseBook());
    expect(hasErrors(issues)).toBe(false);
  });

  it("detects orphan edge source", () => {
    const book = baseBook();
    book.edges.push({ source: "ghost", target: "b", mechanism: "", lag: "", strength: 1 });
    const issues = validateBook(book);
    expect(hasErrors(issues)).toBe(true);
    expect(issues.some(i => i.message.includes("ghost"))).toBe(true);
  });

  it("detects orphan edge target", () => {
    const book = baseBook();
    book.edges.push({ source: "a", target: "ghost", mechanism: "", lag: "", strength: 1 });
    expect(hasErrors(validateBook(book))).toBe(true);
  });

  it("detects duplicate node ids", () => {
    const book = baseBook();
    book.nodes.push({ ...book.nodes[0] });
    const issues = validateBook(book);
    expect(issues.some(i => i.message.startsWith("Duplicate"))).toBe(true);
    expect(hasErrors(issues)).toBe(true);
  });

  it("detects self-loops", () => {
    const book = baseBook();
    book.edges.push({ source: "a", target: "a", mechanism: "", lag: "", strength: 1 });
    expect(validateBook(book).some(i => i.message.includes("Self-loop"))).toBe(true);
  });

  it("detects scenario overrides referencing missing nodes", () => {
    const book = baseBook();
    book.scenarios.push({
      id: "s1", name: "S1", probability: 0.5, notes: "",
      overrides: { ghost: "fired" }, portfolioImpact: {},
    });
    expect(hasErrors(validateBook(book))).toBe(true);
  });

  it("detects gatedBy references to missing nodes", () => {
    const book = baseBook();
    book.nodes[1].gatedBy = ["ghost"];
    expect(hasErrors(validateBook(book))).toBe(true);
  });

  it("rejects invalid node id format", () => {
    const book = baseBook();
    book.nodes.push({
      ...book.nodes[0], id: "Has Spaces", label: "X",
    });
    expect(hasErrors(validateBook(book))).toBe(true);
  });

  it("requires title", () => {
    const book = baseBook();
    book.meta.title = "   ";
    expect(hasErrors(validateBook(book))).toBe(true);
  });

  it("warns on probability outside [0,1] without erroring", () => {
    const book = baseBook();
    book.scenarios.push({
      id: "s1", name: "S1", probability: 1.5, notes: "",
      overrides: {}, portfolioImpact: {},
    });
    const issues = validateBook(book);
    expect(issues.some(i => i.severity === "warning" && i.message.includes("probability"))).toBe(true);
    expect(hasErrors(issues)).toBe(false);
  });
});
