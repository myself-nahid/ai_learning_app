from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc, func
from datetime import date, datetime
import math
from typing import List, Optional

from sqlalchemy.orm import selectinload

from app.api.deps import get_db, get_current_user
from app.db.models import User, NewsArticle, UserNewsInteraction, DailySession
from app.schemas.home import HomeDashboardResponse, NewsCardResponse, NewsCardSchema, NewsDetailResponse

router = APIRouter(prefix="/home", tags=["Home & News"])

# Helper function to calculate "time ago"
def get_time_ago_string(published_at: datetime) -> str:
    """Helper to calculate '2 hours ago' style strings"""
    diff = datetime.utcnow() - published_at
    seconds = diff.total_seconds()
    if seconds < 3600:
        return f"{int(seconds // 60)} mins ago"
    elif seconds < 86400:
        return f"{int(seconds // 3600)} hours ago"
    return f"{int(seconds // 86400)} days ago"

@router.get("/dashboard", response_model=HomeDashboardResponse)
async def get_home_dashboard(
    category_tab: str = Query("For You", description="Selected tab in UI"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 1. GENERATE GREETING (Based on time of day)
    hour = datetime.now().hour
    if hour < 12: greeting = "Good morning"
    elif hour < 17: greeting = "Good afternoon"
    else: greeting = "Good evening"
    full_greeting = f"{greeting}, {current_user.full_name.split()[0]}"

    # 2. FETCH DAILY PULSE PROGRESS
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
     # 1. FETCH DAILY PULSE (FIXED DATE FILTER)
    pulse_res = await db.execute(
        select(DailySession).filter(
            DailySession.user_id == current_user.id, 
            func.date(DailySession.date) == date.today()
        )
    )
    session = pulse_res.scalars().first()

    # 2. Calculate Progress
    if not session:
        pulse_data = {
            "activities_completed": 0, "total_activities": 5, "progress_percentage": 0,
            "estimated_time_left": "8.0 min left", "check_news": False, 
            "check_lesson": False, "check_quiz": False
        }
    else:
        # news_completed tracks up to 3. Lesson and Quiz are 1 each. Total = 5.
        completed = session.news_completed + (1 if session.lesson_completed else 0) + (1 if session.quiz_completed else 0)
        
        pulse_data = {
            "activities_completed": completed,
            "total_activities": 5,
            "progress_percentage": int((completed / 5) * 100),
            "estimated_time_left": f"{max(0, 8.0 - (completed * 1.6))} min left",
            "check_news": session.news_completed >= 3,
            "check_lesson": session.lesson_completed,
            "check_quiz": session.quiz_completed
        }

    # 3. FETCH NEWS FEED (Based on Tabs)
    # Get user profile to know their interests for the 'For You' tab
    user_res = await db.execute(
        select(User).options(selectinload(User.profile)).filter(User.id == current_user.id)
    )
    user_with_profile = user_res.scalars().first()
    
    query = select(NewsArticle).order_by(desc(NewsArticle.published_at))

    # Apply Filtering Logic per Tab
    if category_tab == "For You":
        # Filter by the primary interest selected during onboarding
        query = query.filter(NewsArticle.category == user_with_profile.profile.primary_interest)
    elif category_tab == "Trending":
        # In a real app, you'd filter by 'is_trending' flag or high view count
        query = query.limit(10) 
    else:
        # Filter by specific category (Tools, Research, Science, etc.)
        query = query.filter(NewsArticle.category == category_tab)

    news_result = await db.execute(query.limit(15))
    articles = news_result.scalars().all()

    # 4. CHECK BOOKMARKS
    # Get list of article IDs that this user has bookmarked
    bookmark_res = await db.execute(
        select(UserNewsInteraction.news_id).filter(
            UserNewsInteraction.user_id == current_user.id,
            UserNewsInteraction.is_bookmarked == True
        )
    )
    bookmarked_ids = set(bookmark_res.scalars().all())

    # 5. FORMAT FINAL NEWS LIST
    formatted_news = []
    for art in articles:
        formatted_news.append({
            "id": art.id,
            "image_url": art.image_url or "",
            "tag": art.tag,
            "headline": art.headline,
            "summary": art.summary,
            "read_time_minutes": art.read_time_minutes,
            "time_ago": get_time_ago_string(art.published_at),
            "is_bookmarked": art.id in bookmarked_ids
        })

    # 6. RETURN COMPLETE DASHBOARD
    return {
        "greeting": full_greeting,
        "unread_notifications": 2, # Hardcoded for now, could be dynamic
        "profile_image": current_user.profile_image,
        "daily_pulse": pulse_data,
        "todays_news": formatted_news
    }

@router.get("/news/all", response_model=List[NewsCardResponse])
async def get_all_news(
    category: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user) # Required for bookmark status
):
    # 1. Fetch raw articles from DB
    query = select(NewsArticle).order_by(NewsArticle.published_at.desc())
    if category:
        query = query.filter(NewsArticle.category == category)
    
    result = await db.execute(query.offset(skip).limit(limit))
    articles = result.scalars().all()

    # 2. Fetch the user's bookmarks to determine 'is_bookmarked'
    bookmark_res = await db.execute(
        select(UserNewsInteraction.news_id).filter(
            UserNewsInteraction.user_id == current_user.id,
            UserNewsInteraction.is_bookmarked == True
        )
    )
    bookmarked_ids = set(bookmark_res.scalars().all())

    # 3. MANUALLY CONSTRUCT THE RESPONSE
    # This fills in the missing 'time_ago' and 'is_bookmarked' fields
    response_data = []
    for art in articles:
        response_data.append({
            "id": art.id,
            "image_url": art.image_url or "",
            "tag": art.tag,
            "headline": art.headline,
            "summary": art.summary,
            "read_time_minutes": art.read_time_minutes,
            # Use the helper function we created earlier
            "time_ago": get_time_ago_string(art.published_at), 
            "is_bookmarked": art.id in bookmarked_ids
        })

    return response_data

# 2. GET NEWS DETAIL (Screen 2)
@router.get("/news/{news_id}", response_model=NewsDetailResponse)
async def get_news_detail(
    news_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 1. Fetch the main article
    article_res = await db.execute(select(NewsArticle).filter(NewsArticle.id == news_id))
    article = article_res.scalars().first()
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")

    # 2. Check if bookmarked
    int_res = await db.execute(
        select(UserNewsInteraction).filter(
            UserNewsInteraction.user_id == current_user.id,
            UserNewsInteraction.news_id == news_id
        )
    )
    interaction = int_res.scalars().first()
    is_bookmarked = interaction.is_bookmarked if interaction else False

    # 3. Fetch 2 related articles
    related_res = await db.execute(
        select(NewsArticle)
        .filter(NewsArticle.category == article.category, NewsArticle.id != news_id)
        .limit(2)
    )
    
    related_cards = []
    for rel in related_res.scalars().all():
        related_cards.append({
            "id": rel.id,
            "image_url": rel.image_url or "",
            "tag": rel.tag,
            "headline": rel.headline,
            "summary": None, # This is now safe because we updated the schema
            "read_time_minutes": rel.read_time_minutes,
            "time_ago": get_time_ago_string(rel.published_at),
            "is_bookmarked": False
        })

    # 4. Return Final Data
    return {
        "id": article.id,
        "image_url": article.image_url or "",
        "tag": article.tag,
        "headline": article.headline,
        "published_date": article.published_at.strftime("%d %b %Y"), 
        "read_time_minutes": article.read_time_minutes,
        "time_ago": get_time_ago_string(article.published_at),
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
    # 1. Update/Create User Interaction
    int_res = await db.execute(select(UserNewsInteraction).filter(
        UserNewsInteraction.user_id == current_user.id, 
        UserNewsInteraction.news_id == news_id
    ))
    interaction = int_res.scalars().first()

    if not interaction:
        interaction = UserNewsInteraction(user_id=current_user.id, news_id=news_id, is_read=True, read_at=datetime.utcnow())
        db.add(interaction)
    elif not interaction.is_read:
        interaction.is_read = True
        interaction.read_at = datetime.utcnow()
    else:
        return {"message": "Already read", "pulse_updated": False}

    # 2. Update Daily Pulse Progress (CRITICAL FIX)
    # Use func.date to match only the Day, regardless of the Time
    pulse_query = await db.execute(select(DailySession).filter(
        DailySession.user_id == current_user.id,
        func.date(DailySession.date) == date.today() # Strictly match today's date
    ))
    session = pulse_query.scalars().first()
    
    pulse_updated = False
    if session:
        # Check A: If it's a specific assigned news
        # Check B: OR just allow any news read to count towards the 3 daily news activities
        if session.news_completed < 3:
            session.news_completed += 1
            pulse_updated = True
        
    await db.commit()
    return {"message": "Article marked as read", "pulse_updated": pulse_updated}

# 4. TOGGLE BOOKMARK
@router.post("/news/{news_id}/bookmark")
async def toggle_bookmark(
    news_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # 1. Look for existing interaction
    int_res = await db.execute(select(UserNewsInteraction).filter(
        UserNewsInteraction.user_id == current_user.id, 
        UserNewsInteraction.news_id == news_id
    ))
    interaction = int_res.scalars().first()

    if not interaction:
        # Create new bookmark
        interaction = UserNewsInteraction(
            user_id=current_user.id, 
            news_id=news_id, 
            is_bookmarked=True
        )
        db.add(interaction)
        final_state = True # We know it's True since we just created it
    else:
        # Toggle existing bookmark
        interaction.is_bookmarked = not interaction.is_bookmarked
        final_state = interaction.is_bookmarked

    # 2. Commit the change
    await db.commit()
    # The 'interaction' object is now expired/unreadable, but we have 'final_state'

    # 3. Return the saved variable
    return {"is_bookmarked": final_state}

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