import asyncio
import json
import logging
from typing import Optional

from openai import AsyncOpenAI
from app.core.config import settings

logger = logging.getLogger(__name__)

# Retry configuration
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2

client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# Minimum quality thresholds
MIN_CARDS = 4           # A lesson must have at least 4 cards
MIN_QUIZ_QUESTIONS = 2  # Must include at least 2 quiz questions
MIN_CARD_TEXT_LEN = 40  # Each card body must be at least 40 characters
QUALITY_PASS_SCORE = 60 # 0–100 — below this triggers a regeneration attempt


async def _call_openai_with_retry(
    prompt: str,
    system_prompt: str = "You output strict, valid JSON only. No markdown fences.",
    max_retries: int = MAX_RETRIES,
) -> dict:
    """Call OpenAI API with exponential backoff retry logic."""
    last_exception = None
    for attempt in range(max_retries):
        try:
            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
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
                await asyncio.sleep(wait_time)

    if last_exception:
        raise last_exception
    raise RuntimeError(f"OpenAI API call failed after {max_retries} attempts.")


def score_content_quality(lesson_data: dict) -> int:
    """
    Evaluate generated lesson content quality on a 0–100 scale.

    Scoring criteria:
    - Card count (≥4 required, ≥6 ideal): 0–30 pts
    - Quiz presence (≥2 questions required): 0–20 pts
    - Card body text length (avg ≥80 chars ideal): 0–25 pts
    - Learning objectives present: 0–15 pts
    - Practical takeaway present: 0–10 pts
    """
    score = 0
    cards = lesson_data.get("cards", [])
    card_count = len(cards)

    # Card count score (0–30)
    if card_count >= 6:
        score += 30
    elif card_count >= 4:
        score += 20
    elif card_count >= 2:
        score += 10

    # Quiz presence score (0–20)
    quiz_cards = [c for c in cards if c.get("type") == "quiz"]
    if len(quiz_cards) >= 3:
        score += 20
    elif len(quiz_cards) >= 2:
        score += 15
    elif len(quiz_cards) == 1:
        score += 8

    # Card body text length (0–25)
    content_cards = [c for c in cards if c.get("type") != "quiz"]
    if content_cards:
        avg_text_len = sum(
            len(c.get("text", "") or c.get("bodyText", ""))
            for c in content_cards
        ) / len(content_cards)
        if avg_text_len >= 120:
            score += 25
        elif avg_text_len >= 80:
            score += 18
        elif avg_text_len >= 40:
            score += 10

    # Learning objectives (0–15)
    if lesson_data.get("learning_objectives") and len(lesson_data["learning_objectives"]) >= 2:
        score += 15
    elif lesson_data.get("learning_objectives"):
        score += 7

    # Practical takeaway (0–10)
    if lesson_data.get("practical_takeaway") and len(str(lesson_data["practical_takeaway"])) >= 30:
        score += 10

    return min(score, 100)


async def transform_news_to_todai_format(raw_article: dict, category: str) -> dict:
    """
    Uses OpenAI to rewrite a raw news article into the TodAI format
    matching frontend types in index.ts.
    """
    title = raw_article.get("title", "")
    description = raw_article.get("description", "")
    content = raw_article.get("content", "") or description
    source_name = raw_article.get("source", {}).get("name", "TechCrunch")

    system_prompt = (
        "You are a senior AI news editor for TodAI — an educational AI literacy app. "
        "Your job is to transform raw news into clear, accurate, engaging articles that help "
        "everyday users understand AI developments. Always be factually accurate and educational."
    )

    prompt = f"""
Transform this raw news article into TodAI's structured editorial format.

Raw Article Title: {title}
Raw Description: {description}
Full Content: {content[:1500]}
Publisher: {source_name}
Category Context: {category}

Return a JSON object with EXACTLY these keys:
1. "headline": Engaging, clear title (max 90 chars). No clickbait.
2. "title": Same as headline.
3. "summary": 2-sentence plain-English summary of what happened and why it matters.
4. "category": One of ["Generative AI", "AI Tools", "Research", "Business", "Science", "General AI"].
5. "tag": Short specific tag (e.g. "LLMs", "Robotics", "AI Safety", "Startups").
6. "read_time_minutes": Integer (2–6 based on content depth).
7. "key_takeaways": Array of exactly 3 clear, specific insight strings.
8. "quote": Object with {{"text": "memorable quote or key statement", "author": "{source_name}"}}.
9. "sections": Array of 2–3 section objects: {{"title": "...", "content": "paragraph text..."}}.
10. "content_blocks": Array of block objects:
    - {{"type": "paragraph", "text": "Detailed 2–3 sentence paragraph..."}}
    - {{"type": "takeaway", "items": ["insight 1", "insight 2", "insight 3"]}}
    - {{"type": "quote", "text": "...", "author": "{source_name}"}}
    - {{"type": "section", "title": "...", "content": "..."}}
    Include at least 3 blocks total.
"""

    return await _call_openai_with_retry(prompt, system_prompt=system_prompt)


async def generate_lesson_and_quiz(
    news_headline: str,
    news_content: str,
    interest: str,
    level: str,
    topic_title: str,
    topic_description: str,
    learning_objectives: list[str],
    practical_focus: Optional[str] = None,
    max_quality_attempts: int = 2,
) -> dict:
    """
    Generates a structured microlearning lesson with quiz cards based on
    a curated AI topic from the curriculum and the day's relevant news.

    Returns a dict with:
    - title, estimated_minutes, learning_objectives, practical_takeaway
    - cards: list of card dicts (intro, concept, example, comparison, list, steps, quiz types)
    - quality_score: 0–100
    """
    system_prompt = (
        "You are an expert instructional designer and AI educator creating microlearning content "
        "for TodAI — an app that teaches people AI concepts in 5-minute daily sessions. "
        "Your content must be clear, accurate, engaging, and immediately practical. "
        "Always ground explanations in real-world examples. Output strict JSON only."
    )

    objectives_text = "\n".join(f"  - {o}" for o in learning_objectives)
    focus_note = f"\nPractical angle: {practical_focus}" if practical_focus else ""

    prompt = f"""
Create a complete microlearning lesson for TodAI.

TOPIC: {topic_title}
TOPIC DESCRIPTION: {topic_description}
USER LEVEL: {level}
DOMAIN INTEREST: {interest}
TODAY'S RELEVANT NEWS: {news_headline}
NEWS CONTEXT: {news_content[:800] if news_content else "No additional context."}
{focus_note}

LEARNING OBJECTIVES (the user must understand these after completing the lesson):
{objectives_text}

REQUIREMENTS:
- Generate 6–8 cards total
- Last 2 cards MUST be quiz cards
- Cards must flow logically: introduce concept → explain → example → compare/list → quiz
- Each content card must have ≥80 words of body text
- Quiz questions must test real understanding, not just recall
- Adapt vocabulary and depth for a {level}-level learner

Return a JSON object with EXACTLY these keys:

{{
  "title": "Engaging lesson title (max 70 chars)",
  "estimated_minutes": 5,
  "practical_takeaway": "One specific action or insight the user can apply today (2–3 sentences)",
  "learning_objectives": ["objective 1", "objective 2", "objective 3"],
  "cards": [
    {{
      "type": "intro",
      "heading": "Card heading",
      "text": "Card body text (≥80 words). Introduce the concept clearly."
    }},
    {{
      "type": "concept",
      "heading": "Core Concept",
      "text": "Deeper explanation (≥80 words). Use plain language and analogies."
    }},
    {{
      "type": "example",
      "heading": "Real-World Example",
      "text": "Brief setup text",
      "exampleData": {{
        "promptPrefix": "Context sentence showing how this works:",
        "predictionWord": "KEY TERM",
        "noteText": "Explanation of the example (2–3 sentences)"
      }}
    }},
    {{
      "type": "list",
      "heading": "Key Points",
      "text": "Overview sentence",
      "listData": [
        {{"icon": "🧠", "text": "Point 1 explained clearly"}},
        {{"icon": "⚡", "text": "Point 2 explained clearly"}},
        {{"icon": "🔍", "text": "Point 3 explained clearly"}}
      ]
    }},
    {{
      "type": "quiz",
      "heading": "Knowledge Check",
      "quizData": {{
        "question": "Clear, specific question testing understanding",
        "options": [
          {{"id": "A", "label": "A", "text": "Option A text"}},
          {{"id": "B", "label": "B", "text": "Option B text"}},
          {{"id": "C", "label": "C", "text": "Option C text"}},
          {{"id": "D", "label": "D", "text": "Option D text"}}
        ],
        "correct_answer": "B",
        "explanation": "Why this is correct (1–2 sentences)"
      }}
    }},
    {{
      "type": "quiz",
      "heading": "Final Check",
      "quizData": {{
        "question": "Another question testing a different objective",
        "options": [
          {{"id": "A", "label": "A", "text": "Option A text"}},
          {{"id": "B", "label": "B", "text": "Option B text"}},
          {{"id": "C", "label": "C", "text": "Option C text"}},
          {{"id": "D", "label": "D", "text": "Option D text"}}
        ],
        "correct_answer": "C",
        "explanation": "Why this is correct (1–2 sentences)"
      }}
    }}
  ]
}}

You may add additional cards between the example/list and the quiz cards if needed.
The quiz cards must always be the LAST cards in the array.
"""

    best_result = None
    best_score = 0

    for attempt in range(max_quality_attempts):
        try:
            result = await _call_openai_with_retry(prompt, system_prompt=system_prompt)
            quality_score = score_content_quality(result)
            result["quality_score"] = quality_score

            logger.info(
                "Lesson generation attempt %d/%d — quality score: %d/100 (topic: %s)",
                attempt + 1,
                max_quality_attempts,
                quality_score,
                topic_title,
            )

            if quality_score >= QUALITY_PASS_SCORE:
                return result

            # Keep best result seen so far
            if quality_score > best_score:
                best_score = quality_score
                best_result = result

        except Exception as e:
            logger.error("Lesson generation attempt %d failed: %s", attempt + 1, str(e))
            if attempt == max_quality_attempts - 1:
                raise

    # Return best available result even if below threshold
    if best_result:
        logger.warning(
            "Returning below-threshold lesson (score: %d) for topic: %s",
            best_score,
            topic_title,
        )
        return best_result

    raise RuntimeError(f"Failed to generate acceptable lesson for topic: {topic_title}")