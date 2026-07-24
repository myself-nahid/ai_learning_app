import asyncio
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from datetime import datetime

# Import instances
from app.worker.celery_app import celery_app
from app.db.session import SessionLocal
from app.db.models import User, NewsArticle, DailySession

# Import services
from app.services.news_service import fetch_raw_ai_news
from app.services.ai_service import transform_news_to_todai_format, generate_lesson_and_quiz

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
                # 2. Fetch Real News from NewsAPI based on User Interest
                # (e.g., query = "AI in Finance & Banking")
                raw_articles = await fetch_raw_ai_news(user.profile.primary_interest)
                
                if not raw_articles or len(raw_articles) < 1:
                    print(f"No news found for {user.profile.primary_interest}")
                    continue
                
                # 3. Transform the raw news into the TodAI Editorial Format (JSON)
                # We process the top article for the structured "Main Story"
                ai_news_data = await transform_news_to_todai_format(
                    raw_articles[0], 
                    user.profile.primary_interest
                )
                
                # 4. Generate Microlearning Lesson & Quiz based on this Headline
                # This ensures the "Lesson" and "Quiz" buttons in your UI are relevant to the news.
                study_material = await generate_lesson_and_quiz(
                    news_headline=ai_news_data['headline'],
                    interest=user.profile.primary_interest,
                    level=user.profile.ai_level
                )

                # 5. Save the transformed news to the database
                new_article = NewsArticle(
                    headline=ai_news_data['headline'],
                    summary=ai_news_data['summary'],
                    tag=ai_news_data['tag'],
                    category=user.profile.primary_interest,
                    content_blocks=ai_news_data['content_blocks'],
                    image_url=raw_articles[0].get('urlToImage'),
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
                
                print(f"Successfully generated Daily Pulse for User: {user.email}")

            except Exception as e:
                print(f"Failed to generate content for user {user.id}: {str(e)}")
                continue # Move to next user if one fails
        
        # Commit all changes to the database
        await db.commit()

from datetime import datetime
import pytz # Need 'pytz' in requirements.txt for timezone math
from app.services.notification_service import send_push_notification

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
                await send_push_notification(
                    fcm_token=user.fcm_token,
                    title="Your Daily Pulse is Ready! ⚡",
                    body="Tap to complete today's 5-minute AI briefing and keep your streak alive.",
                    data_payload={
                        # The mobile app intercepts this 'screen' variable 
                        # and opens the Daily Briefing Sequence instantly.
                        "screen": "daily_briefing_sequence", 
                        "action": "start"
                    }
                )