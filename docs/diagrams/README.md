# Diagrams

## `dialectic-architecture` — the system map (2026-08-13)

One page covering all three co-projects: the dialectic backend and its LLM
participant, the tradingDesk seam, the datastores, and the two things that are
in the tree but **not** in production (`cc-sidecar`, `packages/`).

| File | What it's for |
|---|---|
| `dialectic-architecture.drawio` | **Source of truth.** Edit this. |
| `dialectic-architecture.drawio.png` | 3835×2585, diagram XML embedded — opening it in draw.io recovers the editable diagram. |
| `dialectic-architecture.svg` | Vector, XML embedded. For docs/README embeds. |
| `architecture-map.html` | Self-contained viewer (SVG inlined, no network) + the write-up of what the docs had wrong. |

Colour encodes **role**, not layer: purple = the LLM participant, amber = the
clock, orange = anything that speaks HTTP to another process, green = a
datastore, dashed grey = external or not running.

### Drawn from the code, not from the docs

Every label was sourced from a call site. Five CLAUDE.md claims turned out to
have drifted — the corrections are recorded in the root `CLAUDE.md` under
**"Amendment 2026-08-13"**, and the diagram shows the code's version. Two claims
were checked and confirmed (the seam's hourly heartbeat; cc-sidecar being
pattern-donor only). If you change the diagram, keep that property: verify at
the call site, don't copy a label out of a doc.

`cc-sidecar` is drawn **unconnected on purpose.** Nothing imports it and no unit
runs it — an edge would imply a runtime coupling that does not exist.

### Regenerating the exports

The draw.io desktop CLI is installed at `/usr/bin/drawio` (v31.1.8, from the
jgraph `.deb`). This box is headless and runs as root, so exports need `xvfb-run`
**and** `--no-sandbox` — and the flag must come **last**, or drawio treats it as
the input filename.

```bash
cd docs/diagrams
export HOME=/root

# Editable PNG (the deliverable)
xvfb-run -a --server-args="-screen 0 1600x1200x24" \
  drawio -x -f png -e -s 2 -b 10 \
  -o dialectic-architecture.drawio.png dialectic-architecture.drawio --no-sandbox

# REQUIRED after any -e PNG export: drawio truncates the IEND chunk (8 bytes),
# which makes strict decoders and vision APIs reject the file.
python3 ~/.claude/plugins/cache/365-skills/drawio/*/skills/drawio-skill/scripts/repair_png.py \
  dialectic-architecture.drawio.png

# SVG (no IEND problem — SVG is text)
xvfb-run -a --server-args="-screen 0 1600x1200x24" \
  drawio -x -f svg -e -b 10 \
  -o dialectic-architecture.svg dialectic-architecture.drawio --no-sandbox
```

Two gotchas worth keeping:

- **Don't pass `-e` when exporting a PNG you intend to *look at*** (a review
  preview, a vision check) — the embedded-XML chunk makes vision APIs return
  400. Export that one without `-e` and cap it with `--width 2000`; `-s 2`
  overshoots the 2576px ceiling on a diagram this size.
- `scripts/validate.py` reports `edge routes through vertex` for the
  scheduler→proactive edge. That is a **false positive**: the edge's waypoints
  are in its parent swimlane's coordinate space and the validator reads them as
  absolute. The rendered output is correct — check the PNG, not the linter.

To rebuild `architecture-map.html` after editing the diagram, re-export a
no-`-e` SVG and re-inline it; the page is plain HTML with the SVG pasted in.
