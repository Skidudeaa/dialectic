-- 025: drop the multi-model persona feature (owner decision 2026-08-29).
-- Never routed back through memory/tools/self-model -- a second speaking
-- path bypassing the participant's own discipline. Verified against
-- production before dropping: 1 orphan room_personas row, 0 messages with
-- speaker_type='llm_persona', 0 messages.persona_id set.
ALTER TABLE messages DROP COLUMN IF EXISTS persona_id;
DROP TABLE IF EXISTS room_personas;
