-- Migration 010: tool trace on the LLM decision log
--
-- WHY: The non-streaming heuristic path (orchestrator.on_message) now routes
-- through the tool loop just like the streaming path. The trace already lands
-- in messages.metadata; recording it on the decision row too lets the
-- self-model answer "what did I check before I said that" without joining
-- back to the response message.

ALTER TABLE llm_decisions ADD COLUMN IF NOT EXISTS tool_calls JSONB;
