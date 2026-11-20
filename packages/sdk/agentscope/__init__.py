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
* The finder's ``find_spec`` runs under CPython's global import lock, so it
  only locates files and never imports; the real import happens in the
  loader's ``create_module``, which holds just that module's own lock.
  Importing there would deadlock against a thread that is part-way through
  importing an ``agentscope_trace`` submodule.

Threads
-------
Import ``agentscope`` (or ``agentscope_trace``) once at startup, before
starting threads. While the first ``import agentscope`` is still running,
CPython does not make other threads wait for the half-initialised package:
a thread that first-imports ``agentscope.<name>`` at that moment can get
ModuleNotFoundError. (Concurrent first imports of ``agentscope_trace``
submodules can also fail with CPython's import-cycle ``_DeadlockError``.)
Once the package is imported, concurrent imports under either name are safe.
"""

# Kept minimal until the finder is installed (below): until then, another
# thread importing `agentscope.<name>` finds nothing (see "Threads" above).
# These importlib modules are normally loaded already at startup.
import importlib
import importlib.util
import sys
from importlib.machinery import PathFinder

_OLD = __name__  # "agentscope"
_NEW = "agentscope_trace"


def _locate(name):
    """Find the spec of ``name`` without importing (executing) anything.

    Called from ``find_spec``, which CPython runs under the global import
    lock: importing there deadlocks against a thread that is mid-way through
    importing an ``agentscope_trace`` submodule and needs that lock for its
    own imports. So this only walks the filesystem, one package level at a
    time, using already-imported packages' ``__path__`` where available.
    """
    parts = name.split(".")
    spec = None
    for depth in range(1, len(parts) + 1):
        prefix = ".".join(parts[:depth])
        module = sys.modules.get(prefix)
        if module is not None and getattr(module, "__spec__", None) is not None:
            spec = module.__spec__
            search = getattr(module, "__path__", None)
        else:
            if depth == 1:
                # Top level: a lookup only (meta path finders, e.g. editable
                # installs), no import of a parent package.
                spec = importlib.util.find_spec(prefix)
            else:
                spec = PathFinder.find_spec(prefix, search)
            if spec is None:
                return None
            search = spec.submodule_search_locations
        if search is None and depth < len(parts):
            return None  # a plain module has no submodules
    return spec


class _AliasLoader:
    """Hands back the ``agentscope_trace`` module object itself."""

    def __init__(self, target):
        self._target = target

    def create_module(self, spec):
        # The real import happens here, where only this module's own import
        # lock is held, not the global one (see _locate).
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
        return _locate(self._target).loader.get_code(self._target)


class _AliasFinder:
    """Resolves ``agentscope.<name>`` to the ``agentscope_trace.<name>`` module."""

    _agentscope_trace_alias = True  # marker, so the finder is installed once

    def find_spec(self, fullname, path=None, target=None):
        if not fullname.startswith(_OLD + "."):
            return None
        new_name = _NEW + fullname[len(_OLD) :]
        # No imports here: see _locate.
        real = _locate(new_name)
        if real is None:
            return None  # ModuleNotFoundError then names `agentscope.<name>`
        # origin: runpy uses it as sys.argv[0] for `python -m agentscope.cli`.
        return importlib.util.spec_from_loader(
            fullname,
            _AliasLoader(new_name),
            origin=real.origin,
            is_package=real.submodule_search_locations is not None,
        )


if not any(getattr(f, "_agentscope_trace_alias", False) for f in sys.meta_path):
    # Ahead of the path-based finder, which would otherwise load a second copy
    # of each submodule from agentscope_trace/ under the old name. Installed
    # first thing, so it is in place before anything below can import.
    sys.meta_path.insert(0, _AliasFinder())

import warnings  # noqa: E402

warnings.warn(
    "The `agentscope` import name is deprecated and will be removed in a "
    "future release of agentscope-trace; import `agentscope_trace` instead "
    "(e.g. `from agentscope_trace import AgentScopeCallback`). The shim "
    "clashes with the unrelated `agentscope` package on PyPI.",
    DeprecationWarning,
    stacklevel=2,
)

sys.modules[_OLD] = importlib.import_module(_NEW)
