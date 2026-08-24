# Makefile for AgentScope development orchestration

.PHONY: all setup-sdk setup-server setup-ui setup-all test test-sdk test-server test-ui test-all lint format pre-pr run-server run-ui clean docker-clean help

all: setup-all

help:
	@echo "Available commands:"
	@echo "  make setup-sdk     - Install SDK in editable mode with dev/langchain packages"
	@echo "  make setup-server  - Install Server requirements"
	@echo "  make setup-ui      - Install UI node modules"
	@echo "  make setup-all     - Setup all modules"
	@echo "  make lint          - Run Python and UI linters"
	@echo "  make format        - Auto-format Python codebase with Ruff and Black"
	@echo "  make test-sdk      - Run Python SDK tests"
	@echo "  make test-server   - Run Python Server tests"
	@echo "  make test-ui       - Run Next.js UI lint and build checks"
	@echo "  make test          - Run all test suites"
	@echo "  make pre-pr        - Run comprehensive pre-PR quality, linting & test suite"
	@echo "  make run-server    - Run FastAPI server with hot-reload"
	@echo "  make run-ui        - Run Next.js UI in dev mode"
	@echo "  make clean         - Remove caches, builds, and local db files"
	@echo "  make docker-clean  - Stop containers and destroy sqlite_data volume"

setup-sdk:
	cd packages/sdk && pip install -e ".[dev,langchain]"

setup-server:
	cd packages/server && pip install -r requirements.txt

setup-ui:
	cd packages/ui && npm install --legacy-peer-deps

setup-all: setup-sdk setup-server setup-ui

lint:
	ruff check .
	cd packages/ui && npm run lint

format:
	ruff check --fix .
	black .

test-sdk:
	pytest packages/sdk/tests

test-server:
	pytest packages/server/tests

test-ui:
	cd packages/ui && npm run lint && npm run build

test: test-sdk test-server
	pytest .github/scripts/tests

test-all: test test-ui

pre-pr:
	./scripts/pre_pr_check.sh

run-server:
	cd packages/server && uvicorn main:app --host 0.0.0.0 --port 8765 --reload

run-ui:
	cd packages/ui && npm run dev

# clean: Removes only host-side build caches, dependency folders, and SQLite databases.
# Note: This does NOT delete the persistent named sqlite_data Docker Compose volume.
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -exec rm -rf {} +
	find . -type d -name ".next" -exec rm -rf {} +
	find . -type d -name "node_modules" -exec rm -rf {} +
	rm -f packages/server/agentscope.db packages/server/agentscope.db-journal packages/server/agentscope.db-wal
	rm -f test_live_*.db test_live_*.db-journal test_live_*.db-wal

# docker-clean: Destructively stops Compose services and deletes volume storage.
docker-clean:
	docker compose down -v
