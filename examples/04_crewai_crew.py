"""Trace a CrewAI crew with AgentScope.

Requires: pip install -e "packages/sdk[crewai]" and an LLM key for CrewAI's
default model (e.g. OPENAI_API_KEY). Start the AgentScope server first (see the
README), then run this script and open the dashboard.
"""

from agentscope_trace.integrations.crewai import AgentScopeCrewAIListener
from crewai import Agent, Crew, Process, Task
from crewai.tools import tool

# 1. Register the listener once, before kickoff. Every crew run in this process
#    is streamed to the same AgentScope session.
listener = AgentScopeCrewAIListener(
    host="127.0.0.1", port=8765, session_name="CrewAI research crew"
)


@tool("word_count")
def word_count(text: str) -> str:
    """Count the words in a piece of text."""
    return str(len(text.split()))


researcher = Agent(
    role="Researcher",
    goal="Collect three key facts about a topic",
    backstory="A meticulous analyst.",
)
writer = Agent(
    role="Writer",
    goal="Turn facts into a short paragraph",
    backstory="A concise technical writer.",
    tools=[word_count],
)

crew = Crew(
    name="research-crew",
    agents=[researcher, writer],
    tasks=[
        Task(
            description="List three facts about {topic}.",
            expected_output="Three bullet points",
            agent=researcher,
        ),
        Task(
            description="Write one paragraph from the facts and report its word count.",
            expected_output="A paragraph followed by its word count",
            agent=writer,
        ),
    ],
    process=Process.sequential,
)

if __name__ == "__main__":
    try:
        print(crew.kickoff(inputs={"topic": "observability for AI agents"}).raw)
    finally:
        listener.close()  # delivers pending events, then stops the client
