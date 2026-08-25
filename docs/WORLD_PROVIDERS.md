# World Lens — provider ledger

*Started 2026-08-25 with Phase 0–2 of the World Lens (see
`WORLD_LENS_VISION.md` §"Commercial and licensing reality"). One row per
thing the World fetches, bundles or credits. A provider that is not on this
ledger is not in the product.*

| Provider | Used for | Terms | Attribution shown | Limits / notes |
|---|---|---|---|---|
| **Natural Earth** 10m `ne_10m_geography_marine_polys` | Region rings (Persian Gulf, Gulf of Oman, …) — `dialectic/data/natural_earth/marine.json`, provenance in the file's `meta` | Public domain | "Made with Natural Earth" — on the World's credit line and in every scope's `provenance.credit` | Curated pack taken from God's Eye View (MIT repo, PD data): outer rings, 0.01° simplification, rings stored open. Two features absent upstream as slivers (Drake Passage, Luzon Strait). |
| **OpenStreetMap** raster tiles `tile.openstreetmap.org` | The World basemap | ODbL data; tile usage policy asks for visible attribution and modest load | "© OpenStreetMap contributors" — on screen, in our own credit line | Two-founder product; well inside the policy. If the World ever becomes public or embedded, switch to a tile provider with a plan (Cesium ion Bing, MapTiler) — `mapStack` is one option away. |
| **Re:Earth / Mapterhorn** quantized-mesh terrain `terrain.reearth.land/cesium-mesh/ellipsoid` | Terrain under the globe (keyless) | CC BY 4.0 | "Terrain © Re:Earth / Mapterhorn (CC BY 4.0)" (rides the terrain provider's credit) | Falls back to the plain ellipsoid on any failure; nothing depends on it. |
| **CesiumJS** (npm `cesium` ^1.124, Apache-2.0) | The renderer, lazy-loaded chunk | Apache-2.0 | "CesiumJS" — the engine credit, replacing the default ion logo | No Cesium ion token, no ion assets. Static tree served from `/cesium/`, excluded from the PWA precache. |
| **Hand-authored geometry** (founders) | The Strait of Hormuz polygon and TSS inbound lane, labelled "(approx.)" | — | `provenance.credit`: "Hand-authored sketch by a Dialectic founder — approximate, not a chart." | Seeded by `deploy/seed_hormuz_geo.py`; redraw is an ordinary POST. Never a navigation product. |

## Deliberately not used

| Provider | Why not |
|---|---|
| Google Photorealistic 3D Tiles | Vision §Reject 5 — a billed, foundational dependency for a look. |
| TeleGeography submarine cables | CC BY-NC-SA; excluded from GEV's own MIT grant. |
| OpenSky Network | Non-commercial terms without a separate agreement. |
| OpenAI Realtime | The participant is Claude; no second agent authority. |

## Waiting on a decision before Phase 3

| Provider | What it would give | Open question |
|---|---|---|
| USGS earthquakes (PD, keyless) | Seismic events as `source_reported` scopes | None — first live adapter when Phase 3 opens. |
| adsb.lol `/v2/mil` (ODbL, keyless) | Military ADS-B | Attribution required; fine. |
| NASA FIRMS (CC0, free key) | Active fires | Key registration. |
| AISStream (beta, free key, websocket) | Vessels — the Hormuz layer | No formal terms published; owner decision. |
