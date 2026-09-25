# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException
# pyrefly: ignore [missing-import]
from sqlalchemy.ext.asyncio import AsyncSession
# pyrefly: ignore [missing-import]
from sqlalchemy import select
from datetime import date
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import selectinload

from app.api.deps import get_db, get_current_user
from app.db.models import User, DailyFeed
from app.schemas.ai_content import DailyFeedResponse
from app.services.ai_service import transform_news_to_todai_format

router = APIRouter(prefix="/content", tags=["Daily Content"])

@router.get("/daily-feed", response_model=DailyFeedResponse)
async def get_or_create_daily_feed(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    LEGACY endpoint — deprecated.

    Content sources are now strictly separated:
      - News Feed    → generated from news sources (NewsAPI pipeline).
      - Learning Feed → served from the predefined Excel curriculum
        (LearningPath/Lesson tables, source_type="curriculum"), managed
        via the admin dashboard.

    Learning content must never be generated from news articles, so this
    endpoint no longer creates AI-generated lessons. Clients should use
    /learn/dashboard + /learn/lessons/{id} for the Learning Feed and
    /home/dashboard for the News Feed.
    """
    raise HTTPException(
        status_code=410,
        detail=(
            "This endpoint is deprecated. The Learning Feed is served from the "
            "predefined curriculum — use /learn/dashboard and /learn/lessons/{id}. "
            "News content is available via /home/dashboard."
        ),
    )