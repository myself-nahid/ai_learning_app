import asyncio
import json
import logging

from openai import AsyncOpenAI
from app.core.config import settings

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2  # Initial delay, will be multiplied by retry count

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)


async def _call_openai_with_retry(prompt: str, max_retries: int = MAX_RETRIES):
    """Call OpenAI API with exponential backoff retry logic."""
    last_exception = None
    for attempt in range(max_retries):
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You output strict JSON."},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            last_exception = e
            logger.warning(
                "OpenAI API call failed (attempt %d/%d): %s",
                attempt + 1,
                max_retries,
                str(e),
            )
            if attempt < max_retries - 1:
                wait_time = RETRY_DELAY_SECONDS * (attempt + 1)
                logger.info("Retrying in %d seconds...", wait_time)
                await asyncio.sleep(wait_time)

    logger.error(
        "OpenAI API call failed after %d attempts: %s",
        max_retries,
        str(last_exception),
    )
    raise last_exception


async def transform_news_to_todai_format(raw_article: dict, category: str):
    """
    Uses OpenAI to rewrite a raw news article into the TodAI format.
    """
    prompt = f"""
    You are a professional AI news editor for the app 'TodAI'. 
    Rewrite the following raw news article into a structured, editorial format.
    
    Raw Article Title: {raw_article['title']}
    Raw Article Description: {raw_article['description']}
    
    Return a JSON object with:
    1. 'headline': A catchy title.
    2. 'summary': A 2-sentence intro.
    3. 'tag': A specific tag (e.g., 'Generative AI', 'Robotics').
    4. 'content_blocks': An array of objects. Blocks should include:
       - 'paragraph' type
       - 'takeaways' type (3 key points)
       - 'quote' type (if relevant)
    """

    return await _call_openai_with_retry(prompt)

async def generate_lesson_and_quiz(news_headline: str, interest: str, level: str):
    """
    Generates a microlearning lesson and a quiz based on the news.
    """
    prompt = f"""
    You are an expert AI tutor for 'TodAI'. 
    Create a microlearning lesson based on this news: '{news_headline}'.
    Target Audience: {interest} professional at a {level} level.

    Return a JSON object:
    1. 'title': Catchy lesson title.
    2. 'content_blocks': 3 paragraphs explaining the concept.
    3. 'practical_takeaway': One actionable insight for their career.
    4. 'quiz': A list of 3 questions. Each question has:
       - 'question_text'
       - 'options' (list of 4 strings)
       - 'correct_option' (the exact string)
       - 'explanation' (why it's correct)
    """

    return await _call_openai_with_retry(prompt)