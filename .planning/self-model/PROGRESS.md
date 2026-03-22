# Persistent Self-Model for Dialectic's LLM Orchestrator

## Status: IMPLEMENTATION COMPLETE — NEEDS LIVE TESTING
**Last updated:** 2026-03-22 03:40 UTC-5

## Goal
Give the LLM participant in Dialectic a persistent self-model — accumulated awareness of its own participation state, contribution patterns, and relationship to the conversation.

## Completed
- [x] Phase 1: Deep research on current orchestrator (see RESEARCH.md)
- [x] Phase 2: Architecture design (see ARCHITECTURE.md)
- [x] Phase 3: Schema migration (migrations/001_llm_self_model.sql — applied to DB)
- [x] Phase 4: Self-model module (llm/self_model.py — SelfModel, ParticipationSnapshot)
- [x] Phase 5: Wired into orchestrator (both speak and silence paths log decisions)
- [x] Phase 6: Wired into prompt builder (self_awareness parameter, injected after user models)
- [x] Phase 7: Effectiveness measurement (30s delayed background task)

## Not Yet Done
- [ ] Live conversation test (need to run the server and have humans talk)
- [ ] Wire self-awareness into force_response() and stream_response() paths
- [ ] Wire self-awareness into the second prompt_builder.build() call in force_response
- [ ] Session boundary detection (increment session_count on reconnect)
- [ ] Update llm_message_ratio and active_thread_count in reducer
- [ ] Iterate on prompt rendering based on observed behavior

## Files Modified
- `dialectic/migrations/001_llm_self_model.sql` — NEW: schema for llm_decisions + llm_participation_state
- `dialectic/llm/self_model.py` — NEW: SelfModel class, ParticipationSnapshot, decision logging, effectiveness measurement, prompt rendering
- `dialectic/llm/orchestrator.py` — MODIFIED: imports SelfModel, logs decisions on speak+silence paths, schedules effectiveness measurement
- `dialectic/llm/prompts.py` — MODIFIED: accepts self_awareness parameter, injects it into system prompt

## Architecture Summary
Three layers:
1. **Decision Log** (`llm_decisions` table): append-only record of every speak/silence decision with full context
2. **Participation Reducer** (`llm_participation_state` table): per-room derived state (turns, modes, confidence trend, effectiveness)
3. **Self-Awareness Prompt** (rendered into system prompt): the LLM reads its own participation state before deciding how to respond

## Resume Instructions
To continue this work in a new session:
1. Read this file and RESEARCH.md + ARCHITECTURE.md
2. The schema is already applied to the `dialectic` database
3. The code is wired in but needs live testing
4. Next priorities: test with running server, iterate on prompt rendering
