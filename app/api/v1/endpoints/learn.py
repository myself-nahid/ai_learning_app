# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Depends, HTTPException
# pyrefly: ignore [missing-import]
from sqlalchemy.ext.asyncio import AsyncSession
# pyrefly: ignore [missing-import]
from sqlalchemy import select
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta, date
import math
import json
import random
from typing import Any, Dict, List, Optional

from app.api.deps import get_db, get_current_user
from app.db.models import User, LearningPath, Lesson, UserLessonProgress, WeeklyActivity, NewsArticle
from app.services.session_service import get_or_create_daily_session
from app.schemas.learn import (
    LearnDashboardResponse, PathDetailResponse, LessonContentResponse
)
from app.schemas.response import (
    LessonCompleteRequest,
    LessonCompleteResponse,
    MessageResponse,
    ProgressSaveResponse,
)

router = APIRouter(prefix="/learn", tags=["Learn Section"])


def _shorten_title(title: Optional[str], max_length: int = 60) -> str:
    if not title:
        return "Today's topic"
    cleaned = " ".join(title.split())
    if len(cleaned) <= max_length:
        return cleaned
    return cleaned[: max_length - 3].rstrip() + "..."


def _normalize_topic_label(topic: Optional[str]) -> str:
    if not topic:
        return "Featured News"
    cleaned = " ".join(topic.strip().split())
    if not cleaned:
        return "Featured News"
    return cleaned.title() if cleaned.islower() else cleaned


def _extract_lesson_cards_data(lesson: Optional[Any]) -> List[Any]:
    """Safely read lesson cards from the ORM model without crashing on expired attributes."""
    if not lesson:
        return []

    try:
        cards_data = getattr(lesson, "cards_data", None)
    except Exception:
        cards_data = None

    if cards_data is None:
        try:
            cards_data = lesson.__dict__.get("cards_data")
        except Exception:
            cards_data = None

    if not cards_data:
        return []
    if isinstance(cards_data, list):
        return cards_data
    if isinstance(cards_data, str):
        try:
            parsed = json.loads(cards_data)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _build_shuffled_quiz_data(
    question: str,
    correct_text: str,
    distractors: List[str],
    seed: str = ""
) -> Dict[str, Any]:
    """
    Shuffles correct_text together with distractors, assigns labels A, B, C, D,
    and dynamically sets correctOptionId to whichever label holds correct_text.
    """
    all_texts = [correct_text] + distractors[:3]
    rnd = random.Random(hash(f"{seed}_{question}")) if seed else random.Random()
    rnd.shuffle(all_texts)

    labels = ["A", "B", "C", "D"]
    options = []
    correct_option_id = "A"

    for i, text in enumerate(all_texts):
        lbl = labels[i]
        options.append({"id": lbl, "label": lbl, "text": text})
        if text == correct_text:
            correct_option_id = lbl

    return {
        "question": question,
        "options": options,
        "correctOptionId": correct_option_id,
    }


def _build_multi_lessons_from_article(article: "NewsArticle") -> List[Dict[str, Any]]:
    """
    Build structured lessons dynamically per NewsArticle (between 1 and 7 lessons)
    based on the article's depth, paragraph count, takeaways, and quote data.
    Cards count dynamically adapt per lesson and quizzes are dynamically shuffled.
    """
    headline = (article.headline or article.title or "").strip()
    summary = (article.summary or "").strip()
    topic_label = _normalize_topic_label(article.category or article.tag or headline)
    image_url = article.image_url or "https://images.unsplash.com/photo-1485827404703-89b55fcc595e?q=80&w=300&auto=format&fit=crop"
    content_blocks = article.content_blocks or []
    art_id = str(article.id or headline)

    paragraphs: List[str] = []
    takeaways: List[str] = []
    quote_text: Optional[str] = None

    for block in content_blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type", "")
        bcontent = block.get("content") or block.get("text") or block.get("paragraph") or ""

        if btype == "paragraph" and bcontent:
            paragraphs.append(str(bcontent).strip())
        elif btype == "takeaways":
            items = bcontent if isinstance(bcontent, list) else []
            takeaways.extend([str(i).strip() for i in items if i])
        elif btype == "quote" and bcontent:
            if not quote_text:
                quote_text = str(bcontent).strip()

    short_headline = _shorten_title(headline, 50)

    # Calculate dynamic target lesson count (strictly between 1 and 7)
    total_text_length = len(summary) + sum(len(p) for p in paragraphs)
    score = len(paragraphs) + (len(takeaways) // 2) + (1 if quote_text else 0) + (total_text_length // 350)

    if score <= 1:
        target_count = 2 if total_text_length > 150 else 1
    elif score <= 3:
        target_count = 3
    elif score <= 5:
        target_count = 4
    elif score <= 7:
        target_count = 5
    elif score <= 9:
        target_count = 6
    else:
        target_count = 7

    target_count = max(1, min(7, target_count))

    lessons: List[Dict[str, Any]] = []

    # Blueprint 1: Overview & Fundamentals
    l1_cards: List[Dict[str, Any]] = [
        {
            "cardType": "intro",
            "title": f"Overview: {short_headline}",
            "bodyText": summary or f"Discover key insights behind {topic_label}.",
            "imageUrl": image_url,
        }
    ]
    if paragraphs:
        l1_cards.append({"cardType": "intro", "title": "Why This Matters", "bodyText": paragraphs[0]})
    if takeaways:
        l1_cards.append({"cardType": "list", "title": f"Key Highlights: {topic_label}", "listItems": takeaways[:4]})
    l1_cards.append({
        "cardType": "steps",
        "title": "Getting Started Steps",
        "stepItems": [
            f"Understand the core premise: {short_headline}",
            f"Review how {topic_label} impacts your domain",
            "Identify potential integration points in your daily workflow",
            "Share actionable insights with key team members"
        ]
    })
    l1_cards.append({
        "cardType": "quiz",
        "title": "Check Your Understanding",
        "quizData": _build_shuffled_quiz_data(
            question=f"What is the primary breakthrough reported in {topic_label}?",
            correct_text=f"{short_headline}: {_shorten_title(summary, 60)}",
            distractors=[
                "Hardware price drops in global semiconductor markets",
                "A complete shutdown of cloud data centers worldwide",
                "Legacy database migration to paper record archives",
            ],
            seed=f"{art_id}_l1"
        )
    })
    for i, c in enumerate(l1_cards, start=1): c["id"] = f"card_{i}"
    lessons.append({
        "sequence_order": 1,
        "title": f"1. Introduction: {short_headline}",
        "description": f"Learn the core facts, background, and summary of {topic_label}.",
        "cards_data": l1_cards,
        "estimated_minutes": max(3, math.ceil(len(l1_cards) * 1.2)),
    })

    if target_count >= 2:
        p2 = paragraphs[1] if len(paragraphs) > 1 else (paragraphs[0] if paragraphs else summary)
        l2_cards: List[Dict[str, Any]] = [
            {"cardType": "intro", "title": f"Deep Dive: {short_headline}", "bodyText": p2, "imageUrl": image_url},
            {
                "cardType": "comparison",
                "title": "Traditional Approach vs. AI-Powered Workflow",
                "comparisonData": {
                    "traditionalTitle": "Traditional Approach",
                    "traditionalBullets": ["Manual execution & review", "Slower adaptation to changes", "Fixed rules-based logic"],
                    "aiTitle": f"{topic_label} Advantage",
                    "aiBullets": ["Automated pattern recognition", "Real-time contextual adaptation", "Scalable decision support"]
                }
            },
            {
                "cardType": "steps",
                "title": "Analysis & Verification Steps",
                "stepItems": [
                    "Gather baseline data before implementing change",
                    "Benchmark results against traditional methods",
                    "Refine prompt instructions and workflow rules",
                    "Evaluate accuracy and overall ROI"
                ]
            },
            {
                "cardType": "quiz",
                "title": "Check Your Understanding",
                "quizData": _build_shuffled_quiz_data(
                    question=f"Based on the analysis of {topic_label}, why does this development matter?",
                    correct_text=_shorten_title(p2, 70),
                    distractors=[
                        "It restricts software processing to offline desktop calculators",
                        "It only impacts legacy mainframes manufactured before 2000",
                        "It eliminates the need for any digital communication tools",
                    ],
                    seed=f"{art_id}_l2"
                )
            }
        ]
        for i, c in enumerate(l2_cards, start=1): c["id"] = f"card_{i}"
        lessons.append({
            "sequence_order": 2,
            "title": f"2. Deep Dive: {short_headline}",
            "description": f"Analyze the broader context, expert perspectives, and technical implications of {topic_label}.",
            "cards_data": l2_cards,
            "estimated_minutes": max(3, math.ceil(len(l2_cards) * 1.2)),
        })

    if target_count >= 3:
        t_takeaway = takeaways[0] if takeaways else f"key advancements in {topic_label}"
        l3_cards: List[Dict[str, Any]] = [
            {"cardType": "intro", "title": f"Strategy: Future Impact of {short_headline}", "bodyText": f"As {topic_label} continues to evolve, strategic integration becomes crucial.", "imageUrl": image_url},
        ]
        if quote_text:
            l3_cards.append({"cardType": "intro", "title": "Expert Perspective", "bodyText": f'"{quote_text}"'})
        l3_cards.extend([
            {
                "cardType": "list",
                "title": "Strategic Principles",
                "listItems": ["Align adoption with core objectives", "Invest in continuous learning", "Maintain human oversight", "Monitor compliance"]
            },
            {
                "cardType": "steps",
                "title": "Execution Roadmap",
                "stepItems": ["Conduct capability assessment", "Pilot high-impact project", "Measure metrics & feedback", "Scale successful practices"]
            },
            {
                "cardType": "quiz",
                "title": "Check Your Understanding",
                "quizData": _build_shuffled_quiz_data(
                    question=f"What is the recommended strategic takeaway for teams adopting {topic_label}?",
                    correct_text=f"Pilot a structured approach focusing on: {_shorten_title(t_takeaway, 50)}",
                    distractors=[
                        "Discontinue all quality and compliance checks immediately",
                        "Ignore industry trends until competitors completely take over",
                        "Outsource all strategic decisions without human oversight",
                    ],
                    seed=f"{art_id}_l3"
                )
            }
        ])
        for i, c in enumerate(l3_cards, start=1): c["id"] = f"card_{i}"
        lessons.append({
            "sequence_order": 3,
            "title": f"3. Strategic Execution: {short_headline}",
            "description": f"Master practical steps, future outlook, and strategic execution for {topic_label}.",
            "cards_data": l3_cards,
            "estimated_minutes": max(3, math.ceil(len(l3_cards) * 1.2)),
        })

    if target_count >= 4:
        p3 = paragraphs[2] if len(paragraphs) > 2 else summary
        l4_cards: List[Dict[str, Any]] = [
            {"cardType": "intro", "title": f"Practical Application: {short_headline}", "bodyText": p3, "imageUrl": image_url},
            {"cardType": "list", "title": "Implementation Best Practices", "listItems": takeaways[4:8] if len(takeaways) > 4 else ["Define clear KPIs", "Ensure data privacy", "Train team members", "Establish fallback protocols"]},
            {"cardType": "quiz", "title": "Check Your Understanding", "quizData": _build_shuffled_quiz_data(question=f"How can teams best implement {topic_label} practically?", correct_text="Define clear KPIs, train team members, and ensure data privacy", distractors=["Avoid setting measurable goals", "Never train staff on new workflows", "Remove all security protocols"], seed=f"{art_id}_l4")}
        ]
        for i, c in enumerate(l4_cards, start=1): c["id"] = f"card_{i}"
        lessons.append({"sequence_order": 4, "title": f"4. Practical Application: {short_headline}", "description": f"Learn practical workflows and integration tactics for {topic_label}.", "cards_data": l4_cards, "estimated_minutes": max(3, math.ceil(len(l4_cards) * 1.2))})

    if target_count >= 5:
        l5_cards: List[Dict[str, Any]] = [
            {"cardType": "intro", "title": f"Governance & Risk Management: {short_headline}", "bodyText": f"Managing risks and maintaining compliance is vital when leveraging {topic_label}.", "imageUrl": image_url},
            {"cardType": "steps", "title": "Risk Mitigation Protocol", "stepItems": ["Identify potential compliance gaps", "Enforce encryption and access control", "Conduct regular security audits", "Maintain transparent reporting"]},
            {"cardType": "quiz", "title": "Check Your Understanding", "quizData": _build_shuffled_quiz_data(question=f"What is essential for risk governance in {topic_label}?", correct_text="Conducting regular security audits and enforcing access control", distractors=["Disabling user authentication", "Hiding audit reports from leadership", "Storing credentials in public forums"], seed=f"{art_id}_l5")}
        ]
        for i, c in enumerate(l5_cards, start=1): c["id"] = f"card_{i}"
        lessons.append({"sequence_order": 5, "title": f"5. Governance & Risk: {short_headline}", "description": f"Explore governance frameworks and risk management for {topic_label}.", "cards_data": l5_cards, "estimated_minutes": max(3, math.ceil(len(l5_cards) * 1.2))})

    if target_count >= 6:
        l6_cards: List[Dict[str, Any]] = [
            {"cardType": "intro", "title": f"Real-World Impact & Case Study: {short_headline}", "bodyText": f"Examine how industry leaders are applying {topic_label} to achieve measurable results.", "imageUrl": image_url},
            {"cardType": "list", "title": "Key Outcomes Observed", "listItems": ["30% efficiency increase in routine tasks", "Accelerated time-to-market for new features", "Improved decision confidence among stakeholders", "Enhanced scalability across teams"]},
            {"cardType": "quiz", "title": "Check Your Understanding", "quizData": _build_shuffled_quiz_data(question=f"What real-world impact is commonly seen with {topic_label}?", correct_text="Increased operational efficiency and accelerated decision making", distractors=["Immediate operational slowdowns", "Total loss of project visibility", "Exponential increase in manual errors"], seed=f"{art_id}_l6")}
        ]
        for i, c in enumerate(l6_cards, start=1): c["id"] = f"card_{i}"
        lessons.append({"sequence_order": 6, "title": f"6. Real-World Impact: {short_headline}", "description": f"Analyze case studies and real-world outcomes of {topic_label}.", "cards_data": l6_cards, "estimated_minutes": max(3, math.ceil(len(l6_cards) * 1.2))})

    if target_count >= 7:
        l7_cards: List[Dict[str, Any]] = [
            {"cardType": "intro", "title": f"Strategic Masterclass & Future Outlook: {short_headline}", "bodyText": f"Looking ahead, {topic_label} is poised to redefine long-term strategic advantage.", "imageUrl": image_url},
            {"cardType": "steps", "title": "Mastery Execution Plan", "stepItems": ["Integrate predictive analytics into core product", "Establish cross-functional innovation pods", "Continuously refine custom domain models", "Lead industry benchmark standards"]},
            {"cardType": "quiz", "title": "Check Your Understanding", "quizData": _build_shuffled_quiz_data(question=f"What marks the pinnacle of strategic mastery in {topic_label}?", correct_text="Leading industry benchmark standards through continuous innovation", distractors=["Abandoning all innovation efforts", "Stagnating product capabilities indefinitely", "Ignoring customer feedback and market metrics"], seed=f"{art_id}_l7")}
        ]
        for i, c in enumerate(l7_cards, start=1): c["id"] = f"card_{i}"
        lessons.append({"sequence_order": 7, "title": f"7. Strategic Masterclass: {short_headline}", "description": f"Master executive leadership and long-term vision for {topic_label}.", "cards_data": l7_cards, "estimated_minutes": max(3, math.ceil(len(l7_cards) * 1.2))})

    return lessons


async def _ensure_news_learning_path(
    db: AsyncSession, article: "NewsArticle"
) -> Optional[Dict[str, Any]]:
    """
    Find or create a real LearningPath + 3 Lessons from a NewsArticle.
    Returns a dict with real path_id, lesson_id (first lesson), and derived metadata.
    """
    headline = (article.headline or article.title or "").strip()
    topic_label = _normalize_topic_label(article.category or article.tag or headline)
    short_headline = _shorten_title(headline, 50)
    display_title = short_headline if topic_label.lower() in short_headline.lower() else f"{topic_label}: {short_headline}"
    image_url = article.image_url or "https://images.unsplash.com/photo-1485827404703-89b55fcc595e?q=80&w=300&auto=format&fit=crop"
    description = (article.summary or f"Learn about {topic_label} and how it applies to your work.").strip()

    # ── Look up existing path with this exact title ──────────────────────────
    existing_path_res = await db.execute(
        select(LearningPath).filter(LearningPath.title == display_title)
    )
    existing_path = existing_path_res.scalars().first()

    if existing_path:
        lessons_res = await db.execute(
            select(Lesson)
            .filter(Lesson.path_id == existing_path.id)
            .order_by(Lesson.sequence_order)
        )
        lessons = lessons_res.scalars().all()
        if lessons:
            first_lesson = lessons[0]
            first_lesson_cards = _extract_lesson_cards_data(first_lesson)
            actual_total_cards = len(first_lesson_cards) if first_lesson_cards else 5
            actual_total_lessons = len(lessons)
            actual_total_minutes = sum(l.estimated_minutes or 5 for l in lessons)
            return {
                "path_id": existing_path.id,
                "lesson_id": first_lesson.id,
                "title": first_lesson.title,
                "path_title": existing_path.title,
                "level": existing_path.level or "Beginner",
                "total_lessons": actual_total_lessons,
                "total_minutes": actual_total_minutes,
                "total_cards": actual_total_cards,
                "image_url": image_url,
                "description": description,
            }

    # ── Create new LearningPath with dynamic lessons ──────────────────────────────
    multi_lessons_data = _build_multi_lessons_from_article(article)
    total_lessons = len(multi_lessons_data)
    total_minutes = sum(d["estimated_minutes"] for d in multi_lessons_data)
    path_level = _determine_article_level(article, 1)

    new_path = LearningPath(
        title=display_title,
        description=description,
        level=path_level,
        total_lessons=total_lessons,
        total_minutes=total_minutes,
        image_url=image_url,
    )
    db.add(new_path)
    await db.flush()  # Assigns new_path.id

    first_lesson_id = None
    for idx, ldata in enumerate(multi_lessons_data, start=1):
        lesson_row = Lesson(
            path_id=new_path.id,
            sequence_order=ldata["sequence_order"],
            title=ldata["title"],
            description=ldata["description"],
            estimated_minutes=ldata["estimated_minutes"],
            cards_data=ldata["cards_data"],
        )
        db.add(lesson_row)
        await db.flush()
        if idx == 1:
            first_lesson_id = lesson_row.id

    saved_path_id = new_path.id
    await db.commit()

    return {
        "path_id": saved_path_id,
        "lesson_id": first_lesson_id,
        "title": multi_lessons_data[0]["title"],
        "path_title": display_title,
        "level": "Beginner",
        "total_lessons": total_lessons,
        "total_minutes": total_minutes,
        "total_cards": len(multi_lessons_data[0]["cards_data"]),
        "image_url": image_url,
        "description": description,
    }


def _normalize_lesson_cards(cards_data: Any, lesson_title: str = "Lesson") -> List[Dict[str, Any]]:
    if isinstance(cards_data, str):
        try:
            cards_data = json.loads(cards_data)
        except Exception:
            cards_data = []

    normalized_cards: List[Dict[str, Any]] = []
    if isinstance(cards_data, list):
        for index, card in enumerate(cards_data, start=1):
            if not isinstance(card, dict):
                continue

            if card.get("cardType"):
                normalized_cards.append({**card, "id": card.get("id") or f"card_{index}"})
                continue

            card_type = str(card.get("type") or card.get("cardType") or "intro").lower()
            content = card.get("content") if "content" in card else card
            content_dict = content if isinstance(content, dict) else {}

            if card_type in {"intro", "info", "text"}:
                title = content_dict.get("title") or content_dict.get("heading") or card.get("title") or card.get("heading") or "Introduction"
                body_text = content_dict.get("text") or content_dict.get("body") or (str(content) if isinstance(content, str) else "")
                image_url = content_dict.get("imageUrl") or content_dict.get("image_url") or card.get("imageUrl")
                normalized_cards.append({
                    "id": f"card_{index}",
                    "cardType": "intro",
                    "title": title,
                    "bodyText": body_text,
                    "imageUrl": image_url,
                })
            elif card_type == "example":
                normalized_cards.append({
                    "id": f"card_{index}",
                    "cardType": "example",
                    "title": content_dict.get("heading") or card.get("title") or "Example",
                    "exampleData": {
                        "promptPrefix": content_dict.get("promptPrefix") or content_dict.get("prompt") or "Input prompt",
                        "predictionWord": content_dict.get("predictionWord") or content_dict.get("answer") or "Output prediction",
                        "noteText": content_dict.get("noteText") or content_dict.get("text") or (str(content) if isinstance(content, str) else ""),
                    },
                })
            elif card_type == "comparison":
                normalized_cards.append({
                    "id": f"card_{index}",
                    "cardType": "comparison",
                    "title": content_dict.get("heading") or card.get("title") or "Comparison",
                    "comparisonData": {
                        "traditionalTitle": content_dict.get("traditionalTitle") or "Traditional Approach",
                        "traditionalBullets": content_dict.get("traditionalBullets") or ["Manual execution", "Rules-based logic"],
                        "aiTitle": content_dict.get("aiTitle") or "AI Approach",
                        "aiBullets": content_dict.get("aiBullets") or ["Automated predictions", "Pattern learning"],
                    },
                })
            elif card_type == "list":
                items = content_dict.get("listItems") or content_dict.get("listData") or card.get("listItems") or []
                normalized_items = [
                    (item.get("text") or item.get("label") or str(item)) if isinstance(item, dict) else str(item)
                    for item in items
                ]
                normalized_cards.append({
                    "id": f"card_{index}",
                    "cardType": "list",
                    "title": content_dict.get("heading") or card.get("title") or "Key Takeaways",
                    "listItems": normalized_items or ["Core concepts explained", "Practical applications"],
                })
            elif card_type == "steps":
                items = content_dict.get("stepItems") or content_dict.get("steps") or card.get("stepItems") or []
                normalized_cards.append({
                    "id": f"card_{index}",
                    "cardType": "steps",
                    "title": content_dict.get("heading") or card.get("title") or "How to Apply",
                    "stepItems": items or ["1. Understand concepts", "2. Practice steps", "3. Evaluate results"],
                })
            elif card_type == "quiz":
                question_text = (
                    content_dict.get("question")
                    or card.get("question")
                    or (str(content) if isinstance(content, str) else "")
                    or "Knowledge Check"
                )
                options = content_dict.get("options") or card.get("options") or []
                normalized_options = []
                for opt in options:
                    if isinstance(opt, dict):
                        normalized_options.append({
                            "id": str(opt.get("id") or opt.get("label") or len(normalized_options)),
                            "label": str(opt.get("label") or opt.get("id") or len(normalized_options)),
                            "text": str(opt.get("text") or opt.get("label") or "")
                        })
                    else:
                        normalized_options.append({
                            "id": str(len(normalized_options)),
                            "label": str(len(normalized_options)),
                            "text": str(opt)
                        })
                if not normalized_options:
                    normalized_options = [
                        {"id": "A", "label": "A", "text": "Correct concept application"},
                        {"id": "B", "label": "B", "text": "Incorrect or irrelevant approach"},
                    ]
                correct_ans = (
                    content_dict.get("correctOptionId")
                    or content_dict.get("correct_answer")
                    or card.get("correctOptionId")
                    or "A"
                )
                normalized_cards.append({
                    "id": f"card_{index}",
                    "cardType": "quiz",
                    "title": content_dict.get("heading") or card.get("title") or "Check Your Knowledge",
                    "quizData": {
                        "question": question_text,
                        "options": normalized_options,
                        "correctOptionId": correct_ans,
                    },
                })
            else:
                normalized_cards.append({
                    "id": f"card_{index}",
                    "cardType": "intro",
                    "title": card.get("title") or "Content",
                    "bodyText": str(content or ""),
                })

    if not normalized_cards:
        normalized_cards = [
            {
                "id": "card_1",
                "cardType": "intro",
                "title": lesson_title,
                "bodyText": f"Welcome to {lesson_title}! In this lesson, you will learn key concepts and practical applications.",
            },
            {
                "id": "card_2",
                "cardType": "steps",
                "title": f"Key Steps for {lesson_title}",
                "stepItems": [
                    "1. Read the core principles carefully.",
                    "2. Connect ideas to real-world tasks.",
                    "3. Test your understanding with practice.",
                ],
            },
            {
                "id": "card_3",
                "cardType": "quiz",
                "title": "Knowledge Check",
                "quizData": {
                    "question": f"What is the main goal of {lesson_title}?",
                    "options": [
                        {"id": "A", "label": "A", "text": "To build practical knowledge and skills"},
                        {"id": "B", "label": "B", "text": "To skip foundational learning"},
                    ],
                    "correctOptionId": "A",
                },
            },
        ]

    return normalized_cards


def _determine_article_level(article: "NewsArticle", sequence_order: int = 1) -> str:
    """
    Dynamically determine difficulty level (Beginner, Intermediate, Advanced) based on
    article topic complexity, text length, and lesson depth.
    """
    headline = (article.headline or article.title or "").lower()
    category = (article.category or article.tag or "").lower()
    text = f"{headline} {category}"
    art_id = article.id or 1
    art_hash = art_id % 3

    if sequence_order == 1:
        if any(k in text for k in ["worm", "cyber", "vulnerability", "quantum", "semiconductor"]):
            return "Intermediate"
        elif art_hash == 1:
            return "Intermediate"
        elif art_hash == 2:
            return "Advanced"
        return "Beginner"
    elif sequence_order <= 3:
        if art_hash == 2:
            return "Advanced"
        return "Intermediate"
    else:
        return "Advanced"


def _clean_category_name(title: str) -> str:
    """Extract clean category name before colon, e.g. 'Consulting & Strategy: New AI...' -> 'Consulting & Strategy'"""
    if not title:
        return "General"
    if ":" in title:
        return title.split(":")[0].strip()
    return title.strip()


def _build_continue_learning_payload(
    path: LearningPath,
    lesson: Lesson,
    cards_done: int,
    all_progress: List[UserLessonProgress]
) -> Dict[str, Any]:
    cards_data = _extract_lesson_cards_data(lesson)
    total_cards = len(cards_data) if cards_data else 1
    cards_done = max(0, min(cards_done, total_cards))
    les_pct = int((cards_done / max(1, total_cards)) * 100)

    actual_total_lessons = len(path.lessons) if path.lessons else 1
    path_lesson_ids = {l.id for l in path.lessons} if path.lessons else set()
    path_completed_count = sum(
        1 for pr in all_progress
        if pr.status == "completed" and (pr.path_id == path.id or pr.lesson_id in path_lesson_ids)
    )
    path_pct = int((path_completed_count / max(1, actual_total_lessons)) * 100)

    display_pct = les_pct if cards_done > 0 else (path_pct if path_completed_count > 0 else les_pct)

    est_mins = lesson.estimated_minutes or max(1, math.ceil(total_cards * 1.0))
    remaining_cards = max(0, total_cards - cards_done)
    mins_remaining = max(0 if cards_done >= total_cards else 1, math.ceil(remaining_cards * (est_mins / max(1, total_cards))))

    return {
        "path_id": path.id,
        "lesson_id": lesson.id,
        "title": lesson.title,
        "path_title": path.title,
        "completed_cards": cards_done,
        "total_cards": total_cards,
        "progress_percentage": display_pct,
        "minutes_remaining": mins_remaining,
        "image_url": path.image_url,
    }


# 1. GET LEARN DASHBOARD (Screen 1)
@router.get("/dashboard", response_model=LearnDashboardResponse)
async def get_learn_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    today = datetime.utcnow().date()
    # Get Monday of this week
    week_start = today - timedelta(days=today.weekday())

    # --- Real WeeklyActivity ---
    wa_res = await db.execute(
        select(WeeklyActivity).filter(
            WeeklyActivity.user_id == current_user.id,
            WeeklyActivity.week_start_date >= datetime(week_start.year, week_start.month, week_start.day)
        ).order_by(WeeklyActivity.week_start_date.desc())
    )
    wa = wa_res.scalars().first()

    if wa:
        days_active = wa.days_active or {}
        lessons_completed = wa.total_lessons_this_week or 0
        minutes_spent = wa.total_minutes_this_week or 0
    else:
        days_active = {"mon": False, "tue": False, "wed": False, "thu": False, "fri": False, "sat": False, "sun": False}
        lessons_completed = 0
        minutes_spent = 0

    # Calculate streak from days_active (M→Su order)
    day_order = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    today_idx = today.weekday()  # 0=Mon, 6=Sun
    streak_days = 0
    for i in range(today_idx, -1, -1):
        if days_active.get(day_order[i], False):
            streak_days += 1
        else:
            break

    weekly_stats = {
        "lessons_completed": lessons_completed,
        "minutes_spent": minutes_spent,
        "streak_days": streak_days,
        "days_active": days_active
    }

    news_res = await db.execute(
        select(NewsArticle)
        .order_by(NewsArticle.published_at.desc())
        .limit(3)
    )
    latest_news = news_res.scalars().all()

    # ── Ensure every news article has a real LearningPath + Lesson ──────────
    # This auto-creates DB rows if they don't exist yet, so we always get real IDs.
    news_path_contexts: List[Dict[str, Any]] = []
    for article in latest_news:
        ctx = await _ensure_news_learning_path(db, article)
        if ctx:
            news_path_contexts.append(ctx)

    # Fetch all Paths with lessons loaded (now includes the auto-created ones)
    paths_res = await db.execute(select(LearningPath).options(selectinload(LearningPath.lessons)))
    paths = paths_res.scalars().all()

    # Get all user progress records at once
    all_prog_res = await db.execute(
        select(UserLessonProgress).filter(UserLessonProgress.user_id == current_user.id)
    )
    all_progress = all_prog_res.scalars().all()
    completed_lesson_ids = {prog.lesson_id for prog in all_progress if prog.status == "completed"}

    # ── Continue Learning ────────────────────────────────────────────────────
    # Priority 1: Most recently accessed in-progress / uncompleted lesson
    in_prog_candidates = [
        p for p in all_progress
        if p.status != "completed" and p.lesson_id not in completed_lesson_ids
    ]
    active_progress = None
    if in_prog_candidates:
        in_prog_candidates.sort(key=lambda x: x.last_accessed or datetime.min, reverse=True)
        active_progress = in_prog_candidates[0]

    continue_learning = None
    if active_progress:
        lesson_res = await db.execute(select(Lesson).filter(Lesson.id == active_progress.lesson_id))
        lesson = lesson_res.scalars().first()
        target_path_id = active_progress.path_id or (lesson.path_id if lesson else None)
        path = None
        if target_path_id:
            path_res = await db.execute(select(LearningPath).options(selectinload(LearningPath.lessons)).filter(LearningPath.id == target_path_id))
            path = path_res.scalars().first()

        if lesson and path:
            cards_done = active_progress.cards_completed or 0
            continue_learning = _build_continue_learning_payload(path, lesson, cards_done, all_progress)

    # Priority 2: First news-derived path's lesson if uncompleted
    if not continue_learning and news_path_contexts:
        for ctx in news_path_contexts:
            if ctx["lesson_id"] not in completed_lesson_ids:
                lesson_res = await db.execute(select(Lesson).filter(Lesson.id == ctx["lesson_id"]))
                lesson = lesson_res.scalars().first()
                path_res = await db.execute(select(LearningPath).options(selectinload(LearningPath.lessons)).filter(LearningPath.id == ctx["path_id"]))
                path = path_res.scalars().first()

                if lesson and path:
                    prog_for_les = next((pr for pr in all_progress if pr.lesson_id == ctx["lesson_id"]), None)
                    cards_done = prog_for_les.cards_completed if prog_for_les else 0
                    continue_learning = _build_continue_learning_payload(path, lesson, cards_done, all_progress)
                    break

    # Priority 3: First available uncompleted lesson from any existing path
    if not continue_learning:
        for p in paths:
            sorted_les = sorted(p.lessons, key=lambda x: x.sequence_order)
            for les in sorted_les:
                if les.id not in completed_lesson_ids:
                    prog_for_les = next((pr for pr in all_progress if pr.lesson_id == les.id), None)
                    cards_done = prog_for_les.cards_completed if prog_for_les else 0
                    continue_learning = _build_continue_learning_payload(p, les, cards_done, all_progress)
                    break
            if continue_learning:
                break

    # ── Learning Paths (all real paths with dynamic counts) ─────────────────
    learning_paths = []
    for p in paths:
        actual_total_lessons = len(p.lessons) if p.lessons else (p.total_lessons or 1)
        path_lesson_ids = {les.id for les in p.lessons} if p.lessons else set()
        path_completed = sum(
            1 for prog in all_progress
            if prog.status == "completed"
            and (prog.path_id == p.id or prog.lesson_id in path_lesson_ids)
        )
        progress_pct = int((path_completed / max(1, actual_total_lessons)) * 100)
        total_mins = (
            sum(les.estimated_minutes or 5 for les in p.lessons)
            if p.lessons
            else (p.total_minutes or 5)
        )
        learning_paths.append({
            "path_id": p.id,
            "title": p.title,
            "level": p.level or "Beginner",
            "total_lessons": actual_total_lessons,
            "total_minutes": total_mins,
            "progress_percentage": progress_pct,
            "image_url": p.image_url,
        })

    # ── Recommended Lessons (news + paths, prioritized by uncompleted) ──────
    candidate_lessons = []
    for ctx in news_path_contexts:
        candidate_lessons.append({
            "id": ctx["lesson_id"],
            "lesson_id": ctx["lesson_id"],
            "path_id": ctx["path_id"],
            "title": ctx["title"],
            "description": ctx["description"],
            "level": ctx.get("level", "Beginner"),
            "category": _clean_category_name(ctx.get("path_title") or ctx.get("title") or ""),
            "image_url": ctx["image_url"],
        })

    for p in paths:
        sorted_p_lessons = sorted(p.lessons, key=lambda x: x.sequence_order)
        for idx, les in enumerate(sorted_p_lessons):
            prev_les = sorted_p_lessons[idx - 1] if idx > 0 else None
            is_unlocked = (idx == 0) or (prev_les and prev_les.id in completed_lesson_ids)
            if is_unlocked and les.id not in {c["lesson_id"] for c in candidate_lessons}:
                candidate_lessons.append({
                    "id": les.id,
                    "lesson_id": les.id,
                    "path_id": p.id,
                    "title": les.title,
                    "description": les.description or p.description,
                    "level": p.level or "Beginner",
                    "category": _clean_category_name(p.title),
                    "image_url": p.image_url,
                })

    uncompleted_candidates = [c for c in candidate_lessons if c["lesson_id"] not in completed_lesson_ids]
    completed_candidates = [c for c in candidate_lessons if c["lesson_id"] in completed_lesson_ids]
    ordered_candidates = uncompleted_candidates + completed_candidates

    recommended_lessons = []
    for cand in ordered_candidates:
        lesson_res = await db.execute(select(Lesson).filter(Lesson.id == cand["lesson_id"]))
        lesson = lesson_res.scalars().first()
        cards_data = _extract_lesson_cards_data(lesson)
        total_cards = len(cards_data) if cards_data else 1
        duration_mins = lesson.estimated_minutes if lesson else max(3, math.ceil(total_cards * 1.2))
        recommended_lessons.append({
            **cand,
            "duration": f"{duration_mins} min",
        })

    return {
        "weekly_stats": weekly_stats,
        "continue_learning": continue_learning,
        "learning_paths": learning_paths,
        "recommended_lessons": recommended_lessons,
    }

# 2. GET PATH DETAILS (Screen 2)
@router.get("/path/{path_id}", response_model=PathDetailResponse)
@router.get("/paths/{path_id}", response_model=PathDetailResponse)
async def get_path_details(
    path_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    path_res = await db.execute(select(LearningPath).options(selectinload(LearningPath.lessons)).filter(LearningPath.id == path_id))
    path = path_res.scalars().first()
    if not path: raise HTTPException(status_code=404)

    # Get user progress — query by lesson IDs (handles progress rows where path_id was None)
    path_lesson_ids = [les.id for les in path.lessons] if path.lessons else []
    prog_res = await db.execute(
        select(UserLessonProgress).filter(
            UserLessonProgress.user_id == current_user.id,
            UserLessonProgress.lesson_id.in_(path_lesson_ids),
        )
    )
    progress_map = {p.lesson_id: p for p in prog_res.scalars().all()}

    sorted_lessons = sorted(path.lessons, key=lambda x: x.sequence_order)

    formatted_lessons = []
    completed_count = 0

    for idx, lesson in enumerate(sorted_lessons):
        prog = progress_map.get(lesson.id)
        cards_data = _extract_lesson_cards_data(lesson)
        total_c = len(cards_data) if cards_data else 1
        cards_done = 0

        # Sequential unlock: Lesson 1 is unlocked; subsequent lessons unlock ONLY when previous is completed
        prev_lesson = sorted_lessons[idx - 1] if idx > 0 else None
        prev_prog = progress_map.get(prev_lesson.id) if prev_lesson else None
        prev_is_completed = (idx == 0) or (prev_prog and prev_prog.status == "completed")

        if prog and prog.status == "completed":
            status = "completed"
            cards_done = prog.cards_completed if prog.cards_completed else total_c
            completed_count += 1
        elif prev_is_completed:
            status = "in_progress"
            cards_done = prog.cards_completed if (prog and prog.cards_completed) else 0
        else:
            status = "locked"
            cards_done = 0

        formatted_lessons.append({
            "lesson_id": lesson.id,
            "sequence_order": lesson.sequence_order,
            "title": lesson.title,
            "description": lesson.description,
            "total_cards": total_c,
            "cards_completed": cards_done,
            "estimated_minutes": lesson.estimated_minutes,
            "status": status,
        })

    total_lessons = len(sorted_lessons) or 1
    progress_pct = int((completed_count / total_lessons) * 100)

    return {
        "path_id": path.id, "title": path.title, "description": path.description,
        "level": path.level, "progress_percentage": progress_pct,
        "lessons": formatted_lessons,
    }

# 3. START/RESUME LESSON (Screens 3-8)
@router.get("/lesson/{lesson_id}", response_model=LessonContentResponse)
@router.get("/lessons/{lesson_id}", response_model=LessonContentResponse)
async def get_lesson_content(
    lesson_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    lesson_res = await db.execute(select(Lesson).filter(Lesson.id == lesson_id))
    lesson = lesson_res.scalars().first()

    # Guard: prevent accessing locked lessons out of sequence
    if lesson.sequence_order and lesson.sequence_order > 1 and lesson.path_id:
        prev_lesson_res = await db.execute(
            select(Lesson).filter(
                Lesson.path_id == lesson.path_id,
                Lesson.sequence_order == lesson.sequence_order - 1
            )
        )
        prev_lesson = prev_lesson_res.scalars().first()
        if prev_lesson:
            prev_prog_res = await db.execute(
                select(UserLessonProgress).filter(
                    UserLessonProgress.user_id == current_user.id,
                    UserLessonProgress.lesson_id == prev_lesson.id,
                    UserLessonProgress.status == "completed"
                )
            )
            if not prev_prog_res.scalars().first():
                raise HTTPException(
                    status_code=403,
                    detail="This lesson is locked. Complete the previous lesson first."
                )

    # Capture all lesson data into plain variables NOW (before any commit that would expire ORM attrs)
    lesson_cards_data = lesson.cards_data
    lesson_title = lesson.title or "Lesson"
    lesson_path_id = lesson.path_id
    lesson_estimated_minutes = lesson.estimated_minutes or 5

    cards_done = 0
    try:
        prog_res = await db.execute(
            select(UserLessonProgress).filter(
                UserLessonProgress.user_id == current_user.id,
                UserLessonProgress.lesson_id == lesson_id
            )
        )
        progs = prog_res.scalars().all()
        now = datetime.utcnow()

        if not progs:
            progress = UserLessonProgress(
                user_id=current_user.id,
                lesson_id=lesson_id,
                path_id=lesson_path_id,
                cards_completed=0,
                status="in_progress",
                last_accessed=now,
            )
            db.add(progress)
        else:
            progress = progs[0]
            progress.last_accessed = now
            if not progress.path_id and lesson_path_id:
                progress.path_id = lesson_path_id
            if progress.status != "completed":
                progress.status = "in_progress"

        # Snapshot cards_done BEFORE commit (commit expires progress ORM attrs)
        cards_done = (progress.cards_completed or 0) if progress.cards_completed is not None else 0
        await db.commit()
    except Exception as e:
        print(f"Warning: Failed to update UserLessonProgress in get_lesson_content: {e}")
        await db.rollback()

    # Use the captured plain variables — never touch lesson.* after commit
    normalized = _normalize_lesson_cards(lesson_cards_data, lesson_title)
    total_cards = len(normalized)

    return {
        "lesson_id": lesson_id,
        "path_id": lesson_path_id,
        "title": lesson_title,
        "estimated_minutes": lesson_estimated_minutes,
        "total_cards": total_cards,
        "cards_completed": cards_done,
        "cards": normalized,
    }

# 4. SAVE CARD PROGRESS (As user taps "Continue")
@router.post("/lessons/{lesson_id}/progress", response_model=ProgressSaveResponse)
async def update_lesson_progress(
    lesson_id: int,
    card_index: int, # The index of the card they just finished reading
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    prog_res = await db.execute(
        select(UserLessonProgress).filter(
            UserLessonProgress.user_id == current_user.id,
            UserLessonProgress.lesson_id == lesson_id
        )
    )
    progs = prog_res.scalars().all()
    if progs:
        for p in progs:
            if (p.cards_completed or 0) < card_index:
                p.cards_completed = card_index
            p.last_accessed = datetime.utcnow()
        await db.commit()
    else:
        lesson_res = await db.execute(select(Lesson).filter(Lesson.id == lesson_id))
        lesson = lesson_res.scalars().first()
        p = UserLessonProgress(
            user_id=current_user.id,
            lesson_id=lesson_id,
            path_id=lesson.path_id if lesson else None,
            cards_completed=card_index,
            status="in_progress",
            last_accessed=datetime.utcnow()
        )
        db.add(p)
        await db.commit()
    
    return {"status": "saved"}

# 5. COMPLETE LESSON (Screen 8 action)
@router.post("/lesson/{lesson_id}/complete", response_model=LessonCompleteResponse)
@router.post("/lessons/{lesson_id}/complete", response_model=LessonCompleteResponse)
async def complete_lesson(
    lesson_id: int,
    payload: LessonCompleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if payload.lesson_id != lesson_id:
        lesson_id = payload.lesson_id

    # Mark current lesson as completed
    prog_res = await db.execute(
        select(UserLessonProgress).filter(
            UserLessonProgress.user_id == current_user.id,
            UserLessonProgress.lesson_id == lesson_id
        )
    )
    progs = prog_res.scalars().all()
    if progs:
        for p in progs:
            p.status = "completed"
            p.cards_completed = payload.completed_cards
            p.last_accessed = datetime.utcnow()
    else:
        # Create a completed progress record with full card count and path_id
        lesson_for_path_res = await db.execute(select(Lesson).filter(Lesson.id == lesson_id))
        lesson_for_path = lesson_for_path_res.scalars().first()
        p = UserLessonProgress(
            user_id=current_user.id,
            lesson_id=lesson_id,
            path_id=lesson_for_path.path_id if lesson_for_path else None,
            cards_completed=payload.completed_cards,
            status="completed",
        )
        db.add(p)
        progs = [p]
    
    # Unlock Next Lesson Logic
    lesson_res = await db.execute(select(Lesson).filter(Lesson.id == lesson_id))
    current_lesson = lesson_res.scalars().first()
    
    if current_lesson:
        for p in progs:
            if not p.path_id:
                p.path_id = current_lesson.path_id

        next_lesson_res = await db.execute(
            select(Lesson).filter(Lesson.path_id == current_lesson.path_id, Lesson.sequence_order == current_lesson.sequence_order + 1)
        )
        next_lesson = next_lesson_res.scalars().first()
        
        if next_lesson:
            next_prog_res = await db.execute(
                select(UserLessonProgress).filter(UserLessonProgress.user_id == current_user.id, UserLessonProgress.lesson_id == next_lesson.id)
            )
            next_prog = next_prog_res.scalars().first()
            if next_prog:
                if next_prog.status != "completed":
                    next_prog.status = "in_progress"
                    next_prog.last_accessed = datetime.utcnow()
            else:
                new_prog = UserLessonProgress(
                    user_id=current_user.id,
                    lesson_id=next_lesson.id,
                    path_id=next_lesson.path_id,
                    status="in_progress"
                )
                db.add(new_prog)

    # Update DailySession for /home/dashboard pulse task completion
    daily_session = await get_or_create_daily_session(db, current_user.id)
    daily_session.lesson_completed = True

    # Update WeeklyActivity
    today = datetime.utcnow().date()
    week_start = today - timedelta(days=today.weekday())
    week_start_dt = datetime(week_start.year, week_start.month, week_start.day)
    day_keys = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    today_key = day_keys[today.weekday()]

    wa_res = await db.execute(
        select(WeeklyActivity).filter(
            WeeklyActivity.user_id == current_user.id,
            WeeklyActivity.week_start_date >= week_start_dt
        )
    )
    wa = wa_res.scalars().first()
    
    if wa:
        days_active = dict(wa.days_active or {})
        days_active[today_key] = True
        wa.days_active = days_active
        wa.total_lessons_this_week = (wa.total_lessons_this_week or 0) + 1
        wa.total_minutes_this_week = (wa.total_minutes_this_week or 0) + (current_lesson.estimated_minutes if current_lesson else 5)
    else:
        days_active = {"mon": False, "tue": False, "wed": False, "thu": False, "fri": False, "sat": False, "sun": False}
        days_active[today_key] = True
        wa = WeeklyActivity(
            user_id=current_user.id,
            week_start_date=week_start_dt,
            days_active=days_active,
            total_lessons_this_week=1,
            total_minutes_this_week=current_lesson.estimated_minutes if current_lesson else 5
        )
        db.add(wa)

    await db.commit()
    return {
        "message": "Lesson completed successfully!",
        "streak_updated": True,
        "pulse_updated": True,
    }
