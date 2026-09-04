import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from database import async_session_maker, vacuum_database
from models import SessionModel
from sqlalchemy import delete, func, select

logger = logging.getLogger(__name__)


async def prune_old_sessions(
    retention_days: Optional[int] = None,
    max_sessions: Optional[int] = None,
    vacuum: bool = True,
) -> int:
    """Prune old sessions based on retention policies and run SQLite VACUUM."""
    retention_days_raw = (
        str(retention_days)
        if retention_days is not None
        else (os.getenv("AGENTSCOPE_RETENTION_DAYS") or os.getenv("RETENTION_DAYS"))
    )
    max_sessions_raw = (
        str(max_sessions)
        if max_sessions is not None
        else (os.getenv("AGENTSCOPE_MAX_SESSIONS") or os.getenv("MAX_SESSIONS"))
    )

    if not retention_days_raw and not max_sessions_raw:
        return 0

    total_pruned = 0
    async with async_session_maker() as db:
        try:
            # 1. Prune by retention days
            if retention_days_raw:
                try:
                    days = int(retention_days_raw)
                    cutoff = datetime.now(timezone.utc).replace(
                        tzinfo=None
                    ) - timedelta(days=days)
                    stmt = delete(SessionModel).where(
                        SessionModel.started_at < cutoff
                    )
                    res = await db.execute(stmt)
                    await db.commit()
                    deleted_count = res.rowcount or 0
                    total_pruned += deleted_count
                    if deleted_count:
                        logger.info(
                            f"Pruned {deleted_count} sessions older than "
                            f"{days} days (cutoff: {cutoff.isoformat()})"
                        )
                except ValueError:
                    logger.warning(
                        f"Invalid retention days value: {retention_days_raw}"
                    )

            # 2. Prune by max session limit
            if max_sessions_raw:
                try:
                    limit = int(max_sessions_raw)
                    cnt_stmt = select(func.count(SessionModel.session_id))
                    cnt_res = await db.execute(cnt_stmt)
                    total_sessions = cnt_res.scalar() or 0

                    if total_sessions > limit:
                        excess = total_sessions - limit
                        old_stmt = (
                            select(SessionModel.session_id)
                            .order_by(SessionModel.started_at.asc())
                            .limit(excess)
                        )
                        old_res = await db.execute(old_stmt)
                        ids_to_delete = old_res.scalars().all()

                        if ids_to_delete:
                            del_stmt = delete(SessionModel).where(
                                SessionModel.session_id.in_(ids_to_delete)
                            )
                            await db.execute(del_stmt)
                            await db.commit()
                            total_pruned += len(ids_to_delete)
                            logger.info(
                                f"Pruned {len(ids_to_delete)} oldest sessions "
                                f"to enforce max sessions limit of {limit}."
                            )
                except ValueError:
                    logger.warning(
                        f"Invalid max sessions value: {max_sessions_raw}"
                    )

            if total_pruned > 0 and vacuum:
                await vacuum_database()
        except Exception as e:
            logger.error(f"Error during database session pruning: {e}")
            await db.rollback()

    return total_pruned
