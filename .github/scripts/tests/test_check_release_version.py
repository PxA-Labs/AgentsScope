import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "check_release_version.py"
sys.path.insert(0, str(SCRIPT.parent))

from check_release_version import check, read_version  # noqa: E402


@pytest.mark.parametrize(
    "tag,version",
    [("v0.2.0", "0.2.0"), ("v1.10.3rc1", "1.10.3rc1"), ("v2.0.0.post1", "2.0.0.post1")],
)
def test_matching_release_tags_pass(tag, version):
    assert check(tag, version) == ""


@pytest.mark.parametrize(
    "tag", ["0.2.0", "v0.2", "release-0.2.0", "v0.2.0-beta", "sdk-v0.2.0", ""]
)
def test_malformed_tags_are_rejected(tag):
    assert "not a release tag" in check(tag, "0.2.0")


def test_mismatched_version_is_rejected():
    assert "does not match" in check("v0.3.0", "0.2.0")


def test_reads_the_real_version_file():
    assert read_version()


def test_cli_exit_codes():
    version = read_version()
    ok = subprocess.run(
        [sys.executable, str(SCRIPT), f"v{version}"], capture_output=True, text=True
    )
    assert ok.returncode == 0, ok.stderr
    bad = subprocess.run(
        [sys.executable, str(SCRIPT), "v999.0.0"], capture_output=True, text=True
    )
    assert bad.returncode == 1 and "does not match" in bad.stderr
    usage = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True
    )
    assert usage.returncode == 2
