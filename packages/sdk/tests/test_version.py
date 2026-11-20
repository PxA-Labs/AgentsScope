"""The version is single-sourced and matches the installed distribution."""

import importlib.metadata
import re

import agentscope
from agentscope._version import __version__

DIST_NAME = "agentscope-trace"


def test_version_is_pep440_release():
    assert re.fullmatch(
        r"\d+\.\d+\.\d+((a|b|rc)\d+)?(\.post\d+)?(\.dev\d+)?", __version__
    )


def test_package_exposes_version():
    assert agentscope.__version__ == __version__


def test_installed_distribution_metadata_matches():
    # Fails if the package was installed under the old name or the dynamic
    # version wiring in pyproject.toml breaks.
    assert importlib.metadata.version(DIST_NAME) == __version__
