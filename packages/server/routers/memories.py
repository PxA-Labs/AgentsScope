from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, status
from mem0_integration import get_mem0_client
from pydantic import BaseModel

router = APIRouter(prefix="/sessions/{session_id}/memories", tags=["memories"])


class MemoryCreateRequest(BaseModel):
    text: str
    metadata: Optional[Dict[str, Any]] = None
    categories: Optional[List[str]] = None


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
    """Retrieve all memories associated with this session."""
    client = verify_mem0_client()
    try:
        # Use filters to retrieve user-specific memories for this session
        res = client.get_all(filters={"user_id": session_id})
        return res
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve memories from Mem0: {e}",
        )


@router.post("")
async def add_session_memory(session_id: str, payload: MemoryCreateRequest):
    """Manually add a memory to this session."""
    client = verify_mem0_client()
    try:
        metadata = dict(payload.metadata or {})
        if payload.categories:
            metadata["categories"] = payload.categories
        try:
            res = client.add(
                payload.text,
                user_id=session_id,
                metadata=metadata,
                categories=payload.categories,
            )
        except TypeError:
            res = client.add(payload.text, user_id=session_id, metadata=metadata)
        return res
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add memory to Mem0: {e}",
        )


@router.post("/search")
async def search_session_memories(session_id: str, payload: MemorySearchRequest):
    """Search memories associated with this session using vector similarity search."""
    client = verify_mem0_client()
    try:
        res = client.search(payload.query, filters={"user_id": session_id})
        return res
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to search memories in Mem0: {e}",
        )


@router.delete("/{memory_id}")
async def delete_session_memory(session_id: str, memory_id: str):
    """Delete a specific memory by its ID."""
    client = verify_mem0_client()
    try:
        res = client.delete(memory_id)
        return res
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete memory from Mem0: {e}",
        )
