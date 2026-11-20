"""patch_all / unpatch_all and package import behaviour."""

import logging
import subprocess
import sys
import types

import pytest

from agentscope_trace import patch as patch_module
from agentscope_trace.patch import patch_all, unpatch_all


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    unpatch_all()


def test_importing_agentscope_does_not_import_provider_sdks():
    code = (
        "import sys, agentscope_trace; "
        "print(sorted(m for m in ('openai', 'anthropic', 'google.genai') "
        "if m in sys.modules))"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]"


def test_missing_sdks_are_skipped_silently(monkeypatch, caplog):
    monkeypatch.setattr(patch_module, "_sdk_installed", lambda name: False)
    with caplog.at_level(logging.WARNING):
        assert patch_all() == {"openai": False, "anthropic": False, "gemini": False}
    assert caplog.records == []


def test_incompatible_sdk_is_reported_not_raised(monkeypatch, caplog):
    pytest.importorskip("anthropic")
    monkeypatch.setattr(
        patch_module,
        "_sdk_installed",
        lambda name: name == "anthropic",
    )
    monkeypatch.setitem(
        sys.modules,
        "anthropic.resources.messages",
        types.ModuleType("anthropic.resources.messages"),
    )
    with caplog.at_level(logging.WARNING):
        result = patch_all()
    assert result["anthropic"] is False
    assert any(
        "Skipping anthropic instrumentation" in r.getMessage() for r in caplog.records
    )


def test_patch_all_patches_installed_sdks_and_unpatch_all_restores():
    pytest.importorskip("openai")
    pytest.importorskip("anthropic")
    genai_models = pytest.importorskip("google.genai.models")
    from anthropic.resources.messages import Messages
    from openai.resources.chat.completions import Completions

    originals = (
        Completions.create,
        Messages.create,
        genai_models.Models.generate_content,
    )
    assert patch_all() == {"openai": True, "anthropic": True, "gemini": True}
    assert Completions.create is not originals[0]
    assert Messages.create is not originals[1]
    assert genai_models.Models.generate_content is not originals[2]

    unpatch_all()
    assert (
        Completions.create,
        Messages.create,
        genai_models.Models.generate_content,
    ) == originals


def test_unpatch_all_is_safe_when_nothing_patched():
    unpatch_all()
    unpatch_all()
