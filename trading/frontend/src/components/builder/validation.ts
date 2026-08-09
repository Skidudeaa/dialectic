// Pre-save validation for builder books.
//
// The backend writes whatever it gets; the engine then rejects it on the
// next --dry-run. Catching structural issues here gives faster feedback
// and keeps disk state consistent.

import type { BuilderBook } from "../../lib/types";

export interface ValidationIssue {
  severity: "error" | "warning";
  scope: "node" | "edge" | "scenario" | "meta";
  ref?: string; // node id, edge "src→tgt", scenario id
  message: string;
}

export function validateBook(book: BuilderBook): ValidationIssue[] {
  const issues: ValidationIssue[] = [];
  const nodeIds = new Set<string>();
  const dupIds = new Set<string>();

  // Node checks
  for (const n of book.nodes) {
    if (!n.id || !n.id.trim()) {
      issues.push({ severity: "error", scope: "node", message: "Node has empty id" });
      continue;
    }
    if (nodeIds.has(n.id)) {
      dupIds.add(n.id);
    }
    nodeIds.add(n.id);
    if (!n.label || !n.label.trim()) {
      issues.push({
        severity: "warning",
        scope: "node",
        ref: n.id,
        message: `Node "${n.id}" has no label`,
      });
    }
    // Engine ID convention: lowercase, alphanum + dash/underscore
    if (!/^[a-z0-9][a-z0-9_-]*$/.test(n.id)) {
      issues.push({
        severity: "error",
        scope: "node",
        ref: n.id,
        message: `Node id "${n.id}" must be lowercase, start with alphanum, and contain only [a-z0-9_-]`,
      });
    }
    // Gated-by references must exist
    for (const g of n.gatedBy || []) {
      if (g && !book.nodes.some(other => other.id === g)) {
        issues.push({
          severity: "error",
          scope: "node",
          ref: n.id,
          message: `Node "${n.id}" gatedBy missing node "${g}"`,
        });
      }
    }
  }
  for (const dup of dupIds) {
    issues.push({
      severity: "error",
      scope: "node",
      ref: dup,
      message: `Duplicate node id "${dup}"`,
    });
  }

  // Edge checks — orphan endpoints + self-loops
  for (const e of book.edges) {
    const ref = `${e.source}→${e.target}`;
    if (!nodeIds.has(e.source)) {
      issues.push({
        severity: "error",
        scope: "edge",
        ref,
        message: `Edge source "${e.source}" missing from nodes`,
      });
    }
    if (!nodeIds.has(e.target)) {
      issues.push({
        severity: "error",
        scope: "edge",
        ref,
        message: `Edge target "${e.target}" missing from nodes`,
      });
    }
    if (e.source === e.target) {
      issues.push({
        severity: "error",
        scope: "edge",
        ref,
        message: `Self-loop on "${e.source}"`,
      });
    }
  }

  // Scenario overrides referencing missing nodes
  for (const s of book.scenarios) {
    for (const k of Object.keys(s.overrides || {})) {
      if (!nodeIds.has(k)) {
        issues.push({
          severity: "error",
          scope: "scenario",
          ref: s.id,
          message: `Scenario "${s.name || s.id}" overrides missing node "${k}"`,
        });
      }
    }
    if (s.probability < 0 || s.probability > 1) {
      issues.push({
        severity: "warning",
        scope: "scenario",
        ref: s.id,
        message: `Scenario "${s.name || s.id}" probability ${s.probability} outside [0,1]`,
      });
    }
  }

  // Meta
  if (!book.meta.title.trim()) {
    issues.push({
      severity: "error",
      scope: "meta",
      message: "Title is required",
    });
  }

  return issues;
}

export function hasErrors(issues: ValidationIssue[]): boolean {
  return issues.some(i => i.severity === "error");
}
