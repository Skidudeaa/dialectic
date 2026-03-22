# Persistent Self-Model Architecture

## Core Idea
The LLM participant maintains a persistent, queryable model of its own participation state. This model answers: "What have I been doing? What did I choose not to do? How are my contributions landing? What is the shape of this conversation?"

## Three Layers

### Layer 1: Decision Log (Observable Truth)
Every time the orchestrator runs — whether the LLM speaks or stays silent — persist the full decision trace.

New table: `llm_decisions`
```sql
CREATE TABLE llm_decisions (
    id BIGSERIAL PRIMARY KEY,
    room_id UUID NOT NULL REFERENCES rooms(id),
    thread_id UUID NOT NULL REFERENCES threads(id),
    triggered_by_message_id UUID REFERENCES messages(id),
    decided_at TIMESTAMPTZ DEFAULT NOW(),
    should_interject BOOLEAN NOT NULL,
    reason TEXT NOT NULL,
    confidence REAL NOT NULL,
    use_provoker BOOLEAN NOT NULL,
    considered_reasons TEXT[] NOT NULL DEFAULT '{}',
    human_turn_count INTEGER,
    semantic_novelty REAL,
    unsurfaced_memory_count INTEGER,
    speaker_balance JSONB,
    response_message_id UUID REFERENCES messages(id),
    mode TEXT NOT NULL  -- 'primary' | 'provoker' | 'protocol' | 'mention' | 'annotator'
);
```

This is the sidecar's "raw events" equivalent — append-only truth.

### Layer 2: Participation State (Reduced/Derived)
A per-room reducer that maintains the LLM's current self-model. Updated after each decision.

New table: `llm_participation_state`
```sql
CREATE TABLE llm_participation_state (
    room_id UUID PRIMARY KEY REFERENCES rooms(id),
    -- Temporal awareness
    last_spoke_at TIMESTAMPTZ,
    last_spoke_message_id UUID,
    turns_since_last_spoke INTEGER DEFAULT 0,
    total_messages_sent INTEGER DEFAULT 0,
    total_silences INTEGER DEFAULT 0,
    -- Mode tracking
    primary_count INTEGER DEFAULT 0,
    provoker_count INTEGER DEFAULT 0,
    last_mode TEXT,
    -- Confidence trajectory
    avg_confidence_last_10 REAL,
    confidence_trend TEXT,  -- 'rising' | 'falling' | 'stable'
    -- Contribution balance
    llm_message_ratio REAL,  -- LLM messages / total messages
    avg_response_length INTEGER,
    -- Effectiveness signals
    avg_human_response_length_after INTEGER,
    questions_asked_after INTEGER,
    ignored_count INTEGER DEFAULT 0,  -- LLM spoke, no human response within 3 msgs
    -- Conversation shape
    active_thread_count INTEGER,
    total_fork_count INTEGER,
    last_memory_operation_at TIMESTAMPTZ,
    -- Session awareness
    current_session_start TIMESTAMPTZ,
    session_count INTEGER DEFAULT 0,
    days_since_last_session REAL,
    -- Updated tracking
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Layer 3: Self-Awareness Context (Prompt Injection)
The self-model is rendered into the prompt so the LLM *knows* its own state. New section in prompt assembly between identity and room context:

```
## Your Participation State (This Conversation)
- You last spoke 7 turns ago (3 minutes)
- You've been in primary mode for 4 of your last 5 contributions
- Your last 3 interjections received engaged responses (avg 180 chars)
- 1 recent interjection was ignored (no human response within 3 messages)
- You chose silence 4 times since your last message (reasons: low novelty, speaker balance ok)
- Conversation is across 2 active threads, 1 fork point
- This is session #3 with these participants (last session: 2 days ago)
- Context: 45% of window used, 2 compaction-risk memories
- Your confidence has been stable (avg 0.72 over last 10 decisions)
```

## Implementation Order

### Step 1: Schema migration
Add `llm_decisions` and `llm_participation_state` tables.

### Step 2: Decision logger
After every `on_message()` call (both speak and silence paths), persist the InterjectionDecision + context to `llm_decisions`.

### Step 3: Participation reducer
A `ParticipationReducer` class that:
- Takes a decision log entry
- Updates `llm_participation_state` for that room
- Computes derived metrics (confidence trend, effectiveness, balance)

### Step 4: Self-awareness prompt section
New function in `prompts.py` that queries the participation state and renders it as a prompt section.

### Step 5: Effectiveness tracker
Background task (like self-memory extraction) that runs after each LLM message to measure human response engagement.

### Step 6: Session boundary detection
On WebSocket connect, check time since last LLM message in room. If > 1 hour, increment session_count and set days_since_last_session.
