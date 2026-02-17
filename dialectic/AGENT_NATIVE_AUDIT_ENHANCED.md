# Agent-Native Architecture Audit: Dialectic (Enhanced)

> **Original Audit Date:** January 2026
> **Enhanced By:** 8 parallel specialized research agents
> **Scope:** Full codebase analysis against agent-native principles with research-backed recommendations

---

## Overall Score Summary

| Core Principle | Current Score | Target Score | Status |
|----------------|---------------|--------------|--------|
| Action Parity | 6/26 (23%) | 20/26 (77%) | ❌ → ⚠️ |
| Tools as Primitives | 13/24 (54%) | 22/24 (92%) | ⚠️ → ✅ |
| Context Injection | 7.5/15 (50%) | 13/15 (87%) | ⚠️ → ✅ |
| Shared Workspace | 6/8 (75%) | 8/8 (100%) | ⚠️ → ✅ |
| CRUD Completeness | 2/16 (12.5%) | 12/16 (75%) | ❌ → ⚠️ |
| UI Integration | 7/7 (100%) | 7/7 (100%) | ✅ |
| Capability Discovery | 3/7 (43%) | 6/7 (86%) | ❌ → ✅ |
| Prompt-Native Features | 13/24 (54%) | 21/24 (88%) | ⚠️ → ✅ |

**Current Score: 51%** → **Target Score: 82%**

---

## Research-Backed Implementation Guide

### Phase 1: LLM Memory Writes (P0 - 4h)

**Recommendation from Agent `aaa3830` (Memory Writes Research)**

Transform LLM from read-only participant to full co-creator by enabling memory operations.

#### Tool Schema Definition

```python
# llm/tools.py - Tool definitions for LLM memory operations

from typing import Optional
from pydantic import BaseModel, Field

class AddMemoryInput(BaseModel):
    """
    ARCHITECTURE: Input schema for LLM memory creation.
    WHY: Structured output ensures valid, parseable memory operations.
    """
    key: str = Field(
        description="Short identifier (e.g., 'Alice_position_on_free_will'). Use snake_case.",
        min_length=3,
        max_length=100,
    )
    content: str = Field(
        description="The memory content. Capture positions, definitions, or agreements.",
        min_length=10,
        max_length=2000,
    )
    source_summary: Optional[str] = Field(
        default=None,
        description="Why this is being remembered (e.g., 'Bob explicitly stated this').",
        max_length=200,
    )

class EditMemoryInput(BaseModel):
    """Input schema for LLM memory edits."""
    memory_key: str = Field(description="The key of the memory to edit.")
    new_content: str = Field(description="Updated content.", min_length=10, max_length=2000)
    edit_reason: str = Field(description="Why this is being updated.", max_length=200)

class InvalidateMemoryInput(BaseModel):
    """Input schema for LLM memory invalidation."""
    memory_key: str = Field(description="The key of the memory to invalidate.")
    reason: str = Field(description="Why this is no longer valid.", max_length=200)

# Anthropic API format
MEMORY_TOOLS = [
    {
        "name": "add_memory",
        "description": """Record significant information to shared memory.

Use when:
- A participant makes a clear position statement
- The group agrees on a definition
- An important synthesis emerges

Do NOT use for:
- Trivial observations
- Information already in memory
- Speculative statements""",
        "input_schema": AddMemoryInput.model_json_schema(),
    },
    {
        "name": "edit_memory",
        "description": "Update an existing memory when a position evolves.",
        "input_schema": EditMemoryInput.model_json_schema(),
    },
    {
        "name": "invalidate_memory",
        "description": "Mark a memory as no longer valid.",
        "input_schema": InvalidateMemoryInput.model_json_schema(),
    },
]
```

#### Guardrails Configuration

```python
# llm/orchestrator.py - Rate limiting for memory writes

@dataclass
class MemoryWriteGuardrails:
    """
    ARCHITECTURE: Rate limiting and validation for LLM memory writes.
    WHY: Prevents runaway memory creation without blocking legitimate use.
    TRADEOFF: Strict limits may occasionally block valid writes.
    """
    max_writes_per_response: int = 3      # Circuit breaker per turn
    max_writes_per_hour: int = 20         # Prevents flooding
    min_interval_seconds: int = 5         # Prevents rapid-fire
    max_memory_size_bytes: int = 5000     # Content limit
    semantic_dedup_threshold: float = 0.85  # Near-duplicate prevention

    _write_counts: dict = field(default_factory=dict)
    _last_write: dict = field(default_factory=dict)

    def can_write(self, room_id: UUID) -> tuple[bool, str]:
        """Check if a memory write is allowed."""
        now = datetime.now(timezone.utc)

        # Check minimum interval
        last = self._last_write.get(room_id)
        if last and (now - last).total_seconds() < self.min_interval_seconds:
            return False, f"Rate limit: minimum {self.min_interval_seconds}s between writes"

        # Check hourly limit
        hour_ago = now - timedelta(hours=1)
        recent = sum(c for ts, c in self._write_counts.get(room_id, []) if ts > hour_ago)

        if recent >= self.max_writes_per_hour:
            return False, f"Rate limit: {self.max_writes_per_hour} writes per hour exceeded"

        return True, ""
```

#### Tool Execution Loop

```python
# llm/orchestrator.py - Agent loop pattern

async def on_message_with_tools(
    self,
    room: Room,
    thread: Thread,
    users: list[User],
    messages: list[Message],
    memories: list[Memory],
    mentioned: bool = False,
) -> OrchestrationResult:
    """
    ARCHITECTURE: Tool loop pattern from Anthropic cookbook.
    WHY: Allows LLM to decide when to write memories organically.
    """
    MAX_TOOL_CALLS = 5  # Circuit breaker
    tool_calls = 0
    conversation = list(prompt.messages)

    while tool_calls < MAX_TOOL_CALLS:
        response = await self.provider.generate(
            messages=conversation,
            system=prompt.system,
            tools=MEMORY_TOOLS,
        )

        if response.stop_reason != "tool_use":
            break

        # Execute tool calls
        tool_results = await self._process_tool_calls(response, room.id, thread.id)
        tool_calls += len(tool_results)

        # Continue conversation
        conversation.append({"role": "assistant", "content": response.content})
        conversation.append({"role": "user", "content": tool_results})

    return self._finalize_response(response)
```

**Sources:**
- [ChatGPT Memory Overview](https://openai.com/index/memory-and-new-controls-for-chatgpt/)
- [Claude Memory - Anthropic](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool)
- [Human-in-the-Loop - LangChain](https://docs.langchain.com/oss/python/langchain/human-in-the-loop)

---

### Phase 2: Prompt-Native Interjection (P1 - 3h)

**Recommendation from Agent `a8598fe` (Prompt-Native Research)**

Move hardcoded heuristics from code to prompts, making LLM self-aware of why it speaks.

#### Current Problem

```python
# heuristics.py - Hardcoded, opaque decision logic
class InterjectionEngine:
    def __init__(
        self,
        turn_threshold: int = 4,  # Room config fields NEVER read
        semantic_novelty_threshold: float = 0.7,
    ):
        pass
```

#### Solution: Hybrid Architecture

**Code handles cheap binary gating:**

```python
# heuristics.py - Simplified
class InterjectionEngine:
    """
    ARCHITECTURE: Code handles binary gate, prompt handles nuance.
    WHY: Avoid expensive LLM calls for obvious non-triggers.
    """

    def should_invoke(
        self,
        room: Room,
        messages: list[Message],
        mentioned: bool,
    ) -> tuple[bool, str]:
        """Returns (should_invoke, reason_for_prompt)."""
        if mentioned:
            return True, "You were directly mentioned or addressed."

        human_turns = self._count_human_turns(messages)
        if human_turns >= room.interjection_turn_threshold:
            return True, f"Turn threshold reached ({human_turns} >= {room.interjection_turn_threshold})."

        if self._has_question(messages):
            return True, "A question was posed to the room."

        return False, ""
```

**Prompts encode decision rationale:**

```python
# prompts.py - Inject invocation context
def _build_invocation_context(
    self,
    room: Room,
    messages: list[Message],
    invocation_reason: str,
) -> str:
    """
    ARCHITECTURE: Encode decision parameters in prompt, not code.
    WHY: LLM can self-regulate and explain its behavior.
    """
    human_turns = self._count_human_turns_since_llm(messages)

    return f"""## Invocation Context

**Why you are being called**: {invocation_reason}

**Conversation State**:
- Human turns since your last contribution: {human_turns}
- Room's turn threshold: {room.interjection_turn_threshold}
- Room's novelty sensitivity: {room.semantic_novelty_threshold}

**Your Decision**:
Before responding, briefly assess in <interjection_rationale> tags:
1. Is now the right moment? Why?
2. What specific value will your contribution add?
3. Risk of disrupting productive human dialogue?

If you determine you should observe rather than speak:
- Respond with: <observe reason="..."/>
- This will NOT be broadcast to participants

Otherwise, provide your contribution after the rationale tags."""
```

**LLM can decline via `<observe>`:**

```python
# orchestrator.py - Handle observe responses
if "<observe" in response.content:
    logger.info("LLM chose to observe rather than interject")
    return OrchestrationResult(
        triggered=True,
        decision=decision,
        response=None,  # No message broadcast
        routing=routing,
    )
```

**Sources:**
- [Proactive Conversational Agents with Inner Thoughts](https://arxiv.org/html/2501.00383v2)
- [Nature Machine Intelligence - LLM Personality](https://www.nature.com/articles/s42256-025-01115-6)
- [PolyBotConversation Experiment](https://kleiber.me/blog/2024/10/06/PolyBotConversation-llm-group-chat-experiment/)

---

### Phase 3: Capability Discovery (P1 - 3h)

**Recommendation from Agent `aef4fd5` (UX Discovery Research)**

Users cannot discover what makes Dialectic special. Fix with 6 patterns.

#### Pattern 1: Enhanced Empty State

Replace generic `"No messages yet. Start the conversation!"` with:

```html
<div class="empty-state-enhanced">
    <div class="welcome-header">
        <h2>Start a Dialectic</h2>
        <p>Two humans + one AI, reasoning together.</p>
    </div>

    <div class="starter-prompts">
        <h4>Try one of these:</h4>
        <button class="starter-prompt" data-prompt="What is consciousness? [Claim: I think therefore I am]">
            <span class="prompt-type">Philosophical</span>
            <span class="prompt-text">Explore consciousness with a claim</span>
        </button>
        <button class="starter-prompt" data-prompt="@llm Challenge our assumptions">
            <span class="prompt-type">AI Challenge</span>
            <span class="prompt-text">Summon Claude to provoke discussion</span>
        </button>
    </div>

    <div class="feature-hints">
        <div class="hint-item"><kbd>@llm</kbd> Summon Claude</div>
        <div class="hint-item"><kbd>Claim/Question/Definition</kbd> Tag your message</div>
        <div class="hint-item"><kbd>Fork</kbd> Branch the conversation</div>
    </div>
</div>
```

#### Pattern 2: Slash Command System

```javascript
const commands = {
    '/help': { description: 'Show all commands and features', action: showHelpModal },
    '/llm': { description: 'Summon Claude', action: () => insertText('@llm ') },
    '/fork': { description: 'Branch from last message', action: triggerFork },
    '/claim': { description: 'Tag message as claim', action: () => setType('claim') },
    '/question': { description: 'Tag as question', action: () => setType('question') },
    '/definition': { description: 'Tag as definition', action: () => setType('definition') },
    '/memory': { description: 'Add shared memory', action: showMemoryPanel },
};

// Show palette when typing /
$('#messageInput').addEventListener('input', (e) => {
    if (e.target.value.startsWith('/')) {
        showCommandPalette(e.target.value.slice(1));
    }
});
```

#### Pattern 3: Contextual Tooltips

```html
<button class="type-btn" data-type="claim"
        data-tooltip="Assert something you believe to be true">Claim</button>
<button class="type-btn" data-type="question"
        data-tooltip="Ask for clarification or challenge assumptions">Question</button>
<button class="type-btn" data-type="definition"
        data-tooltip="Establish shared meaning for a term">Definition</button>
```

```css
.type-btn::after {
    content: attr(data-tooltip);
    position: absolute;
    bottom: calc(100% + 8px);
    background: var(--surface);
    border: 1px solid var(--border);
    padding: 0.5rem 0.75rem;
    opacity: 0;
    transition: opacity 0.2s;
}
.type-btn:hover::after { opacity: 1; }
```

#### Pattern 4: Input Intelligence

```javascript
$('#messageInput').addEventListener('input', (e) => {
    const value = e.target.value;

    if (value.includes('@') && !value.includes('@llm')) {
        showInputHint('Type @llm to summon Claude');
    }
    else if (value.endsWith('?') && state.messageType !== 'question') {
        showInputHint('Tip: Use Question type for better structure');
    }
    else if (/\b(i think|i believe)\b/i.test(value) && state.messageType !== 'claim') {
        showInputHint('This sounds like a claim. Tag it!');
    }
});
```

#### Pattern 5: First-Run Onboarding

```javascript
const onboardingSteps = [
    { target: '.message-type-selector', title: 'Structure Your Thoughts',
      content: 'Tag messages as Claims, Questions, or Definitions.' },
    { target: '#messageInput', title: 'Summon the AI',
      content: 'Type @llm to bring Claude into the conversation.' },
    { target: '#forkThreadBtn', title: 'Branch the Discussion',
      content: 'Fork to explore alternatives without losing context.' },
    { target: '[data-tab="memories"]', title: 'Shared Memory',
      content: 'Create persistent definitions and agreements.' },
];

if (!localStorage.getItem('dialectic_onboarded')) {
    setTimeout(() => showOnboardingStep(0), 1000);
}
```

**Sources:**
- [OpenAI UX Principles](https://developers.openai.com/apps-sdk/concepts/ux-principles/)
- [Discord Slash Commands](https://discord.com/blog/slash-commands-are-here)
- [Chameleon - Contextual Help UX](https://www.chameleon.io/blog/contextual-help-ux)

---

### Phase 4: Code Simplification (P2 - 4h)

**Recommendation from Agent `a5e5d7b` (Code Simplicity Review)**

Identified 285 lines (40% of ~700 LOC) for removal without loss of functionality.

#### Files to Simplify

| File | Current LOC | Target LOC | Reduction |
|------|-------------|------------|-----------|
| `llm/heuristics.py` | 133 | 0 | -133 (delete entirely) |
| `llm/prompts.py` | 160 | 95 | -65 (flatten layers) |
| `llm/orchestrator.py` | 393 | 306 | -87 (merge methods) |

#### Delete `heuristics.py` Entirely

The `InterjectionEngine` class encodes decisions that should be in prompts:

```python
# DELETE THIS FILE - Move logic to prompts
class InterjectionEngine:
    def decide(self, messages, mentioned, semantic_novelty):
        # 133 lines of hardcoded rules
        # Room config fields never read
        # Decision rationale lost
```

Replace with simple function in `orchestrator.py`:

```python
def should_invoke_llm(room: Room, messages: list[Message], mentioned: bool) -> tuple[bool, str]:
    """Simple gate - nuance handled in prompt."""
    if mentioned:
        return True, "mentioned"
    if count_human_turns(messages) >= room.interjection_turn_threshold:
        return True, "turn_threshold"
    if has_question(messages[-3:]):
        return True, "question"
    return False, ""
```

#### Flatten `prompts.py`

Current over-abstraction:

```python
class PromptBuilder:
    def build(self, room, users, messages, memories, is_provoker):
        identity = self._select_identity(is_provoker)
        room_ctx = self._build_room_context(room)
        user_ctx = self._blend_user_modifiers(users)  # DELETE - questionable UX
        memory_ctx = self._build_memory_context(memories)
        messages = self._format_messages(messages)
        return self._assemble(identity, room_ctx, user_ctx, memory_ctx, messages)
```

Simplify to:

```python
def build_prompt(
    room: Room,
    messages: list[Message],
    memories: list[Memory],
    invocation_reason: str,
    is_provoker: bool = False,
) -> AssembledPrompt:
    """Single function, no class wrapper."""
    identity = PROVOKER_IDENTITY if is_provoker else BASE_IDENTITY

    system = f"""{identity}

## Room: {room.name}
{room.ontology or 'General philosophical discussion'}

## Invocation Context
{invocation_reason}

## Shared Memories
{format_memories(memories)}"""

    return AssembledPrompt(
        system=system,
        messages=format_messages(messages),
    )
```

#### Merge Orchestrator Methods

Current duplication:

```python
class LLMOrchestrator:
    async def on_message(self, ...): ...
    async def on_provoker_message(self, ...): ...  # Nearly identical
    async def _trigger_llm(self, ...): ...         # Shared logic
    async def _persist_response(self, ...): ...
    async def _emit_system_error(self, ...): ...
```

Merge into single entry point:

```python
class LLMOrchestrator:
    async def handle_turn(
        self,
        room: Room,
        thread: Thread,
        messages: list[Message],
        memories: list[Memory],
        mentioned: bool = False,
    ) -> OrchestrationResult:
        """Single entry point for all LLM invocations."""
        should_speak, reason = should_invoke_llm(room, messages, mentioned)
        if not should_speak:
            return OrchestrationResult(triggered=False)

        is_provoker = reason in ("stagnation", "novelty")
        prompt = build_prompt(room, messages, memories, reason, is_provoker)

        response = await self._generate_with_tools(prompt, room)
        message = await self._persist(thread, response, is_provoker)

        return OrchestrationResult(triggered=True, response=message)
```

---

### Phase 5: CRUD Completeness (P2 - 6h)

**Recommendation from Agent `ac63289` (CRUD Research)**

Target 75% CRUD score (up from 12.5%) by enabling LLM write operations with appropriate guardrails.

#### Access Control Model

```python
# models.py - Add LLM permissions
class LLMPermissions(BaseModel):
    """
    ARCHITECTURE: Delegated access model.
    WHY: AI inherits room-scoped permissions, not global access.
    """
    can_add_memory: bool = True
    can_edit_memory: bool = True
    can_invalidate_memory: bool = True
    can_fork_thread: bool = True
    can_classify_messages: bool = True
    max_memories_per_hour: int = 20
    max_forks_per_hour: int = 5

class Room(BaseModel):
    # ... existing fields ...
    llm_permissions: LLMPermissions = LLMPermissions()
```

#### CRUD Operations Matrix

| Entity | User C | User R | User U | User D | LLM C | LLM R | LLM U | LLM D |
|--------|--------|--------|--------|--------|-------|-------|-------|-------|
| Message | ✅ | ✅ | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ |
| Memory | ✅ | ✅ | ✅ | ✅ | ✅* | ✅ | ✅* | ✅* |
| Thread | ✅ | ✅ | ❌ | ❌ | ✅* | ✅ | ❌ | ❌ |
| Room | ✅ | ✅ | ✅ | ✅ | ❌ | ✅ | ❌ | ❌ |

*With guardrails (rate limits, semantic dedup, permission checks)

#### Human-in-the-Loop for Destructive Ops (Optional)

```python
# For high-stakes rooms, require confirmation
class HITLConfig(BaseModel):
    require_confirmation_for: list[str] = []  # ["invalidate_memory"]
    confirmation_timeout_seconds: int = 60

async def request_confirmation(
    room_id: UUID,
    operation: str,
    context: dict,
) -> bool:
    """Broadcast confirmation request to room users."""
    await connections.broadcast(room_id, OutboundMessage(
        type="llm_confirmation_request",
        payload={
            "operation": operation,
            "context": context,
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=60),
        },
    ))
    # Wait for user approval or timeout
    return await wait_for_confirmation(room_id, operation)
```

---

### Phase 6: Tool Architecture Refactor (P3 - 4h)

**Recommendation from Agents `aa0404e` + `a244a0b` (Architecture + Pattern Reviews)**

Extract decision logic from workflows into queryable primitives.

#### Transform InterjectionEngine to Queryable Signals

```python
# llm/signals.py - Queryable primitives

@dataclass
class TurnCountSignal:
    human_turns: int
    threshold: int
    triggered: bool

    def to_dict(self) -> dict:
        return {
            "human_turns": self.human_turns,
            "threshold": self.threshold,
            "triggered": self.triggered,
        }

@dataclass
class QuestionSignal:
    detected: bool
    question_text: Optional[str]
    directed_at_room: bool

@dataclass
class InterjectionSignals:
    """
    ARCHITECTURE: Queryable decision state.
    WHY: LLM can inspect why it's being invoked.
    """
    mentioned: bool
    turn_count: TurnCountSignal
    question: QuestionSignal
    stagnation: Optional[StagnationSignal]
    novelty: Optional[SemanticNoveltySignal]

    def to_dict(self) -> dict:
        """For LLM inspection via context injection."""
        return {
            "mentioned": self.mentioned,
            "turn_count": self.turn_count.to_dict(),
            "question": self.question.to_dict() if self.question.detected else None,
            # ...
        }

def compute_signals(room: Room, messages: list[Message], mentioned: bool) -> InterjectionSignals:
    """Pure function - computes signals without making decisions."""
    return InterjectionSignals(
        mentioned=mentioned,
        turn_count=TurnCountSignal(
            human_turns=count_human_turns(messages),
            threshold=room.interjection_turn_threshold,
            triggered=count_human_turns(messages) >= room.interjection_turn_threshold,
        ),
        question=detect_question(messages[-3:]),
        stagnation=detect_stagnation(messages),
        novelty=compute_novelty(messages) if room.semantic_novelty_threshold > 0 else None,
    )
```

#### Tool Registry Pattern

```python
# llm/tools/registry.py

class ToolRegistry:
    """
    ARCHITECTURE: Central registry for LLM-callable tools.
    WHY: Single source of truth for tool schemas and execution.
    """

    def __init__(self):
        self._tools: dict[str, ToolConfig] = {}

    def register(self, name: str, config: ToolConfig):
        self._tools[name] = config

    def get_schemas(self, permissions: LLMPermissions) -> list[dict]:
        """Return tool schemas filtered by permissions."""
        return [
            tool.schema for name, tool in self._tools.items()
            if tool.check_permission(permissions)
        ]

    async def execute(
        self,
        name: str,
        input: dict,
        context: ToolExecutionContext,
    ) -> dict:
        """Execute tool with guardrails."""
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"Unknown tool: {name}", "is_error": True}

        if not tool.check_permission(context.permissions):
            return {"error": "Permission denied", "is_error": True}

        if tool.rate_limited and not context.check_rate_limit(name):
            return {"error": "Rate limit exceeded", "is_error": True}

        return await tool.execute(input, context)

# Register tools
registry = ToolRegistry()
registry.register("add_memory", ToolConfig(
    schema=AddMemoryInput.model_json_schema(),
    permission_check=lambda p: p.can_add_memory,
    rate_limited=True,
    execute=handle_add_memory,
))
```

---

## Implementation Roadmap

### Week 1: Core Agency
- [ ] Add tool schemas for memory operations (`llm/tools.py`)
- [ ] Implement guardrails class (`llm/orchestrator.py`)
- [ ] Add tool execution loop to orchestrator
- [ ] Wire Room config fields to prompt assembly
- [ ] Inject interjection rationale into prompts
- [ ] Add `<observe>` response handling

### Week 2: Discoverability
- [ ] Implement enhanced empty state with starter prompts
- [ ] Add slash command system with `/help`
- [ ] Add contextual tooltips to message type buttons
- [ ] Implement input intelligence hints
- [ ] Create first-run onboarding tour
- [ ] Add command palette UI

### Week 3: Code Simplification
- [ ] Delete `heuristics.py` entirely
- [ ] Flatten `prompts.py` to single function
- [ ] Merge orchestrator methods
- [ ] Create queryable signals module
- [ ] Implement tool registry pattern
- [ ] Remove dead code paths

---

## Files Requiring Changes

| File | Changes | LOC Impact |
|------|---------|------------|
| `llm/tools.py` | NEW: Tool schemas | +150 |
| `llm/signals.py` | NEW: Queryable primitives | +80 |
| `llm/orchestrator.py` | Tool loop, guardrails | +100, -87 |
| `llm/prompts.py` | Flatten, add context | -65 |
| `llm/heuristics.py` | DELETE | -133 |
| `transport/handlers.py` | LLM-initiated ops | +30 |
| `frontend/index.html` | Discovery features | +300 |
| `api/main.py` | New endpoints | +45 |

**Net LOC change:** +220 (but 40% reduction in LLM layer complexity)

---

## Verification Checklist

### Memory Writes
```bash
# Test LLM can add memory
curl -X POST /threads/{id}/messages -d '{"content": "@llm What did we agree on? Add it to memory."}'
# Verify memory appears in /rooms/{id}/memories
```

### Interjection Rationale
```bash
# Check LLM response includes <interjection_rationale>
# Check LLM can respond with <observe/> and no message broadcasts
```

### Discovery Features
```bash
# Open fresh browser (incognito)
# Verify onboarding tour appears
# Verify empty state has starter prompts
# Type "/" and verify command palette
# Hover over Claim button and verify tooltip
```

---

## Conclusion

This enhanced audit synthesizes research from 8 specialized agents to provide:

1. **Complete tool schemas** for enabling LLM memory writes
2. **Hybrid architecture** for prompt-native interjection decisions
3. **6 discovery patterns** to surface capabilities to users
4. **40% code reduction** by deleting unnecessary abstractions
5. **CRUD completeness** roadmap with guardrails
6. **Tool registry pattern** for maintainable agent architecture

The path from **51% to 82%** agent-native is achievable with focused work on the recommendations above. The architectural bones are solid—the gaps are addressable.

---

## Sources

### Primary Research
- ChatGPT Memory: https://openai.com/index/memory-and-new-controls-for-chatgpt/
- Claude Memory Tool: https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool
- Proactive Agents: https://arxiv.org/html/2501.00383v2
- LLM Personality: https://www.nature.com/articles/s42256-025-01115-6

### UX Patterns
- OpenAI UX Principles: https://developers.openai.com/apps-sdk/concepts/ux-principles/
- Discord Slash Commands: https://discord.com/blog/slash-commands-are-here
- Progressive Disclosure: https://www.nngroup.com/articles/progressive-disclosure/

### Architecture
- Anthropic Tool Use: https://github.com/anthropics/anthropic-cookbook
- Human-in-the-Loop: https://docs.langchain.com/oss/python/langchain/human-in-the-loop
