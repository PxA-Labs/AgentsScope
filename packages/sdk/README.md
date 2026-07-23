# AgentScope Python SDK

A lightweight tracing library that instruments AI agent pipelines (primarily LangChain) and streams execution traces to the AgentScope server in real time.

## Installation

```bash
# Basic install
pip install -e .

# Or install with langchain support
pip install -e .[langchain]
```

## Features

- **Non-blocking Telemetry**: Uses an asynchronous in-memory queue to send traces so agent execution is never delayed.
- **WebSocket Transport**: Maintains a connection to the AgentScope server with automatic reconnection and buffering.
- **LangChain Callback Handler**: Easily trace chains, tools, agents, and LLMs with two lines of code.
- **Custom Tracing**: `@trace` decorator for tracking non-LangChain code.
