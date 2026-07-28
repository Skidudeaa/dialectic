# Agent memory research — July 2026

Durable copies of a `/deep-research` run reviewing a third-party agent-memory layer
(`github.com/reescalder/agent-memory-supabase`) and deriving what should be ported into
Dialectic's context-aware LLM participant.

Originals lived in a session-scoped scratchpad under OS-managed `/tmp` and were copied here
on 2026-07-28, verified by md5.

| File | What it is |
|---|---|
| `deep-research-output.json` | Full evidence record. 112 agents, 29 sources, 145 claims extracted, top 25 adversarially verified (11 confirmed, 14 refuted). Every finding carries verbatim source quotes, vote tallies and caveats. Read this before re-deriving anything. |
| `memory-verdict.html` | Source of the published artifact. Republish with the `Artifact` tool passing the URL below as `url` to keep the same link. |
| `session-handoff.md` | `ce-handoff/v1` session handoff. Note: its "no other copy" warning is superseded by this directory. |

**Published artifact:** https://claude.ai/code/artifact/2d39bb19-b837-424a-8c7d-42c73ae209d1
(private until shared from the page's share menu)

## The short version

The architecture reviewed is **convergent, not over-engineered** — it independently reproduces
what Zep/Graphiti ships and what Mem0 converged on in v3. Its real gap is measurement, not
sophistication.

Two conclusions that are easy to get wrong later, both verified:

- **Do not argue that retrieval beats full-context on accuracy.** The evidence is split and both
  sides are vendors. Justify retrieval on cost, latency and context hygiene instead.
- **Four widely-repeated claims were refuted 0–3** and cannot be leaned on — that Anthropic's
  guidance endorses "nothing preloaded", that unbounded memory growth justifies pruning, that
  LLM-judge relative orderings are stable, and that long-context consistently underperforms
  purpose-built memory. Details in the JSON under `refuted`.

## For Dialectic specifically

Port the three-lane RRF recall with `speaker_id` added to the entity lane, and both dedup passes.
Don't port paging tiers or inline entity extraction. Event sourcing does **not** make validity
windows redundant — the log records what was *said*, validity windows record when a fact was
*true*; make supersession a projection rebuilt from the event log and fork genealogy resolves for
free. Interjection latency budget is ~1 second.

Caveat governing all of the above: **there is no published prior art on multi-party conversational
memory.** It is transfer-by-analogy from 1:1 assistant systems.
