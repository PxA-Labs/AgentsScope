import time
from langchain.agents import AgentExecutor, create_react_agent
from langchain_core.prompts import PromptTemplate
from langchain_core.tools import tool
from langchain_community.llms.fake import FakeListLLM
from agentscope.callback import AgentScopeCallback

# 1. Initialize callback handler
callback = AgentScopeCallback(
    host="127.0.0.1",
    port=8765,
    session_name="AgentExecutor Telemetry Session",
)

# 2. Define custom developer tool
@tool
def calculate_velocity(mass_and_force: str) -> float:
    """Calculate velocity based on force and mass inputs. The input should be 'mass, force'."""
    time.sleep(0.3)
    try:
        mass_str, force_str = mass_and_force.split(",")
        return float(force_str) / float(mass_str)
    except Exception:
        return 0.0


tools = [calculate_velocity]

# 3. Create reactive LLM and prompt
llm = FakeListLLM(
    responses=[
        "Thought: I need to calculate the velocity using the tool.\nAction: calculate_velocity\nAction Input: 10.0, 50.0",
        "Final Answer: The calculated velocity is 5.0 m/s.",
    ]
)

prompt = PromptTemplate.from_template(
    "Answer the following questions as best you can. You have access to the following tools:\n\n"
    "{tools}\n\nUse the following format:\n\n"
    "Question: the input question you must answer\n"
    "Thought: you should always think about what to do\n"
    "Action: the action to take, should be one of [{tool_names}]\n"
    "Action Input: the input to the action\n"
    "Observation: the result of the action\n"
    "... (this Thought/Action/Action Input/Observation can repeat N times)\n"
    "Thought: I now know the final answer\n"
    "Final Answer: the final answer to the original question\n\n"
    "Question: {input}\n\n"
    "Thought:\n{agent_scratchpad}"
)

# 4. Initialize reactive agent and executor
agent = create_react_agent(llm, tools, prompt)
executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

if __name__ == "__main__":
    print("Launching AgentExecutor pipeline with AgentScope telemetry...")
    result = executor.invoke(
        {"input": "What is the velocity for mass 10 and force 50?"},
        config={"callbacks": [callback]},
    )
    print(f"Final Answer: {result['output']}")

    # Flush logs
    time.sleep(2)
    print("Telemetry complete.")
