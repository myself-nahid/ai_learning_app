import asyncio
import logging

import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2


async def fetch_raw_ai_news(query: str):
    """
    Fetches raw headlines from NewsAPI.org
    """
    url = "https://newsapi.org/v2/everything"
    params = {
        "q": f"AI {query}", # e.g., "AI Finance"
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
                    logger.info(
                        "Fetched %d news articles for query '%s'",
                        len(data["articles"]),
                        query,
                    )
                    return data["articles"]
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