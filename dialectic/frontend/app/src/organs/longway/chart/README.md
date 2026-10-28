# Chart integration

`Chart.tsx` is the default `ChartProps` component and exports `LegCard`,
`SeasonStrip`, and `JourneyStrip`. Prefer importing the default from `chart/index`
(the React.lazy wrapper) and the named cards from that same entry. Cards live in
`Cards.tsx`, so eager cards do not import MapLibre. Wrap the chart in Suspense;
keep selection, focus, myth and the leg card in the Bench. `onDiscuss` receives
`(journey.slug, index)`. All CSS selectors are chart-scoped.

The map keeps one instance, updates its sources on projection changes, composes
myth/selection/focus filters and opacity, and removes markers, animation frames,
resize observation and the map on unmount. Coastlines are fetched once, including
across StrictMode replay. Tokens are inherited from the mounted chart's shell;
missing values fall back to the original globe's light palette. Canvas theme
changes require a remount (`ponytail` in `mapStyle.ts`).

## Original fixture

`fixtures/chart.json` is unmodified stdout from:

```
python3 /root/theLongWay/tools/longway.py chart
```

Captured 2026-10-28, SHA256
`eef2beb283dd1ac6c733368fe0d5af0b22cd01331491d5476b5d8f63b757d50f`.
It has 19 records, 18 with routes: `friends-2027` has `route: null` and no
segments (despite the TypeScript contract declaring an array). Ogasawara has a
dashed Tokyo–Chichijima leg and a pencil Chichijima–Hahajima extension. Eritrea's
slug is `eritrea-asmara-massawa`. Tests preserve these observed inputs, rather
than modifying the register to match the older examples. `fixtures/projection.ts`
adds only server-owned fields; all vehicles are never-heard in this offline
projection. The fix/age test supplies explicit synthetic fixes.

`public/longway/land-50m.json` is the original Natural Earth public-domain file;
SHA256 `619477ff690c086885e45cb91707d783805561bd75ae8e437b7d4694b0204e0f`.

## Checks and bounded preview

From `dialectic/frontend/app`:

```
npx vitest run src/organs/longway/chart
npm run build
npm run lint
node src/organs/longway/chart/verify-build.mjs
python3 -m http.server 4187 --bind 127.0.0.1 --directory /tmp/longway-chart-preview
```

The separate preview build checks the actual Rollup module graph: Chart is a
separate dynamic chunk, MapLibre is absent from eager imports, Cesium is absent
from the whole chart graph, and coastlines are not bundled. Its default output
is `/tmp/longway-chart-preview`; an alternate output directory can be passed as
the script's first argument. This is an isolated fixture harness, not the app's
entry or a live feed. Stop the preview server after use.

At implementation time the 10 mocked component tests, TypeScript, the main build,
and the lazy-Cesium verifier passed. A local Chrome/SwiftShader check at 390×844
rendered the original coastlines and 18 route labels, then Ogasawara with myth
and focus: three stop markers existed and only Tokyo and Chichijima were visible;
there was no horizontal overflow. Screenshots: `/tmp/longway-globe-390.png` and
`/tmp/longway-ogasawara-390.png`; receipt `/tmp/longway-browser.log` (its one resource
error is the preview's missing favicon). This is simulated browser evidence,
not a physical-device or live-feed check. Esri's configured fade is tested in the
style; the browser probe did not reach the imagery zoom range.

The largest remaining connection is shell-owned:
`src/organs/longway/LongwayBench.tsx` does not exist in this checkout. It must
mount the lazy chart and wire these props/cards to `useLongwayChart`. Therefore
the current trading `npm run build` passes but does not emit Chart; the independent
preview build does. No trading shell source or Vite configuration was changed.
