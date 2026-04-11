// Inline RSI/ATR/SMA badge for the ThesisViewer node list.
//
// WHY display-only: per the overlay=true tripwire in the engine, derived
// indicators are NON-CAUSAL. This badge renders them for operator context
// — RSI color hints where price sits in its recent range — but nothing
// here feeds back into the DAG. Colors are intentionally mild (not
// alarming) because the same colors in a "fired" badge would be misread
// as a state transition.
import type { TVIndicatorReading } from "../lib/types";

interface Props {
  reading: TVIndicatorReading | undefined;
}

function rsiClass(rsi: number): string {
  // >=70 overbought → amber/red (display hint, NOT a state change)
  if (rsi >= 70) return "text-amber";
  // <=30 oversold → teal (possible reversal tell)
  if (rsi <= 30) return "text-teal";
  return "text-text-dim";
}

export default function TVIndicatorBadge({ reading }: Props) {
  if (!reading) return null;

  // Collect numeric values from the reading, skipping metadata keys.
  const rsi = typeof reading.rsi14 === "number" ? reading.rsi14 : null;
  const atr = typeof reading.atr14 === "number" ? reading.atr14 : null;

  if (rsi === null && atr === null) return null;

  return (
    <span className="flex items-center gap-1 text-[9px] font-mono ml-1">
      {rsi !== null && (
        <span className={rsiClass(rsi)} title={`RSI(14) = ${rsi.toFixed(1)}`}>
          RSI:{rsi.toFixed(0)}
        </span>
      )}
      {atr !== null && (
        <span className="text-text-dim" title={`ATR(14) = ${atr.toFixed(2)}`}>
          ATR:{atr.toFixed(1)}
        </span>
      )}
    </span>
  );
}
