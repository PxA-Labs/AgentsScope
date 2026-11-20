import asyncio
import os
import threading
import time

import pytest

import agentscope.client as client_module
from agentscope import _pricing


@pytest.fixture(autouse=True)
def isolate_pricing_state():
    original_table = {
        name: rates.copy() for name, rates in _pricing.PRICING_TABLE.items()
    }
    original_env = os.environ.get("AGENTSCOPE_CUSTOM_PRICING")
    yield
    _pricing.PRICING_TABLE.clear()
    _pricing.PRICING_TABLE.update(
        {name: rates.copy() for name, rates in original_table.items()}
    )
    if original_env is None:
        os.environ.pop("AGENTSCOPE_CUSTOM_PRICING", None)
    else:
        os.environ["AGENTSCOPE_CUSTOM_PRICING"] = original_env


@pytest.fixture
def run_sender_loop(monkeypatch):
    """Run ``client._main_async_loop`` the way the sender thread does.

    The loop gets a fresh ``_Sender``; ``_Sender.backoff`` is replaced by a
    recorder that asks the sender to stop (``request_stop``) once it has been
    called ``backoffs`` times. Returns the requested backoff durations.
    """
    from agentscope.client import _Sender, _SenderEventLoop

    def run(client, backoffs=1):
        waits = []

        async def recording_backoff(self, seconds):
            waits.append(seconds)
            if len(waits) >= backoffs:
                self.request_stop(time.monotonic())

        monkeypatch.setattr(_Sender, "backoff", recording_backoff)
        loop = _SenderEventLoop()
        try:
            loop.run_until_complete(
                asyncio.wait_for(client._main_async_loop(_Sender()), timeout=10)
            )
        finally:
            loop.close()
        return waits

    return run


@pytest.fixture
def inline_status_patch(monkeypatch):
    """Run the status-PATCH helper thread inline; leave every other thread real.

    Only ``agentscope.client``'s view of ``threading`` is replaced, and only
    the thread named AgentScopeSessionPatchThread runs inline. The global
    ``threading.Thread`` and the sender's own threads stay untouched. Returns
    a list that records each inline start.
    """
    real_thread = threading.Thread
    started = []

    class InlineThread:
        def __init__(self, target):
            self.target = target

        def start(self):
            started.append(True)
            self.target()

    def thread_factory(*args, **kwargs):
        if kwargs.get("name") == "AgentScopeSessionPatchThread":
            return InlineThread(kwargs["target"])
        return real_thread(*args, **kwargs)

    class ThreadingView:
        Thread = staticmethod(thread_factory)

        def __getattr__(self, name):
            return getattr(threading, name)

    monkeypatch.setattr(client_module, "threading", ThreadingView())
    return started
