import asyncio
import logging
from datetime import datetime
import random

from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.worker.celery_app import celery_app
from app.db.session import SessionLocal
from app.db.models import ActivityLog, User, NewsArticle, DailySession
from app.services.news_service import fetch_raw_ai_news
from app.services.ai_service import transform_news_to_todai_format, generate_lesson_and_quiz

logger = logging.getLogger(__name__)

# HELPER: To run async functions inside synchronous Celery workers
def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

@celery_app.task(name="generate_real_daily_content")
def generate_real_daily_content():
    """
    Synchronous entry point for Celery.
    """
    return run_async(process_real_daily_pulse_for_all_users())

async def process_real_daily_pulse_for_all_users():
    """
    The main logic to generate News, Lessons, and Quizzes for every onboarded user.
    """
    async with SessionLocal() as db:
        # 1. Fetch all users who have completed onboarding
        result = await db.execute(
            select(User).options(selectinload(User.profile)).filter(User.is_verified == True)
        )
        users = result.scalars().all()

        for user in users:
            if not user.profile:
                continue
            
            try:
                # 1. Pick a focus for today's news from their list of interests
                daily_focus = random.choice(user.profile.interests)
                
                # 2. Fetch Real News based on that specific focus
                raw_articles = await fetch_raw_ai_news(daily_focus)
                
                if not raw_articles or len(raw_articles) < 1:
                    continue
                
                # 3. Transform the raw news
                ai_news_data = await transform_news_to_todai_format(
                    raw_articles[0], 
                    daily_focus
                )
                
                # 4. Generate Lesson & Quiz
                study_material = await generate_lesson_and_quiz(
                    news_headline=ai_news_data['headline'],
                    interest=daily_focus,
                    level=user.profile.ai_level
                )

                # 5. Save to database using the chosen focus category
                source_article = raw_articles[0]
                new_article = NewsArticle(
                    headline=ai_news_data['headline'],
                    summary=ai_news_data['summary'],
                    tag=ai_news_data['tag'],
                    category=daily_focus,
                    content_blocks=ai_news_data['content_blocks'],
                    image_url=source_article.get('urlToImage'),
                    publisher=source_article.get('source', {}).get('name'),
                    original_url=source_article.get('url'),
                    published_at=datetime.utcnow()
                )
                db.add(new_article)
                await db.flush() # Secure the article ID

                # 6. Create the Daily Session (The "Daily Pulse")
                # This record is what the Home Dashboard reads to show progress (0/5 activities)
                new_session = DailySession(
                    user_id=user.id,
                    date=datetime.utcnow(),
                    assigned_news_ids=[new_article.id], # In prod, you'd add more IDs here
                    lesson_data=study_material, # Contains: title, content, takeaway, and quiz questions
                    news_completed=0,
                    lesson_completed=False,
                    quiz_completed=False
                )
                db.add(new_session)
                
                success_log = ActivityLog(
                    user_id=user.id,
                    action_type="AI_GEN_SUCCESS",
                    description=f"AI content generated for {user.full_name}"
                )
                db.add(success_log)
                
                logger.info(
                    "Successfully generated Daily Pulse for User: %s",
                    user.email,
                )

            except Exception as e:
                logger.error(
                    "Failed to generate content for user %d: %s",
                    user.id,
                    str(e),
                    exc_info=True,
                )

                error_log = ActivityLog(
                    user_id=user.id,
                    action_type="AI_GEN_FAIL",
                    description=f"AI generation failed for {user.full_name} — check logs"
                )
                db.add(error_log)
                continue 
        
        # Commit all changes (news, sessions, and logs) to the database
        await db.commit()

from datetime import datetime
import pytz # Need 'pytz' in requirements.txt for timezone math
from app.services.notification_service import send_push_notification


async def _send_user_daily_reminder(user):
    if not user.fcm_token:
        return None

    await send_push_notification(
        token=user.fcm_token,
        title="Your Daily Pulse is Ready! ⚡",
        body="Tap to complete today's 5-minute AI briefing and keep your streak alive.",
        data_payload={
            "screen": "daily_briefing_sequence",
            "action": "start",
        },
    )
    return None


@celery_app.task(name="process_daily_reminders")
def process_daily_reminders():
    return run_async(send_reminders_async())

async def send_reminders_async():
    async with SessionLocal() as db:
        # 1. Get all active users who want notifications and have a token
        result = await db.execute(
            select(User).filter(
                User.is_active == True,
                User.push_notifications == True,
                User.fcm_token.isnot(None)
            )
        )
        users = result.scalars().all()

        for user in users:
            if not user.daily_reminder_time:
                continue

            # 2. Convert current UTC time to the User's specific Timezone
            user_tz = pytz.timezone(user.timezone)
            current_time_in_user_tz = datetime.now(pytz.utc).astimezone(user_tz)
            
            # 3. Check if current hour and minute match their setting
            user_reminder_time = user.daily_reminder_time
            
            if (current_time_in_user_tz.hour == user_reminder_time.hour and 
                current_time_in_user_tz.minute == user_reminder_time.minute):
                
                # 4. SEND THE NOTIFICATION!
                await _send_user_daily_reminder(user)