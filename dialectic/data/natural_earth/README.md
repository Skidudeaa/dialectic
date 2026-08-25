# Natural Earth marine polygons

`marine.json` — 292 named seas, gulfs, straits and bays from Natural Earth
10m physical vectors (`ne_10m_geography_marine_polys`), **public domain**
(https://www.naturalearthdata.com/about/terms-of-use/). Exact provenance —
source URL, upstream commit `ca96624a56bd078437bca8184e78163e5039ad19`,
fetch time, curation parameters — is in the file's own `meta` header.

Taken 2026-08-25 from the God's Eye View curated pack
(https://github.com/bilawalsidhu/gods-eye-view, MIT; the pack itself is PD
data). Rings are stored OPEN (no closing vertex), simplified at 0.01°,
outer rings only. `deploy/seed_hormuz_geo.py` closes a ring before it
reaches `geo_scopes.validate_geometry`.

Credit line to show wherever a region from this file renders:
"Made with Natural Earth" (voluntary; not legally required).

NOT taken from that pack: `regions.json` (not needed yet), and nothing from
`telegeography_submarine_cables/` (CC BY-NC-SA — excluded on purpose).
