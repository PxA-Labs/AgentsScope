"""Trace direct Anthropic SDK calls with AgentScope.

Requires: pip install -e "packages/sdk[anthropic]" and ANTHROPIC_API_KEY.
Start the AgentScope server first (see the README), then run this script.
"""

import os
import time

import anthropic
from agentscope_trace import patch_anthropic, trace
from agentscope_trace.decorators import configure

configure(host="127.0.0.1", port=8765, session_name="Anthropic direct calls")
patch_anthropic()  # instruments every Anthropic client in this process

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
client = anthropic.Anthropic()


@trace(name="Researcher", agent_type="agent")
def research(question: str) -> str:
    # Non-streaming call: one llm_start / llm_end pair nested under Researcher.
    answer = client.messages.create(
        model=MODEL,
        max_tokens=200,
        system="Answer in one sentence.",
        messages=[{"role": "user", "content": question}],
    )
    summary = answer.content[0].text

    # Streaming helper: recorded when the with-block exits.
    with client.messages.stream(
        model=MODEL,
        max_tokens=100,
        messages=[{"role": "user", "content": f"Give a title for: {summary}"}],
    ) as stream:
        title = "".join(stream.text_stream)
    return f"{title}\n{summary}"


if __name__ == "__main__":
    print(research("Why is the sky blue?"))
    time.sleep(2)  # let the background client flush events
