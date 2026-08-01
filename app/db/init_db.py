import logging
# pyrefly: ignore [missing-import]
from sqlalchemy import text
# pyrefly: ignore [missing-import]
from sqlalchemy import select
from app.db.session import SessionLocal, engine
from app.db.models import LearningPath, Lesson, QuizSet, QuizQuestion, NewsArticle


logger = logging.getLogger(__name__)


async def ensure_news_article_columns():
    """Ensure the news_articles table has publisher and original_url columns."""
    logger.info("Ensuring news_articles publisher/original_url columns exist.")
    async with engine.begin() as conn:
        await conn.execute(text(
            "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS publisher VARCHAR"
        ))
        await conn.execute(text(
            "ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS original_url VARCHAR"
        ))
    logger.info("news_articles schema check complete.")


async def init_db():
    """
    Run schema migrations only.

    All LearningPath, Lesson, QuizSet and QuizQuestion rows are created
    dynamically by the /learn/dashboard and /quiz-tab/dashboard endpoints
    from live NewsArticle records (fetched via NewsAPI + generated via OpenAI).
    No static dummy data is seeded here.
    """
    await ensure_news_article_columns()
    logger.info("Database initialization check complete.")
