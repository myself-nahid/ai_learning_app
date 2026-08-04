import logging
from datetime import date, datetime, timedelta
# pyrefly: ignore [missing-import]
from sqlalchemy.ext.asyncio import AsyncSession
# pyrefly: ignore [missing-import]
from sqlalchemy import select, delete
# pyrefly: ignore [missing-import]
from sqlalchemy import func, or_

from app.db.models import DailySession, UserNewsInteraction

logger = logging.getLogger(__name__)


async def _cleanup_stale_streak_data(db: AsyncSession, user_id: int) -> None:
    """
    Silently prune DailySession rows older than 3 days and WeeklyActivity rows
    from weeks prior to the current week for this user.
    Keeps the DB lean and prevents stale streak data from persisting.
    Called once per day when a new DailySession is created.
    """
    try:
        from app.db.models import WeeklyActivity
        # pyrefly: ignore [missing-import]
        from sqlalchemy import func as sa_func

        cutoff_date = datetime.utcnow() - timedelta(days=3)

        # 1. Delete DailySession rows older than 3 days
        await db.execute(
            delete(DailySession).where(
                DailySession.user_id == user_id,
                DailySession.date < cutoff_date,
            )
        )

        # 2. Delete WeeklyActivity rows from previous weeks (before current week's Monday)
        today = datetime.utcnow().date()
        current_week_monday = today - timedelta(days=today.weekday())
        week_cutoff = datetime(current_week_monday.year, current_week_monday.month, current_week_monday.day)

        await db.execute(
            delete(WeeklyActivity).where(
                WeeklyActivity.user_id == user_id,
                WeeklyActivity.week_start_date < week_cutoff,
            )
        )

        await db.commit()
        logger.info("[session_service] Cleaned up stale streak data for user_id=%s", user_id)
    except Exception as e:
        logger.warning("[session_service] Streak cleanup failed (non-critical): %s", str(e))


async def get_or_create_daily_session(db: AsyncSession, user_id: int) -> DailySession:
    """
    Retrieves or creates today's DailySession for a user.
    Synchronizes news, lesson, and quiz completion for TODAY ONLY.
    Old DailySession (>3 days) and prior-week WeeklyActivity rows are cleaned up
    automatically when a fresh session is created — each streak is valid for 24h.
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

        # Prune stale streak data on new day (non-blocking, best-effort)
        await _cleanup_stale_streak_data(db, user_id)

    # 2. Count news articles read TODAY
    read_res = await db.execute(
        select(func.count(UserNewsInteraction.id)).filter(
            UserNewsInteraction.user_id == user_id,
            UserNewsInteraction.is_read == True,
            UserNewsInteraction.read_at >= today_start
        )
    )
    read_count_today = read_res.scalar() or 0
    session.news_completed = min(3, max(session.news_completed, read_count_today))

    # 3. Check if a lesson was completed TODAY
    from app.db.models import UserLessonProgress
    lesson_res = await db.execute(
        select(func.count(UserLessonProgress.id)).filter(
            UserLessonProgress.user_id == user_id,
            UserLessonProgress.status == "completed",
            UserLessonProgress.last_accessed >= today_start
        )
    )
    if (lesson_res.scalar() or 0) > 0:
        session.lesson_completed = True

    # 4. Check if a quiz was completed TODAY
    from app.db.models import QuizAttempt
    quiz_res = await db.execute(
        select(func.count(QuizAttempt.id)).filter(
            QuizAttempt.user_id == user_id,
            QuizAttempt.status == "completed",
            QuizAttempt.completed_at >= today_start
        )
    )
    if (quiz_res.scalar() or 0) > 0:
        session.quiz_completed = True

    await db.commit()
    return session

 