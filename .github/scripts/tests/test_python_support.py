"""Keep the supported Python range consistent across packaging and CI.

The SDK's ``requires-python`` floor must be the lowest version CI tests on, and
no workflow may run on a version below it (otherwise dependency resolution for
packages that dropped that version fails, as it did for #254 and #261).
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SDK_PYPROJECT = REPO_ROOT / "packages" / "sdk" / "pyproject.toml"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

VERSION_RE = re.compile(r"""["']?(3\.\d+)["']?""")


def _version_tuple(version: str) -> tuple[int, int]:
    major, minor = version.split(".")[:2]
    return int(major), int(minor)


def _requires_python_floor() -> tuple[int, int]:
    text = SDK_PYPROJECT.read_text()
    match = re.search(r'^requires-python\s*=\s*">=\s*(3\.\d+)"', text, re.MULTILINE)
    assert match, "packages/sdk/pyproject.toml must declare requires-python >= 3.X"
    return _version_tuple(match.group(1))


def _workflow_python_versions() -> dict[str, set[tuple[int, int]]]:
    """Collect literal python-version values (scalars and matrix lists)."""
    found: dict[str, set[tuple[int, int]]] = {}
    for path in sorted(WORKFLOWS_DIR.glob("*.y*ml")):
        versions: set[tuple[int, int]] = set()
        for line in path.read_text().splitlines():
            key, _, value = line.partition(":")
            if key.strip() != "python-version" or "${{" in value:
                continue
            versions.update(_version_tuple(v) for v in VERSION_RE.findall(value))
        if versions:
            found[path.name] = versions
    return found


def test_requires_python_floor_is_declared():
    assert _requires_python_floor() >= (3, 11)


def test_no_workflow_runs_below_requires_python():
    floor = _requires_python_floor()
    too_old = {
        name: sorted(v for v in versions if v < floor)
        for name, versions in _workflow_python_versions().items()
    }
    too_old = {name: v for name, v in too_old.items() if v}
    assert not too_old, f"workflows use Python below requires-python {floor}: {too_old}"


def test_ci_matrix_covers_requires_python_floor():
    ci_versions = _workflow_python_versions().get("ci.yml", set())
    assert ci_versions, "ci.yml declares no python-version"
    assert min(ci_versions) == _requires_python_floor(), (
        "the lowest Python version tested in ci.yml must equal the "
        "requires-python floor so the minimum supported version is exercised"
    )
