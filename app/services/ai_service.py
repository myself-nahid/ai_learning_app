from openai import AsyncOpenAI
from app.core.config import settings
from app.schemas.home import NewsDetailResponse 
import json

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

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

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": "You output strict JSON."},
                  {"role": "user", "content": prompt}],
        response_format={ "type": "json_object" }
    )
    
    ai_data = json.loads(response.choices[0].message.content)
    return ai_data

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

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": "You output strict JSON."},
                  {"role": "user", "content": prompt}],
        response_format={ "type": "json_object" }
    )
    return json.loads(response.choices[0].message.content)