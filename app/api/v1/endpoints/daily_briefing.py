from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime, timedelta

from app.api.deps import get_db, get_current_user
from app.db.models import User, DailySession, NewsArticle, UserProgress, WeeklyActivity
from app.schemas.daily_briefing import (
    DailyBriefingSequenceResponse, SequenceItem, 
    DailyBriefingCompleteRequest, DailyBriefingResultResponse
)

router = APIRouter(prefix="/daily-briefing", tags=["Push Notification Flow"])

# 1. GET THE FULL SEQUENCE (Loads instantly on App open)
@router.get("/sequence", response_model=DailyBriefingSequenceResponse)
async def get_briefing_sequence(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Fetch today's session
    session_res = await db.execute(select(DailySession).filter(
        DailySession.user_id == current_user.id, DailySession.date >= today_start
    ))
    session = session_res.scalars().first()

    if not session:
        raise HTTPException(status_code=404, detail="Today's briefing is still generating.")

    sequence_items = []

    # A. Append News Articles
    news_res = await db.execute(select(NewsArticle).filter(NewsArticle.id.in_(session.assigned_news_ids)))
    articles = news_res.scalars().all()
    for art in articles:
        sequence_items.append(SequenceItem(
            type="news",
            data={
                "id": art.id, "headline": art.headline, "tag": art.tag,
                "read_time_minutes": art.read_time_minutes,
                "image_url": art.image_url, "content_blocks": art.content_blocks
            }
        ))

    # B. Append Quiz
    if session.lesson_data and "quiz" in session.lesson_data:
        sequence_items.append(SequenceItem(
            type="quiz",
            data={"questions": session.lesson_data["quiz"]}
        ))

    return DailyBriefingSequenceResponse(session_id=session.id, items=sequence_items)

# 2. SUBMIT COMPLETION & GET STREAK RESULTS
@router.post("/{session_id}/complete", response_model=DailyBriefingResultResponse)
async def complete_briefing(
    session_id: int,
    data: DailyBriefingCompleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 1. Fetch Session
    session_res = await db.execute(select(DailySession).filter(DailySession.id == session_id))
    session = session_res.scalars().first()
    if not session or session.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Session not found")

    # 2. Grade Quiz
    score = 0
    quiz_data = session.lesson_data.get("quiz", []) if session.lesson_data else []
    user_answers = {a.question_index: a.selected_option_key for a in data.quiz_answers}
    
    for idx, q in enumerate(quiz_data):
        if user_answers.get(idx) == q.get("correct_option"):
            score += 1

    session.quiz_completed = True
    session.news_completed = len(session.assigned_news_ids) if session.assigned_news_ids else 0
    session.is_fully_completed = True

    # 3. Update User Progress & Streaks (SAFE FALLBACKS ADDED)
    prog_res = await db.execute(select(UserProgress).filter(UserProgress.user_id == current_user.id))
    progress = prog_res.scalars().first()
    
    if not progress:
        progress = UserProgress(
            user_id=current_user.id,
            current_xp=0,
            current_streak=0,
            longest_streak=0
        )
        db.add(progress)
    else:
        # Failsafe if existing DB records somehow have NULLs
        progress.current_xp = progress.current_xp or 0
        progress.current_streak = progress.current_streak or 0
        progress.longest_streak = progress.longest_streak or 0
    
    today = datetime.utcnow().date()
    if progress.last_completion_date:
        last_date = progress.last_completion_date.date()
        if last_date == today - timedelta(days=1):
            progress.current_streak += 1 # Streak continues!
        elif last_date != today:
            progress.current_streak = 1  # Streak broken, reset to 1
    else:
        progress.current_streak = 1 # First time
        
    progress.last_completion_date = datetime.utcnow()
    progress.current_xp += 10
    
    if progress.current_streak > progress.longest_streak:
        progress.longest_streak = progress.current_streak

    # 4. Update Weekly Activity (M,T,W,T,F,S,S UI) (SAFE JSON HANDLING)
    monday = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())
    weekly_res = await db.execute(select(WeeklyActivity).filter(WeeklyActivity.user_id == current_user.id, WeeklyActivity.week_start_date == monday))
    weekly_act = weekly_res.scalars().first()

    default_days = {"mon": False, "tue": False, "wed": False, "thu": False, "fri": False, "sat": False, "sun": False}

    if not weekly_act:
        weekly_act = WeeklyActivity(
            user_id=current_user.id, 
            week_start_date=monday,
            days_active=default_days
        )
        db.add(weekly_act)

    day_names = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    current_day = day_names[today.weekday()]
    
    # Create a new dict to ensure SQLAlchemy detects the JSON change safely
    new_days_active = dict(weekly_act.days_active or default_days)
    new_days_active[current_day] = True
    weekly_act.days_active = new_days_active

    # --- FIX START: Extract data to safe variables BEFORE commit ---
    final_streak = progress.current_streak
    final_weekly_tracker = new_days_active
    # --- FIX END ---

    await db.commit()

    # 5. Format Duration (e.g. 504 -> "8:24")
    mins, secs = divmod(data.duration_seconds, 60)
    duration_str = f"{mins}:{secs:02d}"

    return DailyBriefingResultResponse(
        focus_percentage=data.focus_percentage,
        duration_formatted=duration_str,
        quiz_score=score,
        quiz_total=len(quiz_data),
        current_streak=final_streak,            
        weekly_tracker=final_weekly_tracker     
    )