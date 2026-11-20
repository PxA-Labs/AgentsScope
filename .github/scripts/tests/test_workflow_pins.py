"""Guards for GitHub Actions supply-chain hygiene.

* Every third-party action must be pinned to a full 40-character commit SHA
  (OpenSSF Scorecard "Pinned-Dependencies").
* Every ``github/codeql-action/*`` step must reference the same commit, because
  CodeQL refuses to run when init/autobuild/analyze come from different
  releases.
"""

import re
from pathlib import Path

import pytest

WORKFLOWS_DIR = Path(__file__).resolve().parents[2] / "workflows"

# Matches `uses: owner/repo[/path]@ref` and captures the action and the ref.
USES_RE = re.compile(r"^\s*-?\s*uses:\s*([^@\s]+)@([^\s#]+)", re.MULTILINE)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _workflow_files():
    return sorted(WORKFLOWS_DIR.glob("*.y*ml"))


def _action_refs():
    refs = []
    for path in _workflow_files():
        for action, ref in USES_RE.findall(path.read_text()):
            # Local actions (./path) and docker:// images are not GitHub refs.
            if action.startswith("./") or action.startswith("docker://"):
                continue
            refs.append((path.name, action, ref))
    return refs


def test_workflows_exist():
    assert _workflow_files(), f"no workflow files found in {WORKFLOWS_DIR}"


@pytest.mark.parametrize(
    "workflow,action,ref",
    _action_refs(),
    ids=lambda v: v if isinstance(v, str) else None,
)
def test_actions_are_pinned_to_commit_sha(workflow, action, ref):
    assert SHA_RE.match(ref), (
        f"{workflow}: '{action}@{ref}' must be pinned to a full commit SHA "
        f"(append the version as a '# vX.Y.Z' comment)"
    )


def test_codeql_action_steps_share_one_commit():
    codeql = {
        (workflow, action, ref)
        for workflow, action, ref in _action_refs()
        if action.startswith("github/codeql-action")
    }
    assert codeql, "expected at least one github/codeql-action step"
    shas = {ref for _, _, ref in codeql}
    assert len(shas) == 1, (
        "all github/codeql-action/* steps must use the same commit, found: "
        + ", ".join(f"{w}:{a}@{r[:7]}" for w, a, r in sorted(codeql))
    )
