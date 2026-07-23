# Makefile for AgentScope development orchestration

.PHONY: setup-sdk setup-server setup-ui setup-all test test-sdk test-server run-server run-ui clean help

help:
	@echo "Available commands:"
	@echo "  make setup-sdk     - Install SDK in editable mode with dev/langchain packages"
	@echo "  make setup-server  - Install Server requirements"
	@echo "  make setup-ui      - Install UI node modules"
	@echo "  make setup-all     - Setup all modules"
	@echo "  make test-sdk      - Run Python SDK tests"
	@echo "  make test-server   - Run Python Server tests"
	@echo "  make test          - Run all tests"
	@echo "  make run-server    - Run FastAPI server with hot-reload"
	@echo "  make run-ui        - Run Next.js UI in dev mode"
	@echo "  make clean         - Remove caches, builds, and local db files"

setup-sdk:
	cd packages/sdk && pip install -e .[dev,langchain]

setup-server:
	cd packages/server && pip install -r requirements.txt

setup-ui:
	cd packages/ui && npm install --legacy-peer-deps

setup-all: setup-sdk setup-server setup-ui

test-sdk:
	cd packages/sdk && pytest

test-server:
	cd packages/server && pytest

test: test-sdk test-server

run-server:
	cd packages/server && uvicorn main:app --host 0.0.0.0 --port 8765 --reload

run-ui:
	cd packages/ui && npm run dev

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".next" -exec rm -rf {} +
	find . -type d -name "node_modules" -exec rm -rf {} +
	rm -f packages/server/agentscope.db packages/server/agentscope.db-journal packages/server/agentscope.db-wal
