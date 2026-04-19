// Step 5 — Builder.
//
// New surface — visual graph editor. Mini illustration shows a node + edge
// being drawn so the affordance is clear without making us paint a real
// editor screenshot.

import StepFrame from "../StepFrame";

function BuilderSketch() {
  return (
    <svg
      viewBox="0 0 320 130"
      className="w-full h-auto"
      role="img"
      aria-label="A new node being dragged in the graph builder"
    >
      <defs>
        <marker
          id="arrow-b"
          viewBox="0 0 10 10"
          refX="8"
          refY="5"
          markerWidth="6"
          markerHeight="6"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#d4a843" />
        </marker>
      </defs>

      {/* Existing node */}
      <rect
        x="20"
        y="35"
        width="80"
        height="40"
        rx="6"
        fill="#1a1a1a"
        stroke="#333"
      />
      <text
        x="60"
        y="58"
        textAnchor="middle"
        fontFamily="JetBrains Mono, ui-monospace, monospace"
        fontSize="10"
        fill="#e5e5e5"
      >
        brent
      </text>
      <text
        x="60"
        y="70"
        textAnchor="middle"
        fontFamily="JetBrains Mono, ui-monospace, monospace"
        fontSize="7"
        fill="#737373"
      >
        price · $115
      </text>

      {/* Drag-to-connect edge */}
      <path
        d="M 100 55 Q 160 30 200 55"
        stroke="#d4a843"
        strokeWidth="2"
        fill="none"
        strokeDasharray="4 3"
        markerEnd="url(#arrow-b)"
      />

      {/* New node being placed */}
      <rect
        x="200"
        y="35"
        width="100"
        height="40"
        rx="6"
        fill="rgba(212,168,67,0.1)"
        stroke="#d4a843"
        strokeDasharray="3 3"
      />
      <text
        x="250"
        y="58"
        textAnchor="middle"
        fontFamily="JetBrains Mono, ui-monospace, monospace"
        fontSize="10"
        fill="#d4a843"
      >
        em-stress
      </text>
      <text
        x="250"
        y="70"
        textAnchor="middle"
        fontFamily="JetBrains Mono, ui-monospace, monospace"
        fontSize="7"
        fill="#737373"
      >
        gate · drop here
      </text>

      {/* Toolbar hint */}
      <g>
        <rect x="20" y="100" width="280" height="18" rx="3" fill="#111" stroke="#262626" />
        <text
          x="30"
          y="113"
          fontFamily="JetBrains Mono, ui-monospace, monospace"
          fontSize="8"
          fill="#737373"
        >
          [+ event] [+ price] [+ deadline] [+ gate]
        </text>
        <text
          x="225"
          y="113"
          fontFamily="JetBrains Mono, ui-monospace, monospace"
          fontSize="8"
          fill="#22c55e"
        >
          ✓ valid
        </text>
        <text
          x="265"
          y="113"
          fontFamily="JetBrains Mono, ui-monospace, monospace"
          fontSize="8"
          fill="#d4a843"
        >
          save
        </text>
      </g>
    </svg>
  );
}

export default function BuilderStep() {
  return (
    <StepFrame
      title="Build a thesis without writing JSON."
      lede={
        <>
          The Builder gives you a visual canvas: drag in nodes, drag from one
          to another to draw a causal edge, and use the side editors for
          thresholds, indicators, and scenarios. Validate before you save.
        </>
      }
      illustration={<BuilderSketch />}
      bullets={[
        {
          title: "Node palette + drag-to-connect",
          body: "Event, price, indicator, deadline, gate, conditional, reversal — all the types the engine understands, with sub-editors for each shape.",
        },
        {
          title: "Pre-save validation",
          body: "Cycles, missing thresholds, broken refs — the validator catches these before the JSON ever lands on disk.",
        },
        {
          title: "Library page lists every book",
          body: "Edit existing theses (iran-hormuz, trump-tariffs) or fork a copy as a starting point.",
        },
      ]}
    />
  );
}
