import { useEffect, useState } from "react";

// HeroGraph — a stylized causal DAG that fires nodes in sequence to
// teach the propagation idea at a glance. CSS-only animation; no canvas,
// no extra deps. Honors prefers-reduced-motion via index.css.
//
// The 6 nodes loosely mirror the iran-hormuz transmission chain:
//   hormuz → brent → diesel → freight → employment → demand-destruction
// Each has a fixed (x,y) on a 600×260 viewBox. Edges are static SVG paths;
// the "fire" wave walks the chain by toggling a CSS class on a 4s loop.

interface Node {
  id: string;
  label: string;
  x: number;
  y: number;
}

interface Edge {
  from: string;
  to: string;
}

const NODES: readonly Node[] = [
  { id: "hormuz", label: "hormuz", x: 60, y: 130 },
  { id: "brent", label: "brent", x: 175, y: 70 },
  { id: "diesel", label: "diesel", x: 175, y: 200 },
  { id: "freight", label: "freight", x: 305, y: 130 },
  { id: "employment", label: "employment", x: 435, y: 70 },
  { id: "demand", label: "demand", x: 435, y: 200 },
  { id: "recession", label: "recession", x: 555, y: 130 },
];

const EDGES: readonly Edge[] = [
  { from: "hormuz", to: "brent" },
  { from: "hormuz", to: "diesel" },
  { from: "brent", to: "freight" },
  { from: "diesel", to: "freight" },
  { from: "freight", to: "employment" },
  { from: "freight", to: "demand" },
  { from: "employment", to: "recession" },
  { from: "demand", to: "recession" },
];

// Order in which nodes "fire" during the loop. Each step lights one node
// and the edges into it.
const FIRE_ORDER = [
  "hormuz",
  "brent",
  "diesel",
  "freight",
  "employment",
  "demand",
  "recession",
];

const STEP_MS = 700;

function nodeById(id: string): Node {
  const n = NODES.find((x) => x.id === id);
  if (!n) throw new Error(`unknown node ${id}`);
  return n;
}

export default function HeroGraph() {
  const [step, setStep] = useState(0);

  useEffect(() => {
    const id = window.setInterval(() => {
      setStep((s) => (s + 1) % (FIRE_ORDER.length + 2));
    }, STEP_MS);
    return () => window.clearInterval(id);
  }, []);

  // A node is "fired" once its turn has come and stays fired until the loop resets.
  const firedSet = new Set<string>(FIRE_ORDER.slice(0, Math.min(step, FIRE_ORDER.length)));

  return (
    <svg
      viewBox="0 0 600 260"
      role="img"
      aria-label="Animated causal graph: shock propagates from hormuz through brent, diesel, freight, employment and demand into recession"
      className="w-full h-auto max-h-[260px]"
    >
      <defs>
        <radialGradient id="hg-bg" cx="50%" cy="50%" r="60%">
          <stop offset="0%" stopColor="rgba(212,168,67,0.06)" />
          <stop offset="100%" stopColor="rgba(0,0,0,0)" />
        </radialGradient>
        <filter id="hg-glow" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="2.5" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>

      <rect x="0" y="0" width="600" height="260" fill="url(#hg-bg)" />

      {/* Edges */}
      {EDGES.map((e) => {
        const a = nodeById(e.from);
        const b = nodeById(e.to);
        const fired = firedSet.has(e.from) && firedSet.has(e.to);
        return (
          <line
            key={`${e.from}-${e.to}`}
            x1={a.x}
            y1={a.y}
            x2={b.x}
            y2={b.y}
            stroke={fired ? "var(--color-amber)" : "var(--color-border-emphasis)"}
            strokeWidth={fired ? 1.5 : 1}
            strokeOpacity={fired ? 0.85 : 0.5}
            style={{ transition: "stroke 240ms, stroke-opacity 240ms, stroke-width 240ms" }}
          />
        );
      })}

      {/* Nodes */}
      {NODES.map((n) => {
        const fired = firedSet.has(n.id);
        const fill = fired ? "var(--color-amber)" : "var(--color-elevated)";
        const stroke = fired ? "var(--color-amber)" : "var(--color-border-emphasis)";
        return (
          <g key={n.id} style={{ transition: "transform 240ms" }}>
            <circle
              cx={n.x}
              cy={n.y}
              r={fired ? 10 : 8}
              fill={fill}
              stroke={stroke}
              strokeWidth={1.5}
              filter={fired ? "url(#hg-glow)" : undefined}
              style={{ transition: "r 240ms, fill 240ms, stroke 240ms" }}
            />
            <text
              x={n.x}
              y={n.y + 24}
              textAnchor="middle"
              fontFamily="var(--font-mono)"
              fontSize="10"
              fill={fired ? "var(--color-amber)" : "var(--color-text-muted)"}
              style={{ transition: "fill 240ms" }}
            >
              {n.label}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
