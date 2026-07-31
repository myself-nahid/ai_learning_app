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
    Fetches raw headlines from NewsAPI.org
    """
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": f'"{query}" AND (AI OR "artificial intelligence" OR "generative AI" OR "machine learning" OR "deep learning" OR OpenAI OR ChatGPT OR LLM OR "large language model")',
        "sortBy": "publishedAt",
        "language": "en",
        "pageSize": 5, # We only need the top 5 to select the best 1
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
                    relevant_articles = [
                        article for article in data["articles"]
                        if _is_relevant_ai_article(article, query)
                    ]
                    logger.info(
                        "Fetched %d news articles for query '%s' (%d relevant)",
                        len(data["articles"]),
                        query,
                        len(relevant_articles),
                    )
                    return relevant_articles
                return []
        except httpx.TimeoutException as e:
            last_exception = e
            logger.warning(
                "NewsAPI timeout for query '%s' (attempt %d/%d)",
                query,
                attempt + 1,
                MAX_RETRIES,
            )
        except httpx.HTTPStatusError as e:
            last_exception = e
            logger.warning(
                "NewsAPI HTTP error %d for query '%s' (attempt %d/%d)",
                e.response.status_code,
                query,
                attempt + 1,
                MAX_RETRIES,
            )
        except Exception as e:
            last_exception = e
            logger.warning(
                "NewsAPI request failed for query '%s' (attempt %d/%d): %s",
                query,
                attempt + 1,
                MAX_RETRIES,
                str(e),
            )

        if attempt < MAX_RETRIES - 1:
            wait_time = RETRY_DELAY_SECONDS * (attempt + 1)
            await asyncio.sleep(wait_time)

    logger.error(
        "NewsAPI request failed after %d attempts for query '%s': %s",
        MAX_RETRIES,
        query,
        str(last_exception),
    )
    return []