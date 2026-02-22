# api/personas.py — CRUD endpoints for multi-model room personas

"""
ARCHITECTURE: Separate router for persona management, included in main app.
WHY: Keeps persona CRUD isolated from core messaging endpoints.
TRADEOFF: Extra file vs growing main.py further.
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from models import RoomPersona, TriggerStrategy
from api.token_utils import extract_room_token

logger = logging.getLogger(__name__)

router = APIRouter(tags=["personas"])

_db_pool: Optional[asyncpg.Pool] = None


def set_personas_db_pool(pool: asyncpg.Pool) -> None:
    global _db_pool
    _db_pool = pool


async def _get_db():
    async with _db_pool.acquire() as conn:
        yield conn


# ============================================================
# REQUEST / RESPONSE SCHEMAS
# ============================================================

class CreatePersonaRequest(BaseModel):
    name: str
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    identity_prompt: str
    personality: dict = {}
    trigger_strategy: str = "on_mention"
    display_order: int = 0


class UpdatePersonaRequest(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    identity_prompt: Optional[str] = None
    personality: Optional[dict] = None
    trigger_strategy: Optional[str] = None
    is_active: Optional[bool] = None
    display_order: Optional[int] = None


class PersonaResponse(BaseModel):
    id: UUID
    room_id: UUID
    name: str
    provider: str
    model: str
    identity_prompt: str
    personality: dict
    trigger_strategy: str
    is_active: bool
    display_order: int


# ============================================================
# ENDPOINTS
# ============================================================

@router.post("/rooms/{room_id}/personas", response_model=PersonaResponse)
async def create_persona(
    room_id: UUID,
    request: CreatePersonaRequest,
    token: str = Depends(extract_room_token),
    db=Depends(_get_db),
):
    """
    Create a new LLM persona for a room.

    ARCHITECTURE: Validates trigger_strategy against known enum values.
    WHY: Prevents silent misconfiguration of persona triggers.
    """
    # Verify room token
    room_row = await db.fetchrow(
        "SELECT id FROM rooms WHERE id = $1 AND token = $2",
        room_id, token,
    )
    if not room_row:
        raise HTTPException(status_code=401, detail="Invalid room token")

    # Validate trigger strategy
    valid_strategies = {s.value for s in TriggerStrategy}
    if request.trigger_strategy not in valid_strategies:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid trigger_strategy. Valid: {', '.join(valid_strategies)}",
        )

    if not request.name or not request.name.strip():
        raise HTTPException(status_code=400, detail="Persona name cannot be empty")

    if not request.identity_prompt or not request.identity_prompt.strip():
        raise HTTPException(status_code=400, detail="identity_prompt cannot be empty")

    persona_id = uuid4()
    now = datetime.now(timezone.utc)

    try:
        await db.execute(
            """INSERT INTO room_personas
               (id, room_id, name, provider, model, identity_prompt,
                personality, trigger_strategy, is_active, created_at, display_order)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, true, $9, $10)""",
            persona_id, room_id, request.name.strip(), request.provider,
            request.model, request.identity_prompt.strip(),
            request.personality, request.trigger_strategy, now,
            request.display_order,
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(
            status_code=409,
            detail=f"Persona named '{request.name}' already exists in this room",
        )

    return PersonaResponse(
        id=persona_id,
        room_id=room_id,
        name=request.name.strip(),
        provider=request.provider,
        model=request.model,
        identity_prompt=request.identity_prompt.strip(),
        personality=request.personality,
        trigger_strategy=request.trigger_strategy,
        is_active=True,
        display_order=request.display_order,
    )


@router.get("/rooms/{room_id}/personas", response_model=List[PersonaResponse])
async def list_personas(
    room_id: UUID,
    token: str = Depends(extract_room_token),
    include_inactive: bool = Query(False),
    db=Depends(_get_db),
):
    """List all personas for a room."""
    room_row = await db.fetchrow(
        "SELECT id FROM rooms WHERE id = $1 AND token = $2",
        room_id, token,
    )
    if not room_row:
        raise HTTPException(status_code=401, detail="Invalid room token")

    query = "SELECT * FROM room_personas WHERE room_id = $1"
    if not include_inactive:
        query += " AND is_active = true"
    query += " ORDER BY display_order, created_at"

    rows = await db.fetch(query, room_id)

    return [
        PersonaResponse(
            id=row["id"],
            room_id=row["room_id"],
            name=row["name"],
            provider=row["provider"],
            model=row["model"],
            identity_prompt=row["identity_prompt"],
            personality=row["personality"] or {},
            trigger_strategy=row["trigger_strategy"],
            is_active=row["is_active"],
            display_order=row["display_order"] or 0,
        )
        for row in rows
    ]


@router.put("/personas/{persona_id}", response_model=PersonaResponse)
async def update_persona(
    persona_id: UUID,
    request: UpdatePersonaRequest,
    token: str = Depends(extract_room_token),
    db=Depends(_get_db),
):
    """Update a persona's configuration."""
    row = await db.fetchrow(
        "SELECT * FROM room_personas WHERE id = $1", persona_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Persona not found")

    # Verify room token
    room_row = await db.fetchrow(
        "SELECT id FROM rooms WHERE id = $1 AND token = $2",
        row["room_id"], token,
    )
    if not room_row:
        raise HTTPException(status_code=401, detail="Invalid room token")

    # Validate trigger strategy if provided
    if request.trigger_strategy is not None:
        valid_strategies = {s.value for s in TriggerStrategy}
        if request.trigger_strategy not in valid_strategies:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid trigger_strategy. Valid: {', '.join(valid_strategies)}",
            )

    # Build dynamic UPDATE
    updates = []
    params = [persona_id]
    idx = 2

    field_map = {
        "name": request.name,
        "provider": request.provider,
        "model": request.model,
        "identity_prompt": request.identity_prompt,
        "personality": request.personality,
        "trigger_strategy": request.trigger_strategy,
        "is_active": request.is_active,
        "display_order": request.display_order,
    }

    for col, val in field_map.items():
        if val is not None:
            updates.append(f"{col} = ${idx}")
            params.append(val)
            idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    query = f"UPDATE room_personas SET {', '.join(updates)} WHERE id = $1 RETURNING *"
    updated = await db.fetchrow(query, *params)

    return PersonaResponse(
        id=updated["id"],
        room_id=updated["room_id"],
        name=updated["name"],
        provider=updated["provider"],
        model=updated["model"],
        identity_prompt=updated["identity_prompt"],
        personality=updated["personality"] or {},
        trigger_strategy=updated["trigger_strategy"],
        is_active=updated["is_active"],
        display_order=updated["display_order"] or 0,
    )


@router.delete("/personas/{persona_id}")
async def delete_persona(
    persona_id: UUID,
    token: str = Depends(extract_room_token),
    db=Depends(_get_db),
):
    """Delete a persona."""
    row = await db.fetchrow(
        "SELECT room_id FROM room_personas WHERE id = $1", persona_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Persona not found")

    # Verify room token
    room_row = await db.fetchrow(
        "SELECT id FROM rooms WHERE id = $1 AND token = $2",
        row["room_id"], token,
    )
    if not room_row:
        raise HTTPException(status_code=401, detail="Invalid room token")

    await db.execute("DELETE FROM room_personas WHERE id = $1", persona_id)

    return {"status": "deleted"}
