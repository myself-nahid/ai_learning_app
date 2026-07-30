import logging
from datetime import date, datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, or_

from app.db.models import DailySession, UserNewsInteraction

logger = logging.getLogger(__name__)


async def get_or_create_daily_session(db: AsyncSession, user_id: int) -> DailySession:
    """
    Retrieves or creates today's DailySession for a user.
    Synchronizes news_completed count with actual unique news articles read today.
    """
    today_date = date.today()
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    # 1. Fetch today's session
    pulse_res = await db.execute(
        select(DailySession).filter(
            DailySession.user_id == user_id,
            func.date(DailySession.date) == today_date
        )
    )
    session = pulse_res.scalars().first()

    if not session:
        session = DailySession(
            user_id=user_id,
            date=datetime.utcnow(),
            assigned_news_ids=[],
            lesson_data={},
            news_completed=0,
            lesson_completed=False,
            quiz_completed=False,
            is_fully_completed=False,
        )
        db.add(session)
        await db.flush()

    # 2. Sync news_completed count with total articles read by user
    read_res = await db.execute(
        select(func.count(UserNewsInteraction.id)).filter(
            UserNewsInteraction.user_id == user_id,
            UserNewsInteraction.is_read == True
        )
    )
    read_count_today = read_res.scalar() or 0

    synced = min(3, max(session.news_completed, read_count_today))
    if session.news_completed != synced:
        session.news_completed = synced

    return session
 