import asyncio
import logging
import os
from typing import Optional

from mem0 import MemoryClient

logger = logging.getLogger(__name__)

# Initialize client
MEM0_API_KEY = os.getenv("MEM0_API_KEY")
client: Optional[MemoryClient] = None

if MEM0_API_KEY:
    try:
        client = MemoryClient(api_key=MEM0_API_KEY)
        logger.info("Mem0 client initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize Mem0 client: {e}")
else:
    logger.warning(
        "MEM0_API_KEY is not configured in environment. "
        "Mem0 memory integration is disabled."
    )


def get_mem0_client() -> Optional[MemoryClient]:
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
