#!/usr/bin/env bash
# ==============================================================================
# AgentScope Pre-PR Quality & Standards Verification Script
# ==============================================================================
# Run this script before submitting a pull request to verify code formatting,
# linting, security standards, and automated unit/integration test suites.
#
# Usage:
#   ./scripts/pre_pr_check.sh
#   make pre-pr
# ==============================================================================

set -eo pipefail

BOLD="\033[1m"
GREEN="\033[32m"
RED="\033[31m"
YELLOW="\033[33m"
CYAN="\033[36m"
RESET="\033[0m"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo -e "${BOLD}${CYAN}======================================================================${RESET}"
echo -e "${BOLD}${CYAN}          AgentScope Pre-PR Quality & Standards Verification         ${RESET}"
echo -e "${BOLD}${CYAN}======================================================================${RESET}"
echo ""

FAILED_STEPS=0

run_step() {
    local step_name="$1"
    shift
    echo -e "${BOLD}--> [RUNNING]${RESET} ${step_name}..."
    if "$@"; then
        echo -e "${GREEN}    [PASSED]${RESET} ${step_name}\n"
    else
        echo -e "${RED}    [FAILED]${RESET} ${step_name}\n"
        FAILED_STEPS=$((FAILED_STEPS + 1))
    fi
}

# 1. Python Linting (Ruff)
echo -e "${YELLOW}Step 1: Python Linting & Security Analysis${RESET}"
run_step "Ruff Linting Check" ruff check .

# 2. Python Code Formatting (Black)
echo -e "${YELLOW}Step 2: Python Code Formatting${RESET}"
run_step "Black Code Formatting Check" black --check .

# 3. Python Unit & Integration Tests (Pytest)
echo -e "${YELLOW}Step 3: Python SDK & Server Test Suites${RESET}"
run_step "Pytest SDK & Server Tests" pytest packages/sdk/tests packages/server/tests .github/scripts/tests

# 4. Next.js UI Linting (ESLint)
echo -e "${YELLOW}Step 4: Next.js UI Linting${RESET}"
if [ -d "packages/ui" ] && [ -f "packages/ui/package.json" ]; then
    run_step "UI Linting" bash -c "cd packages/ui && npm run lint"
else
    echo "Skipping UI Linting (packages/ui not found)."
fi

# 5. Next.js UI Build & TypeScript Typecheck
echo -e "${YELLOW}Step 5: Next.js UI Production Build & Type Checking${RESET}"
if [ -d "packages/ui" ] && [ -f "packages/ui/package.json" ]; then
    run_step "UI Production Build" bash -c "cd packages/ui && npm run build"
else
    echo "Skipping UI Build (packages/ui not found)."
fi

# 6. Next.js UI Unit Tests (Vitest)
echo -e "${YELLOW}Step 6: Next.js UI Type Check & Unit Tests${RESET}"
if [ -d "packages/ui" ] && [ -f "packages/ui/package.json" ]; then
    run_step "UI Type Check" bash -c "cd packages/ui && npx tsc --noEmit"
    run_step "UI Unit Tests (Vitest + coverage)" bash -c "cd packages/ui && npm run test:coverage"
else
    echo "Skipping UI Unit Tests (packages/ui not found)."
fi

# 7. Next.js UI E2E Smoke Test (Playwright)
# Needs the server's Python dependencies and Playwright's Chromium
# (cd packages/ui && npx playwright install --only-shell chromium).
# Set SKIP_UI_E2E=1 to skip it.
echo -e "${YELLOW}Step 7: Next.js UI E2E Smoke Test${RESET}"
if [ "${SKIP_UI_E2E:-0}" = "1" ]; then
    echo "Skipping UI E2E smoke test (SKIP_UI_E2E=1)."
elif [ -d "packages/ui" ] && [ -f "packages/ui/package.json" ]; then
    run_step "UI E2E Smoke Test (Playwright)" bash -c "cd packages/ui && npm run test:e2e"
else
    echo "Skipping UI E2E smoke test (packages/ui not found)."
fi

echo -e "${BOLD}${CYAN}======================================================================${RESET}"
if [ "$FAILED_STEPS" -eq 0 ]; then
    echo -e "${BOLD}${GREEN}✔ ALL PRE-PR CHECKS PASSED! Your branch is ready for Pull Request.${RESET}"
    echo -e "${BOLD}${CYAN}======================================================================${RESET}"
    exit 0
else
    echo -e "${BOLD}${RED}✘ ${FAILED_STEPS} PRE-PR CHECK(S) FAILED. Please resolve errors before opening a PR.${RESET}"
    echo -e "${YELLOW}Tip: Run 'ruff check --fix .' and 'black .' to resolve Python formatting.${RESET}"
    echo -e "${BOLD}${CYAN}======================================================================${RESET}"
    exit 1
fi
