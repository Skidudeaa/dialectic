---
title: "Stored XSS in generated HTML dashboards via unescaped JSON config values"
date: 2026-03-31
category: security-issues
module: thesis-graph-engine
problem_type: security_issue
component: tooling
symptoms:
  - "Config values injected raw into HTML template markers (__TITLE__, __CLAIM__, __AS_OF__)"
  - "~40 innerHTML interpolation sites in embedded JS used config strings without escaping"
  - "importState() loads user-selected JSON and renders via innerHTML with no sanitization"
  - "bookgen.py f-string interpolation of config text into HTML situation/provenance sections"
root_cause: missing_validation
resolution_type: code_fix
severity: critical
tags:
  - xss
  - html-escape
  - innerhtml
  - json-config
  - html-generation
  - template-injection
  - security-review
---

# Stored XSS in Generated HTML Dashboards via Unescaped JSON Config Values

## Problem

The thesis graph engine (`thesisgraph.py`, ~2300 lines) and legacy `bookgen.py` generate self-contained HTML dashboards by substituting JSON config values into HTML templates via string replacement. Three XSS attack surfaces existed: server-side template markers, client-side innerHTML assignments, and legacy f-string interpolation. A crafted config JSON could execute arbitrary JavaScript in the viewer's browser, with full access to localStorage (positions, journal, portfolio state).

## Symptoms

- No `html.escape()` calls anywhere in the codebase
- Config values appeared raw in `<title>` tags, `content="..."` attributes, and innerHTML assignments
- A malicious config JSON with `"title": "</title><script>alert(1)</script>"` would execute arbitrary JavaScript
- `importState()` loads user-selected JSON files and renders them via innerHTML — a direct DOM XSS path requiring no config regeneration

## What Didn't Work

This vulnerability was discovered through a structured 7-agent code review (compound engineering review), not a reported incident. No prior fix attempts existed — the escaping requirement was missed during initial development because the JSON configs were treated as trusted internal data.

## Solution

Three-layer fix applied across the codebase:

### 1. Server-side Python escaping (`thesisgraph.py`, `bookgen.py`)

```python
import html as html_mod  # alias avoids collision with local `html` variable

# In generate_html():
esc = lambda s: html_mod.escape(s, quote=True)
replacements = {
    "__TITLE__": esc(title),
    "__AS_OF__": esc(as_of),
    "__CLAIM__": esc(claim),
    # ... JS object literals (json.dumps output) are NOT escaped
}
```

`quote=True` is critical — `__CLAIM__` appears in a `content="..."` attribute context where unescaped quotes break out of the attribute.

### 2. Client-side JavaScript escaping (embedded in `JS_LOGIC` string)

```javascript
function esc(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
```

Applied to ~30 innerHTML interpolation sites across `renderNodeDetail`, `renderJournal`, `renderCascade`, `renderScenarios`, `renderPortfolio`, and `renderMarketBar`:

```javascript
// Before (vulnerable):
let h = `<div class="nd-title">${node.label}</div>`;
// After (safe):
let h = `<div class="nd-title">${esc(node.label)}</div>`;
```

### 3. Legacy bookgen.py

Same `html_mod.escape(quote=True)` treatment on title, subtitle, claim, and all `build_situation_html`/`build_provenance_html` interpolations.

## Why This Works

The root cause was that config-sourced text was treated as trusted HTML. In this architecture, JSON configs are the primary attack surface — they're shared between users, imported at runtime via `importState()`, and their values flow into both Python-generated HTML and browser-rendered DOM. Escaping at the output boundary (template substitution and innerHTML assignment) neutralizes injection regardless of input source.

The key distinction: `json.dumps()` output for `NODES`, `SCENARIOS`, etc. are JavaScript object literals parsed by the JS engine, not HTML text — they do **not** need HTML escaping. Only values that land in HTML text content or attribute contexts need escaping.

## Prevention

1. **New innerHTML sites:** Any new innerHTML assignment in the JS template must use `esc()` on config-sourced values. Values from code (computed colors, numeric calculations, state strings from a fixed enum) do not need escaping.
2. **New template markers:** Any new `__MARKER__` in `generate_html()` that carries user-provided text must use `html_mod.escape(value, quote=True)` before substitution.
3. **Do not escape JS object literals:** The `json.dumps()` output for NODES, SCENARIOS, CASCADE, etc. must not be escaped — they are JS code, not HTML text.
4. **Test with XSS payloads:** Generate HTML with payloads like `"<script>alert(1)</script>"` and `"'><img src=x onerror=alert(1)>"` in config title/claim/context fields, then verify the output contains only escaped entities.
5. **importState() is a high-risk path:** Any imported JSON state file has its values rendered via innerHTML. The `esc()` function in the render pipeline is the only defense — there is no server-side validation on import.

## Related Issues

- Implementation plan: `docs/plans/2026-03-31-001-fix-48h-review-findings-plan.md` (Unit 3)
- Precedent: Sextant XML injection solution uses the same defense-in-depth pattern (encode at generation + strip at emission)
- The Dialectic integration plan documents a similar 3-layer defense for LLM prompt injection
- Affected files: `tools/thesis_graph/thesisgraph.py`, `tools/commodity-book/bookgen.py`
