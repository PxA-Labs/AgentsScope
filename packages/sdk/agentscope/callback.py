import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence
from uuid import UUID

from agentscope.client import AgentScopeClient

# Gracefully handle missing langchain-core dependencies
try:
    from langchain_core.callbacks import AsyncCallbackHandler
    from langchain_core.outputs import LLMResult

    # Document type might not be directly imported or could be from different places
    # We will safely accept Sequence[Any] in the callback
except ImportError:

    class AsyncCallbackHandler:  # type: ignore
        pass

    class LLMResult:  # type: ignore
        pass


class AgentScopeCallback(AsyncCallbackHandler):
    """LangChain callback handler that streams telemetry to the AgentScope server."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8765,
        session_name: Optional[str] = None,
        session_metadata: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the callback handler.

        Args:
            host: The AgentScope server host.
            port: The AgentScope server port.
            session_name: Custom name for this run session.
            session_metadata: Arbitrary tags or configurations for the session.
        """
        super().__init__()
        self.client = AgentScopeClient(
            host=host,
            port=port,
            session_name=session_name,
            session_metadata=session_metadata,
        )

    def _resolve_name(
        self,
        serialized: Optional[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]],
        default: str,
    ) -> str:
        """Helper to extract a descriptive agent/node name from LangChain metadata."""
        if metadata:
            if name := (metadata.get("agent_name") or metadata.get("run_name")):
                return str(name)
        if serialized:
            if name := serialized.get("name"):
                return str(name)
            if id_path := serialized.get("id"):
                if isinstance(id_path, list) and id_path:
                    return str(id_path[-1])
        return default

    # --- Chain Callbacks ---

    async def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        try:
            agent_name = self._resolve_name(serialized, metadata, default="Chain")
            event = {
                "event_id": str(run_id),
                "session_id": "",  # populated client-side / server-side
                "parent_event_id": (str(parent_run_id) if parent_run_id else None),
                "event_type": "chain_start",
                "agent_name": agent_name,
                "agent_type": "chain",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "latency_ms": None,
                "status": "running",
                "payload": {
                    "chain_type": (
                        serialized.get("name") or serialized.get("id", ["Chain"])[-1]
                    ),
                    "inputs": inputs,
                    "outputs": None,
                    "error": None,
                },
            }
            self.client.emit(event)
        except Exception as e:
            logging.warning(f"AgentScope callback error in on_chain_start: {e}")

    async def on_chain_end(
        self,
        outputs: Dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        try:
            event = {
                "event_id": str(run_id),
                "session_id": "",
                "parent_event_id": (str(parent_run_id) if parent_run_id else None),
                "event_type": "chain_end",
                "agent_name": "Chain",
                "agent_type": "chain",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "latency_ms": None,
                "status": "completed",
                "payload": {
                    "chain_type": "Chain",
                    "inputs": {},
                    "outputs": outputs,
                    "error": None,
                },
            }
            self.client.emit(event)

            if not parent_run_id:
                # Root execution chain completed, mark session finished
                self.client.patch_session_status("completed")
        except Exception as e:
            logging.warning(f"AgentScope callback error in on_chain_end: {e}")

    async def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        try:
            event = {
                "event_id": str(run_id),
                "session_id": "",
                "parent_event_id": (str(parent_run_id) if parent_run_id else None),
                "event_type": "chain_error",
                "agent_name": "Chain",
                "agent_type": "chain",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "latency_ms": None,
                "status": "error",
                "payload": {
                    "chain_type": "Chain",
                    "inputs": {},
                    "outputs": None,
                    "error": str(error),
                },
            }
            self.client.emit(event)

            if not parent_run_id:
                # Root execution chain failed, mark session failed
                self.client.patch_session_status("failed")
        except Exception as e:
            logging.warning(f"AgentScope callback error in on_chain_error: {e}")

    # --- LLM Callbacks ---

    async def on_llm_start(
        self,
        serialized: Dict[str, Any],
        prompts: List[str],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        try:
            agent_name = self._resolve_name(serialized, metadata, default="LLM")
            model = ""
            if invocation_params := kwargs.get("invocation_params"):
                model = (
                    invocation_params.get("model")
                    or invocation_params.get("model_name")
                    or ""
                )
            elif metadata:
                model = metadata.get("model") or metadata.get("model_name") or ""
            if not model and serialized:
                model = serialized.get("name") or serialized.get("id", ["LLM"])[-1]

            event = {
                "event_id": str(run_id),
                "session_id": "",
                "parent_event_id": (str(parent_run_id) if parent_run_id else None),
                "event_type": "llm_start",
                "agent_name": agent_name,
                "agent_type": "llm",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "latency_ms": None,
                "status": "running",
                "payload": {
                    "model": model,
                    "prompts": prompts,
                    "completion": None,
                    "prompt_tokens": None,
                    "completion_tokens": None,
                    "total_tokens": None,
                    "temperature": kwargs.get("invocation_params", {}).get(
                        "temperature"
                    ),
                    "streaming": kwargs.get("invocation_params", {}).get(
                        "stream", False
                    ),
                },
            }
            self.client.emit(event)
        except Exception as e:
            logging.warning(f"AgentScope callback error in on_llm_start: {e}")

    async def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        try:
            completion = ""
            prompt_tokens = None
            completion_tokens = None
            total_tokens = None

            # Reconstruct response completion text
            if hasattr(response, "generations") and response.generations:
                completions = []
                for gen_list in response.generations:
                    for gen in gen_list:
                        if hasattr(gen, "text"):
                            completions.append(gen.text)
                completion = "\n".join(completions)

            # Retrieve token usage from response outputs
            if hasattr(response, "llm_output") and response.llm_output:
                token_usage = response.llm_output.get("token_usage")
                if token_usage:
                    prompt_tokens = token_usage.get("prompt_tokens") or token_usage.get(
                        "input_tokens"
                    )
                    completion_tokens = token_usage.get(
                        "completion_tokens"
                    ) or token_usage.get("output_tokens")
                    total_tokens = token_usage.get("total_tokens") or (
                        (prompt_tokens + completion_tokens)
                        if (prompt_tokens is not None and completion_tokens is not None)
                        else None
                    )

            event = {
                "event_id": str(run_id),
                "session_id": "",
                "parent_event_id": (str(parent_run_id) if parent_run_id else None),
                "event_type": "llm_end",
                "agent_name": "LLM",
                "agent_type": "llm",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "latency_ms": None,
                "status": "completed",
                "payload": {
                    "model": "",
                    "prompts": [],
                    "completion": completion,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "temperature": None,
                    "streaming": False,
                },
            }
            self.client.emit(event)
        except Exception as e:
            logging.warning(f"AgentScope callback error in on_llm_end: {e}")

    async def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        try:
            event = {
                "event_id": str(run_id),
                "session_id": "",
                "parent_event_id": (str(parent_run_id) if parent_run_id else None),
                "event_type": "llm_error",
                "agent_name": "LLM",
                "agent_type": "llm",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "latency_ms": None,
                "status": "error",
                "payload": {
                    "model": "",
                    "prompts": [],
                    "completion": None,
                    "prompt_tokens": None,
                    "completion_tokens": None,
                    "total_tokens": None,
                    "temperature": None,
                    "streaming": False,
                },
            }
            self.client.emit(event)
        except Exception as e:
            logging.warning(f"AgentScope callback error in on_llm_error: {e}")

    # --- Tool Callbacks ---

    async def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        try:
            tool_name = self._resolve_name(serialized, metadata, default="Tool")
            event = {
                "event_id": str(run_id),
                "session_id": "",
                "parent_event_id": (str(parent_run_id) if parent_run_id else None),
                "event_type": "tool_start",
                "agent_name": tool_name,
                "agent_type": "tool",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "latency_ms": None,
                "status": "running",
                "payload": {
                    "tool_name": tool_name,
                    "tool_description": serialized.get("description"),
                    "input": input_str,
                    "output": None,
                    "error": None,
                },
            }
            self.client.emit(event)
        except Exception as e:
            logging.warning(f"AgentScope callback error in on_tool_start: {e}")

    async def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        try:
            event = {
                "event_id": str(run_id),
                "session_id": "",
                "parent_event_id": (str(parent_run_id) if parent_run_id else None),
                "event_type": "tool_end",
                "agent_name": "Tool",
                "agent_type": "tool",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "latency_ms": None,
                "status": "completed",
                "payload": {
                    "tool_name": "Tool",
                    "tool_description": None,
                    "input": "",
                    "output": str(output),
                    "error": None,
                },
            }
            self.client.emit(event)
        except Exception as e:
            logging.warning(f"AgentScope callback error in on_tool_end: {e}")

    async def on_tool_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        try:
            event = {
                "event_id": str(run_id),
                "session_id": "",
                "parent_event_id": (str(parent_run_id) if parent_run_id else None),
                "event_type": "tool_error",
                "agent_name": "Tool",
                "agent_type": "tool",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "latency_ms": None,
                "status": "error",
                "payload": {
                    "tool_name": "Tool",
                    "tool_description": None,
                    "input": "",
                    "output": None,
                    "error": str(error),
                },
            }
            self.client.emit(event)
        except Exception as e:
            logging.warning(f"AgentScope callback error in on_tool_error: {e}")

    # --- Retriever Callbacks ---

    async def on_retriever_start(
        self,
        serialized: Dict[str, Any],
        query: str,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        try:
            retriever_name = self._resolve_name(
                serialized, metadata, default="Retriever"
            )
            event = {
                "event_id": str(run_id),
                "session_id": "",
                "parent_event_id": (str(parent_run_id) if parent_run_id else None),
                "event_type": "retriever_start",
                "agent_name": retriever_name,
                "agent_type": "retriever",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "latency_ms": None,
                "status": "running",
                "payload": {
                    "query": query,
                    "documents": None,
                },
            }
            self.client.emit(event)
        except Exception as e:
            logging.warning(f"AgentScope callback error in on_retriever_start: {e}")

    async def on_retriever_end(
        self,
        documents: Sequence[Any],
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        try:
            formatted_docs = []
            for doc in documents:
                # Format each document cleanly
                content = getattr(doc, "page_content", "") or str(doc)
                doc_metadata = getattr(doc, "metadata", {}) or {}
                formatted_docs.append({"content": content, "metadata": doc_metadata})

            event = {
                "event_id": str(run_id),
                "session_id": "",
                "parent_event_id": (str(parent_run_id) if parent_run_id else None),
                "event_type": "retriever_end",
                "agent_name": "Retriever",
                "agent_type": "retriever",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "latency_ms": None,
                "status": "completed",
                "payload": {
                    "query": "",
                    "documents": formatted_docs,
                },
            }
            self.client.emit(event)
        except Exception as e:
            logging.warning(f"AgentScope callback error in on_retriever_end: {e}")

    # --- Agent Callbacks ---

    async def on_agent_action(
        self,
        action: Any,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        try:
            tool = getattr(action, "tool", "Unknown")
            tool_input = getattr(action, "tool_input", "")
            log = getattr(action, "log", "")

            event = {
                "event_id": str(run_id),
                "session_id": "",
                "parent_event_id": (str(parent_run_id) if parent_run_id else None),
                "event_type": "agent_action",
                "agent_name": "Agent",
                "agent_type": "agent",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "latency_ms": None,
                "status": "running",
                "payload": {
                    "tool_name": tool,
                    "tool_description": log,
                    "input": str(tool_input),
                    "output": None,
                    "error": None,
                },
            }
            self.client.emit(event)
        except Exception as e:
            logging.warning(f"AgentScope callback error in on_agent_action: {e}")

    async def on_agent_finish(
        self,
        finish: Any,
        *,
        run_id: UUID,
        parent_run_id: Optional[UUID] = None,
        **kwargs: Any,
    ) -> None:
        try:
            output = getattr(finish, "return_values", {})
            log = getattr(finish, "log", "")

            event = {
                "event_id": str(run_id),
                "session_id": "",
                "parent_event_id": (str(parent_run_id) if parent_run_id else None),
                "event_type": "agent_finish",
                "agent_name": "Agent",
                "agent_type": "agent",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "latency_ms": None,
                "status": "completed",
                "payload": {
                    "chain_type": "AgentFinish",
                    "inputs": {"log": log},
                    "outputs": output,
                    "error": None,
                },
            }
            self.client.emit(event)
        except Exception as e:
            logging.warning(f"AgentScope callback error in on_agent_finish: {e}")
