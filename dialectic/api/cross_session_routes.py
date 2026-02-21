# api/cross_session_routes.py — REST endpoints for cross-session memory features

"""
ARCHITECTURE: API layer for cross-room memory operations.
WHY: Separate router keeps main.py focused on core room operations.
TRADEOFF: Additional file vs cleaner organization.
"""

from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from models import Memory, MemoryReference, UserMemoryCollection, CrossRoomMemoryResult
from memory.cross_session import CrossSessionMemoryManager, GlobalSearchResult

router = APIRouter(prefix="/cross-session", tags=["cross-session"])


# ================================================================
# REQUEST/RESPONSE SCHEMAS
# ================================================================

class GlobalMemorySearchRequest(BaseModel):
    query: str = Field(..., min_length=3, max_length=1000)
    current_room_id: Optional[UUID] = None
    include_current_room: bool = True
    limit: int = Field(default=10, ge=1, le=50)


class GlobalMemorySearchResponse(BaseModel):
    results: List[GlobalSearchResult]
    query: str
    total_results: int


class PromoteMemoryRequest(BaseModel):
    memory_id: UUID


class CreateReferenceRequest(BaseModel):
    source_memory_id: UUID
    target_thread_id: Optional[UUID] = None
    target_message_id: Optional[UUID] = None
    citation_context: Optional[str] = Field(None, max_length=500)


class CreateCollectionRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    auto_inject: bool = False


class AddToCollectionRequest(BaseModel):
    memory_id: UUID
    notes: Optional[str] = Field(None, max_length=500)


class RelevantMemoriesResponse(BaseModel):
    memories: List[CrossRoomMemoryResult]
    context_query: str


# ================================================================
# DEPENDENCY - Will be injected from main.py
# ================================================================

# These will be set by main.py when mounting the router
_db_dependency = None
_auth_dependency = None
_cross_session_manager = None


def set_dependencies(db_dep, auth_dep, manager):
    """Called by main.py to inject dependencies."""
    global _db_dependency, _auth_dependency, _cross_session_manager
    _db_dependency = db_dep
    _auth_dependency = auth_dep
    _cross_session_manager = manager


async def get_manager():
    if _cross_session_manager is None:
        raise HTTPException(500, "Cross-session manager not initialized")
    return _cross_session_manager


# ================================================================
# ROUTES: Global Memory Search
# ================================================================

@router.post("/search", response_model=GlobalMemorySearchResponse)
async def search_memories_globally(
    request: GlobalMemorySearchRequest,
    # user = Depends(_auth_dependency),  # Uncomment when integrated
    manager: CrossSessionMemoryManager = Depends(get_manager),
):
    """
    Search all memories across all rooms the user participates in.
    
    Returns memories ranked by semantic similarity to the query.
    """
    # TODO: Get user_id from auth dependency
    user_id = UUID("00000000-0000-0000-0000-000000000001")  # Placeholder
    
    results = await manager.search_user_memories(
        user_id=user_id,
        query=request.query,
        current_room_id=request.current_room_id,
        limit=request.limit,
        include_current_room=request.include_current_room,
    )

    return GlobalMemorySearchResponse(
        results=results,
        query=request.query,
        total_results=len(results)
    )


@router.get("/rooms/{room_id}/relevant-memories", response_model=RelevantMemoriesResponse)
async def get_relevant_cross_room_memories(
    room_id: UUID,
    context: str = Query(..., min_length=3, max_length=1000),
    limit: int = Query(default=5, ge=1, le=20),
    min_similarity: float = Query(default=0.7, ge=0.0, le=1.0),
    manager: CrossSessionMemoryManager = Depends(get_manager),
):
    """
    Get memories from OTHER rooms that are relevant to the given context.
    
    Used for automatic cross-room context injection.
    """
    # TODO: Get user_id from auth
    user_id = UUID("00000000-0000-0000-0000-000000000001")
    
    memories = await manager.get_relevant_cross_room_memories(
        user_id=user_id,
        current_room_id=room_id,
        context=context,
        limit=limit,
        min_similarity=min_similarity,
    )

    return RelevantMemoriesResponse(
        memories=memories,
        context_query=context
    )


# ================================================================
# ROUTES: Memory Promotion
# ================================================================

@router.post("/memories/{memory_id}/promote", response_model=Memory)
async def promote_memory_to_global(
    memory_id: UUID,
    manager: CrossSessionMemoryManager = Depends(get_manager),
):
    """
    Promote a room-scoped memory to global scope.
    
    After promotion, the memory will be accessible in all rooms
    the user participates in.
    """
    # TODO: Get user_id from auth and verify ownership
    user_id = UUID("00000000-0000-0000-0000-000000000001")
    
    try:
        memory = await manager.promote_memory_to_global(
            memory_id=memory_id,
            user_id=user_id,
        )
        return memory
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/memories/{memory_id}/demote", response_model=Memory)
async def demote_memory_from_global(
    memory_id: UUID,
    manager: CrossSessionMemoryManager = Depends(get_manager),
):
    """
    Demote a global memory back to room scope.
    """
    user_id = UUID("00000000-0000-0000-0000-000000000001")
    
    try:
        memory = await manager.demote_memory_from_global(
            memory_id=memory_id,
            user_id=user_id,
        )
        return memory
    except ValueError as e:
        raise HTTPException(404, str(e))


# ================================================================
# ROUTES: Memory References (Citations)
# ================================================================

@router.post("/rooms/{room_id}/references", response_model=MemoryReference)
async def create_memory_reference(
    room_id: UUID,
    request: CreateReferenceRequest,
    manager: CrossSessionMemoryManager = Depends(get_manager),
):
    """
    Create a reference (citation) from a memory to the current room.
    
    This links a memory from another room to a message in this room,
    creating a cross-session knowledge connection.
    """
    user_id = UUID("00000000-0000-0000-0000-000000000001")
    
    try:
        reference = await manager.create_reference(
            source_memory_id=request.source_memory_id,
            target_room_id=room_id,
            target_thread_id=request.target_thread_id,
            target_message_id=request.target_message_id,
            referenced_by_user_id=user_id,
            referenced_by_llm=False,
            citation_context=request.citation_context,
        )
        return reference
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.get("/rooms/{room_id}/references", response_model=List[MemoryReference])
async def get_room_references(
    room_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
    manager: CrossSessionMemoryManager = Depends(get_manager),
):
    """
    Get all memory references pointing to this room.
    
    Shows which external memories have been cited in this room.
    """
    references = await manager.get_references_for_room(
        room_id=room_id,
        limit=limit,
    )
    return references


@router.get("/memories/{memory_id}/references", response_model=List[MemoryReference])
async def get_memory_citations(
    memory_id: UUID,
    manager: CrossSessionMemoryManager = Depends(get_manager),
):
    """
    Get all places where a memory has been cited.
    
    Shows the "citation graph" of where this memory has been referenced.
    """
    references = await manager.get_references_from_memory(memory_id=memory_id)
    return references


# ================================================================
# ROUTES: User Collections
# ================================================================

@router.get("/collections", response_model=List[UserMemoryCollection])
async def get_user_collections(
    manager: CrossSessionMemoryManager = Depends(get_manager),
):
    """
    Get all memory collections for the current user.
    """
    user_id = UUID("00000000-0000-0000-0000-000000000001")
    collections = await manager.get_user_collections(user_id=user_id)
    return collections


@router.post("/collections", response_model=UserMemoryCollection)
async def create_collection(
    request: CreateCollectionRequest,
    manager: CrossSessionMemoryManager = Depends(get_manager),
):
    """
    Create a new memory collection.
    
    Collections can be set to auto_inject, which means their memories
    will be automatically included in all room contexts.
    """
    user_id = UUID("00000000-0000-0000-0000-000000000001")
    
    collection = await manager.create_collection(
        user_id=user_id,
        name=request.name,
        description=request.description,
        auto_inject=request.auto_inject,
    )
    return collection


@router.get("/collections/{collection_id}/memories", response_model=List[Memory])
async def get_collection_memories(
    collection_id: UUID,
    manager: CrossSessionMemoryManager = Depends(get_manager),
):
    """
    Get all memories in a collection.
    """
    # TODO: Verify user owns collection
    memories = await manager.get_collection_memories(collection_id=collection_id)
    return memories


@router.post("/collections/{collection_id}/memories")
async def add_memory_to_collection(
    collection_id: UUID,
    request: AddToCollectionRequest,
    manager: CrossSessionMemoryManager = Depends(get_manager),
):
    """
    Add a memory to a collection.
    """
    user_id = UUID("00000000-0000-0000-0000-000000000001")
    
    membership = await manager.add_memory_to_collection(
        collection_id=collection_id,
        memory_id=request.memory_id,
        user_id=user_id,
        notes=request.notes,
    )
    return {"status": "added", "collection_id": str(collection_id), "memory_id": str(request.memory_id)}


@router.get("/auto-inject-memories", response_model=List[Memory])
async def get_auto_inject_memories(
    manager: CrossSessionMemoryManager = Depends(get_manager),
):
    """
    Get all memories from the user's auto-inject collections.
    
    These memories are automatically included in LLM context for all rooms.
    """
    user_id = UUID("00000000-0000-0000-0000-000000000001")
    memories = await manager.get_auto_inject_memories(user_id=user_id)
    return memories
