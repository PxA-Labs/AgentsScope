"""Deprecated compatibility alias: ``agentscope`` -> ``agentscope_trace``.

The SDK's import package was renamed to ``agentscope_trace`` (#297). This shim
keeps ``import agentscope`` and ``from agentscope.<submodule> import ...``
working for at least one minor release, and emits one ``DeprecationWarning``
when it is first imported.

This file is the only part of the ``agentscope-trace`` distribution that still
installs a top-level ``agentscope`` package, which is the same name as the
unrelated agentscope-ai project on PyPI (``pip install agentscope``). Installing
both still overwrites this file, so the clash only goes away once the shim is
removed. New code should import ``agentscope_trace``.

How it works
------------
Re-exporting with ``from agentscope_trace import *`` would give
``agentscope.decorators`` and ``agentscope_trace.decorators`` as two separate
module objects: two global clients, two ``current_parent_run_id`` context
variables, two ``_is_patched`` flags, and ``monkeypatch.setattr`` on one name
not affecting the other. So nothing here is copied; both names resolve to the
same module objects:

* ``sys.modules["agentscope"]`` is replaced by the ``agentscope_trace`` module
  itself, so ``import agentscope`` returns ``agentscope_trace``.
* A meta path finder answers ``agentscope.<name>`` by importing
  ``agentscope_trace.<name>`` and returning that module object. Submodules are
  aliased lazily, on first import, so optional integrations (crewai, autogen,
  llamaindex) are imported only when asked for, exactly as before.
"""

import importlib
import importlib.abc
import importlib.util
import sys
import warnings

_OLD = __name__  # "agentscope"
_NEW = "agentscope_trace"


class _AliasLoader(importlib.abc.Loader):
    """Hands back the already-imported ``agentscope_trace`` module object."""

    def __init__(self, target):
        self._target = target

    def create_module(self, spec):
        module = importlib.import_module(self._target)
        # The import system overwrites __spec__ on the object returned here
        # (it keeps __name__, __loader__, __path__ and __file__); remember the
        # real one so exec_module can put it back.
        self._real_spec = module.__spec__
        return module

    def exec_module(self, module):
        # Already executed under its real name; executing again would create
        # a second copy of its module-level state.
        module.__spec__ = self._real_spec

    def get_code(self, fullname):
        # Lets `python -m agentscope.cli` keep working through runpy.
        real = importlib.util.find_spec(self._target)
        return real.loader.get_code(self._target)


class _AliasFinder(importlib.abc.MetaPathFinder):
    """Resolves ``agentscope.<name>`` to the ``agentscope_trace.<name>`` module."""

    _agentscope_trace_alias = True  # marker, so the finder is installed once

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith(_OLD + "."):
            return None
        new_name = _NEW + fullname[len(_OLD) :]
        if importlib.util.find_spec(new_name) is None:
            return None  # ModuleNotFoundError then names `agentscope.<name>`
        real = importlib.import_module(new_name)
        is_package = hasattr(real, "__path__")
        # origin: runpy uses it as sys.argv[0] for `python -m agentscope.cli`.
        return importlib.util.spec_from_loader(
            fullname,
            _AliasLoader(new_name),
            origin=real.__spec__.origin,
            is_package=is_package,
        )


warnings.warn(
    "The `agentscope` import name is deprecated and will be removed in a "
    "future release of agentscope-trace; import `agentscope_trace` instead "
    "(e.g. `from agentscope_trace import AgentScopeCallback`). The shim "
    "clashes with the unrelated `agentscope` package on PyPI.",
    DeprecationWarning,
    stacklevel=2,
)

if not any(getattr(f, "_agentscope_trace_alias", False) for f in sys.meta_path):
    # Ahead of the path-based finder, which would otherwise load a second copy
    # of each submodule from agentscope_trace/ under the old name.
    sys.meta_path.insert(0, _AliasFinder())

sys.modules[_OLD] = importlib.import_module(_NEW)
