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
    return <span className="text-[10px] text-text-dim font-mono">loading...</span>;
  }

  return (
    <div className="space-y-0">
      {items.map((item) => (
        <div key={item.symbol} className="flex items-center justify-between py-px px-0.5 hover:bg-elevated/50 rounded-sm">
          <div className="min-w-0 mr-1">
            <span className="text-[11px] font-mono font-medium text-amber block leading-tight">{item.symbol}</span>
            <span className="text-[9px] text-text-dim truncate block leading-tight">{item.label}</span>
          </div>
          <div className="text-right shrink-0">
            {item.last_price !== null ? (
              <span className="text-[11px] font-mono text-text-primary">
                {item.source === "polymarket"
                  ? `${(item.last_price * 100).toFixed(0)}%`
                  : item.last_price.toFixed(2)}
              </span>
            ) : (
              <span className="text-[10px] font-mono text-text-dim">--</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
