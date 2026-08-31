# Contributing to AgentScope

First off, thank you for considering contributing to AgentScope! It's community members like you that make AgentScope an awesome open-source project.

AgentScope is distributed as open-source software under the [Apache License 2.0](LICENSE). We welcome contributions of all kinds, whether you are fixing bugs, improving documentation, submitting feature proposals, or building new agent integrations.

---

## Ways to Contribute

There are many ways to contribute to AgentScope beyond writing code:

- **Bug Reports**: Report issues, unexpected behaviors, or edge-case failures you encounter.
- **Feature Requests**: Propose new capabilities, agent primitives, UI enhancements, or architectural improvements.
- **Code Contributions**: Fix open issues, optimize performance, or build new core components.
- **Documentation Improvements**: Correct typos, clarify tutorials, improve API references, or add inline docstrings.
- **Examples and Integrations**: Share example agent configurations, workflows, and integrations with third-party tools or frameworks.

---

## Development Setup

Follow these steps to set up your local development environment for AgentScope:

```bash
# Clone the repo
git clone https://github.com/archittmittal/AgentsScope.git
cd AgentsScope

# Server
cd packages/server
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8765

# UI
cd packages/ui
npm install
npm run dev

# SDK (editable install)
cd packages/sdk
pip install -e '.[dev]'
```

---

## Code Style

To keep the codebase clean, consistent, and maintainable, please follow these style guidelines:

### Python
- Format code using **black** and lint with **ruff**.
- Include type hints for all function arguments and return types.
- Follow the **Google Docstring Format** for modules, classes, and public functions.

### TypeScript
- Format code using **Prettier** and lint with **ESLint**.
- Ensure TypeScript is running in **strict mode** with no implicit `any` types.

### Pre-Commit & Pre-PR Quality Checks
- Install pre-commit hooks to automatically format and validate code on commit:
  ```bash
  pip install pre-commit
  pre-commit install
  ```
- Run the full **Pre-PR Quality Suite** before opening a pull request:
  ```bash
  make pre-pr
  # or directly: ./scripts/pre_pr_check.sh
  ```
- Automatically auto-format the entire codebase:
  ```bash
  make format
  ```

---

## Security & OpenSSF Standards

AgentScope adheres to **Open Source Security Foundation (OpenSSF)** standards and best practices:

- **Security Policy:** Review [`SECURITY.md`](SECURITY.md) for vulnerability disclosure guidelines, supported versions, and response SLAs.
- **Scorecard Analysis:** Automated weekly security health checks via `.github/workflows/scorecard.yml`.
- **Static Analysis (SAST):** Code scanned via GitHub CodeQL and Ruff security rules.
- **Supply Chain Security:** Automated dependency monitoring and security updates via Dependabot.
- **Least Privilege:** CI/CD workflows run under explicit, minimal GitHub token permissions.

---

## Git Workflow

Follow this step-by-step workflow when submitting code or documentation changes:

1. **Fork the repository** on GitHub.
2. **Create a feature branch** from `main`:
   ```bash
   git checkout -b feature/my-feature
   ```
3. **Make your changes** cleanly within your feature branch.
4. **Run the Pre-PR Quality Suite**:
   ```bash
   make pre-pr
   ```
5. **Commit with conventional commits**:
   ```bash
   git commit -m "feat: add new feature"
   ```
6. **Push to your fork and open a Pull Request** against the primary repository's `main` branch.

---

## Commit Messages

We enforce the [Conventional Commits](https://www.conventionalcommits.org/) specification for clear and structured git histories:

- `feat:` A new feature or capability
- `fix:` A bug fix
- `docs:` Documentation changes only
- `chore:` Maintenance, dependency updates, or build tasks
- `refactor:` Code restructuring without functional changes
- `test:` Adding or updating tests
- `ci:` Continuous integration and automation workflows

---

## Pull Request Process

1. **Update Documentation**: Ensure relevant guides, API docs, or README files are updated to reflect your changes.
2. **Add Tests**: Provide unit tests or integration tests for new features and bug fixes.
3. **Ensure Pre-PR Quality Gates Pass**: Verify all checks pass cleanly (`make pre-pr`).
4. **Request Review**: Assign maintainers for review and respond to feedback constructively.
5. **Squash Merge**: PRs will be squash-merged into `main` after approval and CI verification.

---

## Reporting Bugs

Before creating a bug report, please check existing issues to avoid duplicates. When opening a bug report via GitHub Issues, please include:

- **Steps to Reproduce**: Clear, sequential instructions to replicate the behavior.
- **Expected Behavior**: What you expected to happen.
- **Actual Behavior**: What actually happened (include logs, stack traces, and screenshots if applicable).
- **Environment Info**: OS version, Python version, Node.js version, and package versions.

---

## Feature Requests

We welcome ideas for new features! When submitting a feature request:

- Use GitHub Issues with the **`feature request`** label.
- Clearly describe the **use case** and problem you are trying to solve.
- Outline your **proposed solution** or architectural design if available.

---

## Code of Conduct

We are committed to providing a welcoming, respectful, and inclusive community for everyone.

- Be respectful, constructive, and empathetic in all interactions.
- Refrain from unacceptable behavior such as harassment, discrimination, or personal attacks.
- Refer to `CODE_OF_CONDUCT.md` (which may be created separately in the repository root) for full community guidelines.

---

## Questions?

- Open a **GitHub Discussion** for Q&A, ideas, or general conversation.
- Check existing issues, pull requests, and documentation before opening a new inquiry.
