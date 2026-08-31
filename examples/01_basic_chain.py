import time

from agentscope.callback import AgentScopeCallback
from langchain_community.llms.fake import FakeListLLM
from langchain_core.prompts import ChatPromptTemplate

# 1. Initialize AgentScope callback handler
callback = AgentScopeCallback(
    host="127.0.0.1",
    port=8765,
    session_name="Basic LLM Chain Tracing",
)

# 2. Build simple mock LLM and prompt
llm = FakeListLLM(
    responses=["Antigravity is a hypothetical force that opposes gravity."]
)
prompt = ChatPromptTemplate.from_template("Explain the concept of {topic}.")

# 3. Chain prompt and LLM
chain = prompt | llm

if __name__ == "__main__":
    print("Executing LangChain pipeline with AgentScope telemetry...")
    # Run the chain passing the callback handler
    result = chain.invoke({"topic": "antigravity"}, config={"callbacks": [callback]})
    print(f"Result: {result}")

    # Wait briefly for client logs to flush
    time.sleep(2)
    print("Telemetry complete.")
