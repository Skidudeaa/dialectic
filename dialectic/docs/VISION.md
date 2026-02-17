# Dialectic: Vision Document

*From "built" to "I can't stop using this"*

---

## I. What Dialectic Actually Is

Dialectic is not a chat app with an AI bolted on. It is a **collaborative reasoning engine** where two humans and an LLM think together as equals. The LLM is not waiting to be asked -- it is watching, judging, and choosing when to speak based on configurable heuristics. It can challenge, provoke, synthesize, or stay silent. Conversations fork like evolutionary branches, creating a living tree of ideas.

This is the only platform where:

1. **The AI has agency over its own speech** -- it interjects based on turn count, semantic novelty, stagnation detection, and explicit mention. It chooses between two personas: a co-thinker ("primary") and a destabilizer ("provoker").
2. **Conversations evolve biologically** -- any message can become a fork point, creating a cladogram of divergent reasoning paths. Each fork inherits its ancestor's memories up to the fork point.
3. **Philosophical calibration is first-class** -- per-user `aggression_level` and `metaphysics_tolerance` sliders, room-level ontologies and rules, and a layered prompt system that blends all participants' preferences into a single coherent voice.
4. **Knowledge is versioned and contestable** -- shared memories are not just notes. They have versions, embeddings, invalidation chains, and cross-room semantic references. A memory can be promoted from room-scope to global, creating a personal knowledge graph that spans all conversations.

The backend is substantial: event sourcing, vector memory with pgvector, cascading LLM fallback chains, smart context truncation, cross-session memory injection, presence tracking, push notifications, and full-text search. The raw infrastructure for something extraordinary exists.

**But nobody can use it yet.**

---

## II. The Immediate Path to Usability

Before any "next level" features matter, three things must be true:

### 1. One-Command Launch

A new user clones the repo and runs `docker compose up`. Within 60 seconds they see a login screen. They register, create a room, invite a friend via link, and start reasoning with Claude.

**What this requires:**
- `docker-compose.yml` with PostgreSQL (+ pgvector), the FastAPI backend, and a static file server for the web frontend
- A seed script that creates the database schema, enables the pgvector extension, and optionally loads a demo room
- Environment variable templating (`.env.example`) with clear instructions for adding API keys
- The web frontend served as the default entry point

### 2. Auth Wired to Core

The auth module exists (`api/auth/`) with JWT tokens, email verification, sessions, and PIN support. But the core WebSocket endpoint and REST routes do not enforce authentication. Anyone can connect as any user by passing a `user_id` query parameter.

**What this requires:**
- WebSocket connections must validate JWT tokens on handshake
- REST endpoints must use the `get_current_user` dependency from `api/auth/dependencies.py`
- Remove the ability to self-declare `user_id`

### 3. The Web Frontend Works End-to-End

The single-file `index.html` is the most complete UI. It needs to be validated against the current API surface: does login work? Does room creation work? Does the WebSocket handshake succeed with auth? Does streaming display correctly? Does forking work?

If there are gaps, they need to be closed. The web frontend is the proof-of-life for the entire system.

---

## III. First-Run Magic

The moment someone opens Dialectic for the first time determines whether they come back. Here is what should happen:

### The "Overture" Experience

1. **Register with one field** -- display name (email optional for beta). Instantly land in a demo room called "The Agora."

2. **The Agora** is pre-seeded with a conversation between two fictional users and Claude, demonstrating what Dialectic does. The conversation shows:
   - A human making a claim
   - The other human pushing back
   - Claude interjecting with a synthesis that neither human anticipated
   - A fork point where the conversation branches
   - A shared memory being created, then edited, then referenced later

3. **The user can scroll through this conversation**, then click "Join" to become a participant. Claude acknowledges the new arrival and asks a provocative question related to the existing thread.

4. **A tooltip tour** highlights the unique controls: the fork button on any message, the memories panel, the LLM settings (aggression, metaphysics tolerance), and the thread cladogram.

5. **After the first exchange**, a prompt appears: "Create your own room?" with one-click room creation.

This is not a tutorial. It is an experience that demonstrates the *feel* of three-way reasoning before demanding any investment from the user.

---

## IV. Five "Two Steps Beyond" Feature Designs

### Feature 1: Dialectic Replay

**The idea:** Re-experience any conversation as it unfolded in real time, like watching a chess game replay. Messages appear at their original pace. The LLM's "thinking" indicator pulses before its interjections. Forks branch visually as they were created.

**Why it matters:** Conversations are temporal objects. Reading a transcript misses the rhythm -- the long pause before a devastating question, the rapid-fire exchange when two people lock into an argument, the moment the LLM chose to stay silent vs. when it interrupted. Replay reveals the *dynamics* that make a conversation great.

**Implementation design:**

The foundation already exists: every state change is an event in the `events` table with a timestamp. Replay is literally replaying the event stream.

```
New endpoint: GET /api/rooms/{room_id}/threads/{thread_id}/replay

Response: Server-Sent Events stream

Each event:
{
  "event_type": "message_created" | "thread_forked" | "memory_added" | ...,
  "original_timestamp": "2025-03-15T14:23:07Z",
  "delay_ms": 4200,  // Time since previous event
  "payload": { ... }  // Original event payload
}
```

**Client behavior:**
- Render events with configurable playback speed (1x, 2x, 4x, 8x)
- Show a timeline scrubber at the bottom
- Pause/resume with spacebar
- Click any point in the timeline to jump
- Display a "heat map" above the timeline: dense red = intense exchange, sparse blue = reflection
- Show the LLM's `InterjectionDecision` metadata alongside its messages: "Triggered by: stagnation_detected, confidence: 0.6, persona: provoker"

**The insight this unlocks:** Users start to understand *why* the LLM speaks when it does. They tune their heuristic settings not abstractly, but by watching the replay and thinking "it should have spoken here" or "it should have stayed quiet there." The LLM becomes a calibratable instrument, not a black box.

**Schema additions:**
```sql
-- Replay sessions (for sharing replays)
CREATE TABLE replay_sessions (
    id UUID PRIMARY KEY,
    thread_id UUID NOT NULL REFERENCES threads(id),
    created_by_user_id UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL,
    start_event_sequence BIGINT,  -- Optional: start from specific point
    end_event_sequence BIGINT,    -- Optional: end at specific point
    speed_multiplier FLOAT DEFAULT 1.0,
    annotations JSONB DEFAULT '[]',  -- User-added annotations at specific timestamps
    is_public BOOLEAN DEFAULT FALSE  -- Shareable link
);
```

---

### Feature 2: Conversation DNA

**The idea:** Every conversation has a unique character -- some are argumentative duels, others are collaborative explorations, some spiral into productive chaos. Conversation DNA is a real-time visual fingerprint that captures this character across multiple dimensions, rendered as a distinctive glyph that evolves as the conversation progresses.

**Why it matters:** When you have dozens of rooms, you need to see at a glance what *kind* of thinking is happening. Conversation DNA replaces "Room 7 - Last message 2 hours ago" with an immediate visceral sense of the room's intellectual character.

**The dimensions (computed from message data):**

1. **Dialectical tension** (0-1): How much disagreement vs. agreement. Computed from counter-examples, "but" statements, question density, and LLM provoker frequency.

2. **Velocity** (0-1): Message frequency over time. High velocity = rapid exchange. Low = contemplative pauses.

3. **Asymmetry** (0-1): How evenly distributed is participation? 0 = one person dominating. 1 = perfectly balanced three-way.

4. **Depth** (0-1): Average message length, presence of structured types (CLAIM, DEFINITION, COUNTEREXAMPLE), and reference density.

5. **Divergence** (0-1): How many forks exist? How far apart are the active threads? High divergence = exploratory conversation.

6. **Memory density** (0-1): How many memories have been created, edited, or invalidated relative to message count? High = concept-formation conversation.

**Visual rendering:**

Each dimension maps to a parameter of a generative shape (a radial visualization or a waveform). The shape is unique for each conversation and updates live. Conversations with similar DNA cluster visually.

**Implementation:**

```python
# New module: dialectic/analytics/dna.py

@dataclass
class ConversationDNA:
    thread_id: UUID
    computed_at: datetime
    tension: float
    velocity: float
    asymmetry: float
    depth: float
    divergence: float
    memory_density: float

    @property
    def fingerprint(self) -> str:
        """6-char hex encoding of DNA for display."""
        values = [self.tension, self.velocity, self.asymmetry,
                  self.depth, self.divergence, self.memory_density]
        # Each value maps to 0-15, then hex-encode
        return ''.join(hex(min(15, int(v * 15)))[2:] for v in values)

    @property
    def archetype(self) -> str:
        """Human-readable conversation type."""
        if self.tension > 0.7 and self.velocity > 0.6:
            return "Crucible"  # Intense, fast-paced debate
        if self.depth > 0.7 and self.velocity < 0.3:
            return "Deep Dive"  # Slow, thorough exploration
        if self.divergence > 0.6:
            return "Rhizome"  # Branching, exploratory
        if self.asymmetry < 0.3 and self.tension < 0.4:
            return "Symposium"  # Balanced, collaborative
        if self.memory_density > 0.6:
            return "Forge"  # Concept-building
        return "Open Field"
```

**New endpoint:**
```
GET /api/rooms/{room_id}/dna
GET /api/rooms/{room_id}/threads/{thread_id}/dna
```

**Frontend integration:** The DNA glyph replaces or augments the room card in the room list. Users see at a glance: "The Ethics room is a *Crucible* right now" vs "The Epistemology room is in *Deep Dive* mode."

---

### Feature 3: Counterfactual Forking ("What If" Mode)

**The idea:** Select any message in the conversation history and ask: "What if the conversation had gone differently from here?" The LLM replays from that fork point, generating plausible alternative responses for all participants (including the other human), creating a ghost thread that shows an alternate timeline.

**Why it matters:** This is the feature that makes Dialectic a *thinking tool* rather than just a communication tool. It lets you explore the landscape of possible conversations, not just the one that happened. It turns every conversation into a choose-your-own-adventure for ideas.

**How it differs from regular forking:** Regular forking creates a new thread where *real humans* continue from a fork point. Counterfactual forking creates a *simulated* thread where the LLM impersonates all participants based on their established patterns, exploring an alternative path autonomously.

**Implementation design:**

```python
# New WebSocket message type
MessageTypes.COUNTERFACTUAL_FORK = "counterfactual_fork"

# Payload
{
    "fork_after_message_id": "uuid",
    "divergence_prompt": "What if Alice had agreed instead of disagreeing?",
    "max_turns": 10,  # How many simulated turns to generate
    "temperature": 0.9  # Higher = more creative divergence
}
```

**The LLM prompt for counterfactual generation:**

```
You are replaying an alternative version of a conversation. The real conversation
diverged at the message marked [FORK POINT]. Generate what MIGHT have happened
if the conversation had gone differently.

The user has suggested this divergence: "{divergence_prompt}"

You must simulate ALL participants, including:
{for user in users}
- {user.display_name}: Style modifier="{user.style_modifier}",
  aggression={user.aggression_level},
  metaphysics_tolerance={user.metaphysics_tolerance}
{endfor}

Generate {max_turns} messages, alternating between participants naturally.
Mark each message with the speaker's name. Stay true to each person's
established voice and positions, but allow the divergence to create
genuinely different outcomes.

Format each message as:
[SPEAKER: display_name]
message content

[SPEAKER: display_name]
message content
```

**Frontend rendering:** Counterfactual threads appear as dashed lines in the cladogram, with ghosted message bubbles. They are visually distinct from real conversation forks. Users can "promote" a counterfactual thread to a real thread if they want to continue the alternate timeline with actual human participation.

**Schema:**
```sql
ALTER TABLE threads ADD COLUMN is_counterfactual BOOLEAN DEFAULT FALSE;
ALTER TABLE threads ADD COLUMN counterfactual_prompt TEXT;
ALTER TABLE messages ADD COLUMN is_simulated BOOLEAN DEFAULT FALSE;
ALTER TABLE messages ADD COLUMN simulated_speaker_user_id UUID;  -- Who the LLM was impersonating
```

---

### Feature 4: Intellectual Resonance Network

**The idea:** Dialectic knows who you reason well with. By analyzing conversation patterns across rooms, it builds an "intellectual resonance" graph that shows which pairs of thinkers produce the most productive conversations, which topics create the most heat between specific people, and which combinations of people + topic + LLM configuration produce breakthrough moments.

**Why it matters:** Finding the right thinking partner is one of the hardest problems in intellectual life. Dialectic has the data to solve it -- not through simplistic compatibility scoring, but through deep analysis of conversational dynamics.

**What "resonance" means (formally):**

Two participants have high resonance when their conversations exhibit:
- **Productive tension**: high disagreement that resolves into synthesis (not circular argument)
- **Idea amplification**: concepts introduced by one person get extended and refined by the other
- **Memory creation rate**: high-resonance pairs generate more shared memories per message
- **Fork richness**: their conversations produce more forks (more "what if" moments)
- **Balanced provocation**: the LLM provoker triggers less often (because the humans are already pushing each other)

**Implementation:**

```python
# dialectic/analytics/resonance.py

@dataclass
class ResonancePair:
    user_a_id: UUID
    user_b_id: UUID
    overall_score: float  # 0-1
    rooms_shared: int
    total_exchanges: int
    tension_resolution_rate: float  # % of disagreements that reach synthesis
    idea_amplification_index: float
    memory_creation_rate: float  # Memories per 100 messages
    fork_richness: float  # Forks per 100 messages
    strongest_topics: list[str]  # Derived from memory keys

@dataclass
class ResonanceNetwork:
    """Full graph of intellectual resonance for a user."""
    user_id: UUID
    pairs: list[ResonancePair]
    suggested_partners: list[UUID]  # People the user hasn't talked to but might resonate with
    topic_affinities: dict[str, float]  # Topics this user is drawn to
```

**The "Suggested Partners" algorithm:**

Using the cross-session memory system, find users who:
1. Have created memories with similar embeddings to this user's memories (they think about similar things)
2. Have different `aggression_level` and `metaphysics_tolerance` settings (productive tension)
3. Are not yet in any shared rooms

This creates an organic "matchmaking" system for intellectual partners.

**Endpoints:**
```
GET /api/users/me/resonance  -- Your full resonance network
GET /api/users/me/resonance/{other_user_id}  -- Detailed pair analysis
GET /api/users/me/suggestions  -- Suggested thinking partners
```

**Privacy:** All resonance data is computed from rooms the user participates in. Users can opt out of the suggestion system. Resonance scores are never shown to other users without mutual consent.

---

### Feature 5: Living Argument Maps

**The idea:** Automatically extract the logical structure of a conversation and render it as an interactive argument map. Claims, evidence, counter-examples, and rebuttals are identified and linked. The map shows which claims are well-supported, which are contested, and which are dangling without evidence.

**Why it matters:** After a long conversation, participants often lose track of the logical landscape. "Wait, what were we actually disagreeing about?" Living argument maps answer this in real time. They also provide an entirely new way to navigate a conversation -- not chronologically, but *logically*.

**Why Dialectic is uniquely positioned for this:** The message type system already classifies messages as CLAIM, QUESTION, DEFINITION, COUNTEREXAMPLE. The memory system captures agreed-upon conclusions. The event log provides the temporal structure. The LLM can be asked to extract argument structure from messages that weren't explicitly typed.

**Implementation design:**

```python
# dialectic/analytics/argument_map.py

class ArgumentNodeType(str, Enum):
    CLAIM = "claim"
    EVIDENCE = "evidence"
    COUNTER = "counter"
    REBUTTAL = "rebuttal"
    CONCESSION = "concession"
    QUESTION = "question"
    DEFINITION = "definition"
    SYNTHESIS = "synthesis"

@dataclass
class ArgumentNode:
    id: UUID
    source_message_id: UUID
    node_type: ArgumentNodeType
    content: str  # Extracted/summarized claim
    speaker_user_id: Optional[UUID]
    speaker_type: SpeakerType
    confidence: float  # How confident the extraction is
    support_count: int  # How many nodes support this
    opposition_count: int  # How many nodes oppose this

@dataclass
class ArgumentEdge:
    source_node_id: UUID
    target_node_id: UUID
    relation: str  # "supports", "opposes", "refines", "questions"
    strength: float  # 0-1

@dataclass
class ArgumentMap:
    thread_id: UUID
    nodes: list[ArgumentNode]
    edges: list[ArgumentEdge]
    root_claims: list[UUID]  # Top-level claims being debated
    resolved_claims: list[UUID]  # Claims with consensus
    contested_claims: list[UUID]  # Claims under active debate
    orphan_claims: list[UUID]  # Claims with no support or opposition
```

**How extraction works:**

On each new message, the LLM is asked (as a background task, not in the conversation flow) to:
1. Identify any claims, evidence, counter-examples, or other argument nodes in the message
2. Link them to existing nodes in the map (supports, opposes, refines)
3. Detect if any previously contested claim has been resolved

This uses a separate, small LLM call (Haiku-class) with a structured output schema, running asynchronously so it never slows down the conversation.

**Frontend rendering:**

The argument map is a force-directed graph rendered alongside the chat. Nodes are colored by type (green = supported claim, red = contested, yellow = orphan). Clicking a node scrolls the chat to the source message. The map updates live as the conversation progresses.

**The "argument health" indicator:**

A simple metric visible at the top of the chat: "This conversation has 3 contested claims, 2 resolved, and 4 unsupported assertions." This creates gentle accountability -- if you make a claim, the system notices it is floating without support.

**Schema additions:**
```sql
CREATE TABLE argument_nodes (
    id UUID PRIMARY KEY,
    thread_id UUID NOT NULL REFERENCES threads(id),
    source_message_id UUID REFERENCES messages(id),
    node_type TEXT NOT NULL,
    content TEXT NOT NULL,
    speaker_user_id UUID REFERENCES users(id),
    speaker_type TEXT,
    confidence FLOAT NOT NULL DEFAULT 0.8,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE argument_edges (
    source_node_id UUID NOT NULL REFERENCES argument_nodes(id),
    target_node_id UUID NOT NULL REFERENCES argument_nodes(id),
    relation TEXT NOT NULL,
    strength FLOAT NOT NULL DEFAULT 0.5,
    PRIMARY KEY (source_node_id, target_node_id, relation)
);

CREATE INDEX idx_argument_nodes_thread ON argument_nodes(thread_id);
```

---

## V. The Pitch: Why Dialectic Matters

### The Problem

Every collaboration tool treats AI as a servant. You ask, it answers. You prompt, it generates. The human stays in the driver's seat, and the AI stays in the back.

But the most important conversations in human history were not one-sided. They were dialectical -- thesis, antithesis, synthesis. Socrates did not wait to be asked. He interrupted. He provoked. He stayed silent when silence was more powerful than speech.

We have built AI that can do this. But we have wrapped it in interfaces that prevent it.

### The Solution

Dialectic gives the AI a seat at the table. Not as an assistant, but as an interlocutor with its own heuristic will. It watches the conversation. It decides when to speak. It chooses its persona -- collaborative thinker or devil's advocate -- based on the state of the dialogue. And when the conversation stagnates, it does not wait to be summoned. It intervenes.

But Dialectic also gives the *humans* tools that no chat platform provides:

- **Fork any moment** into an alternate timeline and explore what would have happened
- **Build shared memory** that persists, evolves, and connects across conversations
- **Calibrate the AI's personality** with philosophical precision -- not just "be more creative" but "increase metaphysics tolerance to 0.8, set aggression to 0.3"
- **Watch the conversation's DNA** evolve in real time -- see whether you're in a *Crucible* or a *Deep Dive*
- **Map the argument** as it unfolds, tracking which claims have support and which are floating free

### Where It Goes

**Near-term (3-6 months):**
- Public beta with the web frontend
- Dialectic Replay for shareable conversation recordings
- Conversation DNA visible on room cards
- Living argument maps (v1)

**Medium-term (6-12 months):**
- Counterfactual forking
- Intellectual resonance network and partner suggestions
- Multi-LLM rooms (different AI participants with different models/personas)
- Exported argument maps as publishable artifacts (blog posts, papers)

**Long-term (12+ months):**
- A marketplace of room configurations -- "Import Socratic Seminar mode," "Import Scientific Peer Review mode"
- Federated Dialectic instances for organizations (internal knowledge-building with shared memory graphs)
- Academic partnerships: Dialectic as a tool for structured philosophical inquiry, debate training, and collaborative research
- An API for building on top of the conversation engine -- let other applications use heuristic interjection, fork genealogy, and versioned memory

### The Core Bet

The bet is that AI-as-participant is more valuable than AI-as-tool. That the future of human-AI collaboration is not "I ask, you answer" but "we think together, and the AI tells us when we're going in circles." That conversations are the most important data structure in intellectual life, and they deserve the same version control, branching, and analysis that we give to source code.

Dialectic is git for ideas.

---

## VI. Implementation Priority Matrix

| Feature | Impact | Effort | Dependencies | Priority |
|---------|--------|--------|--------------|----------|
| Docker compose + one-command launch | Critical | Low | None | P0 |
| Auth wired to core endpoints | Critical | Medium | None | P0 |
| Web frontend validation | Critical | Medium | Auth | P0 |
| First-run "Agora" experience | High | Medium | Working frontend | P1 |
| Conversation DNA | High | Medium | Analytics module | P1 |
| Dialectic Replay | High | Medium | Event sourcing (exists) | P1 |
| Living Argument Maps | Very High | High | Background LLM calls | P2 |
| Counterfactual Forking | Very High | High | Fork system (exists) | P2 |
| Intellectual Resonance | High | Very High | Cross-session memory, analytics | P3 |

---

*This document is a living artifact. It should be updated as features ship and new ideas emerge from actual usage. The most important next step is not building any of these features -- it is getting the system into a state where someone can use it, so that real conversations can reveal which features actually matter.*
