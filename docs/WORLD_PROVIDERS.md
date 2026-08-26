# World Lens provider ledger

Checked against primary/official sources on **2026-08-25**. Technical
feasibility is not provider approval. No live signal provider is configured on
`codex/world-lens-truth-before-spectacle`.

## Active rendering and durable-reference inputs

| Provider | Current use | Operating / terms boundary | Decision |
|---|---|---|---|
| [Natural Earth](https://www.naturalearthdata.com/about/terms-of-use/) 10m marine geography | Curated region rings in `dialectic/data/natural_earth/marine.json` | Public domain; preserve source metadata and “Made with Natural Earth.” | **Active** as name-to-existing-geometry reference, not a live feed. |
| [OpenStreetMap standard raster tiles](https://operations.osmfoundation.org/policies/tiles/) | Interactive World basemap | Community tiles are best-effort with **no SLA** and may block without notice. Visible attribution, normal browser Referer/User-Agent, cache-header compliance (or at least 7 days where headers cannot be read), and the exact HTTPS URL are required. Bulk download, prefetch, offline packs, cache bypass, and headless viewport scraping are prohibited. | **Active only for modest interactive use.** Public/commercial growth must move to an OSM-derived provider or self-hosting. |
| [Re:Earth](https://github.com/reearth/reearth-terrain) / Mapterhorn terrain | Optional terrain | CC BY 4.0 attribution; failure falls back to ellipsoid and cannot alter evidence truth. | **Active optional rendering layer.** |
| [CesiumJS](https://github.com/CesiumGS/cesium/blob/main/LICENSE.md) | Lazy World renderer | Apache-2.0. No Cesium ion token or ion asset dependency. | **Active renderer.** `/cesium/` and the lazy chunk remain outside PWA precache. |
| Founder-inspected approximate geometry | Hormuz polygon and lane | Explicit named-human attribution; approximate, not a navigational chart. Migration 022 makes every correction append-only. | **Durable only after human inspection/ratification.** |

## Closed live-provider gates

| Provider | Official technical contract checked 2026-08-25 | Decision |
|---|---|---|
| [AISStream documentation](https://aisstream.io/documentation) | Server-side WSS with API key; direct browser connections forbidden. The service states **no SLA or uptime guarantee** and events are **not durably replayed**; slow consumers may lose buffered messages. Reconnect requires backoff and a complete replacement subscription. The official site exposes documentation and a privacy policy, but no service/data license sufficient for Dialectic product redistribution was found; absence is not consent. | **CLOSED.** Requires explicit owner terms/license/redistribution decision, outage/replay semantics, bounded Hormuz subscription, and ordinary-use value proof. |
| [OpenSky terms of use](https://opensky-network.org/about/terms-of-use) | Operational REST use in any live product/service/automated system requires a **previous written agreement**, even for non-profit/governmental entities; commercial/for-profit use also requires written permission/license. | **EXCLUDED unless a written agreement is executed and recorded.** |
| [NASA FIRMS Area API](https://firms.modaps.eosdis.nasa.gov/api/area/) | Exact contract: `/api/area/csv/[MAP_KEY]/[SOURCE]/[AREA_COORDINATES]/[DAY_RANGE]` plus optional date. A free **FIRMS MAP_KEY** is mandatory; documented limit is 5,000 transactions per 10 minutes. The adapter must choose and record an exact dataset ID (`VIIRS_SNPP_NRT`, `VIIRS_NOAA20_NRT`, `VIIRS_NOAA21_NRT`, `MODIS_NRT`, or a standard-processing counterpart); “FIRMS” alone is not a dataset. Day range is 1–5. [Data availability](https://firms.modaps.eosdis.nasa.gov/api/data_availability/) governs current dates. | **CLOSED.** Key possession proves only transport. Requires exact dataset, bounded area/day/budget, latency/false-positive semantics, attribution, and thesis-value selection. |
| [USGS earthquake GeoJSON](https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php) / [FDSN event service](https://earthquake.usgs.gov/fdsnws/event/1/wsdl) | GeoJSON is an official programmatic interface; USGS directs automated display clients to real-time GeoJSON for best performance/availability. | **TECHNICALLY VALID, THESIS-UNSELECTED.** Do not activate merely because it is easy. |

## Excluded or not selected

- Google Photorealistic 3D Tiles: billed foundational spectacle without causal
  value.
- TeleGeography cables: noncommercial/share-alike data outside the upstream
  repository's MIT grant.
- `adsb.lol`: not selected in the approved Task 1–5 architecture; any future
  proposal requires its own current terms and value review.
- No provider may write `GeoScope` on poll. Provider bytes remain ephemeral
  `WorldSignal` snapshots until a human places one through the canonical
  append-only door.
