from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, status
from mem0_integration import (
    add_custom_memory_async,
    delete_all_session_memories_async,
    delete_memory_async,
    get_all_memories_async,
    get_mem0_client,
    search_memories_async,
    update_memory_async,
)
from pydantic import BaseModel

router = APIRouter(prefix="/sessions/{session_id}/memories", tags=["memories"])


class MemoryCreateRequest(BaseModel):
    text: str
    metadata: Optional[Dict[str, Any]] = None


class MemoryUpdateRequest(BaseModel):
    text: str


class MemorySearchRequest(BaseModel):
    query: str


def verify_mem0_client():
    client = get_mem0_client()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Mem0 integration is disabled. Please configure MEM0_API_KEY "
                "in the server environment (.env file)."
            ),
        )
    return client


@router.get("")
async def list_session_memories(session_id: str):
    """Retrieve all memories associated with this session asynchronously."""
    verify_mem0_client()
    try:
        res = await get_all_memories_async(session_id)
        return res
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve memories from Mem0: {e}",
        )


@router.post("")
async def add_session_memory(session_id: str, payload: MemoryCreateRequest):
    """Manually add a memory to this session asynchronously."""
    verify_mem0_client()
    try:
        metadata = payload.metadata or {}
        res = await add_custom_memory_async(
            payload.text, session_id=session_id, metadata=metadata
        )
        return res
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add memory to Mem0: {e}",
        )


@router.post("/search")
async def search_session_memories(session_id: str, payload: MemorySearchRequest):
    """Search memories associated with this session using vector search."""
    verify_mem0_client()
    try:
        res = await search_memories_async(payload.query, session_id=session_id)
        return res
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search memories in Mem0: {e}",
        )


@router.put("/{memory_id}")
async def update_session_memory(
    session_id: str, memory_id: str, payload: MemoryUpdateRequest
):
    """Update an existing memory text by its ID."""
    verify_mem0_client()
    try:
        res = await update_memory_async(memory_id, payload.text)
        return res
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update memory in Mem0: {e}",
        )


@router.delete("/{memory_id}")
async def delete_session_memory(session_id: str, memory_id: str):
    """Delete a specific memory by its ID."""
    verify_mem0_client()
    try:
        res = await delete_memory_async(memory_id)
        return res
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete memory from Mem0: {e}",
        )


@router.delete("")
async def delete_all_session_memories(session_id: str):
    """Delete all memories associated with this session."""
    verify_mem0_client()
    try:
        res = await delete_all_session_memories_async(session_id)
        return res
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to bulk delete session memories from Mem0: {e}",
        )

