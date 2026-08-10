import time
import asyncio
import agentscope.decorators as as_deco

# 1. Configure the global telemetry client settings
as_deco.configure(
    host="127.0.0.1", port=8765, session_name="Decorator Tracing Session"
)


# 2. Decorate standard synchronous function
@as_deco.trace(name="SyncMathProcess", agent_type="chain")
def process_data_sync(value: int) -> int:
    print(f"Inside sync process: value={value}")
    time.sleep(0.4)
    return value + 100


# 3. Decorate standard asynchronous function
@as_deco.trace(name="AsyncNetworkRequest", agent_type="retriever")
async def fetch_data_async(url: str) -> dict:
    print(f"Inside async fetch: url={url}")
    await asyncio.sleep(0.3)
    return {"status": 200, "data": "telemetry payload"}


if __name__ == "__main__":
    print("Launching synchronous trace step...")
    res_sync = process_data_sync(10)
    print(f"Sync result: {res_sync}\n")

    print("Launching asynchronous trace step...")
    res_async = asyncio.run(fetch_data_async("https://api.agentscope.dev/v1"))
    print(f"Async result: {res_async}")

    time.sleep(2)
    print("Telemetry complete.")
