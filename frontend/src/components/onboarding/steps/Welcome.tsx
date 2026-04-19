// Step 1 — Welcome.
//
// Sets the conceptual frame: tradingDesk is a *causal graph engine*, not yet
// another dashboard. The illustration shows a 3-node mini DAG firing in
// sequence so the user sees propagation before they ever see a real thesis.

import StepFrame from "../StepFrame";
import TryThis from "../TryThis";

function MiniGraph() {
  // Three nodes in a chain — first fired, second approaching, third stable.
  // Pure SVG so it stays crisp at any zoom and ships zero kb of bitmap.
  return (
    <svg
      viewBox="0 0 320 110"
      className="w-full h-auto"
      role="img"
      aria-label="A causal chain: hormuz fired, brent approaching, em-stress stable"
    >
      <defs>
        <marker
          id="arrow"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#525252" />
        </marker>
      </defs>

      {/* Edges */}
      <line
        x1="60"
        y1="55"
        x2="140"
        y2="55"
        stroke="#525252"
        strokeWidth="1.5"
        markerEnd="url(#arrow)"
      />
      <line
        x1="180"
        y1="55"
        x2="260"
        y2="55"
        stroke="#333"
        strokeWidth="1.5"
        strokeDasharray="3 3"
        markerEnd="url(#arrow)"
      />

      {/* Node 1 — fired */}
      <g>
        <circle
          cx="40"
          cy="55"
          r="22"
          fill="rgba(239,68,68,0.18)"
          stroke="#ef4444"
          strokeWidth="1.5"
        />
        <text
          x="40"
          y="58"
          textAnchor="middle"
          fontFamily="JetBrains Mono, ui-monospace, monospace"
          fontSize="10"
          fill="#ef4444"
        >
          hormuz
        </text>
        <text
          x="40"
          y="92"
          textAnchor="middle"
          fontFamily="JetBrains Mono, ui-monospace, monospace"
          fontSize="8"
          fill="#737373"
        >
          fired
        </text>
      </g>

      {/* Node 2 — approaching */}
      <g>
        <circle
          cx="160"
          cy="55"
          r="22"
          fill="rgba(212,168,67,0.18)"
          stroke="#d4a843"
          strokeWidth="1.5"
        />
        <text
          x="160"
          y="58"
          textAnchor="middle"
          fontFamily="JetBrains Mono, ui-monospace, monospace"
          fontSize="10"
          fill="#d4a843"
        >
          brent
        </text>
        <text
          x="160"
          y="92"
          textAnchor="middle"
          fontFamily="JetBrains Mono, ui-monospace, monospace"
          fontSize="8"
          fill="#737373"
        >
          approaching
        </text>
      </g>

      {/* Node 3 — stable */}
      <g>
        <circle
          cx="280"
          cy="55"
          r="22"
          fill="#1a1a1a"
          stroke="#333"
          strokeWidth="1.5"
        />
        <text
          x="280"
          y="58"
          textAnchor="middle"
          fontFamily="JetBrains Mono, ui-monospace, monospace"
          fontSize="9"
          fill="#737373"
        >
          em-stress
        </text>
        <text
          x="280"
          y="92"
          textAnchor="middle"
          fontFamily="JetBrains Mono, ui-monospace, monospace"
          fontSize="8"
          fill="#525252"
        >
          stable
        </text>
      </g>
    </svg>
  );
}

export default function WelcomeStep() {
  return (
    <StepFrame
      title="Trading Desk turns macro theses into causal graphs."
      lede={
        <>
          When one node fires, the graph propagates the signal downstream and
          tells you which dependent positions just got more — or less — likely.
          You stop guessing about second-order effects.
        </>
      }
      illustration={<MiniGraph />}
      bullets={[
        {
          title: "Nodes are observable economic states",
          body: "events, prices, indicators, deadlines, gates. Each has a threshold; cross it and the node fires.",
        },
        {
          title: "Edges are transmission channels",
          body: "with mechanisms, lags, and amplification factors — the actual causal story between price A and price B.",
        },
        {
          title: "Confluence tells you when to trade",
          body: "when several independent paths converge on the same node, conviction is highest.",
        },
      ]}
      primaryLabel="Show me how"
      tryThis={
        <TryThis
          intro={
            <>
              Open any room and paste this. Claude will scan all five
              books — iran-hormuz, trump-tariffs, japan-rate-shock,
              ai-capex-unwind, china-property-cascade — and rank them.
            </>
          }
          snippets={[
            {
              text: "@claude what's the highest-confluence node across all five books right now, and which one would you trade first?",
              ariaLabel: "Copy starter prompt for Claude across all books",
            },
          ]}
        />
      }
    />
  );
}
