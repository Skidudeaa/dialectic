// NodeEditor — property panel for the selected node.
//
// All fields that matter for the thesis engine are editable here.
// Designed for speed: tab between fields, enter to confirm.

import { useState } from "react";
import {
  Trash2, Plus, X, ChevronDown, ChevronRight,
} from "lucide-react";
import type { BuilderNode, BuilderFeed, BuilderIndicator } from "../../lib/types";

interface Props {
  node: BuilderNode;
  allNodeIds: string[];
  onChange: (updated: BuilderNode) => void;
  onDelete: () => void;
}

const NODE_TYPES = [
  "event", "price", "indicator", "gate", "deadline",
  "conditional", "reversal", "constraint",
] as const;

const NODE_STATES = [
  "monitoring", "active", "fired", "approaching",
  "stable", "resolved", "partial",
] as const;

const FEED_SOURCES = [
  "yahoo", "polymarket", "fred", "eia", "bls", "usda", "manual",
] as const;

const INDICATOR_STATUSES = ["red", "amber", "green", "grey"] as const;

// ── Module-scope presentational components ────────────────────────────
// Declared outside NodeEditor so React doesn't allocate a fresh component
// type each render (which would reset state and trip react-hooks/static-components).

function Section({
  id, label, count, expanded, onToggle,
}: {
  id: string;
  label: string;
  count?: number;
  expanded: boolean;
  onToggle: (id: string) => void;
}) {
  return (
    <button
      onClick={() => onToggle(id)}
      className="flex items-center gap-1.5 w-full py-1.5 text-[11px] font-mono uppercase tracking-wide text-text-muted hover:text-text-primary"
    >
      {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
      {label}
      {count !== undefined && count > 0 && (
        <span className="ml-auto text-amber text-[10px]">{count}</span>
      )}
    </button>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 mb-2">
      <label className="text-[10px] font-mono text-text-dim uppercase">{label}</label>
      {children}
    </div>
  );
}

function Input({
  value, onChange: onCh, placeholder, type = "text",
}: {
  value: string | number;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <input
      type={type}
      value={value ?? ""}
      onChange={e => onCh(e.target.value)}
      placeholder={placeholder}
      className="px-2 py-1 bg-elevated border border-border rounded text-[12px] text-text-primary font-mono focus:border-amber focus:outline-none"
    />
  );
}

function Select({
  value, options, onChange: onCh,
}: {
  value: string;
  options: readonly string[];
  onChange: (v: string) => void;
}) {
  return (
    <select
      value={value}
      onChange={e => onCh(e.target.value)}
      className="px-2 py-1 bg-elevated border border-border rounded text-[12px] text-text-primary font-mono focus:border-amber focus:outline-none"
    >
      {options.map(o => <option key={o} value={o}>{o}</option>)}
    </select>
  );
}

export default function NodeEditor({ node, allNodeIds, onChange, onDelete }: Props) {
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    core: true, feeds: false, thresholds: false, indicators: false, gates: false,
  });

  const toggle = (section: string) =>
    setExpandedSections(prev => ({ ...prev, [section]: !prev[section] }));

  const update = <K extends keyof BuilderNode>(key: K, value: BuilderNode[K]) =>
    onChange({ ...node, [key]: value });

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-border">
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full" style={{
            backgroundColor: node.state === "fired" ? "#ef4444" :
              node.state === "approaching" ? "#d4a843" :
              node.state === "active" ? "#3b82f6" : "#525252"
          }} />
          <span className="text-[12px] font-mono text-text-primary font-semibold">{node.label || node.id}</span>
        </div>
        <button
          onClick={onDelete}
          className="p-1 text-text-dim hover:text-danger rounded"
          title="Delete node"
        >
          <Trash2 size={13} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-1">
        {/* ── Core Properties ─────────────────────────────────────── */}
        <Section id="core" label="Core" expanded={!!expandedSections.core} onToggle={toggle} />
        {expandedSections.core && (
          <div className="pl-2 space-y-0">
            <Field label="ID">
              <Input value={node.id} onChange={v => update("id", v.toLowerCase().replace(/[^a-z0-9-]/g, "-"))} placeholder="node-id" />
            </Field>
            <Field label="Label">
              <Input value={node.label} onChange={v => update("label", v)} placeholder="Display name" />
            </Field>
            <Field label="Type">
              <Select value={node.type} options={NODE_TYPES} onChange={v => update("type", v as BuilderNode["type"])} />
            </Field>
            <Field label="Phase">
              <input
                type="range" min="1" max="5" step="1"
                value={node.phase}
                onChange={e => update("phase", parseInt(e.target.value))}
                className="w-full accent-amber"
              />
              <span className="text-[10px] font-mono text-text-muted">Phase {node.phase}</span>
            </Field>
            <Field label="State">
              <Select value={node.state} options={NODE_STATES} onChange={v => update("state", v as BuilderNode["state"])} />
            </Field>
            <Field label="Context">
              <textarea
                value={node.context}
                onChange={e => update("context", e.target.value)}
                placeholder="Why this node matters..."
                rows={3}
                className="px-2 py-1 bg-elevated border border-border rounded text-[12px] text-text-primary font-mono focus:border-amber focus:outline-none resize-y"
              />
            </Field>
            <div className="flex gap-2">
              <Field label="Probability">
                <Input
                  type="number"
                  value={node.probability ?? ""}
                  onChange={v => update("probability", v ? parseFloat(v) : null)}
                  placeholder="0.0 - 1.0"
                />
              </Field>
              <Field label="Current Price">
                <Input
                  type="number"
                  value={node.current ?? ""}
                  onChange={v => update("current", v ? parseFloat(v) : null)}
                  placeholder="e.g. 110.50"
                />
              </Field>
            </div>
            <div className="flex gap-4 py-1">
              <label className="flex items-center gap-1.5 text-[11px] font-mono text-text-muted">
                <input
                  type="checkbox"
                  checked={node.countdown}
                  onChange={e => update("countdown", e.target.checked)}
                  className="accent-amber"
                />
                Countdown
              </label>
              <label className="flex items-center gap-1.5 text-[11px] font-mono text-text-muted">
                <input
                  type="checkbox"
                  checked={node.irreversible}
                  onChange={e => update("irreversible", e.target.checked)}
                  className="accent-danger"
                />
                Irreversible
              </label>
            </div>
            {node.countdown && (
              <Field label="Deadline">
                <Input
                  type="date"
                  value={node.deadline ?? ""}
                  onChange={v => update("deadline", v || null)}
                />
              </Field>
            )}
          </div>
        )}

        {/* ── Data Feeds ──────────────────────────────────────────── */}
        <Section id="feeds" label="Data Feeds" count={node.feeds.length} expanded={!!expandedSections.feeds} onToggle={toggle} />
        {expandedSections.feeds && (
          <div className="pl-2 space-y-2">
            {node.feeds.map((feed, i) => (
              <div key={i} className="flex gap-1 items-start p-1.5 bg-surface rounded border border-border">
                <div className="flex-1 space-y-1">
                  <Select
                    value={feed.source}
                    options={FEED_SOURCES}
                    onChange={v => {
                      const feeds = [...node.feeds];
                      feeds[i] = { ...feed, source: v as BuilderFeed["source"] };
                      update("feeds", feeds);
                    }}
                  />
                  {(feed.source === "yahoo") && (
                    <Input
                      value={feed.symbol ?? ""}
                      onChange={v => {
                        const feeds = [...node.feeds];
                        feeds[i] = { ...feed, symbol: v };
                        update("feeds", feeds);
                      }}
                      placeholder="Symbol (e.g. BZ=F)"
                    />
                  )}
                  {(feed.source === "polymarket") && (
                    <Input
                      value={feed.market ?? ""}
                      onChange={v => {
                        const feeds = [...node.feeds];
                        feeds[i] = { ...feed, market: v };
                        update("feeds", feeds);
                      }}
                      placeholder="Market slug"
                    />
                  )}
                  {(feed.source === "fred" || feed.source === "eia" || feed.source === "bls" || feed.source === "usda") && (
                    <Input
                      value={feed.series ?? ""}
                      onChange={v => {
                        const feeds = [...node.feeds];
                        feeds[i] = { ...feed, series: v };
                        update("feeds", feeds);
                      }}
                      placeholder="Series ID"
                    />
                  )}
                  <Input
                    value={feed.label ?? ""}
                    onChange={v => {
                      const feeds = [...node.feeds];
                      feeds[i] = { ...feed, label: v };
                      update("feeds", feeds);
                    }}
                    placeholder="Label"
                  />
                </div>
                <button
                  onClick={() => update("feeds", node.feeds.filter((_, j) => j !== i))}
                  className="p-0.5 text-text-dim hover:text-danger"
                >
                  <X size={12} />
                </button>
              </div>
            ))}
            <button
              onClick={() => update("feeds", [...node.feeds, { source: "yahoo", symbol: "", label: "" }])}
              className="flex items-center gap-1 text-[11px] font-mono text-amber hover:text-text-primary"
            >
              <Plus size={12} /> Add Feed
            </button>
          </div>
        )}

        {/* ── Thresholds ──────────────────────────────────────────── */}
        <Section id="thresholds" label="Thresholds" count={node.thresholds.length} expanded={!!expandedSections.thresholds} onToggle={toggle} />
        {expandedSections.thresholds && (
          <div className="pl-2 space-y-2">
            {node.thresholds.map((t, i) => (
              <div key={i} className="flex gap-1 items-center">
                <input
                  type="number"
                  value={t.level}
                  onChange={e => {
                    const ts = [...node.thresholds];
                    ts[i] = { ...t, level: parseFloat(e.target.value) || 0 };
                    update("thresholds", ts);
                  }}
                  className="w-20 px-2 py-1 bg-elevated border border-border rounded text-[12px] text-text-primary font-mono"
                  placeholder="Level"
                />
                <input
                  value={t.label}
                  onChange={e => {
                    const ts = [...node.thresholds];
                    ts[i] = { ...t, label: e.target.value };
                    update("thresholds", ts);
                  }}
                  className="flex-1 px-2 py-1 bg-elevated border border-border rounded text-[12px] text-text-primary font-mono"
                  placeholder="Label"
                />
                <button
                  onClick={() => update("thresholds", node.thresholds.filter((_, j) => j !== i))}
                  className="p-0.5 text-text-dim hover:text-danger"
                >
                  <X size={12} />
                </button>
              </div>
            ))}
            <button
              onClick={() => update("thresholds", [...node.thresholds, { level: 0, label: "" }])}
              className="flex items-center gap-1 text-[11px] font-mono text-amber hover:text-text-primary"
            >
              <Plus size={12} /> Add Threshold
            </button>
          </div>
        )}

        {/* ── Manual Indicators ───────────────────────────────────── */}
        <Section id="indicators" label="Indicators" count={node.indicators.length} expanded={!!expandedSections.indicators} onToggle={toggle} />
        {expandedSections.indicators && (
          <div className="pl-2 space-y-2">
            {node.indicators.map((ind, i) => (
              <div key={i} className="flex gap-1 items-center">
                <input
                  value={ind.label}
                  onChange={e => {
                    const inds = [...node.indicators];
                    inds[i] = { ...ind, label: e.target.value };
                    update("indicators", inds);
                  }}
                  className="flex-1 px-2 py-1 bg-elevated border border-border rounded text-[12px] text-text-primary font-mono"
                  placeholder="Label"
                />
                <input
                  value={ind.value}
                  onChange={e => {
                    const inds = [...node.indicators];
                    inds[i] = { ...ind, value: e.target.value };
                    update("indicators", inds);
                  }}
                  className="w-24 px-2 py-1 bg-elevated border border-border rounded text-[12px] text-text-primary font-mono"
                  placeholder="Value"
                />
                <select
                  value={ind.status}
                  onChange={e => {
                    const inds = [...node.indicators];
                    inds[i] = { ...ind, status: e.target.value as BuilderIndicator["status"] };
                    update("indicators", inds);
                  }}
                  className="w-16 px-1 py-1 bg-elevated border border-border rounded text-[12px] text-text-primary font-mono"
                >
                  {INDICATOR_STATUSES.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
                <button
                  onClick={() => update("indicators", node.indicators.filter((_, j) => j !== i))}
                  className="p-0.5 text-text-dim hover:text-danger"
                >
                  <X size={12} />
                </button>
              </div>
            ))}
            <button
              onClick={() => update("indicators", [...node.indicators, { label: "", feed: "manual", value: "", status: "grey" as const }])}
              className="flex items-center gap-1 text-[11px] font-mono text-amber hover:text-text-primary"
            >
              <Plus size={12} /> Add Indicator
            </button>
          </div>
        )}

        {/* ── Gate Dependencies ────────────────────────────────────── */}
        <Section id="gates" label="Gate Dependencies" count={node.gatedBy.length} expanded={!!expandedSections.gates} onToggle={toggle} />
        {expandedSections.gates && (
          <div className="pl-2 space-y-2">
            {node.gatedBy.map((gateId, i) => (
              <div key={i} className="flex gap-1 items-center">
                <select
                  value={gateId}
                  onChange={e => {
                    const gates = [...node.gatedBy];
                    gates[i] = e.target.value;
                    update("gatedBy", gates);
                  }}
                  className="flex-1 px-2 py-1 bg-elevated border border-border rounded text-[12px] text-text-primary font-mono"
                >
                  <option value="">-- select node --</option>
                  {allNodeIds.filter(id => id !== node.id).map(id => (
                    <option key={id} value={id}>{id}</option>
                  ))}
                </select>
                <button
                  onClick={() => update("gatedBy", node.gatedBy.filter((_, j) => j !== i))}
                  className="p-0.5 text-text-dim hover:text-danger"
                >
                  <X size={12} />
                </button>
              </div>
            ))}
            <button
              onClick={() => update("gatedBy", [...node.gatedBy, ""])}
              className="flex items-center gap-1 text-[11px] font-mono text-amber hover:text-text-primary"
            >
              <Plus size={12} /> Add Gate
            </button>
            {node.gatedBy.length > 1 && (
              <Field label="Gate Logic">
                <Select
                  value={node.logic ?? "all"}
                  options={["all", "any"] as const}
                  onChange={v => update("logic", v)}
                />
              </Field>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
