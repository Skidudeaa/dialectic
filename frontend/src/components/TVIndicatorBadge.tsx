// Inline RSI/ATR/SMA badge for the ThesisViewer node list.
//
// WHY display-only: per the overlay=true tripwire in the engine, derived
// indicators are NON-CAUSAL. This badge renders them for operator context
// — RSI color hints where price sits in its recent range — but nothing
// here feeds back into the DAG. Colors are intentionally mild (not
// alarming) because the same colors in a "fired" badge would be misread
// as a state transition.
//
// The leading "·" separator and lowercase keys reinforce that these are
// metadata about price, not state of the node.
import type { TVIndicatorReading } from "../lib/types";

interface Props {
  reading: TVIndicatorReading | undefined;
  /** When true, shows SMA50 alongside RSI/ATR (used in expanded node detail). */
  expanded?: boolean;
}

function rsiClass(rsi: number): string {
  // >=70 overbought → amber (display hint, NOT a state change)
  if (rsi >= 70) return "text-amber";
  // <=30 oversold → teal (possible reversal tell)
  if (rsi <= 30) return "text-teal";
  // 60-70 / 30-40 mild leans
  if (rsi >= 60) return "text-amber/70";
  if (rsi <= 40) return "text-teal/70";
  return "text-text-dim";
}

/** Format a RFC3339 timestamp as a relative age string ("12m", "3h", "2d"). */
function relativeAge(iso: string | undefined): string | null {
  if (!iso) return null;
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return null;
  const seconds = Math.max(0, (Date.now() - then) / 1000);
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

export default function TVIndicatorBadge({ reading, expanded = false }: Props) {
  if (!reading) return null;

  const rsi = typeof reading.rsi14 === "number" ? reading.rsi14 : null;
  const atr = typeof reading.atr14 === "number" ? reading.atr14 : null;
  const sma = typeof reading.sma50 === "number" ? reading.sma50 : null;

  if (rsi === null && atr === null && sma === null) return null;

  const age = relativeAge(reading.computedAt);
  // Prefix with non-causal marker dot. aria-label flags the same to AT users.
  return (
    <span
      className="inline-flex items-center gap-1 text-[9px] font-mono ml-1 text-text-dim"
      aria-label="non-causal indicator overlays"
      title={`Display-only overlay (non-causal). source=${reading.source ?? "?"}${age ? ` · age=${age}` : ""}`}
    >
      <span aria-hidden className="text-text-dim/60">·</span>
      {rsi !== null && (
        <span className={rsiClass(rsi)} title={`RSI(14) = ${rsi.toFixed(1)} — non-causal`}>
          rsi:{rsi.toFixed(0)}
        </span>
      )}
      {atr !== null && (
        <span className="text-text-dim" title={`ATR(14) = ${atr.toFixed(2)} — non-causal`}>
          atr:{atr.toFixed(1)}
        </span>
      )}
      {expanded && sma !== null && (
        <span className="text-text-dim" title={`SMA(50) = ${sma.toFixed(2)} — non-causal`}>
          sma:{sma.toFixed(1)}
        </span>
      )}
    </span>
  );
}
