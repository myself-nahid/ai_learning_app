import logging
from datetime import date, datetime
# pyrefly: ignore [missing-import]
from sqlalchemy.ext.asyncio import AsyncSession
# pyrefly: ignore [missing-import]
from sqlalchemy import select
# pyrefly: ignore [missing-import]
from sqlalchemy import func, or_

from app.db.models import DailySession, UserNewsInteraction

logger = logging.getLogger(__name__)


async def get_or_create_daily_session(db: AsyncSession, user_id: int) -> DailySession:
    """
    Retrieves or creates today's DailySession for a user.
    Synchronizes news, lesson, and quiz completion for TODAY ONLY.
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

 