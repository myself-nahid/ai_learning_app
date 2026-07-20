import asyncio
from app.worker.celery_app import celery_app
from app.db.session import SessionLocal
from app.db.models import User, DailyFeed
from app.services.ai_service import generate_daily_learning_content
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from datetime import date

# This helper allows us to run our async FastAPI logic inside sync Celery
def run_async(coro):
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(coro)

@celery_app.task(name="generate_all_users_feed")
def generate_all_users_feed():
    return run_async(process_feeds())

async def process_feeds():
    async with SessionLocal() as db:
        # 1. Get all verified users with profiles
        result = await db.execute(
            select(User).options(selectinload(User.profile)).filter(User.is_verified == True)
        )
        users = result.scalars().all()
        
        today = date.today()
        
        for user in users:
            if not user.profile:
                continue
                
            # 2. Check if feed exists (to avoid double billing OpenAI)
            feed_check = await db.execute(
                select(DailyFeed).filter(DailyFeed.user_id == user.id, DailyFeed.date == today)
            )
            if feed_check.scalars().first():
                continue
                
            # 3. Generate and Save
            try:
                ai_content = await generate_daily_learning_content(
                    interests=user.profile.interests,
                    difficulty=user.profile.difficulty_level
                )
                
                new_feed = DailyFeed(
                    user_id=user.id,
                    date=today,
                    news_summary=ai_content.news_summary,
                    lesson=ai_content.lesson,
                    quiz_data=[q.model_dump() for q in ai_content.quiz]
                )
                db.add(new_feed)
            except Exception as e:
                print(f"Error generating for user {user.id}: {e}")
                
        await db.commit()