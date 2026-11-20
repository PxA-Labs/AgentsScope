"""Trace an AutoGen group chat with AgentScope.

Requires: pip install -e "packages/sdk[autogen]" "autogen-ext[openai]" and
OPENAI_API_KEY. Start the AgentScope server first (see the README).
"""

import asyncio

from agentscope_trace.decorators import configure
from agentscope_trace.integrations.autogen import (
    AgentScopeAutoGenTracer,
    trace_model_client,
)
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_ext.models.openai import OpenAIChatCompletionClient

configure(host="127.0.0.1", port=8765, session_name="AutoGen group chat")


async def word_count(text: str) -> str:
    """Count the words in a piece of text."""
    return str(len(text.split()))


async def main() -> None:
    model = trace_model_client(OpenAIChatCompletionClient(model="gpt-4o-mini"))
    researcher = AssistantAgent(
        "researcher",
        model_client=model,
        system_message="List three facts about the topic.",
    )
    writer = AssistantAgent(
        "writer",
        model_client=model,
        tools=[word_count],
        reflect_on_tool_use=True,
        system_message="Write one paragraph from the facts, check its word count, "
        "then reply with TERMINATE.",
    )
    team = RoundRobinGroupChat(
        [researcher, writer],
        termination_condition=TextMentionTermination("TERMINATE")
        | MaxMessageTermination(6),
    )
    result = await AgentScopeAutoGenTracer(name="facts-team").run(
        team, task="Observability for AI agents"
    )
    print(result.messages[-1].content)
    await model.close()


if __name__ == "__main__":
    asyncio.run(main())
