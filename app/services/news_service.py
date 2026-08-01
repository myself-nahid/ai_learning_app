import asyncio
import logging
import re
from typing import Optional

import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2

AI_RELEVANCE_TERMS = [
    "ai",
    "artificial intelligence",
    "generative ai",
    "llm",
    "openai",
    "chatgpt",
    "machine learning",
    "deep learning",
    "copilot",
    "model",
    "automation",
    "agent",
    "nlp",
    "computer vision",
]


def _normalize_text(value: Optional[str]) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def _is_relevant_ai_article(article: dict, query: str) -> bool:
    """Return True only for articles that meaningfully relate to AI, not just general topic words."""
    text_blob = " ".join([
        _normalize_text(article.get("title")),
        _normalize_text(article.get("description")),
        _normalize_text(article.get("content")),
        _normalize_text(article.get("source", {}).get("name")),
    ])
    if not text_blob:
        return False

    normalized_query = _normalize_text(query)
    query_terms = [term for term in normalized_query.split() if len(term) > 2]
    query_is_ai_related = any(term in normalized_query for term in ["ai", "artificial", "generative", "llm", "model", "openai", "chatgpt", "machine learning", "automation"])

    strong_ai_terms = [
        "openai",
        "chatgpt",
        "gpt",
        "llm",
        "large language model",
        "generative ai",
        "machine learning",
        "deep learning",
        "copilot",
        "computer vision",
        "nlp",
        "multimodal",
        "foundation model",
    ]
    if any(term in text_blob for term in strong_ai_terms):
        return True

    ai_terms = [term for term in AI_RELEVANCE_TERMS if term in text_blob]
    if ai_terms:
        # Accept common AI wording only when it is paired with a meaningful AI-related action
        # or the query itself is already AI-focused.
        if query_is_ai_related:
            return True
        return any(term in text_blob for term in ["model", "assistant", "automation", "platform", "tool", "workflow", "productivity", "startup", "technology"])

    if query_is_ai_related:
        return any(term in text_blob for term in query_terms)

    return False


async def fetch_raw_ai_news(query: str):
    """
    Fetches raw headlines from NewsAPI.org with robust query fallback
    """
    url = "https://newsapi.org/v2/everything"
    clean_query = query.replace('"', '').strip()
    
    # Primary search query
    params = {
        "q": f'{clean_query} AND (AI OR "artificial intelligence" OR technology OR OpenAI OR ChatGPT)',
        "sortBy": "publishedAt",
        "language": "en",
        "pageSize": 10,
        "apiKey": settings.NEWS_API_KEY
    }
    
    last_exception = None
    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, timeout=15.0)
                response.raise_for_status()
                data = response.json()

                if data.get("status") == "ok" and data.get("articles"):
                    articles = data["articles"]
                    relevant_articles = [
                        article for article in articles
                        if article.get("title") and "[Removed]" not in article.get("title")
                    ]
                    if relevant_articles:
                        logger.info("Fetched %d live news articles from NewsAPI for '%s'", len(relevant_articles), query)
                        return relevant_articles

                # Fallback to broader query if primary returned 0 articles
                params["q"] = "artificial intelligence OR OpenAI OR ChatGPT OR LLM"
                response = await client.get(url, params=params, timeout=15.0)
                data = response.json()
                if data.get("status") == "ok" and data.get("articles"):
                    articles = [a for a in data["articles"] if a.get("title") and "[Removed]" not in a.get("title")]
                    return articles
                return []
        except httpx.TimeoutException as e:
            last_exception = e
            logger.warning("NewsAPI timeout for query '%s' (attempt %d/%d)", query, attempt + 1, MAX_RETRIES)
        except httpx.HTTPStatusError as e:
            last_exception = e
            logger.warning("NewsAPI HTTP error %d for query '%s' (attempt %d/%d)", e.response.status_code, query, attempt + 1, MAX_RETRIES)
        except Exception as e:
            last_exception = e
            logger.warning("NewsAPI request failed for query '%s' (attempt %d/%d): %s", query, attempt + 1, MAX_RETRIES, str(e))

        if attempt < MAX_RETRIES - 1:
            wait_time = RETRY_DELAY_SECONDS * (attempt + 1)
            await asyncio.sleep(wait_time)

    return []


async def fetch_and_generate_live_news_for_user(db, topics: list = None, max_articles: int = 15):
    """
    Fetches real live news articles from NewsAPI and uses OpenAI to rewrite them into TodAI format.
    Stores the results directly in the database.
    """
    from datetime import datetime
    from sqlalchemy import select
    from app.db.models import NewsArticle
    from app.services.ai_service import transform_news_to_todai_format

    if not topics:
        topics = ["Generative AI", "Artificial Intelligence", "Machine Learning", "AI Tools", "Technology"]

    created_articles = []
    for topic in topics:
        if len(created_articles) >= max_articles:
            break

        raw_articles = await fetch_raw_ai_news(topic)
        for raw in raw_articles:
            if len(created_articles) >= max_articles:
                break
            
            title = raw.get("title")
            if not title or "[Removed]" in title:
                continue

            # Check duplicate in DB by headline or title
            dup_check = await db.execute(select(NewsArticle).filter(NewsArticle.headline == title))
            if dup_check.scalars().first():
                continue

            try:
                ai_news = await transform_news_to_todai_format(raw, topic)
                content_blocks = ai_news.get("content_blocks")
                if not isinstance(content_blocks, list):
                    content_blocks = [
                        {"type": "paragraph", "text": raw.get("description") or title},
                        {"type": "takeaway", "items": ai_news.get("takeaways") or ai_news.get("points") or [title]},
                        {"type": "quote", "text": raw.get("description") or title, "author": raw.get("source", {}).get("name") or "NewsAPI"}
                    ]

                image_url = raw.get("urlToImage") or "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?q=80&w=600&auto=format&fit=crop"

                new_article = NewsArticle(
                    headline=ai_news.get("headline") or title,
                    summary=ai_news.get("summary") or raw.get("description") or title,
                    tag=ai_news.get("tag") or topic,
                    category=topic,
                    content_blocks=content_blocks,
                    image_url=image_url,
                    publisher=raw.get("source", {}).get("name") or "NewsAPI",
                    original_url=raw.get("url") or "https://newsapi.org",
                    read_time_minutes=3,
                    published_at=datetime.utcnow()
                )
                db.add(new_article)
                await db.flush()
                created_articles.append(new_article)
            except Exception as e:
                logger.error("Failed to transform live article '%s' via OpenAI: %s", title, str(e))
                continue

    if created_articles:
        await db.commit()
        logger.info("Successfully created %d live AI news articles via NewsAPI & OpenAI!", len(created_articles))

    return created_articles

