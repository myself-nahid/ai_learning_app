from openai import AsyncOpenAI
from app.core.config import settings
from app.schemas.ai_content import DailyContent
from typing import List

# Initialize Async OpenAI Client
client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

async def generate_daily_learning_content(interests: List[str], difficulty: str) -> DailyContent:
    """
    Calls OpenAI to generate the daily news, lesson, and quiz using Structured Outputs.
    """
    
    # In a real app, you would fetch real news from an API like NewsAPI here.
    # For now, we instruct the AI to use its latest knowledge.
    prompt = f"""
    You are an expert AI tutor and news curator. 
    The user is interested in these topics: {', '.join(interests)}.
    Their learning difficulty level is: {difficulty}.
    
    Please generate today's daily feed for this user containing:
    1. A brief summary of recent trends or news in those topics.
    2. A microlearning lesson expanding on one of the concepts mentioned in the news.
    3. A 3-question interactive quiz to test their knowledge on the lesson.
    """

    # Using gpt-4o-mini for speed and cost-effectiveness
    response = await client.beta.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a helpful AI tutor. You must strictly output the requested JSON format."},
            {"role": "user", "content": prompt}
        ],
        response_format=DailyContent, # This forces the exact JSON structure!
    )
    
    # Return the perfectly formatted Pydantic object
    return response.choices[0].message.parsed