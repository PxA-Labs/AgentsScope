"""Trace a LlamaIndex RAG query with AgentScope.

Runs offline with LlamaIndex's mock embedding and LLM, so it needs no API key:
    pip install -e "packages/sdk[llamaindex]"   (Python 3.11+)
Start the AgentScope server first (see the README), then run this script.
Swap Settings.llm / Settings.embed_model for real models in your app.
"""

from agentscope_trace.decorators import configure, get_global_client
from agentscope_trace.integrations.llamaindex import instrument_llamaindex
from llama_index.core import Document, Settings, VectorStoreIndex
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.llms import MockLLM

configure(host="127.0.0.1", port=8765, session_name="LlamaIndex RAG")
instrument_llamaindex()

Settings.embed_model = MockEmbedding(embed_dim=16)
Settings.llm = MockLLM(max_tokens=32)

index = VectorStoreIndex.from_documents(
    [
        Document(
            text="AgentScope shows agent runs as a live DAG.",
            metadata={"src": "readme"},
        ),
        Document(
            text="Retriever nodes list the documents that were retrieved.",
            metadata={"src": "docs"},
        ),
    ]
)

if __name__ == "__main__":
    engine = index.as_query_engine(similarity_top_k=2)
    print(engine.query("What does AgentScope show?"))
    # Deliver queued events and exit (relies on the shutdown fix for #294).
    get_global_client().stop()
