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

    if last_exception:
        raise last_exception
    raise RuntimeError(f"OpenAI API call failed after {max_retries} attempts.")



async def transform_news_to_todai_format(raw_article: dict, category: str):
    """
    Uses OpenAI to rewrite a raw news article into the TodAI format matching frontend types in index.ts.
    """
    title = raw_article.get("title", "")
    description = raw_article.get("description", "")
    source_name = raw_article.get("source", {}).get("name", "TechCrunch")

    prompt = f"""
    You are a professional AI news editor for the app 'TodAI'. 
    Rewrite the following raw news article into a structured, editorial format matching the app's exact JSON schema.
    
    Raw Article Title: {title}
    Raw Article Description: {description}
    Source Publisher: {source_name}
    Target Category Context: {category}
    
    Return a JSON object with EXACTLY the following keys:
    1. 'headline': Catchy, engaging title string.
    2. 'title': Same as headline string.
    3. 'summary': Clear 2-sentence summary string.
    4. 'category': Pick the best matching category string from ['Generative AI', 'AI Tools', 'Research', 'Business', 'Science', 'General AI'].
    5. 'tag': Specific short tag string (e.g. 'Generative AI', 'AI Tools', 'Research', 'Business', 'Science', 'Robotics', 'Finance', 'Strategy').
    6. 'read_time_minutes': Estimated reading time integer (e.g. 3 or 4).
    7. 'key_takeaways': An array of 3 bullet point strings summarizing the key insights.
    8. 'quote': An object with '{{"text": "Key quote from article", "author": "{source_name}"}}'.
    9. 'sections': An array of section objects, each with '{{"title": "Section Title", "content": "Section paragraph content..."}}'.
    10. 'content_blocks': An array of block objects representing the article body:
        - {{"type": "paragraph", "text": "Detailed paragraph text..."}}
        - {{"type": "takeaway", "items": ["Key takeaway 1", "Key takeaway 2", "Key takeaway 3"]}}
        - {{"type": "quote", "text": "Memorable quote...", "author": "{source_name}"}}
        - {{"type": "section", "title": "Section Title", "content": "Detailed section text..."}}
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