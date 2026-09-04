import asyncio

from retention import prune_old_sessions


def test_prune_old_sessions_noop_when_no_config(monkeypatch):
    monkeypatch.delenv("AGENTSCOPE_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("RETENTION_DAYS", raising=False)
    monkeypatch.delenv("AGENTSCOPE_MAX_SESSIONS", raising=False)
    monkeypatch.delenv("MAX_SESSIONS", raising=False)

    pruned = asyncio.run(prune_old_sessions())
    assert pruned == 0
