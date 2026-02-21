# Coding Conventions

**Analysis Date:** 2026-01-20

## Naming Patterns

**Files:**
- Lowercase with underscores: `vector_store.py`, `memory_manager.py`
- Module names match primary class (singular): `manager.py` contains `MemoryManager`
- `__init__.py` re-exports public API with explicit `__all__`

**Functions:**
- snake_case: `get_thread_messages()`, `fork_thread()`
- Private methods prefixed with underscore: `_handle_send_message()`, `_detect_stagnation()`
- Async functions use `async def` consistently

**Variables:**
- snake_case for locals and parameters: `room_id`, `thread_row`, `max_seq`
- UPPER_CASE for module constants: `MAX_RETRIES`, `RETRY_DELAYS`, `DATABASE_URL`
- Descriptive names preferred: `semantic_novelty_threshold` not `snt`

**Classes:**
- PascalCase: `LLMOrchestrator`, `MemoryManager`, `InterjectionEngine`
- Dataclasses for simple data containers: `Connection`, `SimilarityMatch`, `EmbeddingResult`
- Pydantic `BaseModel` for validated/serializable models: `Room`, `User`, `Message`

**Types/Enums:**
- PascalCase: `MessageType`, `SpeakerType`, `ProviderName`
- String enums inherit from both `str` and `Enum`: `class EventType(str, Enum)`

## Code Style

**Formatting:**
- No formatter config detected (no `.prettierrc`, `.black`, etc.)
- Consistent 4-space indentation used throughout
- Line length appears uncapped but generally under 100 characters

**Linting:**
- No linting config detected (no `.flake8`, `pyproject.toml` with ruff, etc.)
- Type hints used consistently on function signatures
- f-strings preferred for string formatting

## Import Organization

**Order:**
1. Standard library imports: `from datetime import datetime`, `from typing import Optional`
2. Third-party imports: `import asyncpg`, `from fastapi import FastAPI`
3. Local imports: `from models import Room, User`, `from .providers import LLMProvider`

**Path Aliases:**
- Relative imports within packages: `from .providers import ...`
- Absolute imports from project root: `from models import ...`
- NOTE: Some files include `sys.path.insert(0, '/root/DwoodAmo/dialectic')` - this is a workaround, not a pattern to follow

## Error Handling

**Patterns:**
- Raise `ValueError` for domain errors: `raise ValueError(f"Memory {memory_id} not found")`
- Raise `HTTPException` in API layer: `raise HTTPException(status_code=401, detail="Invalid room token")`
- Use `EnvironmentError` for missing config: `raise EnvironmentError("FATAL: export ANTHROPIC_API_KEY")`

**Async Error Handling:**
```python
try:
    await handler(conn, message.payload)
except Exception as e:
    logger.exception(f"Handler error for {message.type}")
    await self._send_error(conn, str(e))
```

**Graceful Degradation:**
```python
try:
    novelty = await self.memory.compute_message_novelty(conn.room_id, content)
except Exception:
    novelty = 0.5  # Default on failure
```

## Logging

**Framework:** Python standard library `logging`

**Setup Pattern:**
```python
import logging
logger = logging.getLogger(__name__)
```

**Log Levels:**
- `logger.info()` for significant operations: `logger.info(f"Created memory {memory_id}: {key}")`
- `logger.warning()` for non-fatal issues: `logger.warning(f"Failed to send to {conn.user_id}: {e}")`
- `logger.error()` for failures: `logger.error(f"Failed to generate embedding for {memory_id}: {e}")`
- `logger.debug()` for detailed traces: `logger.debug(f"No interjection: {decision.reason}")`
- `logger.exception()` to include stack trace: `logger.exception(f"Handler error for {message.type}")`

## Comments

**ARCHITECTURE/WHY/TRADEOFF Pattern:**
Every major class documents design decisions using structured docstrings:
```python
class InterjectionEngine:
    """
    ARCHITECTURE: Rule-based + heuristic interjection triggers.
    WHY: LLM should feel like a participant, not a reactive tool.
    TRADEOFF: False positives (annoying) vs false negatives (silent).
    """
```

**Section Separators:**
```python
# ============================================================
# DATABASE
# ============================================================
```

**Inline Comments:**
- Used sparingly for non-obvious logic
- Document async operations: `# Generate embedding async`

## Function Design

**Size:**
- Most functions under 50 lines
- Long functions broken into private helper methods (see `_persist_response`, `_emit_system_error`)

**Parameters:**
- Use type hints on all parameters
- Use `Optional[X]` for nullable parameters with `= None` default
- Use keyword arguments for optional parameters

**Return Values:**
- Always type-hinted
- Dataclasses or Pydantic models for complex returns
- Use `Optional[X]` when function may return nothing

**Example Signature:**
```python
async def fork_thread(
    db,
    room_id: UUID,
    source_thread_id: UUID,
    fork_after_message_id: UUID,
    forking_user_id: UUID,
    title: Optional[str] = None
) -> Thread:
```

## Module Design

**Exports:**
- Each package has `__init__.py` with explicit `__all__` list
- Re-export public classes/functions for clean imports

**Example** (`llm/__init__.py`):
```python
from .providers import LLMProvider, LLMRequest, LLMResponse, ProviderName, get_provider
from .router import ModelRouter, RoutingResult
from .heuristics import InterjectionEngine, InterjectionDecision
from .prompts import PromptBuilder, AssembledPrompt
from .orchestrator import LLMOrchestrator, OrchestrationResult

__all__ = [
    "LLMProvider", "LLMRequest", "LLMResponse", "ProviderName", "get_provider",
    "ModelRouter", "RoutingResult",
    "InterjectionEngine", "InterjectionDecision",
    "PromptBuilder", "AssembledPrompt",
    "LLMOrchestrator", "OrchestrationResult",
]
```

**Barrel Files:**
- Used consistently for all packages
- Import from package, not module: `from llm import LLMOrchestrator` not `from llm.orchestrator import LLMOrchestrator`

## Data Modeling Patterns

**Pydantic Models:**
- Use `Field(default_factory=...)` for mutable defaults
- UUIDs generated via `uuid4`: `id: UUID = Field(default_factory=uuid4)`
- Timestamps via `datetime`: `created_at: datetime`

**Dataclasses:**
- Use for internal data transfer objects
- Use `@dataclass` decorator
- Use `field(default_factory=...)` for mutable defaults

**Enums:**
- String enums for database-compatible values: `class SpeakerType(str, Enum)`
- Access via `.value` when serializing to DB: `speaker_type.value`

## Database Patterns

**Query Style:**
- Raw SQL with parameterized queries: `$1`, `$2`, etc.
- Explicit column lists in INSERT statements
- Use `COALESCE` for null handling

**Connection Pattern:**
```python
async with db_pool.acquire() as db:
    row = await db.fetchrow("SELECT * FROM ...")
```

**Common Operations:**
```python
# Single row
row = await db.fetchrow("SELECT * FROM rooms WHERE id = $1", room_id)

# Multiple rows
rows = await db.fetch("SELECT * FROM memories WHERE room_id = $1", room_id)

# Single value
max_seq = await db.fetchval("SELECT COALESCE(MAX(sequence), 0) FROM messages WHERE thread_id = $1", thread_id)

# Execute (no return)
await db.execute("INSERT INTO ...", ...)
```

## Async Patterns

**All I/O is async:**
- Database operations
- HTTP requests (httpx)
- WebSocket operations

**Async Context Managers:**
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Setup
    yield
    # Teardown
```

**Async Iteration:**
```python
async for line in response.aiter_lines():
    if line.startswith("data: "):
        yield event["delta"]["text"]
```

---

*Convention analysis: 2026-01-20*
