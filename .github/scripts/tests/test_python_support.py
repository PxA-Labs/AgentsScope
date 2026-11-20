"""Keep the supported Python range consistent across packaging and CI.

The SDK's ``requires-python`` floor must be the lowest version the SDK and
server test jobs run on, and no workflow may run on a version below it
(otherwise dependency resolution for packages that dropped that version
fails, as it did for #254 and #261).
"""

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SDK_PYPROJECT = REPO_ROOT / "packages" / "sdk" / "pyproject.toml"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# Jobs whose matrices must start at the requires-python floor.
TEST_JOBS = ("test-python-sdk", "test-python-server")

VERSION_RE = re.compile(r"^3\.\d+$")


def _version_tuple(version: str) -> tuple[int, int]:
    major, minor = version.split(".")[:2]
    return int(major), int(minor)


def _requires_python_floor() -> tuple[int, int]:
    text = SDK_PYPROJECT.read_text()
    match = re.search(r'^requires-python\s*=\s*">=\s*(3\.\d+)"', text, re.MULTILINE)
    assert match, "packages/sdk/pyproject.toml must declare requires-python >= 3.X"
    return _version_tuple(match.group(1))


def _literal_versions(value) -> set[tuple[int, int]]:
    """Versions from a python-version value: a scalar or a list, skipping ${{ }}."""
    values = value if isinstance(value, list) else [value]
    versions = set()
    for v in values:
        text = str(v).strip()
        if VERSION_RE.match(text):
            versions.add(_version_tuple(text))
    return versions


def job_python_versions(workflow: dict) -> dict[str, set[tuple[int, int]]]:
    """Map job id -> literal Python versions from its matrix and setup steps."""
    found: dict[str, set[tuple[int, int]]] = {}
    for job_id, job in (workflow.get("jobs") or {}).items():
        versions: set[tuple[int, int]] = set()
        matrix = (job.get("strategy") or {}).get("matrix") or {}
        if isinstance(matrix, dict) and "python-version" in matrix:
            versions |= _literal_versions(matrix["python-version"])
        for step in job.get("steps") or []:
            with_ = step.get("with") or {}
            if "python-version" in with_:
                versions |= _literal_versions(with_["python-version"])
        if versions:
            found[job_id] = versions
    return found


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text()) or {}


def _ci() -> dict:
    return _load(WORKFLOWS_DIR / "ci.yml")


def check_no_job_below(
    workflows: dict[str, dict], floor: tuple[int, int]
) -> dict[str, list]:
    too_old = {}
    for name, workflow in workflows.items():
        for job_id, versions in job_python_versions(workflow).items():
            old = sorted(v for v in versions if v < floor)
            if old:
                too_old[f"{name}:{job_id}"] = old
    return too_old


def check_test_jobs_start_at_floor(ci: dict, floor: tuple[int, int]) -> list[str]:
    problems = []
    versions = job_python_versions(ci)
    for job_id in TEST_JOBS:
        if job_id not in versions:
            problems.append(f"{job_id}: no python-version found")
        elif min(versions[job_id]) != floor:
            problems.append(
                f"{job_id}: lowest version {min(versions[job_id])} != floor {floor}"
            )
    return problems


def test_requires_python_floor_is_declared():
    assert _requires_python_floor() >= (3, 11)


def test_no_workflow_runs_below_requires_python():
    workflows = {p.name: _load(p) for p in sorted(WORKFLOWS_DIR.glob("*.y*ml"))}
    too_old = check_no_job_below(workflows, _requires_python_floor())
    assert not too_old, f"workflows use Python below requires-python: {too_old}"


def test_sdk_and_server_test_matrices_start_at_the_floor():
    problems = check_test_jobs_start_at_floor(_ci(), _requires_python_floor())
    assert not problems, problems


# --- the checks themselves catch the shapes a line-based parser missed -------

BLOCK_LIST_MATRIX = """
jobs:
  test-python-sdk:
    strategy:
      matrix:
        python-version:
          - "3.10"
          - "3.12"
    steps:
      - uses: actions/setup-python@x
        with:
          python-version: ${{ matrix.python-version }}
"""

FLOOR_ONLY_IN_LINT = """
jobs:
  lint-python:
    steps:
      - uses: actions/setup-python@x
        with:
          python-version: "3.11"
  test-python-sdk:
    strategy:
      matrix:
        python-version: ["3.12", "3.13"]
  test-python-server:
    strategy:
      matrix:
        python-version: ["3.12", "3.13"]
"""


def test_block_list_matrix_below_floor_is_caught():
    workflow = yaml.safe_load(BLOCK_LIST_MATRIX)
    assert check_no_job_below({"ci.yml": workflow}, (3, 11)) == {
        "ci.yml:test-python-sdk": [(3, 10)]
    }


@pytest.mark.parametrize("job_id", TEST_JOBS)
def test_floor_missing_from_test_matrices_is_caught(job_id):
    problems = check_test_jobs_start_at_floor(
        yaml.safe_load(FLOOR_ONLY_IN_LINT), (3, 11)
    )
    assert any(p.startswith(job_id) for p in problems), problems
