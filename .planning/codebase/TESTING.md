# Testing Patterns

**Analysis Date:** 2026-01-20

## Test Framework

**Runner:**
- No test framework detected
- No `pytest`, `unittest`, or other test runner in `requirements.txt`
- No test configuration files found

**Assertion Library:**
- Not applicable (no tests exist)

**Run Commands:**
```bash
# No test commands available
# Tests need to be implemented
```

## Test File Organization

**Location:**
- No test files exist in the codebase
- No `tests/` directory
- No `*_test.py` or `test_*.py` files found

**Recommended Pattern (not yet implemented):**
```
dialectic/
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # pytest fixtures
│   ├── test_models.py           # Unit tests for models.py
│   ├── test_operations.py       # Unit tests for operations.py
│   ├── api/
│   │   └── test_main.py         # API endpoint tests
│   ├── llm/
│   │   ├── test_heuristics.py   # Interjection logic tests
│   │   ├── test_prompts.py      # Prompt assembly tests
│   │   ├── test_router.py       # Routing/retry tests
│   │   └── test_orchestrator.py # Integration tests
│   ├── memory/
│   │   ├── test_manager.py      # Memory lifecycle tests
│   │   ├── test_embeddings.py   # Embedding provider tests
│   │   └── test_vector_store.py # Vector search tests
│   └── transport/
│       ├── test_websocket.py    # Connection manager tests
│       └── test_handlers.py     # Message handler tests
```

## Test Structure

**Recommended Pattern:**
```python
import pytest
from uuid import uuid4
from datetime import datetime

from models import Message, SpeakerType, MessageType
from llm.heuristics import InterjectionEngine, InterjectionDecision


class TestInterjectionEngine:
    """Tests for InterjectionEngine decision logic."""

    @pytest.fixture
    def engine(self):
        return InterjectionEngine(turn_threshold=4)

    @pytest.fixture
    def sample_message(self):
        return Message(
            id=uuid4(),
            thread_id=uuid4(),
            sequence=1,
            created_at=datetime.utcnow(),
            speaker_type=SpeakerType.HUMAN,
            user_id=uuid4(),
            message_type=MessageType.TEXT,
            content="Test message",
        )

    def test_explicit_mention_triggers_interjection(self, engine, sample_message):
        """@llm mention should always trigger interjection."""
        decision = engine.decide(messages=[sample_message], mentioned=True)

        assert decision.should_interject is True
        assert decision.reason == "explicit_mention"
        assert decision.confidence == 1.0

    def test_turn_threshold_triggers_interjection(self, engine):
        """Should interject after turn_threshold human messages."""
        messages = [
            Message(
                id=uuid4(),
                thread_id=uuid4(),
                sequence=i,
                created_at=datetime.utcnow(),
                speaker_type=SpeakerType.HUMAN,
                user_id=uuid4(),
                message_type=MessageType.TEXT,
                content=f"Message {i}",
            )
            for i in range(5)
        ]

        decision = engine.decide(messages=messages)

        assert decision.should_interject is True
        assert "turn_threshold" in decision.reason
```

## Mocking

**Recommended Framework:** `pytest-mock` or `unittest.mock`

**Database Mocking Pattern:**
```python
import pytest
from unittest.mock import AsyncMock, MagicMock

@pytest.fixture
def mock_db():
    """Mock asyncpg database connection."""
    db = AsyncMock()
    db.fetchrow = AsyncMock()
    db.fetch = AsyncMock()
    db.fetchval = AsyncMock()
    db.execute = AsyncMock()
    return db

async def test_memory_add(mock_db):
    """Test adding a memory."""
    mock_db.fetchval.return_value = 0

    manager = MemoryManager(mock_db)
    memory = await manager.add_memory(
        room_id=uuid4(),
        key="test_key",
        content="test content",
        created_by_user_id=uuid4(),
    )

    assert memory.key == "test_key"
    assert mock_db.execute.call_count == 3  # event + memory + version
```

**HTTP Client Mocking:**
```python
import httpx
import pytest

@pytest.fixture
def mock_anthropic_response():
    return {
        "content": [{"text": "Response text"}],
        "model": "claude-sonnet-4-20250514",
        "usage": {"input_tokens": 100, "output_tokens": 50},
        "stop_reason": "end_turn",
    }

async def test_anthropic_complete(mock_anthropic_response, respx_mock):
    """Test Anthropic API completion."""
    respx_mock.post("https://api.anthropic.com/v1/messages").respond(
        json=mock_anthropic_response
    )

    provider = AnthropicProvider()
    request = LLMRequest(
        messages=[{"role": "user", "content": "Hello"}],
        system="You are helpful.",
        model="claude-sonnet-4-20250514",
    )

    response = await provider.complete(request)

    assert response.content == "Response text"
    assert response.provider == ProviderName.ANTHROPIC
```

**What to Mock:**
- External API calls (Anthropic, OpenAI)
- Database connections
- WebSocket connections
- Time-dependent operations

**What NOT to Mock:**
- Pure business logic (heuristics, prompt building)
- Data transformations
- Model validation

## Fixtures and Factories

**Recommended Test Data Pattern:**
```python
# tests/conftest.py
import pytest
from uuid import uuid4
from datetime import datetime
from models import Room, User, Thread, Message, SpeakerType, MessageType


@pytest.fixture
def room_factory():
    """Factory for creating test rooms."""
    def _create_room(**kwargs):
        defaults = {
            "id": uuid4(),
            "created_at": datetime.utcnow(),
            "token": uuid4().hex,
            "name": "Test Room",
            "primary_provider": "anthropic",
            "fallback_provider": "openai",
            "primary_model": "claude-sonnet-4-20250514",
            "provoker_model": "claude-haiku-4-20250514",
            "auto_interjection_enabled": True,
            "interjection_turn_threshold": 4,
        }
        defaults.update(kwargs)
        return Room(**defaults)
    return _create_room


@pytest.fixture
def user_factory():
    """Factory for creating test users."""
    def _create_user(**kwargs):
        defaults = {
            "id": uuid4(),
            "created_at": datetime.utcnow(),
            "display_name": "Test User",
            "aggression_level": 0.5,
            "metaphysics_tolerance": 0.5,
        }
        defaults.update(kwargs)
        return User(**defaults)
    return _create_user


@pytest.fixture
def message_factory():
    """Factory for creating test messages."""
    def _create_message(thread_id=None, sequence=1, **kwargs):
        defaults = {
            "id": uuid4(),
            "thread_id": thread_id or uuid4(),
            "sequence": sequence,
            "created_at": datetime.utcnow(),
            "speaker_type": SpeakerType.HUMAN,
            "user_id": uuid4(),
            "message_type": MessageType.TEXT,
            "content": "Test message content",
        }
        defaults.update(kwargs)
        return Message(**defaults)
    return _create_message
```

**Location:**
- Put fixtures in `tests/conftest.py` for shared fixtures
- Put module-specific fixtures in test files

## Coverage

**Requirements:** Not enforced (no tests exist)

**Recommended Setup:**
```bash
# Install pytest-cov
pip install pytest pytest-cov pytest-asyncio

# Run with coverage
pytest --cov=dialectic --cov-report=html

# View coverage report
open htmlcov/index.html
```

**Recommended Configuration** (`pyproject.toml`):
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.coverage.run]
source = ["dialectic"]
omit = ["*/tests/*", "*/__init__.py"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "if TYPE_CHECKING:",
    "raise NotImplementedError",
]
```

## Test Types

**Unit Tests (Priority: HIGH):**
- `llm/heuristics.py` - Interjection decision logic
- `llm/prompts.py` - Prompt assembly
- `models.py` - Pydantic model validation
- `operations.py` - Thread forking logic

**Integration Tests (Priority: MEDIUM):**
- `llm/router.py` - Retry and fallback behavior
- `memory/manager.py` - Memory lifecycle with mock DB
- `transport/handlers.py` - Message handler dispatch

**E2E Tests (Priority: LOW):**
- Full WebSocket conversation flow
- API endpoint integration
- Requires running PostgreSQL with pgvector

## Common Patterns

**Async Testing:**
```python
import pytest

@pytest.mark.asyncio
async def test_async_operation():
    """Test async function."""
    result = await some_async_function()
    assert result == expected
```

**Error Testing:**
```python
import pytest

def test_missing_env_var_raises():
    """Test that missing API key raises EnvironmentError."""
    import os
    original = os.environ.pop("ANTHROPIC_API_KEY", None)

    try:
        with pytest.raises(EnvironmentError, match="FATAL"):
            AnthropicProvider()
    finally:
        if original:
            os.environ["ANTHROPIC_API_KEY"] = original


async def test_memory_not_found_raises(mock_db):
    """Test that missing memory raises ValueError."""
    mock_db.fetchrow.return_value = None

    manager = MemoryManager(mock_db)

    with pytest.raises(ValueError, match="not found"):
        await manager.edit_memory(
            memory_id=uuid4(),
            new_content="new content",
            edited_by_user_id=uuid4(),
        )
```

**WebSocket Testing:**
```python
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

def test_websocket_invalid_token(client):
    """Test WebSocket rejects invalid token."""
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(
            f"/ws/{uuid4()}?token=invalid&user_id={uuid4()}"
        ):
            pass
```

## Testing Gaps (Current State)

**Critical Missing Tests:**
- No tests exist for any module
- Interjection heuristics untested
- Prompt assembly untested
- Memory operations untested
- API endpoints untested
- WebSocket handlers untested

**Recommended Testing Priority:**
1. `llm/heuristics.py` - Core decision logic
2. `llm/prompts.py` - Prompt construction
3. `models.py` - Data validation
4. `memory/manager.py` - Memory lifecycle
5. `api/main.py` - REST endpoints
6. `transport/handlers.py` - WebSocket handlers

## Mock Embeddings for Testing

The codebase includes `MockEmbeddings` class in `memory/embeddings.py` for testing without API keys:

```python
class MockEmbeddings(EmbeddingProvider):
    """Mock embeddings for testing without API keys."""
    DIMENSIONS = 1536

    async def embed(self, text: str) -> EmbeddingResult:
        # Generate deterministic fake embedding based on text hash
        import hashlib
        h = hashlib.sha256(text.encode()).hexdigest()
        vector = [float(int(h[i:i+2], 16)) / 255.0 for i in range(0, min(len(h), self.DIMENSIONS * 2), 2)]
        vector.extend([0.0] * (self.DIMENSIONS - len(vector)))
        return EmbeddingResult(
            vector=vector[:self.DIMENSIONS],
            model="mock",
            tokens=len(text.split()),
        )
```

Use by unsetting `OPENAI_API_KEY` environment variable during tests.

---

*Testing analysis: 2026-01-20*
