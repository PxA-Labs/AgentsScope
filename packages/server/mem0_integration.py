import asyncio
import logging
import os
from typing import Any, Optional

try:
    from mem0 import MemoryClient
except ImportError:
    MemoryClient = None  # type: ignore

logger = logging.getLogger(__name__)

# Initialize client
MEM0_API_KEY = os.getenv("MEM0_API_KEY")
client: Optional[Any] = None

if MEM0_API_KEY and MemoryClient:
    try:
        client = MemoryClient(api_key=MEM0_API_KEY)
        logger.info("Mem0 client initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Mem0 client: {e}")
else:
    logger.warning(
        "MEM0_API_KEY is not configured or mem0 is not installed. "
        "Mem0 memory integration is disabled."
    )


def get_mem0_client() -> Optional[Any]:
    return client


async def add_memory_async(
    text: str, session_id: str, agent_name: Optional[str] = None
) -> None:
    """Send memory to Mem0 without blocking server request ingestion."""
    c = get_mem0_client()
    if not c:
        logger.debug("Mem0 client not configured, skipping memory addition.")
        return

    def _add():
        try:
            metadata = {}
            if agent_name:
                metadata["agent_name"] = agent_name

            logger.info(
                f"Extracting memory for session {session_id} from text: {text[:60]}..."
            )
            res = c.add(text, user_id=session_id, metadata=metadata)
            logger.info(f"Mem0 add response: {res}")
        except Exception as e:
            logger.error(f"Failed to add memory to Mem0: {e}")

    asyncio.create_task(asyncio.to_thread(_add))


async def get_all_memories_async(session_id: str) -> Any:
    """Retrieve all memories for a session asynchronously."""
    c = get_mem0_client()
    if not c:
        return []
    return await asyncio.to_thread(c.get_all, filters={"user_id": session_id})


def _extract_memory_items(memories: Any) -> list:
    """Normalise Mem0 list responses (plain list or ``{"results": [...]}``)."""
    if isinstance(memories, list):
        return memories
    if isinstance(memories, dict) and isinstance(memories.get("results"), list):
        return memories["results"]
    return []


def _memory_item_id(item: Any) -> Optional[str]:
    return item.get("id") if isinstance(item, dict) else getattr(item, "id", None)


async def memory_belongs_to_session(memory_id: str, session_id: str) -> bool:
    """Return True if ``memory_id`` is one of the memories scoped to ``session_id``."""
    memories = await get_all_memories_async(session_id)
    return any(
        _memory_item_id(item) == memory_id for item in _extract_memory_items(memories)
    )


async def add_custom_memory_async(
    text: str, session_id: str, metadata: Optional[dict] = None
) -> Any:
    """Add a custom memory asynchronously."""
    c = get_mem0_client()
    if not c:
        return None
    return await asyncio.to_thread(
        c.add, text, user_id=session_id, metadata=metadata or {}
    )


async def search_memories_async(query: str, session_id: str) -> Any:
    """Search memories asynchronously."""
    c = get_mem0_client()
    if not c:
        return []
    return await asyncio.to_thread(c.search, query, filters={"user_id": session_id})


async def update_memory_async(memory_id: str, text: str) -> Any:
    """Update a specific memory asynchronously."""
    c = get_mem0_client()
    if not c:
        return None
    return await asyncio.to_thread(c.update, memory_id, text)


async def delete_memory_async(memory_id: str) -> Any:
    """Delete a specific memory asynchronously."""
    c = get_mem0_client()
    if not c:
        return None
    return await asyncio.to_thread(c.delete, memory_id)


async def delete_all_session_memories_async(session_id: str) -> Any:
    """Delete all memories for a session asynchronously."""
    c = get_mem0_client()
    if not c:
        return None
    if hasattr(c, "delete_all"):
        return await asyncio.to_thread(c.delete_all, user_id=session_id)

    # Fallback deletion if client doesn't support delete_all directly
    memories = await get_all_memories_async(session_id)
    deleted_count = 0
    for m in _extract_memory_items(memories):
        m_id = _memory_item_id(m)
        if m_id:
            await delete_memory_async(m_id)
            deleted_count += 1
    return {"deleted": deleted_count}
