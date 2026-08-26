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

## Amendment 2026-08-25 22:20 CDT — production Synapse status

Phase 3 Synapse is live from application commit `85fed38`, but it activates no
new external signal provider. CesiumJS, modest OSM rendering, optional Re:Earth
terrain, Natural Earth reference geometry, and human-authored approximate
scopes retain the active decisions above. `WorldSignalStore` remains empty and
unconfigured by design. AISStream, OpenSky, FIRMS, and USGS retain their exact
closed/excluded/thesis-unselected gates; production deployment does not alter
terms approval.

## Amendment 2026-08-26 — live signal adapters activated (amend-beside)

The owner's instruction was explicit: *"I need god's eye implementation in
dialectic to actually resemble and function like the god's eye github
project."* God's Eye View's whole claim is that **the sources are public and
the data is real**, so a World with no feed cannot satisfy it. Phase 4's
provider gate is therefore opened here, deliberately and per-provider. Prefer
this table over the closed/unselected rows above for the five providers named;
every other row stands unchanged.

`dialectic/world_adapters.py` is the only place any of this runs. It polls,
converts to bounded `WorldSignalSnapshot`s, and replaces one provider at a
time in the in-process `WorldSignalStore`. **It writes no database row and
creates no geography.** The authority ladder is untouched: a provider
observation becomes durable only when a person places it through
`api/geo.py`.

| Provider | Endpoint actually called | Key | Poll floor | Flag | State |
|---|---|---|---|---|---|
| USGS | `earthquakes/feed/v1.0/summary/all_day.geojson` | none | 5 min | `WORLD_SIGNALS_USGS_ENABLED` | **ON.** Public domain; the official programmatic interface USGS directs automated display clients to. The 2026-08-25 row called it "technically valid, thesis-unselected" — it is now selected. |
| adsb.lol | `api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{nm}` | none | job cadence (120 s) | `WORLD_SIGNALS_ADSB_ENABLED` | **ON.** Community ADS-B, ODbL, no key, no written-agreement clause. Chosen **instead of OpenSky**, whose terms above still require a written agreement for any live product — that exclusion stands and is not worked around. Credit string: "Data from adsb.lol (ODbL)". |
| wheretheiss.at | `v1/satellites/25544` | none | job cadence | `WORLD_SIGNALS_ISS_ENABLED` | **ON.** One request per poll, far inside the service's ~1/second guidance. One object: the ISS. |
| Launch Library 2 | `ll.thespacedevs.com/2.3.0/launches/upcoming/` | none | **30 min** | `WORLD_SIGNALS_LAUNCH_ENABLED` | **ON.** CC BY 4.0. The anonymous tier documents roughly fifteen requests an hour, which is why this adapter carries its own floor rather than riding the job's 120 s cadence. |
| NASA FIRMS | `api/area/csv/{key}/VIIRS_NOAA20_NRT/{bbox}/1` | **`FIRMS_MAP_KEY` required** | 10 min | `WORLD_SIGNALS_FIRMS_ENABLED` | **DARK until a key is set.** The 2026-08-25 row demanded an exact dataset ID rather than "FIRMS": this adapter names `VIIRS_NOAA20_NRT`, day range 1. With no key it reports `not_configured` and never touches the network — proven by a test that fails if it does. |

AISStream and OpenSky remain **CLOSED / EXCLUDED** exactly as recorded above.
Nothing here reaches either, and Google photorealistic tiles remain excluded.

### The room fence is the coverage boundary

God's Eye View shows the whole planet because it has no rooms. Signals here
are offered only to rooms that already own **accepted** geography, bounded by
their live scopes' bbox padded by 1.5°, capped at 24 rooms. A room that has
placed nothing receives nothing. The one deliberate exception is the ISS,
which is a global object and is offered to every configured room with its
`coverage` string saying so.

### Rendering acquired from God's Eye View

The six sensor shaders under
`dialectic/frontend/app/src/components/workspace/world/shaders/` are **copied
verbatim** from [God's Eye View](https://github.com/bilawalsidhu/gods-eye-view)
(**MIT License, Copyright (c) 2026 Bilawal Sidhu**), whose MIT grant covers
source code. Each file carries the notice in its header and the GLSL is left
unedited so upstream fixes re-apply by diff. Upstream's third-party carve-outs
are respected: **no** bundled dataset, **no** 3D model, and **no** provider
data was taken from that repository — every feed above is called directly and
appears in the table on its own terms.

The HUD readouts are **not** ported: upstream draws them inside the fragment
shader as seven-segment glyphs, which is invisible to a screen reader and
absent when WebGL is. `WorldHud.tsx` is ordinary DOM over the canvas, and
every number in it also exists in the complete text list below the globe.
