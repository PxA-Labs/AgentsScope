# AgentScope Developer Setup & Contribution Guide

Welcome to the **AgentScope** development repository. This document outlines step-by-step instructions for configuring your local environment, executing test suites, running example pipelines, and contributing code changes.

---

## 1. Project Architecture Overview

AgentScope is structured as a monorepo containing three core packages:

*   **`packages/sdk/`**: Python-based telemetry and monitoring SDK. Contains the `@trace` decorator and LangChain tracking callbacks.
*   **`packages/server/`**: FastAPI-based observability server, persisting sessions and telemetry log events to SQLite.
*   **`packages/ui/`**: Next.js (Tailwind CSS, Zustand, React Flow) developer dashboard displaying live telemetry streams and session analytics.

---

## 2. Local Environment Setup

### Prerequisites
*   **Python**: Version `3.10` or higher.
*   **Node.js**: Version `18` or higher (with `npm`).
*   **Git**: For version control.

### Python Backend & SDK Setup
1.  Create and activate a virtual environment in the repository root:
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows, use: venv\Scripts\activate
    ```
2.  Install dependencies for the SDK:
    ```bash
    cd packages/sdk
    pip install -e .
    cd ../..
    ```
3.  Install dependencies for the Server:
    ```bash
    cd packages/server
    pip install -r requirements.txt -r requirements-dev.txt
    cd ../..
    ```

### Node.js UI Dashboard Setup
1.  Navigate to the UI directory:
    ```bash
    cd packages/ui
    ```
2.  Install frontend dependencies:
    ```bash
    npm install
    ```
3.  Build the dashboard to verify compilation:
    ```bash
    npm run build
    ```
4.  Navigate back to root:
    ```bash
    cd ../..
    ```

---

## 3. Running Services Locally

To verify end-to-end telemetry flows, boot up the observability server followed by the UI client.

### Step 1: Start the Observability Server
Launch Uvicorn in the server folder (exposing port `8765` by default):
```bash
cd packages/server
uvicorn main:app --reload --port 8765
```

### Step 2: Start the UI Dev Server
Launch the Next.js development server (runs on `http://localhost:3000` by default):
```bash
cd packages/ui
npm run dev
```

---

## 4. Running the Local Test Suite

We use `pytest` to validate Python modifications and maintain code quality. We provide helper commands in the root `Makefile` to simplify validation.

*   **Run all tests (SDK & Server)**:
    ```bash
    make test
    ```
*   **Run SDK tests only**:
    ```bash
    cd packages/sdk
    pytest
    ```
*   **Run Server tests only**:
    ```bash
    cd packages/server
    pytest
    ```

---

## 5. Telemetry Pipeline Verification

To verify that your setup intercepts agent executions and streams them to the local server, execute a simple Python telemetry script:

```python
import time
import asyncio
import agentscope.decorators as as_deco

# 1. Configure telemetry client to send records to the server
as_deco.configure(
    host="127.0.0.1",
    port=8765,
    session_name="Manual Verification Session"
)

# 2. Instrument functions using the @trace decorator
@as_deco.trace(name="MathChain", agent_type="chain")
def run_math_computation(base_val: int) -> int:
    time.sleep(0.5)
    return base_val * 20

@as_deco.trace(name="GreetingAgent", agent_type="agent")
async def async_greeting(user_name: str) -> str:
    await asyncio.sleep(0.3)
    return f"Hello, {user_name}!"

# 3. Execute instrumented methods
if __name__ == "__main__":
    print("Launching instrumented pipeline...")
    res_sync = run_math_computation(5)
    print(f"Sync Result: {res_sync}")

    res_async = asyncio.run(async_greeting("Developer"))
    print(f"Async Result: {res_async}")
    print("Verification execution complete. Open http://localhost:3000 to view session events.")
```
Ensure the server and UI are running, execute this script, and confirm that the session name and logged events appear on the dashboard in real-time.
