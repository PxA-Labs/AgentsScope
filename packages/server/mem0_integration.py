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
    if not client:
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
            res = client.add(text, user_id=session_id, metadata=metadata)
            logger.info(f"Mem0 add response: {res}")
        except Exception as e:
            logger.error(f"Failed to add memory to Mem0: {e}")

    asyncio.create_task(asyncio.to_thread(_add))


async def get_all_memories_async(session_id: str) -> Any:
    """Retrieve all memories for a session asynchronously."""
    if not client:
        return []
    return await asyncio.to_thread(client.get_all, filters={"user_id": session_id})


async def add_custom_memory_async(
    text: str, session_id: str, metadata: Optional[dict] = None
) -> Any:
    """Add a custom memory asynchronously."""
    if not client:
        return None
    return await asyncio.to_thread(
        client.add, text, user_id=session_id, metadata=metadata or {}
    )


async def search_memories_async(query: str, session_id: str) -> Any:
    """Search memories asynchronously."""
    if not client:
        return []
    return await asyncio.to_thread(
        client.search, query, filters={"user_id": session_id}
    )


async def update_memory_async(memory_id: str, text: str) -> Any:
    """Update a specific memory asynchronously."""
    if not client:
        return None
    return await asyncio.to_thread(client.update, memory_id, text)


async def delete_memory_async(memory_id: str) -> Any:
    """Delete a specific memory asynchronously."""
    if not client:
        return None
    return await asyncio.to_thread(client.delete, memory_id)


async def delete_all_session_memories_async(session_id: str) -> Any:
    """Delete all memories for a session asynchronously."""
    if not client:
        return None
    if hasattr(client, "delete_all"):
        return await asyncio.to_thread(client.delete_all, user_id=session_id)

    # Fallback deletion if client doesn't support delete_all directly
    memories = await get_all_memories_async(session_id)
    items = []
    if isinstance(memories, list):
        items = memories
    elif isinstance(memories, dict) and "results" in memories:
        items = memories["results"]

    deleted_count = 0
    for m in items:
        m_id = m.get("id") if isinstance(m, dict) else getattr(m, "id", None)
        if m_id:
            await delete_memory_async(m_id)
            deleted_count += 1
    return {"deleted": deleted_count}

