from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import date
from sqlalchemy.orm import selectinload

from app.api.deps import get_db, get_current_user
from app.db.models import User, DailyFeed
from app.schemas.ai_content import DailyFeedResponse
from app.services.ai_service import generate_daily_learning_content

router = APIRouter(prefix="/content", tags=["Daily Content"])

@router.get("/daily-feed", response_model=DailyFeedResponse)
async def get_or_create_daily_feed(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # 1. Ensure the user has completed onboarding
    result = await db.execute(
        select(User).options(selectinload(User.profile)).filter(User.id == current_user.id)
    )
    user = result.scalars().first()
    
    if not user.profile:
        raise HTTPException(status_code=400, detail="Please complete onboarding first.")

    today = date.today()

    # 2. Check if we already generated content for them today
    feed_result = await db.execute(
        select(DailyFeed).filter(DailyFeed.user_id == user.id, DailyFeed.date == today)
    )
    existing_feed = feed_result.scalars().first()

    if existing_feed:
        # Convert date to string for Pydantic response
        existing_feed.date = str(existing_feed.date) 
        return existing_feed

    # 3. If no feed exists for today, GENERATE IT (Takes 5-15 seconds)
    try:
        ai_content = await generate_daily_learning_content(
            interests=user.profile.interests,
            difficulty=user.profile.difficulty_level
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate AI content: {str(e)}")

    # 4. Save the generated content to the database
    new_feed = DailyFeed(
        user_id=user.id,
        date=today,
        news_summary=ai_content.news_summary,
        lesson=ai_content.lesson,
        quiz_data=[q.model_dump() for q in ai_content.quiz] # Convert Pydantic list to JSON
    )
    
    db.add(new_feed)
    await db.commit()
    await db.refresh(new_feed)

    new_feed.date = str(new_feed.date)
    return new_feed