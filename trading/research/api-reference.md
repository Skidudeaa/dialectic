# Data Source API Reference

Verified live March 30, 2026. All findings from actual endpoint testing.

## Price Data

### Yahoo Finance (PRIMARY -- no key, no CORS)

| Endpoint | URL Pattern | Use |
|---|---|---|
| v8 chart | `query1.finance.yahoo.com/v8/finance/chart/{sym}?interval={int}&range={range}` | OHLCV series |
| v7 spark | `query1.finance.yahoo.com/v7/finance/spark?symbols={csv}&range=1d&interval=1d` | Multi-symbol latest |
| v7 quote | `query1.finance.yahoo.com/v7/finance/quote?symbols={csv}` | Detailed quote |

- **Auth:** None. Send `User-Agent: Mozilla/5.0` header server-side.
- **Rate limit:** ~2000 req/hr. Batch up to ~20 symbols per request.
- **CORS:** No. Browser needs `api.allorigins.win/raw?url=` proxy (`corsproxy.io` returns 403).
- **Freshness:** 15-min delay futures; real-time US equities during market hours.

#### Yahoo Symbol Map

| Category | Symbols |
|---|---|
| Crude/Energy | `CL=F` (WTI), `BZ=F` (Brent), `NG=F` (NatGas) |
| Brent curve | `BZK26.NYM`, `BZV26.NYM` (month code + year + `.NYM`) |
| Metals | `GC=F` (Gold), `SI=F` (Silver), `HG=F` (Copper) |
| Grains | `ZW=F` (Wheat), `ZC=F` (Corn), `ZS=F` (Soybeans) |
| Macro | `^VIX`, `^TNX` (10Y yield), `^TYX` (30Y), `DX-Y.NYB` (Dollar Index) |
| FX | `EURUSD=X` |
| Indices | `^GSPC` (S&P), `^IXIC` (Nasdaq) |
| Shipping | `BDRY` (Dry Bulk ETF), `BWET` (Tanker ETF) |
| Fed Funds | `ZQ=F` (front), `ZQM26.CBT`, `ZQU26.CBT` (implied rate = 100 - price) |

### Alternatives (all require free API key)

| API | CORS | Rate Limit | Futures | Verdict |
|---|---|---|---|---|
| Twelve Data | Yes | 800/day, 8/min | Paid only | Best equity backup |
| Finnhub | Yes | 60/min | Limited | Good equity backup |
| Alpha Vantage | Yes | 25/day, 5/min | No | Last resort |
| Polygon.io | Yes | 5/min free | Some | Too restrictive |
| IEX Cloud | -- | -- | -- | Dead (connection refused) |

## Macro/Economic Data

### FRED (810k+ series -- key required, no CORS)

`api.stlouisfed.org/fred/series/observations?series_id={id}&api_key={key}&file_type=json`

Free registration at `fred.stlouisfed.org`. 120 req/min. Needs CORS proxy for browser.

| Series ID | Data | Frequency |
|---|---|---|
| `DFF` | Fed Funds Effective Rate | Daily |
| `DGS10` | 10Y Treasury | Daily |
| `T10YIE` | 10Y Breakeven Inflation | Daily |
| `BAMLH0A0HYM2` | HY OAS | Daily |
| `CPIAUCSL` | CPI All Urban | Monthly |
| `UNRATE` | Unemployment | Monthly |
| `PAYEMS` | Nonfarm Payrolls | Monthly |
| `UMCSENT` | Consumer Sentiment | Monthly |
| `DCOILWTICO` | WTI Crude | Daily |
| `VIXCLS` | VIX | Daily |

### EIA v2 (Energy -- key required, CORS enabled)

`api.eia.gov/v2/petroleum/pri/spt/data/?api_key={key}&...`

Free instant registration. Covers crude spot, inventories, diesel, natgas storage, gasoline. Browser-fetchable.

### BLS (Employment/CPI -- no key needed, CORS enabled)

POST to `api.bls.gov/publicAPI/v2/timeseries/data/` with JSON body. 25 queries/day without key. Series: `CES0000000001` (Nonfarm), `CUUR0000SA0` (CPI-U), `LNS14000000` (Unemployment).

### ECB (European rates/FX -- no key, CORS enabled)

`data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?lastNObservations=3&format=jsondata`

Daily EUR/USD, interest rates, money supply. Fast and reliable.

### CFTC COT Reports (Positioning -- no key, CORS enabled)

| Dataset | Socrata URL |
|---|---|
| Futures Only | `publicreporting.cftc.gov/resource/6dca-aqww.json` |
| Disaggregated | `publicreporting.cftc.gov/resource/kh3c-gbw2.json` |

Weekly (Tue data, Fri release). SoQL queries: `$limit`, `$order`, `$where`. Has Producer/Merchant, Swap Dealer, Managed Money breakdowns. Browser-fetchable.

### USDA Fertilizer (no key, CORS enabled)

`agtransport.usda.gov/api/views/8bgf-5mdv/rows.json` -- Urea, UAN, DAP, MAP, Potash, Ammonia. Monthly, 2-3 month lag.

## Prediction Markets

### Polymarket -- Two APIs needed

**Gamma API** (discovery/metadata): `gamma-api.polymarket.com`
- `GET /events?limit=5&active=true&order=volume&ascending=false`
- `GET /markets?slug={slug}`
- No auth. Cloudflare-cached (180s). No CORS -- server-side or proxy.
- Returns: `outcomePrices` (JSON array of decimals), volume/liquidity stats, `clobTokenIds`

**CLOB API** (orderbook/history): `clob.polymarket.com`
- `GET /book?token_id={id}` -- L2 orderbook
- `GET /price?token_id={id}&side=buy` -- best price
- `GET /midpoint?token_id={id}` -- midpoint
- `GET /prices-history?market={token_id}&interval={1h|6h|1d|1w|max}&fidelity={minutes}`
- No auth for reads. ~60 req/min.

**Workflow:** Gamma gives `clobTokenIds` -> use those as `token_id` in CLOB endpoints.

**WebSocket:** `wss://ws-subscriptions-clob.polymarket.com/ws/market` (10 concurrent subscriptions)

**Key fields in Gamma response:** `outcomePrices`, `volume24hr`, `bestBid`, `bestAsk`, `spread`, `clobTokenIds`, `conditionId`, `slug`, `endDateIso`, `oneWeekPriceChange`

### Kalshi (CFTC-regulated -- no auth for reads, no CORS)

`api.elections.kalshi.com/trade-api/v2/events?series_ticker={ticker}`

| Ticker | Markets |
|---|---|
| `KXCPI` | CPI monthly predictions |
| `KXFED` | Fed funds rate per FOMC |
| `KXGDP` | GDP growth predictions |

Prices in dollars (`yes_ask_dollars`, `yes_bid_dollars`). Most valuable for macro probability signals.

### Others

| Platform | URL | Auth | Notes |
|---|---|---|---|
| Manifold | `api.manifold.markets/v0/search-markets?term=X&limit=5&sort=liquidity` | None | Play money, good signal, CORS unknown |
| PredictIt | `predictit.org/api/marketdata/all/` | None | Winding down, 251 markets remain |
| Metaculus | `metaculus.com/api/v2/questions/` | Required | Auth-gated since 2026 |

## CORS / Proxy Summary

| Tier | APIs | Browser Strategy |
|---|---|---|
| Direct browser fetch, no key | CFTC COT, BLS, ECB, USDA Socrata | Fetch directly |
| Browser fetch, free key embedded | EIA, Finnhub, Twelve Data | Fetch with key param |
| Needs `allorigins.win` proxy | Yahoo Finance, FRED | `api.allorigins.win/raw?url=` |
| Server-side only | Kalshi, Polymarket, USDA NASS | Python fetch at generation time |

## Dead Ends

- **IEX Cloud:** Connection refused.
- **CBOE direct VIX:** 403. Use Yahoo `^VIX` or FRED `VIXCLS`.
- **CNN Fear & Greed:** Bot detection blocks automated requests.
- **Reddit/Twitter APIs:** Rate-limited or paid-only since 2023.
- **CME/ICE direct:** Commercial subscriptions only. Yahoo provides delayed prices.
- **Baltic Dry Index direct:** No free API. Use `BDRY` ETF via Yahoo.
- **Put/Call Ratio:** No free JSON endpoint. CBOE publishes but no API.

## Open-Source Polymarket Tools

- `Polymarket/py-clob-client` -- Official Python CLOB client
- `Polymarket/agents` -- Official AI trading agent framework
- `luuisotorres/polymarket-intelligence` -- FastAPI+React tracker (most complete)
- `harish-garg/Awesome-Polymarket-Tools` -- Curated resource list
