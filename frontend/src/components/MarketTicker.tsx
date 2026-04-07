import { useState, useEffect, useRef } from "react";
import { apiFetch } from "../lib/api";
import type { WatchlistItem } from "../lib/types";

export default function MarketTicker() {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const intervalRef = useRef<ReturnType<typeof setInterval>>(undefined);

  useEffect(() => {
    loadWatchlist();
    intervalRef.current = setInterval(loadWatchlist, 60_000);
    return () => clearInterval(intervalRef.current);
  }, []);

  async function loadWatchlist() {
    try {
      const data = await apiFetch<WatchlistItem[]>("/api/market/watchlist");
      setItems(data);
    } catch { /* ignore */ }
  }

  if (items.length === 0) {
    return <p className="text-text-dim text-xs">Loading watchlist...</p>;
  }

  return (
    <div className="space-y-0.5">
      {items.map((item) => (
        <div key={item.symbol} className="flex items-center justify-between py-0.5 px-1 rounded hover:bg-elevated/50">
          <div className="min-w-0">
            <span className="text-xs font-mono block truncate">{item.symbol}</span>
            {item.label !== item.symbol && (
              <span className="text-xs text-text-dim truncate block">{item.label}</span>
            )}
          </div>
          <div className="text-right shrink-0 ml-2">
            {item.last_price !== null ? (
              <span className="text-xs font-mono text-text-primary">
                {item.source === "polymarket"
                  ? `${(item.last_price * 100).toFixed(0)}%`
                  : item.last_price.toFixed(2)}
              </span>
            ) : (
              <span className="text-xs text-text-dim">--</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
