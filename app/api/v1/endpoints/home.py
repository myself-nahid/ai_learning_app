from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc
from datetime import datetime
import math

from app.api.deps import get_db, get_current_user
from app.db.models import User, NewsArticle, UserNewsInteraction, DailySession
from app.schemas.home import HomeDashboardResponse, NewsCardSchema, NewsDetailResponse

router = APIRouter(prefix="/home", tags=["Home & News"])

# Helper function to calculate "time ago"
def get_time_ago(published_at: datetime) -> str:
    diff = datetime.utcnow() - published_at
    hours = diff.total_seconds() // 3600
    if hours < 1:
        return "Just now"
    elif hours < 24:
        return f"{int(hours)} hours ago"
    return f"{int(hours // 24)} days ago"

# 1. GET HOME DASHBOARD (Screen 1)
@router.get("/dashboard", response_model=HomeDashboardResponse)
async def get_dashboard(
    category_tab: str = "For You", # Supports the filter tabs in UI
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Determine Greeting
    hour = datetime.utcnow().hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"

    # 1. Fetch Daily Pulse (Assume Celery worker creates this daily at 2 AM)
    pulse_query = await db.execute(
        select(DailySession).filter(
            DailySession.user_id == current_user.id,
            DailySession.date >= datetime.utcnow().replace(hour=0, minute=0, second=0)
        )
    )
    session = pulse_query.scalars().first()

    if not session:
        # Fallback if worker hasn't run
        pulse_data = {
            "activities_completed": 0, "total_activities": 5, "progress_percentage": 0,
            "estimated_time_left": "5 min left", "check_news": False, 
            "check_lesson": False, "check_quiz": False
        }
    else:
        completed = session.news_completed + int(session.lesson_completed) + int(session.quiz_completed)
        pulse_data = {
            "activities_completed": completed,
            "total_activities": 5,
            "progress_percentage": int((completed / 5) * 100),
            "estimated_time_left": f"{math.ceil((5 - completed) * 1.5)} min left",
            "check_news": session.news_completed >= 3,
            "check_lesson": session.lesson_completed,
            "check_quiz": session.quiz_completed
        }

    # 2. Fetch News based on Tab
    query = select(NewsArticle).order_by(desc(NewsArticle.published_at)).limit(10)
    if category_tab != "For You" and category_tab != "Trending":
        query = query.filter(NewsArticle.category == category_tab)
        
    news_result = await db.execute(query)
    articles = news_result.scalars().all()

    # 3. Fetch user interactions to see what is bookmarked
    interactions_result = await db.execute(
        select(UserNewsInteraction).filter(UserNewsInteraction.user_id == current_user.id)
    )
    interactions = {int_act.news_id: int_act for int_act in interactions_result.scalars().all()}

    # Format News Cards
    news_cards = []
    for article in articles:
        is_book = interactions.get(article.id).is_bookmarked if article.id in interactions else False
        news_cards.append({
            "id": article.id,
            "image_url": article.image_url or "https://via.placeholder.com/400",
            "tag": article.tag,
            "headline": article.headline,
            "summary": article.summary,
            "read_time_minutes": article.read_time_minutes,
            "time_ago": get_time_ago(article.published_at),
            "is_bookmarked": is_book
        })

    return {
        "greeting": f"{greeting}, {current_user.full_name.split()[0]}",
        "unread_notifications": 2, # Mocked for now
        "profile_image": current_user.profile_image,
        "daily_pulse": pulse_data,
        "todays_news": news_cards
    }

# 2. GET NEWS DETAIL (Screen 2)
@router.get("/news/{news_id}", response_model=NewsDetailResponse)
async def get_news_detail(
    news_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    article_res = await db.execute(select(NewsArticle).filter(NewsArticle.id == news_id))
    article = article_res.scalars().first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    # Fetch Interaction
    int_res = await db.execute(
        select(UserNewsInteraction).filter(
            UserNewsInteraction.user_id == current_user.id,
            UserNewsInteraction.news_id == news_id
        )
    )
    interaction = int_res.scalars().first()
    is_bookmarked = interaction.is_bookmarked if interaction else False

    # Fetch 2 related articles for "More News" section
    related_res = await db.execute(
        select(NewsArticle)
        .filter(NewsArticle.category == article.category, NewsArticle.id != news_id)
        .limit(2)
    )
    related_cards = [
        {
            "id": rel.id, "image_url": rel.image_url or "", "tag": rel.tag,
            "headline": rel.headline, "summary": None, "read_time_minutes": rel.read_time_minutes,
            "time_ago": get_time_ago(rel.published_at), "is_bookmarked": False
        } for rel in related_res.scalars().all()
    ]

    return {
        "id": article.id,
        "image_url": article.image_url or "",
        "tag": article.tag,
        "headline": article.headline,
        "date_str": article.published_at.strftime("%d %b %Y"),
        "read_time_minutes": article.read_time_minutes,
        "time_ago": get_time_ago(article.published_at),
        "content_blocks": article.content_blocks,
        "is_bookmarked": is_bookmarked,
        "related_news": related_cards
    }

# 3. MARK NEWS AS READ (Updates the Daily Pulse Progress!)
@router.post("/news/{news_id}/read")
async def mark_news_read(
    news_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 1. Update Interaction
    int_res = await db.execute(select(UserNewsInteraction).filter(
        UserNewsInteraction.user_id == current_user.id, UserNewsInteraction.news_id == news_id
    ))
    interaction = int_res.scalars().first()

    if not interaction:
        interaction = UserNewsInteraction(user_id=current_user.id, news_id=news_id, is_read=True, read_at=datetime.utcnow())
        db.add(interaction)
    elif not interaction.is_read:
        interaction.is_read = True
        interaction.read_at = datetime.utcnow()
    else:
        return {"message": "Already read"} # Don't add to pulse again

    # 2. Update Daily Pulse Progress
    pulse_query = await db.execute(select(DailySession).filter(
        DailySession.user_id == current_user.id,
        DailySession.date >= datetime.utcnow().replace(hour=0, minute=0, second=0)
    ))
    session = pulse_query.scalars().first()
    
    if session and news_id in session.assigned_news_ids and session.news_completed < 3:
        session.news_completed += 1
        
    await db.commit()
    return {"message": "Article marked as read", "pulse_updated": True}

# 4. TOGGLE BOOKMARK
@router.post("/news/{news_id}/bookmark")
async def toggle_bookmark(
    news_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    int_res = await db.execute(select(UserNewsInteraction).filter(
        UserNewsInteraction.user_id == current_user.id, UserNewsInteraction.news_id == news_id
    ))
    interaction = int_res.scalars().first()

    if not interaction:
        interaction = UserNewsInteraction(user_id=current_user.id, news_id=news_id, is_bookmarked=True)
        db.add(interaction)
    else:
        interaction.is_bookmarked = not interaction.is_bookmarked

    await db.commit()
    return {"is_bookmarked": interaction.is_bookmarked}


from app.worker.tasks import generate_real_daily_content


@router.get("/daily-lesson")
async def get_daily_lesson(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    res = await db.execute(select(DailySession).filter(
        DailySession.user_id == current_user.id,
        DailySession.date >= datetime.utcnow().replace(hour=0, minute=0, second=0)
    ))
    session = res.scalars().first()
    if not session or not session.lesson_data:
        raise HTTPException(status_code=404, detail="Lesson not ready yet.")
    
    return {
        "title": session.lesson_data['title'],
        "content": session.lesson_data['content_blocks'],
        "takeaway": session.lesson_data['practical_takeaway']
    }

@router.post("/daily-lesson/complete")
async def complete_lesson(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    res = await db.execute(select(DailySession).filter(DailySession.user_id == current_user.id))
    session = res.scalars().first()
    session.lesson_completed = True
    await db.commit()
    return {"message": "Lesson completed! +10 XP"}

@router.get("/daily-quiz")
async def get_daily_quiz(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    res = await db.execute(select(DailySession).filter(DailySession.user_id == current_user.id))
    session = res.scalars().first()
    return session.lesson_data['quiz'] # Returns the 3 questions

@router.post("/trigger-daily-pulse")
async def trigger_daily_pulse(
    current_user: User = Depends(get_current_user)
):
    """
    Manually triggers the AI News & Learning generation 
    for the current user immediately.
    """
    # .delay() sends it to the Celery Worker queue
    generate_real_daily_content.delay() 
    
    return {
        "status": "processing",
        "message": "AI is fetching news and writing your lesson. Check back in 15 seconds."
    }


# --- GET TODAY'S LESSON ---
@router.get("/daily-lesson")
async def get_todays_lesson(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Fetch today's session
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(DailySession).filter(
            DailySession.user_id == current_user.id,
            DailySession.date >= today_start
        )
    )
    session = result.scalars().first()

    if not session or not session.lesson_data:
        raise HTTPException(status_code=404, detail="Today's lesson is not ready.")

    # Return only the lesson part of the JSON
    return {
        "title": session.lesson_data.get("title"),
        "content_blocks": session.lesson_data.get("content_blocks"),
        "practical_takeaway": session.lesson_data.get("practical_takeaway")
    }

# --- MARK LESSON AS COMPLETE ---
@router.post("/daily-lesson/complete")
async def complete_lesson(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(DailySession).filter(DailySession.user_id == current_user.id, DailySession.date >= today_start)
    )
    session = result.scalars().first()
    
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.lesson_completed = True
    await db.commit()
    return {"message": "Lesson completed! Progress updated."}

# --- GET TODAY'S QUIZ ---
@router.get("/daily-quiz")
async def get_todays_quiz(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    result = await db.execute(
        select(DailySession).filter(DailySession.user_id == current_user.id, DailySession.date >= today_start)
    )
    session = result.scalars().first()

    if not session or not session.lesson_data:
        raise HTTPException(status_code=404, detail="Today's quiz is not ready.")

    # Return only the quiz array from the JSON
    return session.lesson_data.get("quiz")