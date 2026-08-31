# Security Policy

The AgentScope team takes the security of our multi-agent observability dashboard, SDKs, and underlying infrastructure seriously. We appreciate the responsible disclosure of security vulnerabilities from the community and security researchers.

This security policy aligns with the **Open Source Security Foundation (OpenSSF)** best practices.

---

## Supported Versions

Only the latest active release branch and recent minor releases receive security updates and vulnerability patches.

| Version | Supported          | Security Maintenance Status |
| ------- | ------------------ | --------------------------- |
| 0.1.x   | :white_check_mark: | Active Support              |
| < 0.1.0 | :x:                | Unsupported                 |

If you are running an older version, we strongly recommend upgrading to the latest release before reporting an issue.

---

## Reporting a Vulnerability

**Please do NOT report security vulnerabilities through public GitHub issues or discussions.**

### Preferred Method: GitHub Private Vulnerability Reporting

1. Navigate to the [Security tab](https://github.com/PxA-Labs/AgentsScope/security) on the AgentsScope repository.
2. Click **"Report a vulnerability"** under Private vulnerability reporting.
3. Fill out the advisory form with comprehensive technical details, steps to reproduce, proof-of-concept (PoC) code or requests, and potential impact assessment.

### Alternative Method: Direct Security Contact

If GitHub Private Vulnerability Reporting is unavailable, you can email our core maintainers directly at:
- **Email:** `security@agentscope.io` (or maintainer contact via GitHub profile)
- **Subject:** `[SECURITY VULNERABILITY] <Component>: <Brief Description>`

### What to Include in Your Report

To help us triage and reproduce the issue rapidly, please include:
- **Component Affected:** (e.g., Python SDK, FastAPI Server backend, Next.js UI dashboard, Docker Compose environment).
- **Vulnerability Category:** (e.g., Remote Code Execution, Authentication Bypass, Cross-Site Scripting, SQL Injection, Supply Chain Dependency, Information Disclosure).
- **Step-by-step Reproduction Instructions:** Clear, repeatable steps or a minimal code snippet reproducing the problem.
- **Proof of Concept:** Exploit script, network payload, or curl reproduction where applicable.
- **Impact Assessment:** How an attacker could exploit this vulnerability and the potential severity (CVSS estimate).
- **Suggested Fix (Optional):** If you have identified a mitigation or patch, feel free to share it.

---

## Response and Disclosure Process

We follow a coordinated vulnerability disclosure (CVD) process:

1. **Acknowledgment:** We will acknowledge receipt of your vulnerability report within **48 hours**.
2. **Investigation & Triage:** Maintainers will investigate, reproduce the issue, and provide an initial severity assessment within **5 business days**.
3. **Patch Development:** A security fix will be prepared and tested in private collaboration with the reporter.
4. **Release & Advisory:** A patch release will be published alongside a GitHub Security Advisory crediting the reporter (unless anonymity is requested).
5. **Public Disclosure:** Public disclosure will occur after the patch has been made available to users.

---

## Security Best Practices for Deploying AgentScope

When deploying AgentScope in production or staging environments, adhere to these recommendations:

1. **Network Isolation:** The FastAPI server (port 8765) and Next.js UI (port 3000) are designed for local and internal network observability. Avoid exposing unauthenticated dashboard ports directly to the public internet without an authenticating reverse proxy (e.g., NGINX with OAuth2/OIDC, Cloudflare Access).
2. **Environment Variable Sanitization:** Ensure sensitive tokens (OpenAI, Anthropic, Gemini, Mem0 API keys) are stored in secure environment variables or vault secret managers, never hardcoded in repository files.
3. **CORS Allowlist:** In multi-tenant or containerized environments, configure `CORS_ALLOW_ORIGINS` to restrict allowed origins to explicit internal dashboard domains.
4. **Database File Permissions:** Restrict file system permissions for SQLite databases (`agentscope.db`) to the specific user running the server process (`chmod 600 agentscope.db`).

---

## Supply Chain & Quality Standards

AgentScope implements strict supply chain security and automated code quality controls:
- **Automated Dependency Scanning:** Monitored weekly via GitHub Dependabot.
- **Static Application Security Testing (SAST):** Scanned continuously with GitHub CodeQL and OpenSSF Scorecard.
- **Least Privilege Tokens:** GitHub Actions workflows operate under minimal token permissions.
- **Pre-PR Quality Enforcement:** All pull requests must pass automated linting, security AST analysis, and test suites before merge.
