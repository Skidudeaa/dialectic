import { useState, useEffect, useRef, useMemo } from "react";
import { RefreshCw, ArrowUp, ArrowDown } from "lucide-react";
import { apiFetch, subscribeRoomMessages } from "../lib/api";
import type { PriceTickPayload, WatchlistItem, WSMessage } from "../lib/types";

const REFRESH_MS = 60_000;
// Unit 6: how long a cell flashes after a live tick lands.
const FLASH_MS = 900;

function formatPrice(item: WatchlistItem): string {
  if (item.last_price === null) return "—";
  if (item.source === "polymarket") {
    return `${(item.last_price * 100).toFixed(0)}%`;
  }
  if (item.last_price >= 1000) return item.last_price.toFixed(0);
  if (item.last_price >= 100) return item.last_price.toFixed(2);
  return item.last_price.toFixed(2);
}

function freshnessLabel(when: Date | null): string {
  if (!when) return "—";
  const sec = Math.floor((Date.now() - when.getTime()) / 1000);
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  return `${Math.floor(sec / 3600)}h ago`;
}

interface MarketTickerProps {
  roomId?: string;
  thesisId?: string | null;
}

export default function MarketTicker({ roomId, thesisId }: MarketTickerProps = {}) {
  const [items, setItems] = useState<WatchlistItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  // symbol -> "up" | "down" | null — drives the tick flash
  const [flash, setFlash] = useState<Record<string, "up" | "down">>({});
  const [, force] = useState(0);
  const intervalRef = useRef<ReturnType<typeof setInterval>>(undefined);
  const tickRef = useRef<ReturnType<typeof setInterval>>(undefined);
  const flashTimers = useRef<Record<string, ReturnType<typeof setTimeout>>>({});

  useEffect(() => {
    loadWatchlist();
    intervalRef.current = setInterval(loadWatchlist, REFRESH_MS);
    // Tick the freshness label every 15s without re-fetching
    tickRef.current = setInterval(() => force((n) => n + 1), 15_000);
    return () => {
      clearInterval(intervalRef.current);
      clearInterval(tickRef.current);
    };
  }, []);

  // Unit 6: apply live price.tick deltas in place — no refetch on receipt.
  useEffect(() => {
    const unsub = subscribeRoomMessages((msg: WSMessage) => {
      if (msg.type !== "price.tick") return;
      const payload = msg.payload as unknown as PriceTickPayload;
      // WHY: a single RoomSocket may be attached to a different thesis than
      // the one MarketTicker is displaying (e.g. chat room switched, ticker
      // pinned). Filter on thesis_id so we don't flash unrelated books.
      if (thesisId && payload.thesis_id !== thesisId) return;

      const changes = payload.changes || {};
      if (Object.keys(changes).length === 0) return;

      setItems((prev) =>
        prev.map((it) => {
          const change = changes[it.symbol];
          if (!change) return it;
          const curr = change.curr;
          if (curr === undefined || curr === null) return it;
          // Compute a fresh change_pct relative to the previous price so
          // the ▲/▼ arrow reflects this tick.
          const prevPrice = it.last_price;
          const change_pct =
            prevPrice && prevPrice > 0
              ? ((curr - prevPrice) / prevPrice) * 100
              : it.change_pct;
          return { ...it, last_price: curr, change_pct };
        }),
      );
      setLastUpdated(new Date());

      // Schedule flash highlights per changed symbol.
      const nextFlash: Record<string, "up" | "down"> = {};
      for (const [symbol, entry] of Object.entries(changes)) {
        if (entry.curr == null || entry.prev == null) continue;
        if (entry.curr === entry.prev) continue;
        nextFlash[symbol] = entry.curr > entry.prev ? "up" : "down";
      }
      if (Object.keys(nextFlash).length > 0) {
        setFlash((prev) => ({ ...prev, ...nextFlash }));
        for (const symbol of Object.keys(nextFlash)) {
          if (flashTimers.current[symbol]) {
            clearTimeout(flashTimers.current[symbol]);
          }
          flashTimers.current[symbol] = setTimeout(() => {
            setFlash((prev) => {
              const next = { ...prev };
              delete next[symbol];
              return next;
            });
            delete flashTimers.current[symbol];
          }, FLASH_MS);
        }
      }
    });
    return () => {
      unsub();
    };
    // WHY: roomId is in the deps only so a room switch in Dashboard rebuilds
    // the subscription and picks up the new thesisId filter. The subscription
    // itself taps the process-wide WS fan-out, not a specific room socket.
  }, [roomId, thesisId]);

  async function loadWatchlist() {
    try {
      const data = await apiFetch<WatchlistItem[]>("/api/market/watchlist");
      setItems(data);
      setLastUpdated(new Date());
      setError(null);
    } catch {
      setError("fetch failed");
    } finally {
      setLoading(false);
    }
  }

  // Group by source for visual structure (yahoo prices vs polymarket %)
  const groups = useMemo(() => {
    const m = new Map<string, WatchlistItem[]>();
    for (const it of items) {
      const k = it.source || "other";
      if (!m.has(k)) m.set(k, []);
      m.get(k)!.push(it);
    }
    return Array.from(m.entries());
  }, [items]);

  return (
    <div>
      <div className="flex items-center justify-between mb-1 px-0.5">
        <span className="text-[10px] text-text-dim font-medium uppercase tracking-widest">
          Market
        </span>
        <div className="flex items-center gap-1">
          <span
            className={`text-[9px] font-mono ${
              error
                ? "text-danger"
                : lastUpdated && Date.now() - lastUpdated.getTime() > 120_000
                  ? "text-amber"
                  : "text-text-dim"
            }`}
            title={lastUpdated ? lastUpdated.toLocaleString() : ""}
          >
            {error ? error : freshnessLabel(lastUpdated)}
          </span>
          <button
            onClick={loadWatchlist}
            className="text-text-dim hover:text-amber p-0.5"
            disabled={loading}
            title="Refresh"
            aria-label="Refresh market data"
          >
            <RefreshCw size={10} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {loading && items.length === 0 && (
        <div className="space-y-0.5">
          {[0, 1, 2, 3, 4].map((i) => (
            <div key={i} className="flex items-center gap-1 py-0.5 px-0.5 animate-pulse">
              <div className="h-2 w-12 bg-elevated/60 rounded" />
              <div className="h-2 flex-1 bg-elevated/30 rounded" />
              <div className="h-2 w-10 bg-elevated/60 rounded" />
            </div>
          ))}
        </div>
      )}

      {!loading && items.length === 0 && (
        <div className="text-[10px] text-text-dim font-mono px-1 py-2 text-center">
          {error || "no watchlist items"}
        </div>
      )}

      {groups.map(([source, list], gi) => (
        <div key={source} className={gi > 0 ? "mt-1.5 pt-1 border-t border-border/50" : ""}>
          {groups.length > 1 && (
            <div className="text-[8px] font-mono text-text-dim uppercase tracking-widest px-0.5 mb-0.5">
              {source}
            </div>
          )}
          <div className="space-y-0">
            {list.map((item) => (
              <TickerRow
                key={`${source}:${item.symbol}`}
                item={item}
                flashDir={flash[item.symbol]}
              />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function TickerRow({
  item,
  flashDir,
}: {
  item: WatchlistItem;
  flashDir?: "up" | "down";
}) {
  const change = item.change_pct;
  const up = change !== null && change > 0;
  const down = change !== null && change < 0;
  const changeColor = up
    ? "text-teal"
    : down
      ? "text-danger"
      : "text-text-muted";

  // Unit 6: a brief background highlight when a live tick updates this row.
  // Green on up-tick, red on down-tick; fades via Tailwind transition.
  const flashBg = flashDir === "up"
    ? "bg-teal/20"
    : flashDir === "down"
      ? "bg-danger/20"
      : "";

  return (
    <div
      className={`flex items-center justify-between py-px px-0.5 hover:bg-elevated/50 rounded-sm group transition-colors duration-500 ${flashBg}`}
      title={
        item.last_price !== null
          ? `${item.symbol} · ${item.label}\n${formatPrice(item)}${
              change !== null ? ` (${change > 0 ? "+" : ""}${change.toFixed(2)}%)` : ""
            }`
          : item.label
      }
    >
      <div className="min-w-0 mr-1 flex-1">
        <span className="text-[11px] font-mono font-medium text-amber block leading-tight truncate">
          {item.symbol}
        </span>
        <span className="text-[9px] text-text-dim truncate block leading-tight">
          {item.label}
        </span>
      </div>
      <div className="text-right shrink-0 flex flex-col items-end">
        {item.last_price !== null ? (
          <>
            <span className="text-[11px] font-mono text-text-primary leading-tight">
              {formatPrice(item)}
            </span>
            {change !== null ? (
              <span
                className={`text-[9px] font-mono leading-tight flex items-center gap-0.5 ${changeColor}`}
              >
                {up && <ArrowUp size={8} />}
                {down && <ArrowDown size={8} />}
                {change > 0 ? "+" : ""}
                {change.toFixed(2)}%
              </span>
            ) : (
              <span className="text-[9px] font-mono text-text-dim leading-tight">·</span>
            )}
          </>
        ) : (
          <span className="text-[10px] font-mono text-text-dim">—</span>
        )}
      </div>
    </div>
  );
}
