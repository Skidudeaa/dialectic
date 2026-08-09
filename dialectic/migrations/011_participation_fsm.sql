-- Migration 011: participation FSM columns on the self-model state
--
-- WHY: W6 adds a per-room participation state machine (llm/participation_fsm.py)
-- that drives the silence sweep. The machine is stateless between turns — the
-- DB row is its memory — so the FSM's state, when it entered that state (the
-- sweep's 10-minute clock keys off this), and the confidence tier of the
-- state (observed / reconciled / inferred) live beside the rest of the
-- self-model's participation reducer.

ALTER TABLE llm_participation_state ADD COLUMN IF NOT EXISTS fsm_state TEXT;
ALTER TABLE llm_participation_state ADD COLUMN IF NOT EXISTS state_entered_at TIMESTAMPTZ;
ALTER TABLE llm_participation_state ADD COLUMN IF NOT EXISTS state_source TEXT;
