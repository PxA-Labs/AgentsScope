import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from database import vacuum_database
from main import app
from models import SessionModel
from retention import prune_old_sessions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def test_prune_old_sessions_noop_when_no_config(monkeypatch):
    monkeypatch.delenv("AGENTSCOPE_RETENTION_DAYS", raising=False)
    monkeypatch.delenv("RETENTION_DAYS", raising=False)
    monkeypatch.delenv("AGENTSCOPE_MAX_SESSIONS", raising=False)
    monkeypatch.delenv("MAX_SESSIONS", raising=False)

    pruned = asyncio.run(prune_old_sessions())
    assert pruned == 0


@pytest.mark.asyncio
async def test_prune_old_sessions_deletes_expired_and_vacuums(db_engine):
    maker = async_sessionmaker(bind=db_engine, class_=AsyncSession)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with maker() as db:
        db.add_all(
            [
                SessionModel(
                    session_id="retention-old",
                    name="old",
                    status="completed",
                    started_at=now - timedelta(days=10),
                ),
                SessionModel(
                    session_id="retention-new",
                    name="new",
                    status="completed",
                    started_at=now,
                ),
            ]
        )
        await db.commit()

    # VACUUM must run outside a transaction; an error here would be logged and
    # rolled back, so assert on the actual effect of the prune.
    pruned = await prune_old_sessions(retention_days=5, session_maker=maker)
    assert pruned == 1

    async with maker() as db:
        remaining = set(
            (
                await db.execute(
                    select(SessionModel.session_id).where(
                        SessionModel.session_id.in_(["retention-old", "retention-new"])
                    )
                )
            )
            .scalars()
            .all()
        )
    assert remaining == {"retention-new"}


@pytest.mark.asyncio
async def test_vacuum_database_runs_outside_transaction(db_engine):
    await vacuum_database(bind=db_engine)


def test_prune_endpoint_is_not_exposed():
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/sessions/prune" not in paths
