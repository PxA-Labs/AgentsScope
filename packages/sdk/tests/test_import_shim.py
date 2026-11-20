"""The `agentscope` -> `agentscope_trace` compatibility shim (#297).

Warning behaviour is checked in fresh interpreters: the repository's pytest
config ignores DeprecationWarning, and an import warns only the first time.
"""

import importlib
import json
import subprocess
import sys
import textwrap
import warnings

import pytest

import agentscope_trace

# Every submodule the docs and examples import through the old name.
SUBMODULES = [
    "_version",
    "_pricing",
    "callback",
    "cli",
    "client",
    "decorators",
    "exceptions",
    "models",
    "patch",
    "integrations",
    "integrations.autogen",
    "integrations.crewai",
    "integrations.llamaindex",
    "providers",
    "providers._base",
    "providers.anthropic",
    "providers.gemini",
]


def run_python(code):
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result


def run_json(code):
    return json.loads(run_python(code).stdout.strip().splitlines()[-1])


def test_new_import_name_works_without_the_shim():
    from agentscope_trace import AgentScopeCallback, trace  # noqa: F401

    assert agentscope_trace.__name__ == "agentscope_trace"
    for name in agentscope_trace.__all__:
        assert hasattr(agentscope_trace, name), name

    # Importing only the new name must not load the shim (or warn).
    out = run_json("""
        import json, sys, warnings
        warnings.simplefilter("error")
        import agentscope_trace, agentscope_trace.integrations.crewai
        print(json.dumps(sorted(m for m in sys.modules
                                if m == "agentscope" or m.startswith("agentscope."))))
        """)
    assert out == []


@pytest.mark.parametrize("first_import", ["import agentscope", "import agentscope.cli"])
def test_old_name_warns_exactly_once(first_import):
    out = run_json(f"""
        import json, warnings
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            {first_import}
            import agentscope
            import agentscope.decorators
            from agentscope import AgentScopeCallback, trace
            from agentscope.integrations.crewai import AgentScopeCrewAIListener
            from agentscope.providers.anthropic import patch_anthropic
            import agentscope.integrations.autogen, agentscope.integrations.llamaindex
        print(json.dumps([
            {{"category": w.category.__name__, "message": str(w.message),
              "filename": w.filename}}
            for w in caught
        ]))
        """)
    assert len(out) == 1, out
    (warning,) = out
    assert warning["category"] == "DeprecationWarning"
    assert "agentscope_trace" in warning["message"]
    # stacklevel points at the importing code, not at the shim or importlib.
    assert warning["filename"] == "<string>"


def test_old_name_resolves_to_the_same_module_objects():
    names = json.dumps(SUBMODULES)
    out = run_json(f"""
        import importlib, json, sys, warnings
        warnings.simplefilter("ignore", DeprecationWarning)
        names = {names}
        # Old names first, so nothing was imported under the new name yet.
        old = {{n: importlib.import_module("agentscope." + n) for n in names}}
        import agentscope, agentscope_trace
        new = {{n: importlib.import_module("agentscope_trace." + n) for n in names}}
        print(json.dumps({{
            "package": agentscope is agentscope_trace,
            "modules": {{n: old[n] is new[n] for n in names}},
            "real_names": sorted({{m.__name__ for m in old.values()}}),
            # No module was loaded twice under the old name.
            "copies": sorted(
                k for k, m in sys.modules.items()
                if k.startswith("agentscope.") and not m.__name__.startswith(
                    "agentscope_trace")
            ),
            "spec_names": sorted({{m.__spec__.name for m in old.values()}}),
        }}))
        """)
    assert out["package"] is True
    assert out["modules"] == {name: True for name in SUBMODULES}
    assert out["real_names"] == sorted(f"agentscope_trace.{n}" for n in SUBMODULES)
    assert out["copies"] == []
    # The import system must not leave the alias spec on the real module.
    assert out["spec_names"] == out["real_names"]


def test_module_level_state_is_shared():
    out = run_json("""
        import json, warnings
        warnings.simplefilter("ignore", DeprecationWarning)
        import agentscope.client, agentscope.decorators, agentscope.patch
        import agentscope.providers.anthropic, agentscope.providers.gemini
        import agentscope_trace.client as client
        import agentscope_trace.decorators as decorators
        import agentscope_trace.patch as patch
        from agentscope_trace.providers import anthropic, gemini

        agentscope.decorators.configure(host="127.0.0.1", port=9)
        shared_client = agentscope.decorators.get_global_client()
        # Old name registers the client for the atexit flush...
        agentscope.client._track_for_exit(shared_client)
        token = agentscope.decorators.current_parent_run_id.set("run-1")
        agentscope.patch._is_patched = "old"
        agentscope.providers.anthropic._is_patched = "old"
        agentscope.providers.gemini._is_patched = "old"
        result = {
            "client": decorators.get_global_client() is shared_client,
            # ...and the new name's WeakSet and hook flag see it.
            "live_clients": shared_client in client._live_clients
                and client._exit_hook_registered,
            "contextvar": decorators.current_parent_run_id.get() == "run-1",
            "flags": [patch._is_patched, anthropic._is_patched, gemini._is_patched],
            "classes": agentscope.AgentScopeCallback
                is __import__("agentscope_trace").AgentScopeCallback,
        }
        decorators.current_parent_run_id.reset(token)
        shared_client.stop()
        print(json.dumps(result))
        """)
    assert out == {
        "client": True,
        "live_clients": True,
        "contextvar": True,
        "flags": ["old", "old", "old"],
        "classes": True,
    }


def test_monkeypatch_through_old_name_patches_the_real_module(monkeypatch):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        old = importlib.import_module("agentscope.decorators")
    import agentscope_trace.decorators as new

    sentinel = object()
    monkeypatch.setattr("agentscope.decorators.get_global_client", lambda: sentinel)
    assert old is new
    assert new.get_global_client() is sentinel


def test_unknown_submodule_names_the_old_path():
    out = run_python("""
        import warnings
        warnings.simplefilter("ignore", DeprecationWarning)
        try:
            import agentscope.does_not_exist
        except ModuleNotFoundError as exc:
            print(exc.name)
        """)
    assert out.stdout.strip() == "agentscope.does_not_exist"


def test_python_dash_m_through_old_name():
    for module in ("agentscope.cli", "agentscope_trace.cli"):
        out = subprocess.run(
            [sys.executable, "-m", module, "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == f"agentscope-trace {agentscope_trace.__version__}"
