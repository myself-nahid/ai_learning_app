from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc, func, or_
from datetime import date, datetime
import math
from typing import List, Optional

from sqlalchemy.orm import selectinload

from app.api.deps import get_db, get_current_user
from app.db.models import User, NewsArticle, UserNewsInteraction, DailySession, Notification
from app.schemas.home import HomeDashboardResponse, NewsCardResponse, NewsDetailResponse
from app.schemas.response import (
    BookmarkToggleResponse,
    DailyLessonResponse,
    MessageResponse,
    ReadStatusResponse,
    TriggerPulseResponse,
)
from app.services.session_service import get_or_create_daily_session

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
    session = await get_or_create_daily_session(db, current_user.id)

    # news_completed tracks up to 3. Lesson and Quiz are 1 each. Total = 5.
    completed = session.news_completed + (1 if session.lesson_completed else 0) + (1 if session.quiz_completed else 0)

    pulse_data = {
        "activities_completed": completed,
        "total_activities": 5,
        "progress_percentage": int((completed / 5) * 100),
        "estimated_time_left": f"{max(0, math.ceil(8.0 - (completed * 1.6))):.1f} min left",
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
        interests = user_with_profile.profile.interests if (user_with_profile and user_with_profile.profile and user_with_profile.profile.interests) else []
        if interests:
            query = query.filter(
                or_(
                    NewsArticle.category.in_(interests),
                    NewsArticle.tag.in_(interests)
                )
            )
    elif category_tab == "Trending":
        query = query.limit(10)
    else:
        query = query.filter(
            or_(
                NewsArticle.category == category_tab,
                NewsArticle.tag == category_tab,
                NewsArticle.category.contains(category_tab),
                NewsArticle.tag.contains(category_tab)
            )
        )

    news_result = await db.execute(query)
    articles = news_result.scalars().all()

    # Fallback: If tab filter yields 0 articles, return latest articles so feed is never empty
    if not articles:
        fallback_res = await db.execute(select(NewsArticle).order_by(desc(NewsArticle.published_at)))
        articles = fallback_res.scalars().all()

    # 4. CHECK BOOKMARKS (Optimized: single query for bookmark IDs)
    bookmark_res = await db.execute(
        select(UserNewsInteraction.news_id).filter(
            UserNewsInteraction.user_id == current_user.id,
            UserNewsInteraction.is_bookmarked == True
        )
    )
    bookmarked_ids = set(bookmark_res.scalars().all())

    # 5. FORMAT FINAL NEWS LIST (map to frontend DTO shape)
    formatted_news = []
    seen_headlines = set()
    for art in articles:
        if art.headline and art.headline in seen_headlines:
            continue
        seen_headlines.add(art.headline)
        published_time = get_time_ago_string(art.published_at) if art.published_at else "Just now"
        date_str = art.published_at.strftime("%d %b %Y") if art.published_at else datetime.utcnow().strftime("%d %b %Y")
        formatted_news.append({
            "id": str(art.id),
            "title": art.headline or "",
            "summary": art.summary or "",
            "category": art.tag or "Generative AI",
            "readTime": f"{art.read_time_minutes or 3} min read",
            "publishedTime": published_time,
            "date": date_str,
            "publisher": art.publisher or "TechCrunch",
            "publishedDate": date_str,
            "originalUrl": art.original_url or None,
            "imageUrl": art.image_url or None,
            "isBookmarked": art.id in bookmarked_ids
        })

    # 5.5 Count unread notifications dynamically
    unread_count_res = await db.execute(
        select(func.count(Notification.id)).filter(
            Notification.user_id == current_user.id,
            Notification.is_read == False
        )
    )
    unread_notifications = unread_count_res.scalar() or 0

    # 6. RETURN COMPLETE DASHBOARD
    return {
        "greeting": full_greeting,
        "unread_notifications": unread_notifications,
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

    # 3. MANUALLY CONSTRUCT THE RESPONSE (map to frontend DTO)
    response_data = []
    seen_headlines = set()
    for art in articles:
        if art.headline and art.headline in seen_headlines:
            continue
        seen_headlines.add(art.headline)
        date_str = art.published_at.strftime("%d %b %Y") if art.published_at else datetime.utcnow().strftime("%d %b %Y")
        response_data.append({
            "id": str(art.id),
            "title": art.headline or "",
            "summary": art.summary or "",
            "category": art.tag or "Generative AI",
            "readTime": f"{art.read_time_minutes or 3} min read",
            "publishedTime": get_time_ago_string(art.published_at),
            "date": date_str,
            "publisher": art.publisher or "TechCrunch",
            "publishedDate": date_str,
            "originalUrl": art.original_url or None,
            "imageUrl": art.image_url or None,
            "isBookmarked": art.id in bookmarked_ids
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

    # 3. Fetch related articles & check user bookmark status for them
    related_res = await db.execute(
        select(NewsArticle)
        .filter(NewsArticle.category == article.category, NewsArticle.id != news_id)
        .limit(2)
    )
    related_articles = related_res.scalars().all()

    # Get all bookmarked IDs for current user to ensure user-scoped bookmark flags
    rel_bookmark_res = await db.execute(
        select(UserNewsInteraction.news_id).filter(
            UserNewsInteraction.user_id == current_user.id,
            UserNewsInteraction.is_bookmarked == True
        )
    )
    user_bookmarked_ids = set(rel_bookmark_res.scalars().all())

    related_cards = []
    seen_related = set()
    for rel in related_articles:
        if rel.headline and rel.headline in seen_related:
            continue
        seen_related.add(rel.headline)
        rel_date = rel.published_at.strftime("%d %b %Y") if rel.published_at else datetime.utcnow().strftime("%d %b %Y")
        related_cards.append({
            "id": str(rel.id),
            "title": rel.headline or "",
            "summary": rel.summary or "",
            "category": rel.tag or "Generative AI",
            "readTime": f"{rel.read_time_minutes or 3} min read",
            "publishedTime": get_time_ago_string(rel.published_at),
            "date": rel_date,
            "publisher": rel.publisher or "TechCrunch",
            "publishedDate": rel_date,
            "originalUrl": rel.original_url or None,
            "imageUrl": rel.image_url or None,
            "isBookmarked": rel.id in user_bookmarked_ids
        })

    # 4. Return Final Data (map to frontend article shape)
    date_str = article.published_at.strftime("%d %b %Y") if article.published_at else datetime.utcnow().strftime("%d %b %Y")
    content = article.content_blocks if article.content_blocks else None
    key_takeaways = None
    sections = None
    quote = None
    if isinstance(article.content_blocks, list):
        key_takeaways = []
        sections = []
        for b in article.content_blocks:
            if isinstance(b, dict) and b.get('type') in ('takeaway','takeaways','key_takeaways'):
                items = b.get('items') or b.get('takeaways') or []
                key_takeaways.extend(items if isinstance(items, list) else [items])
            elif isinstance(b, dict) and b.get('type') in ('section','sections'):
                sections.append(b)
            elif isinstance(b, dict) and b.get('type') == 'quote':
                quote = b.get('text')

    article_obj = {
        "id": str(article.id),
        "title": article.headline or "",
        "summary": article.summary or (content[0].get('text') if content and isinstance(content, list) and isinstance(content[0], dict) and content[0].get('text') else ""),
        "category": article.tag or "Generative AI",
        "readTime": f"{article.read_time_minutes or 3} min read",
        "publishedTime": get_time_ago_string(article.published_at),
        "date": date_str,
        "publisher": getattr(article, 'publisher', 'TechCrunch'),
        "publishedDate": date_str,
        "originalUrl": getattr(article, 'original_url', None),
        "imageUrl": article.image_url or None,
        "isBookmarked": is_bookmarked,
        "content": content,
        "keyTakeaways": key_takeaways if key_takeaways else None,
        "quote": quote,
        "sections": sections if sections else None,
        "relatedNews": related_cards
    }

    return article_obj

# 3. MARK NEWS AS READ (Updates the Daily Pulse Progress!)
@router.post("/news/{news_id}/read", response_model=ReadStatusResponse)
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
        interaction = UserNewsInteraction(
            user_id=current_user.id, 
            news_id=news_id, 
            is_read=True, 
            read_at=datetime.utcnow()
        )
        db.add(interaction)
    else:
        interaction.is_read = True
        if not interaction.read_at:
            interaction.read_at = datetime.utcnow()

    await db.flush()

    # 2. Get/Create today's DailySession and sync news_completed
    session = await get_or_create_daily_session(db, current_user.id)

    # 3. Explicitly count read articles and sync news_completed
    read_res = await db.execute(
        select(func.count(UserNewsInteraction.id)).filter(
            UserNewsInteraction.user_id == current_user.id,
            UserNewsInteraction.is_read == True
        )
    )
    total_read = read_res.scalar() or 0
    session.news_completed = min(3, max(session.news_completed, total_read))

    await db.commit()

    return {"message": "Article marked as read", "pulse_updated": True}

# 4. TOGGLE BOOKMARK
@router.post("/news/{news_id}/bookmark", response_model=BookmarkToggleResponse)
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

@router.post("/trigger-daily-pulse", response_model=TriggerPulseResponse)
async def trigger_daily_pulse(
    current_user: User = Depends(get_current_user)
):
    """
    Manually triggers the AI News & Learning generation 
    for the current user immediately.
    """
    # Import the Celery task lazily so module import doesn't initialize Celery/Redis
    from app.worker.tasks import generate_real_daily_content

    # .delay() sends it to the Celery Worker queue
    generate_real_daily_content.delay()

    return {
        "status": "processing",
        "message": "AI is fetching news and writing your lesson. Check back in 15 seconds."
    }


@router.get("/health")
async def health(
    db: AsyncSession = Depends(get_db)
):
    """Simple health endpoint for developers: returns counts and last-generated timestamps."""
    # Total articles
    total_articles_res = await db.execute(select(func.count(NewsArticle.id)))
    total_articles = int(total_articles_res.scalar() or 0)

    # Last article timestamp
    last_article_res = await db.execute(select(NewsArticle).order_by(desc(NewsArticle.published_at)).limit(1))
    last_article = last_article_res.scalars().first()
    last_article_at = last_article.published_at.isoformat() if last_article and last_article.published_at else None

    # Total daily sessions
    total_sessions_res = await db.execute(select(func.count(DailySession.id)))
    total_sessions = int(total_sessions_res.scalar() or 0)

    # Last session date
    last_session_res = await db.execute(select(DailySession).order_by(desc(DailySession.date)).limit(1))
    last_session = last_session_res.scalars().first()
    last_session_date = last_session.date.isoformat() if last_session and getattr(last_session, 'date', None) else None

    return {
        "total_articles": total_articles,
        "last_article_published_at": last_article_at,
        "total_daily_sessions": total_sessions,
        "last_daily_session_date": last_session_date
    }


# --- GET TODAY'S LESSON ---
@router.get("/daily-lesson", response_model=DailyLessonResponse)
async def get_todays_lesson(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    session = await get_or_create_daily_session(db, current_user.id)

    if not session or not session.lesson_data:
        raise HTTPException(status_code=404, detail="Today's lesson is not ready.")

    return {
        "title": session.lesson_data.get("title"),
        "content_blocks": session.lesson_data.get("content_blocks"),
        "practical_takeaway": session.lesson_data.get("practical_takeaway")
    }

# --- MARK LESSON AS COMPLETE ---
@router.post("/daily-lesson/complete", response_model=MessageResponse)
async def complete_lesson(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    session = await get_or_create_daily_session(db, current_user.id)
    session.lesson_completed = True
    await db.commit()
    return {"message": "Lesson completed! Progress updated."}

# --- GET TODAY'S QUIZ ---
@router.get("/daily-quiz")
async def get_todays_quiz(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    session = await get_or_create_daily_session(db, current_user.id)

    if not session or not session.lesson_data:
        raise HTTPException(status_code=404, detail="Today's quiz is not ready.")

    return session.lesson_data.get("quiz")
 