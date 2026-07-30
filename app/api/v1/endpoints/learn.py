from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta, date
import math
import json
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


def _build_lesson_cards_from_article(article: "NewsArticle") -> List[Dict[str, Any]]:
    """
    Build rich lesson cards from a real NewsArticle's content_blocks, summary, and headline.
    Always returns at least 3 cards: intro + key points + quiz.
    """
    headline = (article.headline or "").strip()
    summary = (article.summary or "").strip()
    topic_label = _normalize_topic_label(article.category or article.tag or headline)
    image_url = article.image_url or "https://images.unsplash.com/photo-1485827404703-89b55fcc595e?q=80&w=300&auto=format&fit=crop"
    content_blocks = article.content_blocks or []

    cards: List[Dict[str, Any]] = []

    # Card 1: Intro — use the article summary
    cards.append({
        "cardType": "intro",
        "title": _shorten_title(headline, 60),
        "bodyText": summary or f"Explore the key ideas in {topic_label} and how they apply to everyday work.",
        "imageUrl": image_url,
    })

    # Card 2: Extract paragraphs from content_blocks
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

    # Card 2: First paragraph as a deeper intro card
    if paragraphs:
        cards.append({
            "cardType": "intro",
            "title": "Why This Matters",
            "bodyText": paragraphs[0],
        })

    # Card 3: Key takeaways as a list card
    if takeaways:
        cards.append({
            "cardType": "list",
            "title": f"Key Takeaways from {topic_label}",
            "listItems": takeaways[:6],  # Max 6 items
        })
    elif len(paragraphs) > 1:
        # Fall back: use bullet-style sentences from the second paragraph
        sentences = [s.strip() for s in paragraphs[1].replace(".", ".|").split("|") if s.strip()][:4]
        if sentences:
            cards.append({
                "cardType": "list",
                "title": "Key Points",
                "listItems": sentences,
            })

    # Card 4: Quote card if available
    if quote_text:
        cards.append({
            "cardType": "intro",
            "title": "Expert Perspective",
            "bodyText": f'"{quote_text}"',
        })

    # Card 5: Steps card — generic "how to apply" steps derived from topic
    cards.append({
        "cardType": "steps",
        "title": f"How to Apply {topic_label} in Your Work",
        "stepItems": [
            f"1. Read and understand the core idea: {_shorten_title(headline, 50)}",
            f"2. Identify how {topic_label} connects to your daily tasks",
            "3. Try one small experiment or tool this week",
            "4. Share what you learned with your team",
            "5. Revisit next week to track progress",
        ],
    })

    # Final card: Knowledge check quiz
    option_a = f"{topic_label} is a new tool or development"
    option_b = "It has no practical impact on work"
    option_c = "It only affects a small number of experts"
    cards.append({
        "cardType": "quiz",
        "title": "Check Your Understanding",
        "quizData": {
            "question": f"What is the main takeaway from: {_shorten_title(headline, 55)}?",
            "options": [
                {"id": "A", "label": "A", "text": option_a},
                {"id": "B", "label": "B", "text": option_b},
                {"id": "C", "label": "C", "text": option_c},
            ],
            "correctOptionId": "A",
        },
    })

    # Assign sequential IDs
    for i, card in enumerate(cards, start=1):
        card["id"] = f"card_{i}"

    return cards


async def _ensure_news_learning_path(
    db: AsyncSession, article: "NewsArticle"
) -> Optional[Dict[str, Any]]:
    """
    Find or create a real LearningPath + Lesson from a NewsArticle.
    Returns a dict with real path_id, lesson_id, and derived metadata.
    Never returns path_id=0 or lesson_id=0.
    """
    headline = (article.headline or "").strip()
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
        # Use existing path — load its first lesson
        lessons_res = await db.execute(
            select(Lesson)
            .filter(Lesson.path_id == existing_path.id)
            .order_by(Lesson.sequence_order)
        )
        lessons = lessons_res.scalars().all()
        if lessons:
            first_lesson = lessons[0]
            actual_total_cards = len(first_lesson.cards_data) if first_lesson.cards_data else 1
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

    # ── Create new LearningPath ───────────────────────────────────────────────
    cards_data = _build_lesson_cards_from_article(article)
    total_cards = len(cards_data)
    estimated_minutes = max(3, math.ceil(total_cards * 1.2))

    new_path = LearningPath(
        title=display_title,
        description=description,
        level="Beginner",
        total_lessons=1,
        total_minutes=estimated_minutes,
        image_url=image_url,
    )
    db.add(new_path)
    await db.flush()  # Assigns new_path.id

    new_lesson = Lesson(
        path_id=new_path.id,
        sequence_order=1,
        title=display_title,
        description=f"Understand the key ideas behind {topic_label} and how they connect to everyday work.",
        estimated_minutes=estimated_minutes,
        cards_data=cards_data,
    )
    db.add(new_lesson)
    await db.flush()  # Assigns new_lesson.id
    await db.commit()

    return {
        "path_id": new_path.id,
        "lesson_id": new_lesson.id,
        "title": display_title,
        "path_title": display_title,
        "level": "Beginner",
        "total_lessons": 1,
        "total_minutes": estimated_minutes,
        "total_cards": total_cards,
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
    # Priority 1: Most recently accessed in_progress lesson (with status != completed)
    active_progress = None
    for prog in sorted(all_progress, key=lambda x: x.last_accessed or datetime.min, reverse=True):
        if prog.status == "in_progress" and prog.lesson_id not in completed_lesson_ids:
            active_progress = prog
            break

    continue_learning = None
    if active_progress:
        lesson_res = await db.execute(select(Lesson).filter(Lesson.id == active_progress.lesson_id))
        lesson = lesson_res.scalars().first()
        target_path_id = active_progress.path_id or (lesson.path_id if lesson else None)
        path = None
        if target_path_id:
            path_res = await db.execute(select(LearningPath).filter(LearningPath.id == target_path_id))
            path = path_res.scalars().first()

        if lesson and path:
            total_cards = len(lesson.cards_data) if lesson.cards_data else 1
            cards_done = active_progress.cards_completed or 0
            progress_pct = int((cards_done / max(1, total_cards)) * 100)
            continue_learning = {
                "path_id": path.id,
                "lesson_id": lesson.id,
                "title": lesson.title,
                "path_title": path.title,
                "completed_cards": cards_done,
                "total_cards": total_cards,
                "progress_percentage": progress_pct,
                "image_url": path.image_url,
            }

    # Priority 2: First news-derived path's lesson if uncompleted
    if not continue_learning and news_path_contexts:
        for ctx in news_path_contexts:
            if ctx["lesson_id"] not in completed_lesson_ids:
                lesson_res = await db.execute(select(Lesson).filter(Lesson.id == ctx["lesson_id"]))
                lesson = lesson_res.scalars().first()
                total_cards = len(lesson.cards_data) if (lesson and lesson.cards_data) else 1
                prog_for_les = next((pr for pr in all_progress if pr.lesson_id == ctx["lesson_id"]), None)
                cards_done = prog_for_les.cards_completed if prog_for_les else 0
                pct = int((cards_done / max(1, total_cards)) * 100)
                continue_learning = {
                    "path_id": ctx["path_id"],
                    "lesson_id": ctx["lesson_id"],
                    "title": ctx["title"],
                    "path_title": ctx["path_title"],
                    "completed_cards": cards_done,
                    "total_cards": total_cards,
                    "progress_percentage": pct,
                    "image_url": ctx["image_url"],
                }
                break

    # Priority 3: First available uncompleted lesson from any existing path
    if not continue_learning:
        for p in paths:
            sorted_les = sorted(p.lessons, key=lambda x: x.sequence_order)
            for les in sorted_les:
                if les.id not in completed_lesson_ids:
                    prog_for_les = next((pr for pr in all_progress if pr.lesson_id == les.id), None)
                    cards_done = prog_for_les.cards_completed if prog_for_les else 0
                    total_cards = len(les.cards_data) if les.cards_data else 1
                    pct = int((cards_done / max(1, total_cards)) * 100)
                    continue_learning = {
                        "path_id": p.id,
                        "lesson_id": les.id,
                        "title": les.title,
                        "path_title": p.title,
                        "completed_cards": cards_done,
                        "total_cards": total_cards,
                        "progress_percentage": pct,
                        "image_url": p.image_url,
                    }
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
            "category": ctx["path_title"],
            "image_url": ctx["image_url"],
        })

    for p in paths:
        for les in p.lessons:
            if les.id not in {c["lesson_id"] for c in candidate_lessons}:
                candidate_lessons.append({
                    "id": les.id,
                    "lesson_id": les.id,
                    "path_id": p.id,
                    "title": les.title,
                    "description": les.description or p.description,
                    "level": p.level or "Beginner",
                    "category": p.title,
                    "image_url": p.image_url,
                })

    uncompleted_candidates = [c for c in candidate_lessons if c["lesson_id"] not in completed_lesson_ids]
    completed_candidates = [c for c in candidate_lessons if c["lesson_id"] in completed_lesson_ids]
    ordered_candidates = uncompleted_candidates + completed_candidates

    recommended_lessons = []
    for cand in ordered_candidates:
        lesson_res = await db.execute(select(Lesson).filter(Lesson.id == cand["lesson_id"]))
        lesson = lesson_res.scalars().first()
        total_cards = len(lesson.cards_data) if (lesson and lesson.cards_data) else 1
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
        total_c = len(lesson.cards_data) if lesson.cards_data else 1
        cards_done = 0

        if prog and prog.status == "completed":
            status = "completed"
            # Use stored cards_completed if available, otherwise use total_c
            cards_done = prog.cards_completed if prog.cards_completed else total_c
            completed_count += 1
        elif prog and prog.status == "in_progress":
            status = "in_progress"
            cards_done = prog.cards_completed or 0
        else:
            # Sequential unlock: Lesson 1 always available; subsequent lessons unlock when previous is completed
            prev_lesson = sorted_lessons[idx - 1] if idx > 0 else None
            prev_prog = progress_map.get(prev_lesson.id) if prev_lesson else None
            if idx == 0 or (prev_prog and prev_prog.status == "completed"):
                status = "in_progress"
            else:
                status = "locked"

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
    
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    
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
                lesson_id=lesson.id, 
                path_id=lesson.path_id, 
                cards_completed=0,
                status="in_progress",
                last_accessed=now,
            )
            db.add(progress)
        else:
            progress = progs[0]
            progress.last_accessed = now
            if not progress.path_id and lesson.path_id:
                progress.path_id = lesson.path_id
            if progress.status != "completed":
                progress.status = "in_progress"

        await db.commit()
        cards_done = progress.cards_completed if (progress and progress.cards_completed is not None) else 0
    except Exception as e:
        print(f"Warning: Failed to update UserLessonProgress in get_lesson_content: {e}")
        await db.rollback()

    normalized = _normalize_lesson_cards(lesson.cards_data, lesson.title)
    total_cards = len(normalized)

    return {
        "lesson_id": lesson.id,
        "path_id": lesson.path_id,
        "title": lesson.title,
        "estimated_minutes": lesson.estimated_minutes or 5,
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


@router.post("/test/seed-learn-data", response_model=MessageResponse)
async def seed_learn_data(db: AsyncSession = Depends(get_db)):
    # 1. Create a Learning Path
    path = LearningPath(
        title="Generative AI Fundamentals",
        description="Learn how AI creates text, images, audio, and other content.",
        level="Beginner",
        total_lessons=6,
        total_minutes=30,
        image_url="https://images.unsplash.com/photo-1677442136019-21780ecad995"
    )
    db.add(path)
    await db.flush()

    # 2. Create Lesson 1
    lesson1 = Lesson(
        path_id=path.id,
        sequence_order=1,
        title="What Is Generative AI?",
        description="Learn what generative AI means and how it differs from traditional software.",
        estimated_minutes=4,
        cards_data=[{"type": "info", "content": "Welcome to Lesson 1!"}] # Simplified for demo
    )
    
    # 3. Create Lesson 2 (Matching your UI screenshots exactly)
    lesson2 = Lesson(
        path_id=path.id,
        sequence_order=2,
        title="How AI Models Learn",
        description="Understand training data, patterns, and model predictions.",
        estimated_minutes=5,
        cards_data=[
            {
                "type": "info",
                "content": {
                    "heading": "What is a Large Language Model?",
                    "text": "A large language model, or LLM, is an AI system trained to understand and generate human language by learning from billions of text examples."
                }
            },
            {
                "type": "example",
                "content": {
                    "heading": "Think of an LLM as a pattern predictor",
                    "text": "It reads the words that came before and predicts which word is most likely to come next — billions of times per second.",
                    "example_block": "The sky is very -> blue"
                }
            },
            {
                "type": "quiz",
                "content": {
                    "question": "Which statement best describes an LLM?",
                    "options": [
                        "A database that stores every answer",
                        "A model that predicts language patterns",
                        "A search engine that only finds websites",
                        "A robot that understands everything"
                    ],
                    "correct_answer": "A model that predicts language patterns"
                }
            }
        ]
    )
    
    db.add_all([lesson1, lesson2])
    await db.commit()
    return {"message": "Learn Data Seeded Successfully!"}