import httpx
from app.core.config import settings

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
    
    async with httpx.AsyncClient() as client:
        response = await client.get(url, params=params)
        data = response.json()
        
        if data.get("status") == "ok" and data.get("articles"):
            return data["articles"]
        return []