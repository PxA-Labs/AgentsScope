"""Fail a release when the git tag does not match the SDK version.

Usage: python .github/scripts/check_release_version.py <tag>   (e.g. v0.2.0)

Reads packages/sdk/agentscope_trace/_version.py without importing the package, so
it runs before anything is installed.
"""

import re
import sys
from pathlib import Path

VERSION_FILE = (
    Path(__file__).resolve().parents[2]
    / "packages"
    / "sdk"
    / "agentscope_trace"
    / "_version.py"
)
TAG_RE = re.compile(r"^v(?P<version>\d+\.\d+\.\d+((a|b|rc)\d+)?(\.post\d+)?)$")


def read_version(path: Path = VERSION_FILE) -> str:
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', path.read_text(), re.MULTILINE)
    if not match:
        raise ValueError(f"no __version__ found in {path}")
    return match.group(1)


def check(tag: str, version: str) -> str:
    """Return an error message, or an empty string when the tag is valid."""
    match = TAG_RE.match(tag)
    if not match:
        return f"tag {tag!r} is not a release tag like v1.2.3, v1.2.3rc1"
    if match.group("version") != version:
        return (
            f"tag {tag!r} does not match agentscope_trace/_version.py ({version!r}); "
            "bump the version in a PR before tagging"
        )
    return ""


def main(argv: list) -> int:
    if len(argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    error = check(argv[1], read_version())
    if error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"ok: {argv[1]} matches the SDK version")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
