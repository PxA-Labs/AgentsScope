"""Build the agentscope-trace wheel and install it into fresh virtualenvs (#297).

Opt-in, because it builds a wheel and downloads from PyPI:

    AGENTSCOPE_WHEEL_TESTS=1 pytest packages/sdk/tests/test_wheel_install.py

CI runs it in the "Test SDK wheel install" job.
"""

import json
import os
import shutil
import subprocess
import sys
import textwrap
import venv
import zipfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("AGENTSCOPE_WHEEL_TESTS") != "1",
    reason="set AGENTSCOPE_WHEEL_TESTS=1 to build and install the wheel",
)

SDK_DIR = Path(__file__).resolve().parents[1]
# agentscope-ai's unrelated package, which also installs a top-level
# `agentscope`. Pinned so the clash test is reproducible.
AGENTSCOPE_AI = "agentscope==2.0.12"


def run(cmd, **kwargs):
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    assert result.returncode == 0, f"{cmd}\n{result.stdout}\n{result.stderr}"
    return result


@pytest.fixture(scope="module")
def wheel(tmp_path_factory):
    # Build from a copy so setuptools' build/ and *.egg-info stay out of the
    # source tree.
    src = tmp_path_factory.mktemp("src") / "sdk"
    shutil.copytree(
        SDK_DIR,
        src,
        ignore=shutil.ignore_patterns(
            "tests", "build", "dist", "*.egg-info", "__pycache__"
        ),
    )
    out = tmp_path_factory.mktemp("dist")
    run([sys.executable, "-m", "pip", "wheel", "--no-deps", "-w", str(out), str(src)])
    (path,) = out.glob("agentscope_trace-*.whl")
    return path


def make_venv(path):
    venv.EnvBuilder(with_pip=True, clear=True).create(path)
    bindir = path / ("Scripts" if os.name == "nt" else "bin")
    return bindir / "python", bindir


def py(python, code, cwd):
    # cwd outside the repository, so the checkout can't shadow the install.
    out = run([str(python), "-c", textwrap.dedent(code)], cwd=cwd)
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_wheel_ships_the_shim_as_its_only_agentscope_path(wheel):
    names = zipfile.ZipFile(wheel).namelist()
    top_level = {n.split("/", 1)[0] for n in names}
    dist_info = next(t for t in top_level if t.endswith(".dist-info"))
    assert top_level == {"agentscope_trace", "agentscope", dist_info}
    # Only the one-file shim could clash with agentscope-ai's package.
    assert [n for n in names if n.split("/", 1)[0] == "agentscope"] == [
        "agentscope/__init__.py"
    ]
    for required in (
        "agentscope_trace/__init__.py",
        "agentscope_trace/pricing.json",
        "agentscope_trace/integrations/crewai.py",
        "agentscope_trace/providers/anthropic.py",
    ):
        assert required in names
    entry_points = zipfile.ZipFile(wheel).read(f"{dist_info}/entry_points.txt")
    assert "agentscope = agentscope_trace.cli:main" in entry_points.decode()


@pytest.fixture(scope="module")
def installed(wheel, tmp_path_factory):
    env = tmp_path_factory.mktemp("venv")
    python, bindir = make_venv(env)
    run([str(python), "-m", "pip", "install", "-q", str(wheel)])
    return python, bindir, env


def test_fresh_venv_imports_both_names_and_runs_the_cli(installed, tmp_path):
    python, bindir, env = installed
    out = py(
        python,
        """
        import importlib.metadata, json, warnings
        import agentscope_trace
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            import agentscope
            import agentscope.decorators
            from agentscope.integrations.crewai import AgentScopeCrewAIListener
        import agentscope_trace.decorators
        from agentscope_trace import _pricing
        print(json.dumps({
            "file": agentscope_trace.__file__,
            "version": agentscope_trace.__version__,
            "dist_version": importlib.metadata.version("agentscope-trace"),
            "same_package": agentscope is agentscope_trace,
            "same_module": agentscope.decorators is agentscope_trace.decorators,
            "warnings": [w.category.__name__ for w in caught],
            "pricing_loaded": bool(_pricing.PRICING_TABLE),
        }))
        """,
        cwd=tmp_path,
    )
    assert Path(out["file"]).resolve().is_relative_to(env.resolve())
    assert out["version"] == out["dist_version"]
    assert out["same_package"] and out["same_module"]
    assert out["warnings"] == ["DeprecationWarning"]
    assert out["pricing_loaded"]

    cli = run([str(bindir / "agentscope"), "--version"], cwd=tmp_path)
    assert cli.stdout.strip() == f"agentscope-trace {out['version']}"
    assert "start" in run([str(bindir / "agentscope"), "--help"], cwd=tmp_path).stdout


def shim_state(python, cwd):
    return py(
        python,
        """
        import importlib.metadata as md, importlib.util, json, sysconfig
        from pathlib import Path
        init = Path(sysconfig.get_paths()["purelib"]) / "agentscope" / "__init__.py"
        def files(dist):
            try:
                return {str(f) for f in md.files(dist) or ()}
            except md.PackageNotFoundError:
                return set()
        import agentscope_trace
        print(json.dumps({
            "init_exists": init.exists(),
            "init_is_shim": init.exists() and "agentscope_trace" in init.read_text(),
            "overlap": sorted(files("agentscope") & files("agentscope-trace")),
            "agentscope_trace_ok": hasattr(agentscope_trace, "AgentScopeCallback"),
        }))
        """,
        cwd,
    )


def test_agentscope_ai_still_clashes_with_the_shim(installed, wheel, tmp_path):
    """Document what the shim leaves broken (acceptance criterion of #297).

    Both distributions install agentscope/__init__.py, and pip does not detect
    the conflict: whichever is installed last wins, and uninstalling either one
    deletes the shared file. agentscope_trace itself never clashes. The clash
    only disappears once the shim is removed.
    """
    python, _, env = installed
    pip = [str(python), "-m", "pip"]
    # --no-deps: only its files matter here, not its large dependency tree.
    run([*pip, "install", "-q", "--no-deps", AGENTSCOPE_AI])
    after_ai = shim_state(python, tmp_path)
    assert after_ai["overlap"] and all(
        f.startswith("agentscope/") for f in after_ai["overlap"]
    )
    assert "agentscope/__init__.py" in after_ai["overlap"]
    assert after_ai["init_exists"] and not after_ai["init_is_shim"]  # shim gone
    assert after_ai["agentscope_trace_ok"]

    # Reinstalling agentscope-trace overwrites agentscope-ai's __init__.py.
    run([*pip, "install", "-q", "--no-deps", "--force-reinstall", str(wheel)])
    assert shim_state(python, tmp_path)["init_is_shim"]

    # Uninstalling agentscope-ai deletes the shared file, so the shim is gone
    # although agentscope-trace is still installed.
    run([*pip, "uninstall", "-q", "-y", "agentscope"])
    after_uninstall = shim_state(python, tmp_path)
    assert not after_uninstall["init_exists"]
    assert after_uninstall["agentscope_trace_ok"]

    # Leave the shared venv as the other tests expect it.
    run([*pip, "install", "-q", "--no-deps", "--force-reinstall", str(wheel)])
