# Orchestrator Research Findings

## Current Data Flow
Human message → WebSocket → Handler → Orchestrator (new instance per message!) → Heuristics (7-priority cascade) → Context Assembly → Prompt Build → Provider → Response → Self-Memory Extraction → Identity Distillation (on disconnect)

## Critical Finding: Orchestrator is Stateless
A **new** `LLMOrchestrator` is instantiated per WebSocket message (`api/main.py:1568`). No in-memory state survives between messages. The router cache is rebuilt each time.

## What IS Persisted Today
- LLM self-memories (`memories` table, `scope='llm'`): extracted positions/claims, upserted per topic
- Evolved identity (`memories` table, `key='llm_identity:{room_id}'`): distilled at session end
- User models (`memories` table, `key='user_model:{user_id}'`): distilled at session end
- Events (append-only log): every message, memory change, fork
- Message metadata: `model_used`, `prompt_hash`, `token_count`

## What is NOT Persisted (Self-Model Gaps)
1. **No interjection decision history** — OrchestrationResult + InterjectionDecision are ephemeral
2. **No temporal self-awareness in prompts** — LLM doesn't know "I last spoke 3 turns ago"
3. **No confidence tracking over time** — can't analyze "engine hesitating more lately"
4. **No intervention effectiveness** — no measurement of whether interjections engaged or fell flat
5. **No silence reasoning** — when LLM chooses NOT to speak, `considered_reasons` are discarded
6. **No session boundary awareness** — no "session #5" or "3 days since last talk"
7. **No mode history** — no tracking of primary vs provoker switching patterns
8. **No relational state** — no tension tracking, agreement patterns, topic trajectories

## The Seven Heuristics
| # | Name | Trigger | Confidence | Provoker? |
|---|------|---------|------------|-----------|
| 1 | Explicit mention | @llm in message | 1.0 | No |
| 2 | Turn threshold | 4+ consecutive human turns | 0.8 | No |
| 3 | Question detection | Regex: trailing ?, interrogative words | 0.7 | No |
| 4 | Information gap | 2+ unsurfaced relevant memories | 0.65 | No |
| 5 | Semantic novelty | novelty >= 0.7 | varies | **Yes** |
| 6 | Stagnation | 6 msgs, all TEXT, avg <100 chars | 0.6 | **Yes** |
| 7 | Speaker balance | 1 speaker has 70%+ of last 10 msgs | 0.55 | No |

## Extension Points
- `orchestrator.py:213-221` — early return on should_interject=False (log silence decisions)
- `orchestrator.py:293-301` — success return (log interjection decisions)
- `prompts.py:73-152` — build() method (inject temporal self-awareness)
- `heuristics.py:174-186` — no-trigger return (persist considered_reasons)
- `orchestrator.py:502-512` — post-response (effectiveness tracking)
- `api/main.py:1568` — orchestrator creation (make persistent or pass state)

## Key Files
- `llm/orchestrator.py` — central coordinator
- `llm/heuristics.py` — 7-heuristic decision engine
- `llm/prompts.py` — layered prompt assembly
- `llm/context.py` — smart context truncation
- `llm/identity.py` — identity distillation
- `llm/self_memory.py` — post-response claim extraction
- `transport/handlers.py` — WebSocket dispatch, bridge to orchestrator
- `models.py` — all enums and payload schemas
- `schema.sql` — database schema
