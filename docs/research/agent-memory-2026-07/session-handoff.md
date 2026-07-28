---
artifact_contract: "ce-handoff/v1"
created_at: "2026-07-28T07:51:38Z"
title: "Agent-memory research verdict + Dialectic transfer plan"
summary: "Deep-research review of a self-built agent-memory layer (17.8k memories, Supabase pgvector) published as a shareable artifact, with a verified list of which patterns to port into Dialectic's LLM participant."
keywords: ["agent-memory", "dialectic", "pgvector", "rrf-retrieval", "longmemeval", "deep-research", "artifact", "benchmarking"]
cwd: "/root/DwoodAmo"
resume_focus: "Act on the research: either build the LongMemEval-S three-arm benchmark harness, or start porting the three-lane RRF recall + speaker_id attribution into Dialectic's memory layer."
repository: "Skidudeaa/dialectic"
repo_root_sha: "19f08f20b2663520299a5547c700b1d1193b4ebb"
branch: "master"
head: "eb8545b"
worktree_path: "/root/DwoodAmo"
---

# Agent-memory research verdict + Dialectic transfer plan

## Objective and current intent

The user ran `/deep-research` on a third-party agent-memory layer (a public repo by another
author, `github.com/reescalder/agent-memory-supabase`) to answer two questions at once:

1. Is that architecture over-engineered, or convergent with the 2025–26 state of the art?
2. Which of its patterns should be ported into **Dialectic's** context-aware LLM participant —
   the three-way (two humans + LLM) dialogue engine in this repo?

The user then asked for the findings as a shareable artifact for **Dan**, the other human
participant in the Dialectic chat. Dan is the audience for the transfer recommendations.

**No repository code was written or modified this session.** The deliverable is research plus a
published artifact. `git status` changes present at session start were pre-existing.

## Work completed

- Ran the `deep-research` workflow (112 agents, 29 sources, 145 claims extracted, top 25 put
  through 3-vote adversarial verification: **11 confirmed, 14 refuted, 0 unverified**).
- Relayed the findings in chat.
- Built and published an HTML artifact, then redeployed it once to reorder sections.

## Authoritative references

- **Published artifact (live, private until shared):**
  `https://claude.ai/code/artifact/2d39bb19-b837-424a-8c7d-42c73ae209d1`
  Redeploy by republishing the same source file path from this conversation, or by passing that
  URL as `url` from any other conversation. Two versions exist: `initial-verdict`,
  `dialectic-first`.
- **Artifact source (machine-local, session-scoped scratchpad — see fragility warning):**
  `/tmp/claude-0/-root-DwoodAmo/d0bda5e4-a428-49c2-bffe-5e84ee7dcfa3/scratchpad/memory-verdict.html`
- **Full research output (machine-local, 231 KB JSON, the complete evidence record):**
  `/tmp/claude-0/-root-DwoodAmo/d0bda5e4-a428-49c2-bffe-5e84ee7dcfa3/tasks/wrq8tv3hd.output`
  Contains every confirmed finding with verbatim quotes, all 14 refuted claims with vote tallies,
  the caveats block, and the source list. **Read this before re-deriving anything.**
- **Per-agent journal:**
  `/root/.claude/projects/-root-DwoodAmo/d0bda5e4-a428-49c2-bffe-5e84ee7dcfa3/subagents/workflows/wf_7077900a-fe1/journal.jsonl`
- **Workflow script (re-runnable / resumable):**
  `/root/.claude/projects/-root-DwoodAmo/d0bda5e4-a428-49c2-bffe-5e84ee7dcfa3/workflows/scripts/deep-research-wf_7077900a-fe1.js`
  Resume with `Workflow({scriptPath: <above>, resumeFromRunId: "wf_7077900a-fe1"})` — unchanged
  agent calls replay from cache.

## The findings that matter for Dialectic

Ported from the verified research. Every item below is transfer-by-analogy: **no published prior
art exists on multi-party/group conversational memory** — that gap is explicit in the report, and
it governs all of it.

**Port:**
- Three-lane RRF recall (dense vector + Postgres FTS + entity), largely unchanged. Dialectic
  already has pgvector and 1536-d embeddings, so this is a query-function port.
- Add `speaker_id` to the entity lane, so a three-way conversation gets per-speaker attribution
  instead of one undifferentiated "user".
- Nullable-scope-column + optional-filter pattern → per-speaker vs. shared-room memory, shared
  tier as the null case. Note the inversion: soft scoping is arguably a *bug* in a single-user
  agent but is the *correct* default here, because three-way dialogue needs cross-speaker reads.
- Both dedup passes (cosine **and** `pg_trgm` trigram). Two humans restating the same point in
  different words is the common case; trigram catches what embeddings smooth over.

**Do not port:**
- Hierarchical/OS-style paging tiers. Measured at ~32.4s vs 1.0–1.5s per turn user-facing
  (arXiv:2602.19320 Table 5). Disqualifying for mid-conversation interjection.
- Inline entity extraction on the write path — it sits on the hot conversational loop here.
  Extract async off the event log if at all.

**Key architectural conclusion:** event sourcing does **not** make validity windows redundant.
The event log gives time-travel over what was *said*; validity windows track when a *fact was
true*. Two timelines. The recommended shape is to make supersession a **materialized projection
rebuilt from the event log** — log authoritative, memory table a fast index over it. This resolves
fork genealogy for free: a forked thread inherits the projection as-of the fork point and then
diverges, because the projection is a pure function of the ancestor event prefix.

**Latency budget for the interjection engine: ~1 second.** Flat-retrieval systems land at 1.0–1.5s
total/turn; full-context at 1.726s. One indexed RRF query plus generation is the only viable shape.

## Constraints and decisions worth preserving

- **Do not claim retrieval beats full-context on accuracy.** That evidence is split and both sides
  are vendors (Zep says yes, Mem0's own paper concedes full-context "can provide a slight accuracy
  edge"). Justify retrieval on **cost, latency, and context hygiene** only. Cost crossover is ~10
  turns at 100k context — and that test gave the long-context arm a 90% caching discount.
- **Four widely-repeated arguments were refuted 0–3** and must not be leaned on: that Anthropic's
  guidance endorses "nothing preloaded" (it actually recommends a hybrid for latency); that
  unbounded memory growth justifies pruning; that LLM-judge *relative* orderings are stable; that
  long-context consistently underperforms purpose-built memory. All 14 refutations are in the
  output JSON.
- **LoCoMo is not a usable gate** (50 conversations, ~26k tokens, ~6.4% answer-key error rate).
  Use LongMemEval-S as primary and MemoryAgentBench FactConsolidation for lifecycle/supersession.
- Highest-leverage single fact found: the **embedding model dominates the architecture around it**
  — a byte-identical pipeline swapping only the embedder moved LongMemEval-S 47.2% → 53.4%
  (+6.2pp, p=0.004), and naive top-k RAG on the strong embedder came within 1.2pp of Mem0. Any
  benchmark run **must** include a same-embedder naive-RAG control arm or it cannot attribute
  anything to architecture.

## Unfinished work / plausible next steps

The user was offered two paths and chose the artifact first. Both remain open:

1. **Build the LongMemEval-S three-arm harness** against Dialectic's memory layer — full-context
   baseline, naive top-k RAG on the identical embedder, full system. Pass condition: beat 53.4% by
   more than its 49.0–57.8 CI. This was ranked highest value per unit of effort.
2. **Start the Dialectic port** — three-lane RRF recall + `speaker_id` attribution, and/or
   restructure supersession as an event-log projection.

Not started, not scoped, no files touched for either.

## Fragile local state — warning

The artifact's HTML source and the full research output both live under
`/tmp/claude-0/-root-DwoodAmo/d0bda5e4-a428-49c2-bffe-5e84ee7dcfa3/`, a **session-scoped
scratchpad under OS-managed `/tmp`**. Both were confirmed present at handoff time (45 KB and
231 KB respectively). Neither is in version control. If a future session needs to edit the
artifact and that path is gone, the published page can still be read back with `WebFetch` against
its URL and re-authored, but the 231 KB evidence record has no other copy — **if the research
detail matters beyond this artifact, copy it somewhere durable before `/tmp` is reaped.** Nothing
was committed, stashed, copied, or torn down automatically.

Note also: this handoff itself sits in OS-managed `/tmp` and assumes the receiving session sees
the same host filesystem.

## Verification performed

- Research claims: 3 independent skeptics per claim, 2-of-3 needed to refute. Vote tallies are
  recorded per finding in the output JSON and surfaced as chips in the artifact.
- Repo audit of the third-party memory layer was done by reading its published `schema.sql`
  directly, not from its README — which is how the three claim/code discrepancies were found
  (absent LLM judge and regression gate; `filter_project DEFAULT NULL` making project isolation
  soft rather than hard; importance weighting only ~±20%).
- Artifact: published successfully twice, second deploy kept the same URL. **Not visually
  verified in a browser** — no render check was performed beyond authoring.

## Relevant installed skills

- `artifact-design` — was loaded to build the page; load it again before substantive redesign.
- `compound-engineering:ce-plan` / `ce-work` — for scoping and executing either next step above.
- `claude-reflect:reflect` — the global CLAUDE.md asks for a proactive `/reflect` at the end of
  substantial sessions. Not run here; this session produced no commit and touched no tracked
  files, but the learnings queue is only drained by an explicit invocation.
