# api/main.py — FastAPI application

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncGenerator, List, Optional
from uuid import UUID, uuid4
import asyncpg
import logging
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from models import (
    Room, User, Thread, Message, Memory, Event, EventType,
    SpeakerType, MessageType, MemoryScope
)
from memory.manager import MemoryManager
from llm.orchestrator import LLMOrchestrator
from transport.websocket import ConnectionManager, InboundMessage
from transport.handlers import MessageHandler
from api.auth.routes import router as auth_router, set_db_pool as set_auth_db_pool
from api.notifications.routes import router as notifications_router, set_notifications_db_pool
from collections import defaultdict
import time

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================
# RATE LIMITING
# ============================================================

class RateLimiter:
    """
    Simple in-memory rate limiter.

    ARCHITECTURE: Token bucket algorithm with per-IP tracking.
    WHY: Prevents brute force without external dependencies.
    TRADEOFF: Memory grows with unique IPs; single-server only.
    """
    def __init__(self):
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str, limit: int, window_seconds: int) -> bool:
        """Check if request is allowed under rate limit."""
        now = time.time()
        cutoff = now - window_seconds

        # Clean old requests
        self._requests[key] = [t for t in self._requests[key] if t > cutoff]

        if len(self._requests[key]) >= limit:
            return False

        self._requests[key].append(now)
        return True

rate_limiter = RateLimiter()


from fastapi import Request

async def check_rate_limit(
    request: Request,
    limit: int = 60,
    window: int = 60,
) -> None:
    """Rate limit dependency - raises 429 if exceeded."""
    client_ip = request.client.host if request.client else "unknown"
    endpoint = request.url.path
    key = f"{client_ip}:{endpoint}"

    if not rate_limiter.is_allowed(key, limit, window):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later."
        )


# ============================================================
# DATABASE
# ============================================================

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://localhost/dialectic"
)

db_pool: Optional[asyncpg.Pool] = None


async def get_db() -> AsyncGenerator[asyncpg.Connection, None]:
    """Dependency for database connection."""
    async with db_pool.acquire() as conn:
        yield conn


def _validate_environment():
    """Validate required environment variables on startup. Fail fast with clear errors."""
    missing = []
    if not os.environ.get("DATABASE_URL"):
        missing.append("DATABASE_URL")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")

    if missing:
        msg = (
            f"Missing required environment variables: {', '.join(missing)}. "
            "See .env.example for all required/optional variables."
        )
        logger.error(msg)
        raise RuntimeError(msg)

    # Warn about optional but recommended vars
    if not os.environ.get("OPENAI_API_KEY"):
        logger.warning("OPENAI_API_KEY not set. LLM fallback and vector embeddings will be unavailable.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: setup and teardown."""
    global db_pool

    _validate_environment()

    logger.info("Connecting to database...")
    try:
        def _json_encoder(value):
            """JSON encoder that handles UUID and datetime objects."""
            def default(obj):
                if isinstance(obj, UUID):
                    return str(obj)
                if isinstance(obj, datetime):
                    return obj.isoformat()
                raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
            return json.dumps(value, default=default)

        async def _init_connection(conn):
            await conn.set_type_codec(
                'jsonb', encoder=_json_encoder, decoder=json.loads,
                schema='pg_catalog',
            )
            await conn.set_type_codec(
                'json', encoder=_json_encoder, decoder=json.loads,
                schema='pg_catalog',
            )

        db_pool = await asyncpg.create_pool(
            DATABASE_URL, min_size=2, max_size=10, init=_init_connection
        )
        logger.info("Database connected")

        # Set db_pool for auth module
        set_auth_db_pool(db_pool)

        # Set db_pool for notifications module
        set_notifications_db_pool(db_pool)

        async with db_pool.acquire() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except Exception as e:
        logger.warning(f"Database connection failed: {e}")
        logger.warning("Running in demo mode without database")

    yield

    if db_pool:
        await db_pool.close()
        logger.info("Database disconnected")


# ============================================================
# APPLICATION
# ============================================================

app = FastAPI(
    title="Dialectic",
    description="A persistent, forkable, memory-bearing dialogue engine",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS configuration - explicit origins to prevent CSRF attacks
# ARCHITECTURE: Environment-configurable allowed origins with sensible defaults.
# WHY: Wildcard origins with credentials enabled is a security vulnerability.
# TRADEOFF: Requires configuration for production deployments.
ALLOWED_ORIGINS = os.environ.get(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:8000,http://167.99.113.232:3000,http://167.99.113.232:8000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Include auth router with rate limiting applied to all auth endpoints
# ARCHITECTURE: Rate limit dependency applied at router level via dependencies param.
# WHY: Prevents brute-force attacks on login/signup without per-route boilerplate.
# TRADEOFF: Uniform 60/min limit; endpoint-specific limits (e.g., 5/min login) can be layered later.
app.include_router(auth_router, prefix="/auth", tags=["auth"], dependencies=[Depends(check_rate_limit)])

# Include notifications router
app.include_router(notifications_router)

connection_manager = ConnectionManager()


# ============================================================
# AUTH
# ============================================================

async def verify_room_token(
    room_id: UUID,
    token: str,
    db: asyncpg.Connection,
) -> Room:
    """Verify room token and return room if valid."""
    row = await db.fetchrow(
        "SELECT * FROM rooms WHERE id = $1 AND token = $2",
        room_id, token
    )
    if not row:
        raise HTTPException(status_code=401, detail="Invalid room token")
    return Room(**dict(row))


async def verify_room_member(
    room_id: UUID,
    user_id: UUID,
    db: asyncpg.Connection,
) -> None:
    """
    Verify that user_id is a member of the room.

    SECURITY: Prevents user impersonation on REST endpoints. Without this,
    anyone with a room token could act as any user by supplying their UUID.
    """
    membership = await db.fetchrow(
        "SELECT 1 FROM room_memberships WHERE room_id = $1 AND user_id = $2",
        room_id, user_id
    )
    if not membership:
        raise HTTPException(
            status_code=403,
            detail="User is not a member of this room"
        )


# ============================================================
# REQUEST/RESPONSE SCHEMAS
# ============================================================

class CreateRoomRequest(BaseModel):
    name: Optional[str] = None
    global_ontology: Optional[str] = None
    global_rules: Optional[str] = None


class CreateRoomResponse(BaseModel):
    id: UUID
    token: str
    name: Optional[str]


class CreateUserRequest(BaseModel):
    display_name: str
    style_modifier: Optional[str] = None
    aggression_level: float = 0.5
    metaphysics_tolerance: float = 0.5
    custom_instructions: Optional[str] = None


class JoinRoomRequest(BaseModel):
    user_id: UUID


class SendMessageRequest(BaseModel):
    content: str
    message_type: str = "text"
    references_message_id: Optional[UUID] = None


class ForkThreadRequest(BaseModel):
    source_thread_id: UUID
    fork_after_message_id: UUID
    title: Optional[str] = None


class AddMemoryRequest(BaseModel):
    key: str
    content: str
    scope: str = "room"


class EditMemoryRequest(BaseModel):
    content: str
    reason: Optional[str] = None


class MemoryResponse(BaseModel):
    id: UUID
    key: str
    content: str
    scope: str
    version: int
    created_by_user_id: UUID
    status: str


class MessageResponse(BaseModel):
    id: UUID
    thread_id: UUID
    sequence: int
    created_at: datetime
    speaker_type: str
    user_id: Optional[UUID]
    message_type: str
    content: str


class ThreadResponse(BaseModel):
    id: UUID
    room_id: UUID
    parent_thread_id: Optional[UUID]
    title: Optional[str]
    message_count: int


class ThreadNodeResponse(BaseModel):
    """
    Thread node for genealogy tree visualization.

    ARCHITECTURE: Self-referential tree structure with lazy children.
    WHY: Enables cladogram visualization of fork history.
    TRADEOFF: Builds tree in Python (O(n)) vs complex SQL.
    """
    id: UUID
    parent_thread_id: Optional[UUID]
    fork_point_message_id: Optional[UUID]
    title: Optional[str]
    message_count: int
    created_at: datetime
    depth: int
    children: List['ThreadNodeResponse'] = []


ThreadNodeResponse.model_rebuild()  # For self-reference


class SearchResultResponse(BaseModel):
    """Full-text search result with highlighted snippet."""
    id: UUID
    thread_id: UUID
    content: str
    snippet: str  # With highlighted matches
    sender_name: str
    speaker_type: str
    created_at: datetime
    rank: float


class PaginatedMessagesResponse(BaseModel):
    """Paginated messages with cursor information."""
    messages: List[MessageResponse]
    has_more_before: bool
    has_more_after: bool
    oldest_sequence: Optional[int]
    newest_sequence: Optional[int]


class UpdateRoomSettingsRequest(BaseModel):
    """Request to update room LLM heuristic settings."""
    interjection_turn_threshold: Optional[int] = None
    semantic_novelty_threshold: Optional[float] = None
    auto_interjection_enabled: Optional[bool] = None


class RoomSettingsResponse(BaseModel):
    """Current room LLM heuristic settings."""
    interjection_turn_threshold: int
    semantic_novelty_threshold: float
    auto_interjection_enabled: bool


# ============================================================
# REST ENDPOINTS
# ============================================================

@app.post("/rooms", response_model=CreateRoomResponse)
async def create_room(
    request: CreateRoomRequest,
    db=Depends(get_db),
):
    """Create a new room."""
    room_id = uuid4()
    token = uuid4().hex
    now = datetime.now(timezone.utc)

    await db.execute(
        """INSERT INTO rooms (id, created_at, token, name, global_ontology, global_rules)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        room_id, now, token, request.name, request.global_ontology, request.global_rules
    )

    thread_id = uuid4()
    await db.execute(
        """INSERT INTO threads (id, room_id, created_at, title)
           VALUES ($1, $2, $3, $4)""",
        thread_id, room_id, now, "Main"
    )

    await db.execute(
        """INSERT INTO events (id, timestamp, event_type, room_id, payload)
           VALUES ($1, $2, $3, $4, $5)""",
        uuid4(), now, EventType.ROOM_CREATED.value, room_id,
        {"name": request.name}
    )
    await db.execute(
        """INSERT INTO events (id, timestamp, event_type, room_id, thread_id, payload)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        uuid4(), now, EventType.THREAD_CREATED.value, room_id, thread_id,
        {"title": "Main"}
    )

    return CreateRoomResponse(id=room_id, token=token, name=request.name)


@app.post("/users")
async def create_user(
    request: CreateUserRequest,
    db=Depends(get_db),
):
    """Create a new user."""
    user_id = uuid4()
    now = datetime.now(timezone.utc)

    await db.execute(
        """INSERT INTO users
           (id, created_at, display_name, style_modifier,
            aggression_level, metaphysics_tolerance, custom_instructions)
           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
        user_id, now, request.display_name, request.style_modifier,
        request.aggression_level, request.metaphysics_tolerance,
        request.custom_instructions
    )

    return {"id": user_id, "display_name": request.display_name}


@app.post("/rooms/{room_id}/join")
async def join_room(
    room_id: UUID,
    request: JoinRoomRequest,
    token: str = Query(...),
    db=Depends(get_db),
):
    """Join a room."""
    room_row = await db.fetchrow(
        "SELECT * FROM rooms WHERE id = $1 AND token = $2",
        room_id, token
    )
    if not room_row:
        raise HTTPException(status_code=401, detail="Invalid room token")

    existing = await db.fetchrow(
        "SELECT * FROM room_memberships WHERE room_id = $1 AND user_id = $2",
        room_id, request.user_id
    )
    if existing:
        return {"status": "already_member"}

    now = datetime.now(timezone.utc)

    await db.execute(
        """INSERT INTO room_memberships (room_id, user_id, joined_at)
           VALUES ($1, $2, $3)""",
        room_id, request.user_id, now
    )

    await db.execute(
        """INSERT INTO events (id, timestamp, event_type, room_id, user_id, payload)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        uuid4(), now, EventType.USER_JOINED_ROOM.value, room_id, request.user_id, {}
    )

    return {"status": "joined"}


@app.get("/rooms/{room_id}/threads")
async def list_threads(
    room_id: UUID,
    token: str = Query(...),
    db=Depends(get_db),
):
    """List all threads in a room."""
    await verify_room_token(room_id, token, db)

    rows = await db.fetch(
        """SELECT t.*,
                  (SELECT COUNT(*) FROM messages m WHERE m.thread_id = t.id) as message_count
           FROM threads t
           WHERE t.room_id = $1
           ORDER BY t.created_at""",
        room_id
    )

    return [ThreadResponse(
        id=row['id'],
        room_id=row['room_id'],
        parent_thread_id=row['parent_thread_id'],
        title=row['title'],
        message_count=row['message_count'],
    ) for row in rows]


@app.get("/rooms/{room_id}/genealogy", response_model=List[ThreadNodeResponse])
async def get_thread_genealogy(
    room_id: UUID,
    token: str = Query(...),
    max_depth: int = Query(20, ge=1, le=50, description="Maximum tree depth"),
    db=Depends(get_db),
):
    """
    Get full thread genealogy for a room as a tree structure.

    ARCHITECTURE: Recursive CTE with depth tracking.
    WHY: Single query fetches entire tree with depth levels.
    TRADEOFF: Memory for deep trees, but rooms rarely exceed 10 levels.
    """
    await verify_room_token(room_id, token, db)

    # Fetch all threads with message counts using recursive CTE
    rows = await db.fetch(
        """
        WITH RECURSIVE thread_tree AS (
            -- Base case: root threads (no parent)
            SELECT
                t.id,
                t.parent_thread_id,
                t.fork_point_message_id,
                t.title,
                t.created_at,
                0 AS depth
            FROM threads t
            WHERE t.room_id = $1 AND t.parent_thread_id IS NULL

            UNION ALL

            -- Recursive case: child threads
            SELECT
                t.id,
                t.parent_thread_id,
                t.fork_point_message_id,
                t.title,
                t.created_at,
                tt.depth + 1
            FROM threads t
            JOIN thread_tree tt ON t.parent_thread_id = tt.id
            WHERE t.room_id = $1 AND tt.depth < $2
        )
        SELECT
            tt.*,
            (SELECT COUNT(*) FROM messages m WHERE m.thread_id = tt.id) as message_count
        FROM thread_tree tt
        ORDER BY tt.depth, tt.created_at
        """,
        room_id, max_depth
    )

    # Build tree structure in Python (flat list to tree)
    nodes: dict[UUID, ThreadNodeResponse] = {}
    for row in rows:
        nodes[row['id']] = ThreadNodeResponse(
            id=row['id'],
            parent_thread_id=row['parent_thread_id'],
            fork_point_message_id=row['fork_point_message_id'],
            title=row['title'],
            message_count=row['message_count'],
            created_at=row['created_at'],
            depth=row['depth'],
            children=[],
        )

    # Assign children to parents
    roots: List[ThreadNodeResponse] = []
    for node in nodes.values():
        if node.parent_thread_id and node.parent_thread_id in nodes:
            nodes[node.parent_thread_id].children.append(node)
        else:
            roots.append(node)

    return roots


@app.get("/rooms/{room_id}/settings", response_model=RoomSettingsResponse)
async def get_room_settings(
    room_id: UUID,
    token: str = Query(...),
    db=Depends(get_db),
):
    """
    Get current LLM heuristic settings for a room.

    ARCHITECTURE: Direct room table query.
    WHY: Settings are stored on room record, not separate table.
    """
    room = await verify_room_token(room_id, token, db)

    return RoomSettingsResponse(
        interjection_turn_threshold=room.interjection_turn_threshold,
        semantic_novelty_threshold=room.semantic_novelty_threshold,
        auto_interjection_enabled=room.auto_interjection_enabled,
    )


@app.patch("/rooms/{room_id}/settings", response_model=RoomSettingsResponse)
async def update_room_settings(
    room_id: UUID,
    request: UpdateRoomSettingsRequest,
    token: str = Query(...),
    user_id: UUID = Query(...),
    db=Depends(get_db),
):
    """
    Update LLM heuristic settings for a room.

    ARCHITECTURE: Dynamic UPDATE query with only provided fields.
    WHY: Allows partial updates without overwriting unspecified fields.
    TRADEOFF: Slightly more complex than full replacement, but safer.
    """
    await verify_room_token(room_id, token, db)
    await verify_room_member(room_id, user_id, db)

    # Build dynamic UPDATE query with only provided fields
    updates = []
    params = [room_id]
    param_idx = 2

    if request.interjection_turn_threshold is not None:
        # Validate range per RESEARCH.md: 2-12
        if request.interjection_turn_threshold < 2 or request.interjection_turn_threshold > 12:
            raise HTTPException(
                status_code=400,
                detail="interjection_turn_threshold must be between 2 and 12"
            )
        updates.append(f"interjection_turn_threshold = ${param_idx}")
        params.append(request.interjection_turn_threshold)
        param_idx += 1

    if request.semantic_novelty_threshold is not None:
        # Validate range per RESEARCH.md: 0.3-0.95
        if request.semantic_novelty_threshold < 0.3 or request.semantic_novelty_threshold > 0.95:
            raise HTTPException(
                status_code=400,
                detail="semantic_novelty_threshold must be between 0.3 and 0.95"
            )
        updates.append(f"semantic_novelty_threshold = ${param_idx}")
        params.append(request.semantic_novelty_threshold)
        param_idx += 1

    if request.auto_interjection_enabled is not None:
        updates.append(f"auto_interjection_enabled = ${param_idx}")
        params.append(request.auto_interjection_enabled)
        param_idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No settings to update")

    # Execute update
    query = f"UPDATE rooms SET {', '.join(updates)} WHERE id = $1"
    await db.execute(query, *params)

    # Log event
    await db.execute(
        """INSERT INTO events (id, timestamp, event_type, room_id, user_id, payload)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        uuid4(), datetime.now(timezone.utc), EventType.ROOM_SETTINGS_UPDATED.value,
        room_id, user_id, request.model_dump(exclude_none=True)
    )

    # Return updated settings
    row = await db.fetchrow(
        """SELECT interjection_turn_threshold, semantic_novelty_threshold, auto_interjection_enabled
           FROM rooms WHERE id = $1""",
        room_id
    )

    return RoomSettingsResponse(
        interjection_turn_threshold=row['interjection_turn_threshold'],
        semantic_novelty_threshold=row['semantic_novelty_threshold'],
        auto_interjection_enabled=row['auto_interjection_enabled'],
    )


@app.get("/threads/{thread_id}/messages", response_model=PaginatedMessagesResponse)
async def get_messages(
    thread_id: UUID,
    token: str = Query(...),
    include_ancestry: bool = True,
    limit: int = Query(50, ge=1, le=200, description="Max messages to return"),
    before_sequence: Optional[int] = Query(None, description="Return messages before this sequence"),
    after_sequence: Optional[int] = Query(None, description="Return messages after this sequence"),
    db=Depends(get_db),
):
    """
    Get messages in a thread with cursor-based pagination.

    ARCHITECTURE: Bidirectional cursor pagination using sequence numbers.
    WHY: Enables infinite scroll in both directions and precise positioning.
    TRADEOFF: Slightly more complex than offset pagination, but stable under mutations.
    """
    thread_row = await db.fetchrow(
        "SELECT * FROM threads WHERE id = $1", thread_id
    )
    if not thread_row:
        raise HTTPException(status_code=404, detail="Thread not found")

    await verify_room_token(thread_row['room_id'], token, db)

    if include_ancestry:
        # ARCHITECTURE: Single recursive CTE instead of N+1 queries.
        # WHY: Fetches entire thread ancestry in one database round-trip.
        # TRADEOFF: More complex SQL, but O(1) queries vs O(depth) queries.

        all_rows = await db.fetch(
            """
            WITH RECURSIVE thread_ancestry AS (
                -- Base case: current thread (child_fork_point is NULL since we show all messages)
                SELECT id, parent_thread_id, fork_point_message_id,
                       0 as depth, NULL::uuid as child_fork_point_message_id
                FROM threads WHERE id = $1

                UNION ALL

                -- Recursive case: parent threads
                -- child_fork_point_message_id = the fork point of the child thread (ta)
                -- that tells us which messages in the parent (t) to include
                SELECT t.id, t.parent_thread_id, t.fork_point_message_id,
                       ta.depth + 1, ta.fork_point_message_id as child_fork_point_message_id
                FROM threads t
                JOIN thread_ancestry ta ON t.id = ta.parent_thread_id
                WHERE ta.depth < 50  -- Safety limit
            )
            SELECT m.* FROM messages m
            JOIN thread_ancestry ta ON m.thread_id = ta.id
            WHERE NOT m.is_deleted
              AND (
                  ta.depth = 0  -- Current thread: all messages
                  OR m.sequence <= COALESCE(
                      (SELECT sequence FROM messages
                       WHERE id = ta.child_fork_point_message_id),
                      m.sequence
                  )
              )
            ORDER BY m.created_at, m.sequence
            """,
            thread_id
        )
        all_messages = [Message(**dict(row)) for row in all_rows]

        # Apply cursor filters (keep existing logic)
        if before_sequence is not None:
            all_messages = [m for m in all_messages if m.sequence < before_sequence]
            messages = all_messages[-limit:]
        elif after_sequence is not None:
            all_messages = [m for m in all_messages if m.sequence > after_sequence]
            messages = all_messages[:limit]
        else:
            messages = all_messages[-limit:]

        # Calculate has_more flags (keep existing logic)
        if messages:
            oldest_seq = min(m.sequence for m in messages)
            newest_seq = max(m.sequence for m in messages)
            has_more_before = any(m.sequence < oldest_seq for m in all_messages)
            has_more_after = any(m.sequence > newest_seq for m in all_messages)
        else:
            oldest_seq = None
            newest_seq = None
            has_more_before = False
            has_more_after = False
    else:
        # Build query based on cursor direction
        if after_sequence is not None:
            query = """
                SELECT * FROM messages
                WHERE thread_id = $1 AND NOT is_deleted AND sequence > $2
                ORDER BY sequence ASC LIMIT $3
            """
            rows = await db.fetch(query, thread_id, after_sequence, limit)
            messages = [Message(**dict(row)) for row in rows]
        elif before_sequence is not None:
            query = """
                SELECT * FROM messages
                WHERE thread_id = $1 AND NOT is_deleted AND sequence < $2
                ORDER BY sequence DESC LIMIT $3
            """
            rows = await db.fetch(query, thread_id, before_sequence, limit)
            messages = [Message(**dict(row)) for row in reversed(rows)]
        else:
            # Default: most recent messages
            query = """
                SELECT * FROM messages
                WHERE thread_id = $1 AND NOT is_deleted
                ORDER BY sequence DESC LIMIT $2
            """
            rows = await db.fetch(query, thread_id, limit)
            messages = [Message(**dict(row)) for row in reversed(rows)]

        # Calculate has_more flags
        if messages:
            oldest_seq = min(m.sequence for m in messages)
            newest_seq = max(m.sequence for m in messages)

            has_more_before = await db.fetchval(
                "SELECT EXISTS(SELECT 1 FROM messages WHERE thread_id = $1 AND NOT is_deleted AND sequence < $2)",
                thread_id, oldest_seq
            )
            has_more_after = await db.fetchval(
                "SELECT EXISTS(SELECT 1 FROM messages WHERE thread_id = $1 AND NOT is_deleted AND sequence > $2)",
                thread_id, newest_seq
            )
        else:
            oldest_seq = None
            newest_seq = None
            has_more_before = False
            has_more_after = False

    message_responses = [MessageResponse(
        id=m.id,
        thread_id=m.thread_id,
        sequence=m.sequence,
        created_at=m.created_at,
        speaker_type=m.speaker_type.value if hasattr(m.speaker_type, 'value') else m.speaker_type,
        user_id=m.user_id,
        message_type=m.message_type.value if hasattr(m.message_type, 'value') else m.message_type,
        content=m.content,
    ) for m in messages]

    return PaginatedMessagesResponse(
        messages=message_responses,
        has_more_before=has_more_before,
        has_more_after=has_more_after,
        oldest_sequence=oldest_seq,
        newest_sequence=newest_seq,
    )


@app.post("/threads/{thread_id}/messages")
async def send_message(
    thread_id: UUID,
    request: SendMessageRequest,
    token: str = Query(...),
    user_id: UUID = Query(...),
    db=Depends(get_db),
):
    """Send a message (REST fallback for WebSocket)."""
    if not request.content or not request.content.strip():
        raise HTTPException(status_code=400, detail="Message content cannot be empty")

    thread_row = await db.fetchrow(
        "SELECT * FROM threads WHERE id = $1", thread_id
    )
    if not thread_row:
        raise HTTPException(status_code=404, detail="Thread not found")

    room = await verify_room_token(thread_row['room_id'], token, db)
    await verify_room_member(room.id, user_id, db)

    now = datetime.now(timezone.utc)
    message_id = uuid4()

    await db.execute(
        """INSERT INTO messages
           (id, thread_id, sequence, created_at, speaker_type, user_id,
            message_type, content, references_message_id)
           VALUES (
               $1, $2,
               (SELECT COALESCE(MAX(sequence), 0) + 1 FROM messages WHERE thread_id = $2),
               $3, $4, $5, $6, $7, $8
           )""",
        message_id, thread_id, now,
        SpeakerType.HUMAN.value, user_id, request.message_type,
        request.content, request.references_message_id
    )

    # Get the actual sequence that was assigned
    sequence = await db.fetchval(
        "SELECT sequence FROM messages WHERE id = $1", message_id
    )

    await db.execute(
        """INSERT INTO events (id, timestamp, event_type, room_id, thread_id, user_id, payload)
           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
        uuid4(), now, EventType.MESSAGE_CREATED.value,
        room.id, thread_id, user_id,
        {"message_id": str(message_id), "content": request.content}
    )

    return MessageResponse(
        id=message_id,
        thread_id=thread_id,
        sequence=sequence,
        created_at=now,
        speaker_type=SpeakerType.HUMAN.value,
        user_id=user_id,
        message_type=request.message_type,
        content=request.content,
    )


@app.post("/threads/{thread_id}/fork")
async def fork_thread_endpoint(
    thread_id: UUID,
    request: ForkThreadRequest,
    token: str = Query(...),
    user_id: UUID = Query(...),
    db=Depends(get_db),
):
    """Fork a thread."""
    thread_row = await db.fetchrow(
        "SELECT * FROM threads WHERE id = $1", thread_id
    )
    if not thread_row:
        raise HTTPException(status_code=404, detail="Thread not found")

    room = await verify_room_token(thread_row['room_id'], token, db)
    await verify_room_member(room.id, user_id, db)

    from operations import fork_thread
    new_thread = await fork_thread(
        db,
        room_id=room.id,
        source_thread_id=request.source_thread_id,
        fork_after_message_id=request.fork_after_message_id,
        forking_user_id=user_id,
        title=request.title,
    )

    return ThreadResponse(
        id=new_thread.id,
        room_id=new_thread.room_id,
        parent_thread_id=new_thread.parent_thread_id,
        title=new_thread.title,
        message_count=0,
    )


@app.get("/rooms/{room_id}/memories")
async def list_memories(
    room_id: UUID,
    token: str = Query(...),
    include_invalidated: bool = False,
    db=Depends(get_db),
):
    """List all memories in a room."""
    await verify_room_token(room_id, token, db)

    memory_manager = MemoryManager(db)
    memories = await memory_manager.get_room_memories(room_id, include_invalidated)

    return [MemoryResponse(
        id=m.id,
        key=m.key,
        content=m.content,
        scope=m.scope.value if hasattr(m.scope, 'value') else m.scope,
        version=m.version,
        created_by_user_id=m.created_by_user_id,
        status=m.status.value if hasattr(m.status, 'value') else m.status,
    ) for m in memories]


@app.post("/rooms/{room_id}/memories")
async def add_memory(
    room_id: UUID,
    request: AddMemoryRequest,
    token: str = Query(...),
    user_id: UUID = Query(...),
    db=Depends(get_db),
):
    """Add a new memory."""
    await verify_room_token(room_id, token, db)
    await verify_room_member(room_id, user_id, db)

    memory_manager = MemoryManager(db)
    memory = await memory_manager.add_memory(
        room_id=room_id,
        key=request.key,
        content=request.content,
        created_by_user_id=user_id,
        scope=MemoryScope(request.scope),
    )

    return MemoryResponse(
        id=memory.id,
        key=memory.key,
        content=memory.content,
        scope=memory.scope.value,
        version=memory.version,
        created_by_user_id=memory.created_by_user_id,
        status=memory.status.value,
    )


@app.put("/memories/{memory_id}")
async def edit_memory(
    memory_id: UUID,
    request: EditMemoryRequest,
    token: str = Query(...),
    user_id: UUID = Query(...),
    db=Depends(get_db),
):
    """Edit a memory."""
    row = await db.fetchrow("SELECT room_id FROM memories WHERE id = $1", memory_id)
    if not row:
        raise HTTPException(status_code=404, detail="Memory not found")

    await verify_room_token(row['room_id'], token, db)
    await verify_room_member(row['room_id'], user_id, db)

    memory_manager = MemoryManager(db)
    memory = await memory_manager.edit_memory(
        memory_id=memory_id,
        new_content=request.content,
        edited_by_user_id=user_id,
        edit_reason=request.reason,
    )

    return MemoryResponse(
        id=memory.id,
        key=memory.key,
        content=memory.content,
        scope=memory.scope.value if hasattr(memory.scope, 'value') else memory.scope,
        version=memory.version,
        created_by_user_id=memory.created_by_user_id,
        status=memory.status.value if hasattr(memory.status, 'value') else memory.status,
    )


@app.delete("/memories/{memory_id}")
async def invalidate_memory(
    memory_id: UUID,
    token: str = Query(...),
    user_id: UUID = Query(...),
    reason: Optional[str] = None,
    db=Depends(get_db),
):
    """Invalidate a memory."""
    row = await db.fetchrow("SELECT room_id FROM memories WHERE id = $1", memory_id)
    if not row:
        raise HTTPException(status_code=404, detail="Memory not found")

    await verify_room_token(row['room_id'], token, db)
    await verify_room_member(row['room_id'], user_id, db)

    memory_manager = MemoryManager(db)
    await memory_manager.invalidate_memory(
        memory_id=memory_id,
        invalidated_by_user_id=user_id,
        reason=reason,
    )

    return {"status": "invalidated"}


@app.get("/rooms/{room_id}/memories/search")
async def search_memories(
    room_id: UUID,
    query: str,
    token: str = Query(...),
    limit: int = 10,
    db=Depends(get_db),
):
    """Semantic search over memories."""
    await verify_room_token(room_id, token, db)

    memory_manager = MemoryManager(db)
    matches = await memory_manager.search_memories(room_id, query, limit)

    return [{
        "memory_id": str(m.memory_id),
        "key": m.key,
        "content": m.content,
        "score": m.score,
    } for m in matches]


# ============================================================
# FULL-TEXT SEARCH ENDPOINTS
# ============================================================

@app.get("/messages/search", response_model=List[SearchResultResponse])
async def search_messages(
    q: str = Query(..., min_length=1, description="Search query"),
    thread_id: Optional[UUID] = Query(None, description="Filter by thread"),
    date_from: Optional[datetime] = Query(None, description="Filter from date"),
    date_to: Optional[datetime] = Query(None, description="Filter to date"),
    speaker_type: Optional[str] = Query(None, description="Filter by speaker type"),
    limit: int = Query(50, ge=1, le=200, description="Max results"),
    token: str = Query(...),
    user_id: UUID = Query(...),
    db=Depends(get_db),
):
    """
    Full-text search over messages.

    ARCHITECTURE: Uses PostgreSQL tsvector with plainto_tsquery for search.
    WHY: Native FTS is fast, ranked, and supports stemming/normalization.
    TRADEOFF: Less flexible than Elasticsearch, but zero infrastructure overhead.
    """
    # Build query with room membership check
    query = """
        SELECT
            m.id,
            m.thread_id,
            m.content,
            ts_headline('english', m.content, plainto_tsquery('english', $1),
                'StartSel=<mark>, StopSel=</mark>, MaxWords=50, MinWords=20'
            ) as snippet,
            COALESCE(u.display_name, m.speaker_type) as sender_name,
            m.speaker_type,
            m.created_at,
            ts_rank(m.search_vector, plainto_tsquery('english', $1)) as rank
        FROM messages m
        JOIN threads t ON m.thread_id = t.id
        JOIN room_memberships rm ON t.room_id = rm.room_id
        LEFT JOIN users u ON m.user_id = u.id
        WHERE rm.user_id = $2
          AND m.search_vector @@ plainto_tsquery('english', $1)
          AND NOT m.is_deleted
    """
    params = [q, user_id]
    param_idx = 3

    if thread_id:
        query += f" AND m.thread_id = ${param_idx}"
        params.append(thread_id)
        param_idx += 1

    if date_from:
        query += f" AND m.created_at >= ${param_idx}"
        params.append(date_from)
        param_idx += 1

    if date_to:
        query += f" AND m.created_at <= ${param_idx}"
        params.append(date_to)
        param_idx += 1

    if speaker_type:
        query += f" AND m.speaker_type = ${param_idx}"
        params.append(speaker_type)
        param_idx += 1

    query += f" ORDER BY rank DESC, m.created_at DESC LIMIT ${param_idx}"
    params.append(limit)

    rows = await db.fetch(query, *params)

    return [SearchResultResponse(
        id=row['id'],
        thread_id=row['thread_id'],
        content=row['content'],
        snippet=row['snippet'],
        sender_name=row['sender_name'],
        speaker_type=row['speaker_type'],
        created_at=row['created_at'],
        rank=float(row['rank']),
    ) for row in rows]


@app.get("/threads/{thread_id}/messages/context")
async def get_message_context(
    thread_id: UUID,
    message_id: UUID = Query(..., description="Target message ID"),
    context: int = Query(25, ge=1, le=100, description="Messages before/after"),
    token: str = Query(...),
    db=Depends(get_db),
):
    """
    Get messages around a target message for jump-to navigation.

    ARCHITECTURE: Uses sequence numbers for efficient range queries.
    WHY: Enables precise cursor positioning when jumping to search results.
    """
    # Verify thread exists and user has access
    thread_row = await db.fetchrow(
        "SELECT * FROM threads WHERE id = $1", thread_id
    )
    if not thread_row:
        raise HTTPException(status_code=404, detail="Thread not found")

    await verify_room_token(thread_row['room_id'], token, db)

    # Get target message sequence
    target = await db.fetchrow(
        "SELECT sequence FROM messages WHERE id = $1 AND thread_id = $2",
        message_id, thread_id
    )
    if not target:
        raise HTTPException(status_code=404, detail="Message not found in thread")

    target_sequence = target['sequence']

    # Get surrounding messages
    rows = await db.fetch(
        """
        SELECT * FROM messages
        WHERE thread_id = $1
          AND NOT is_deleted
          AND sequence BETWEEN $2 AND $3
        ORDER BY sequence ASC
        """,
        thread_id,
        max(1, target_sequence - context),
        target_sequence + context,
    )

    messages = [Message(**dict(row)) for row in rows]

    return [MessageResponse(
        id=m.id,
        thread_id=m.thread_id,
        sequence=m.sequence,
        created_at=m.created_at,
        speaker_type=m.speaker_type.value if hasattr(m.speaker_type, 'value') else m.speaker_type,
        user_id=m.user_id,
        message_type=m.message_type.value if hasattr(m.message_type, 'value') else m.message_type,
        content=m.content,
    ) for m in messages]


# ============================================================
# WEBSOCKET ENDPOINT
# ============================================================

@app.websocket("/ws/{room_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    room_id: UUID,
):
    """WebSocket connection for real-time messaging."""
    # Accept early so we can receive the auth message before connection_manager.connect()
    # Note: connection_manager.connect() also calls accept(), so we accept here first
    # and skip it there. We need to accept here to receive auth data.
    await websocket.accept()

    # Wait for auth message with timeout
    try:
        auth_data = await asyncio.wait_for(
            websocket.receive_json(),
            timeout=5.0
        )
        token = auth_data.get("token")
        user_id_str = auth_data.get("user_id")
        thread_id_str = auth_data.get("thread_id")

        if not token or not user_id_str:
            await websocket.close(code=4001, reason="Missing credentials")
            return

        user_id = UUID(user_id_str)
        thread_id = UUID(thread_id_str) if thread_id_str else None

    except asyncio.TimeoutError:
        await websocket.close(code=4001, reason="Auth timeout")
        return
    except (KeyError, ValueError, TypeError):
        await websocket.close(code=4001, reason="Invalid auth data")
        return

    # Now validate room token and membership
    async with db_pool.acquire() as db:
        room_row = await db.fetchrow(
            "SELECT * FROM rooms WHERE id = $1 AND token = $2",
            room_id, token
        )
        if not room_row:
            await websocket.close(code=4001, reason="Invalid room token")
            return

        membership = await db.fetchrow(
            "SELECT * FROM room_memberships WHERE room_id = $1 AND user_id = $2",
            room_id, user_id
        )
        if not membership:
            await websocket.close(code=4002, reason="Not a room member")
            return

    conn = await connection_manager.connect(
        websocket=websocket,
        user_id=user_id,
        room_id=room_id,
        thread_id=thread_id,
    )

    try:
        while True:
            data = await websocket.receive_text()
            message = InboundMessage.from_json(data)

            async with db_pool.acquire() as db:
                memory_manager = MemoryManager(db)
                llm_orchestrator = LLMOrchestrator(db)
                handler = MessageHandler(
                    db=db,
                    connection_manager=connection_manager,
                    memory_manager=memory_manager,
                    llm_orchestrator=llm_orchestrator,
                )
                await handler.handle(conn, message)

    except WebSocketDisconnect:
        await connection_manager.disconnect(conn)
    except Exception as e:
        logger.exception(f"WebSocket error: {e}")
        await connection_manager.disconnect(conn)


# ============================================================
# OBSERVABILITY
# ============================================================

@app.get("/health")
async def health():
    """Health check with database connectivity verification."""
    status = {"status": "ok", "checks": {}}

    if db_pool:
        try:
            async with db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            status["checks"]["database"] = "connected"
        except Exception as e:
            status["status"] = "degraded"
            status["checks"]["database"] = f"error: {e}"
    else:
        status["status"] = "degraded"
        status["checks"]["database"] = "no pool"

    status_code = 200 if status["status"] == "ok" else 503
    from fastapi.responses import JSONResponse
    return JSONResponse(content=status, status_code=status_code)


# ============================================================
# USER ENDPOINTS
# ============================================================

class UserRoomResponse(BaseModel):
    """Room with unread count for user's room list."""
    id: UUID
    name: Optional[str]
    unread_count: int
    last_message_at: Optional[datetime]
    last_message_preview: Optional[str]


@app.get("/users/me/rooms", response_model=List[UserRoomResponse])
async def get_user_rooms(
    user_id: UUID = Query(...),
    db=Depends(get_db),
):
    """
    Get rooms the user is a member of with unread message counts.

    ARCHITECTURE: Single query with subqueries for efficiency.
    WHY: Enables room list with unread badges in sidebar.
    """
    rows = await db.fetch(
        """
        SELECT
            r.id,
            r.name,
            (
                SELECT COUNT(*) FROM messages m
                JOIN threads t ON m.thread_id = t.id
                WHERE t.room_id = r.id
                  AND m.created_at > COALESCE(
                      (SELECT MAX(timestamp) FROM message_receipts mr
                       WHERE mr.user_id = $1 AND mr.receipt_type = 'read'
                       AND mr.message_id IN (
                           SELECT id FROM messages WHERE thread_id = t.id
                       )),
                      rm.joined_at
                  )
                  AND (m.user_id IS NULL OR m.user_id != $1)
            ) as unread_count,
            (
                SELECT m.created_at FROM messages m
                JOIN threads t ON m.thread_id = t.id
                WHERE t.room_id = r.id
                ORDER BY m.created_at DESC LIMIT 1
            ) as last_message_at,
            (
                SELECT LEFT(m.content, 50) FROM messages m
                JOIN threads t ON m.thread_id = t.id
                WHERE t.room_id = r.id
                ORDER BY m.created_at DESC LIMIT 1
            ) as last_message_preview
        FROM rooms r
        JOIN room_memberships rm ON r.id = rm.room_id
        WHERE rm.user_id = $1
        ORDER BY last_message_at DESC NULLS LAST
        """,
        user_id
    )

    return [UserRoomResponse(
        id=row['id'],
        name=row['name'],
        unread_count=row['unread_count'] or 0,
        last_message_at=row['last_message_at'],
        last_message_preview=row['last_message_preview'],
    ) for row in rows]


class PresenceUserResponse(BaseModel):
    """User presence info for room."""
    user_id: UUID
    display_name: str
    status: str
    last_heartbeat: Optional[datetime]


@app.get("/rooms/{room_id}/presence", response_model=List[PresenceUserResponse])
async def get_room_presence(
    room_id: UUID,
    token: str = Query(...),
    db=Depends(get_db),
):
    """
    Get presence status for all users in a room.

    ARCHITECTURE: Joins memberships with presence table.
    WHY: Enables online users sidebar panel.
    """
    await verify_room_token(room_id, token, db)

    rows = await db.fetch(
        """
        SELECT
            u.id as user_id,
            u.display_name,
            COALESCE(up.status, 'offline') as status,
            up.last_heartbeat
        FROM room_memberships rm
        JOIN users u ON rm.user_id = u.id
        LEFT JOIN user_presence up ON u.id = up.user_id AND up.room_id = $1
        WHERE rm.room_id = $1
        ORDER BY
            CASE up.status
                WHEN 'online' THEN 1
                WHEN 'away' THEN 2
                ELSE 3
            END,
            u.display_name
        """,
        room_id
    )

    return [PresenceUserResponse(
        user_id=row['user_id'],
        display_name=row['display_name'],
        status=row['status'],
        last_heartbeat=row['last_heartbeat'],
    ) for row in rows]


@app.get("/rooms/{room_id}/events")
async def get_events(
    room_id: UUID,
    token: str = Query(...),
    limit: int = 100,
    after_sequence: Optional[int] = None,
    event_types: Optional[str] = None,
    db=Depends(get_db),
):
    """Get event log for a room."""
    await verify_room_token(room_id, token, db)

    query = "SELECT * FROM events WHERE room_id = $1"
    params = [room_id]

    if after_sequence:
        query += f" AND sequence > ${len(params) + 1}"
        params.append(after_sequence)

    if event_types:
        types = event_types.split(",")
        query += f" AND event_type = ANY(${len(params) + 1})"
        params.append(types)

    query += f" ORDER BY sequence LIMIT ${len(params) + 1}"
    params.append(limit)

    rows = await db.fetch(query, *params)

    return [{
        "id": str(row['id']),
        "sequence": row['sequence'],
        "timestamp": row['timestamp'].isoformat(),
        "event_type": row['event_type'],
        "user_id": str(row['user_id']) if row['user_id'] else None,
        "payload": row['payload'],
    } for row in rows]
