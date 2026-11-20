"""Packaging metadata checks for the SDK distribution (PEP 639)."""

import re
from pathlib import Path

SDK_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SDK_DIR.parents[1]
PYPROJECT = (SDK_DIR / "pyproject.toml").read_text()


def _project_value(key: str) -> str:
    match = re.search(rf"^{re.escape(key)}\s*=\s*(.+)$", PYPROJECT, re.MULTILINE)
    assert match, f"[project].{key} is missing from pyproject.toml"
    return match.group(1).strip()


def test_license_is_spdx_expression_string():
    # PEP 639: `license` must be a plain SPDX string, not the deprecated
    # `{ text = ... }` / `{ file = ... }` table form.
    assert _project_value("license") == '"Apache-2.0"'


def test_license_files_declared():
    assert _project_value("license-files") == '["LICENSE"]'


def test_no_license_classifier_alongside_expression():
    # PEP 639 forbids combining License-Expression with License :: classifiers.
    assert "License ::" not in PYPROJECT


def test_bundled_license_matches_repository_license():
    # license-files cannot reference paths outside the project directory, so
    # the SDK ships its own copy; keep it identical to the repo-level LICENSE.
    sdk_license = (SDK_DIR / "LICENSE").read_bytes()
    root_license = (REPO_ROOT / "LICENSE").read_bytes()
    assert sdk_license == root_license
