import asyncio
import logging
from datetime import datetime
import random

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.worker.celery_app import celery_app
from app.db.session import SessionLocal
from app.db.models import (
    ActivityLog,
    User,
    NewsArticle,
    DailySession,
    AiTopicCurriculum,
    UserConceptProgress,
)
from app.services.news_service import fetch_raw_ai_news
from app.services.ai_service import transform_news_to_todai_format, generate_lesson_and_quiz

logger = logging.getLogger(__name__)


# ─── Helper: run async coroutines inside sync Celery workers ─────────────────

def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


# ─── Topic Selection ─────────────────────────────────────────────────────────

async def _select_next_topic(
    db,
    user_id: int,
    user_level: str,
    user_interests: list[str],
) -> AiTopicCurriculum | None:
    """
    Curriculum-driven topic selection:
    1. Find topics that match the user's level (or easier)
    2. Exclude topics already taught to this user
    3. Prefer topics whose category aligns with the user's interests
    4. Fall back to any unlearned topic if no interest match is found
    5. Fall back to random from interests if curriculum is exhausted (cycle restart)
    """
    # Level hierarchy: Beginner can receive Beginner; Intermediate gets Beginner+Intermediate; Advanced gets all
    level_order = {"Beginner": 1, "Intermediate": 2, "Advanced": 3}
    user_level_rank = level_order.get(user_level, 1)
    eligible_levels = [lvl for lvl, rank in level_order.items() if rank <= user_level_rank]

    # Get IDs already taught to this user
    taught_result = await db.execute(
        select(UserConceptProgress.topic_id).where(UserConceptProgress.user_id == user_id)
    )
    taught_ids = {row[0] for row in taught_result.fetchall()}

    # Fetch all active topics at eligible levels, in sequence order
    all_topics_result = await db.execute(
        select(AiTopicCurriculum)
        .where(
            AiTopicCurriculum.is_active == True,
            AiTopicCurriculum.level.in_(eligible_levels),
        )
        .order_by(AiTopicCurriculum.sequence_order)
    )
    all_topics = all_topics_result.scalars().all()

    if not all_topics:
        return None

    # Filter out already-taught topics
    unlearned = [t for t in all_topics if t.id not in taught_ids]

    if not unlearned:
        # Curriculum completed: restart from the beginning (infinite loop)
        logger.info("User %d has completed the full curriculum — restarting cycle.", user_id)
        unlearned = all_topics

    # Prefer topics whose category aligns with the user's stated interests
    interest_lower = [i.lower() for i in user_interests]
    preferred = [
        t for t in unlearned
        if any(kw in t.category.lower() or kw in t.title.lower() for kw in interest_lower)
    ]

    return preferred[0] if preferred else unlearned[0]


# ─── Main Daily Content Generation Task ──────────────────────────────────────

@celery_app.task(name="generate_real_daily_content")
def generate_real_daily_content():
    """Synchronous entry point for Celery."""
    return run_async(process_real_daily_pulse_for_all_users())


async def process_real_daily_pulse_for_all_users():
    """
    Curriculum-driven Daily Pulse content generation.

    For each verified user:
    1. Select the next unlearned AI topic from the curriculum (not random)
    2. Fetch real news articles related to that topic from NewsAPI
    3. Transform articles to TodAI format using improved OpenAI prompts
    4. Generate a structured 6–8 card lesson with quality scoring
    5. Save the DailySession and record concept progress
    """
    async with SessionLocal() as db:
        result = await db.execute(
            select(User).options(selectinload(User.profile)).filter(User.is_verified == True)
        )
        users = result.scalars().all()

        for user in users:
            if not user.profile:
                continue

            try:
                # ── 1. Select next curriculum topic ──────────────────────────
                topic = await _select_next_topic(
                    db=db,
                    user_id=user.id,
                    user_level=user.profile.ai_level or "Beginner",
                    user_interests=user.profile.interests or [],
                )

                if topic is None:
                    logger.warning("No active curriculum topics found. Skipping user %d.", user.id)
                    continue

                logger.info(
                    "Selected topic '%s' (level: %s) for user %d",
                    topic.title,
                    topic.level,
                    user.id,
                )

                # ── 2. Fetch news relevant to the topic's search keywords ───
                # Use the topic's keywords for a targeted NewsAPI search
                search_query = " OR ".join(topic.search_keywords[:3]) if topic.search_keywords else topic.title
                raw_articles = await fetch_raw_ai_news(search_query)

                # Fall back to interest-based search if no topic-specific articles found
                if not raw_articles:
                    fallback_interest = (
                        random.choice(user.profile.interests)
                        if user.profile.interests
                        else "Artificial Intelligence"
                    )
                    raw_articles = await fetch_raw_ai_news(fallback_interest)

                if not raw_articles:
                    logger.warning(
                        "No news articles found for topic '%s'. Skipping user %d.",
                        topic.title,
                        user.id,
                    )
                    continue

                # ── 3. Transform up to 3 articles into TodAI format ─────────
                article_batch = []
                primary_article_content = ""

                for source_article in raw_articles[:3]:
                    ai_news_data = await transform_news_to_todai_format(source_article, topic.category)
                    new_article = NewsArticle(
                        headline=ai_news_data.get("headline", source_article.get("title", "")),
                        summary=ai_news_data.get("summary", source_article.get("description", "")),
                        tag=ai_news_data.get("tag", topic.category),
                        category=topic.category,
                        content_blocks=ai_news_data.get("content_blocks", []),
                        image_url=source_article.get("urlToImage"),
                        publisher=source_article.get("source", {}).get("name"),
                        original_url=source_article.get("url"),
                        read_time_minutes=ai_news_data.get("read_time_minutes", 3),
                        published_at=datetime.utcnow(),
                    )
                    db.add(new_article)
                    await db.flush()
                    article_batch.append(new_article)

                    # Use the first article's content to ground the lesson
                    if not primary_article_content:
                        primary_article_content = (
                            source_article.get("content")
                            or source_article.get("description")
                            or ""
                        )

                if not article_batch:
                    continue

                # ── 4. Generate the lesson using the full curriculum context ─
                lesson_data = await generate_lesson_and_quiz(
                    news_headline=article_batch[0].headline,
                    news_content=primary_article_content,
                    interest=topic.category,
                    level=user.profile.ai_level or "Beginner",
                    topic_title=topic.title,
                    topic_description=topic.description,
                    learning_objectives=topic.learning_objectives or [],
                    practical_focus=None,
                )

                quality_score = lesson_data.get("quality_score", 0)

                # ── 5. Create the Daily Session ──────────────────────────────
                new_session = DailySession(
                    user_id=user.id,
                    date=datetime.utcnow(),
                    assigned_news_ids=[article.id for article in article_batch],
                    lesson_data=lesson_data,
                    news_completed=0,
                    lesson_completed=False,
                    quiz_completed=False,
                )
                db.add(new_session)
                await db.flush()

                # ── 6. Record concept progress ───────────────────────────────
                concept_progress = UserConceptProgress(
                    user_id=user.id,
                    topic_id=topic.id,
                    taught_at=datetime.utcnow(),
                    quality_score=quality_score,
                    session_id=new_session.id,
                )
                db.add(concept_progress)

                activity_log = ActivityLog(
                    user_id=user.id,
                    action_type="AI_GEN_SUCCESS",
                    description=(
                        f"Daily Pulse generated for {user.full_name} | "
                        f"Topic: '{topic.title}' | Quality: {quality_score}/100"
                    ),
                )
                db.add(activity_log)

                logger.info(
                    "✅ Daily Pulse for user %s — topic: '%s' | quality: %d/100",
                    user.email,
                    topic.title,
                    quality_score,
                )

            except Exception as e:
                logger.error(
                    "Failed to generate content for user %d: %s",
                    user.id,
                    str(e),
                    exc_info=True,
                )
                db.add(ActivityLog(
                    user_id=user.id,
                    action_type="AI_GEN_FAIL",
                    description=f"AI generation failed for {user.full_name} — {str(e)[:200]}",
                ))
                continue

        await db.commit()


# ─── Daily Reminder Task (unchanged) ─────────────────────────────────────────

from datetime import datetime
import pytz
from app.services.notification_service import send_push_notification


async def _send_user_daily_reminder(user):
    if not user.fcm_token:
        return None
    await send_push_notification(
        token=user.fcm_token,
        title="Your Daily Pulse is Ready! ⚡",
        body="Tap to complete today's 5-minute AI briefing and keep your streak alive.",
        data_payload={
            "briefing": True,
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
        result = await db.execute(
            select(User).filter(
                User.is_active == True,
                User.push_notifications == True,
                User.fcm_token.isnot(None),
            )
        )
        users = result.scalars().all()

        for user in users:
            if not user.daily_reminder_time:
                continue
            user_tz = pytz.timezone(user.timezone)
            current_time_in_user_tz = datetime.now(pytz.utc).astimezone(user_tz)
            user_reminder_time = user.daily_reminder_time

            if (
                current_time_in_user_tz.hour == user_reminder_time.hour
                and current_time_in_user_tz.minute == user_reminder_time.minute
            ):
                await _send_user_daily_reminder(user)