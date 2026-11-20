"""Trace direct Google Gen AI (Gemini) SDK calls with AgentScope.

Requires: pip install -e "packages/sdk[gemini]" (Python 3.11+) and GEMINI_API_KEY.
Start the AgentScope server first (see the README), then run this script.
"""

import os
import time

from agentscope_trace import patch_gemini, trace
from agentscope_trace.decorators import configure
from google import genai
from google.genai import types

configure(host="127.0.0.1", port=8765, session_name="Gemini direct calls")
patch_gemini()  # instruments client.models.* and client.aio.models.*

MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
client = genai.Client()


@trace(name="Writer", agent_type="agent")
def write(topic: str) -> str:
    outline = client.models.generate_content(
        model=MODEL,
        contents=f"Three bullet points about {topic}.",
        config=types.GenerateContentConfig(system_instruction="Be concise."),
    ).text

    # Streaming: llm_end fires once the stream is fully consumed.
    parts = []
    for chunk in client.models.generate_content_stream(
        model=MODEL, contents=f"Turn this into a paragraph:\n{outline}"
    ):
        parts.append(chunk.text or "")
    return "".join(parts)


if __name__ == "__main__":
    print(write("observability for AI agents"))
    time.sleep(2)  # let the background client flush events
