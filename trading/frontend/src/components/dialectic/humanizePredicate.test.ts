import { describe, expect, it } from "vitest";
import { humanizePredicate } from "./data";

// The four shapes below are the four `kind` values lifecycle_monitor.Predicate
// can emit (tools/outcomes/lifecycle_monitor.py), with `description` copied
// from web/adapters/outcomes.py::_predicate_description — i.e. exactly what
// /api/v1/trades/{id}/predicates puts on the wire.

describe("humanizePredicate", () => {
  it("renders a state predicate as a sentence", () => {
    expect(humanizePredicate({
      kind: "state", description: "em-stress == fired",
      node_id: "em-stress", expected: "fired",
    })).toBe("em-stress stays fired");
  });

  it("renders a state_set predicate as a sentence", () => {
    expect(humanizePredicate({
      kind: "state_set", description: "brent in {approaching, fired}",
      node_id: "brent", allowed: ["approaching", "fired"],
    })).toBe("brent stays approaching or fired");
  });

  it("serialises three-or-more allowed states with an Oxford-less list", () => {
    expect(humanizePredicate({
      kind: "state_set", description: "x in {a, b, c}",
      node_id: "x", allowed: ["a", "b", "c"],
    })).toBe("x stays a, b or c");
  });

  it("unwraps a dotted confluence path", () => {
    expect(humanizePredicate({
      kind: "threshold", description: "confluenceScores.em-stress >= 1.6",
      path: "confluenceScores.em-stress", op: ">=", value: 1.6,
    })).toBe("confluence on em-stress holds at or above 1.6");
  });

  it("renders a countdown predicate as a deadline", () => {
    expect(humanizePredicate({
      kind: "countdown", description: "planting-miss countdown <= 14d",
      node_id: "planting-miss", op: "<=", days: 14,
    })).toBe("planting-miss lands within 14 days");
  });

  it("singularises a one-day countdown", () => {
    expect(humanizePredicate({
      kind: "countdown", description: "x countdown <= 1d",
      node_id: "x", op: "<=", days: 1,
    })).toBe("x lands within 1 day");
  });

  it("keeps the raw expression out of the sentence but never loses it", () => {
    // The rendered sentence must not leak the field path the redline objected
    // to; the caller puts `description` in title= instead.
    const raw = "confluenceScores.em-stress >= 1.6";
    const out = humanizePredicate({
      kind: "threshold", description: raw,
      path: "confluenceScores.em-stress", op: ">=", value: 1.6,
    });
    expect(out).not.toContain("confluenceScores.");
  });

  // ── degradation: an unreadable truth beats a confident invention ──
  it("falls back to the raw description on an unknown kind", () => {
    expect(humanizePredicate({
      kind: "spread", description: "some-new-shape ~= 3",
    })).toBe("some-new-shape ~= 3");
  });

  it("falls back when the structured fields are missing", () => {
    expect(humanizePredicate({
      kind: "threshold", description: "x >= 2", path: null, op: null, value: null,
    })).toBe("x >= 2");
  });

  it("falls back on an operator it has no words for", () => {
    expect(humanizePredicate({
      kind: "threshold", description: "x <=> 2",
      path: "x", op: "<=>", value: 2,
    })).toBe("x <=> 2");
  });

  it("never returns empty for a predicate that has any description", () => {
    for (const kind of ["state", "state_set", "threshold", "countdown", "??"]) {
      expect(humanizePredicate({ kind, description: "fallback text" })).toBe("fallback text");
    }
  });

  it("handles value 0 rather than treating it as absent", () => {
    expect(humanizePredicate({
      kind: "threshold", description: "spread > 0",
      path: "spread", op: ">", value: 0,
    })).toBe("spread holds above 0");
  });

  it("handles a 0-day countdown rather than treating it as absent", () => {
    expect(humanizePredicate({
      kind: "countdown", description: "x countdown <= 0d",
      node_id: "x", op: "<=", days: 0,
    })).toBe("x lands within 0 days");
  });
});
