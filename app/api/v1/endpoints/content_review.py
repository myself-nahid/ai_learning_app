"""
Admin Content Review API
Provides endpoints for reviewing content quality, tracking curriculum coverage,
and monitoring per-user concept learning progress, plus full CRUD management of
AI curriculum topics (create / read / update / delete).
All endpoints require admin authentication.
"""
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, desc, delete as sa_delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel

from app.api.deps import get_db, get_current_admin
from app.db.models import (
    AiTopicCurriculum,
    UserConceptProgress,
    DailySession,
    LearningPath,
    Lesson,
    User,
    UserLessonProgress,
)
from app.schemas.admin import (
    AiTopicCreate,
    AiTopicUpdate,
    AiTopicDetailResponse,
    AiTopicActionResponse,
)

router = APIRouter(prefix="/admin/content-review", tags=["Admin — Content Review"])


# ─── Shared helpers for AI topic CRUD ─────────────────────────────────────────

async def _serialize_topic(topic: AiTopicCurriculum, db: AsyncSession) -> dict:
    """Serialize a topic with all editable fields plus light coverage stats."""
    coverage_result = await db.execute(
        select(
            func.count(UserConceptProgress.user_id).label("users_taught"),
            func.avg(UserConceptProgress.quality_score).label("avg_quality"),
        ).where(UserConceptProgress.topic_id == topic.id)
    )
    cov = coverage_result.first()

    path_result = await db.execute(
        select(LearningPath.id).where(LearningPath.curriculum_slug == topic.slug)
    )
    learning_path_id = path_result.scalars().first()

    return {
        "id": topic.id,
        "slug": topic.slug,
        "title": topic.title,
        "description": topic.description,
        "level": topic.level,
        "category": topic.category,
        "sequence_order": topic.sequence_order,
        "search_keywords": topic.search_keywords or [],
        "learning_objectives": topic.learning_objectives or [],
        "is_active": topic.is_active,
        "created_at": topic.created_at.isoformat() if topic.created_at else None,
        "coverage": {
            "users_taught": cov.users_taught if cov else 0,
            "avg_quality": round(float(cov.avg_quality or 0), 1) if cov else 0,
        },
        "learning_path_id": learning_path_id,
    }


async def _get_topic_or_404(topic_id: int, db: AsyncSession) -> AiTopicCurriculum:
    result = await db.execute(select(AiTopicCurriculum).where(AiTopicCurriculum.id == topic_id))
    topic = result.scalars().first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


def _validate_slug(slug: str) -> str:
    """Normalize slug: lowercase, hyphen-separated, URL-safe."""
    import re
    normalized = re.sub(r"[^a-z0-9]+", "-", slug.strip().lower()).strip("-")
    if not normalized:
        raise HTTPException(status_code=422, detail="Slug must contain at least one letter or number.")
    return normalized


async def _materialize_learning_feed(topic: AiTopicCurriculum, db: AsyncSession) -> None:
    """Create or refresh the materialized Learning Feed path/lesson for a topic.
    Mirrors seed_learning_paths_from_curriculum() in app/db/init_db.py."""
    path_result = await db.execute(
        select(LearningPath).where(LearningPath.curriculum_slug == topic.slug)
    )
    path = path_result.scalars().first()
    if not path:
        path = LearningPath(
            title=topic.title,
            description=topic.description,
            level=topic.level,
            total_lessons=1,
            total_minutes=5,
            # Topic-derived content feeds the Daily Pulse pipeline, NOT the
            # predefined Learning Feed. source_type="news" keeps it out of
            # /learn/dashboard, the daily lesson assignment, and the admin
            # Excel lesson editor (all filter source_type == "curriculum").
            source_type="news",
            curriculum_slug=topic.slug,
        )
        db.add(path)
        await db.flush()
    else:
        path.source_type = "news"
        path.title = topic.title
        path.description = topic.description
        path.level = topic.level

    lesson_result = await db.execute(
        select(Lesson).where(Lesson.path_id == path.id, Lesson.sequence_order == 1)
    )
    lesson = lesson_result.scalars().first()
    objectives = topic.learning_objectives or []
    remember_text = " ".join(str(item) for item in objectives) or topic.description
    example_text = (
        f"Practice applying the idea of {topic.title.lower()} to a familiar task. "
        "Start with the situation, identify the relevant concept, and explain what result you expect."
    )
    cards = [
        {"id": "card_1", "cardType": "intro", "section": "what_is_it", "title": "What Is It?", "bodyText": topic.description},
        {"id": "card_2", "cardType": "concept", "section": "how_does_it_work", "title": "How Does It Work?", "bodyText": " ".join(str(item) for item in objectives[:2]) or topic.description},
        {"id": "card_3", "cardType": "example", "section": "real_example", "title": "Real Example / Practice Exercise", "bodyText": example_text},
        {"id": "card_4", "cardType": "takeaway", "section": "remember", "title": "What Should I Remember?", "bodyText": remember_text},
    ]
    if not lesson:
        lesson = Lesson(path_id=path.id, sequence_order=1)
        db.add(lesson)
    lesson.title = topic.title
    lesson.description = topic.description
    lesson.learning_goal = " ".join(objectives) or topic.description
    lesson.estimated_minutes = 5
    lesson.cards_data = cards


async def _delete_learning_feed(path_id: int, db: AsyncSession) -> bool:
    """Delete a topic-sourced path, its lessons, and lesson progress.

    Matches by id only (no source_type filter): topic paths used to be
    materialized with source_type="curriculum" before the separation fix,
    and those legacy rows must still be deletable.
    """
    await db.execute(sa_delete(UserLessonProgress).where(UserLessonProgress.path_id == path_id))
    await db.execute(sa_delete(Lesson).where(Lesson.path_id == path_id))
    result = await db.execute(sa_delete(LearningPath).where(
        LearningPath.id == path_id
    ))
    return (result.rowcount or 0) > 0


# ─── 1. Topic Coverage Overview ───────────────────────────────────────────────

@router.get("/topic-coverage")
async def get_topic_coverage(
    level: Optional[str] = Query(None, description="Filter by level: Beginner, Intermediate, Advanced"),
    category: Optional[str] = Query(None, description="Filter by category"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """
    Returns all curriculum topics with how many users have been taught each one
    and the average quality score of generated content for that topic.
    Useful for identifying gaps in content coverage.
    """
    # Fetch all topics
    topic_query = select(AiTopicCurriculum).where(AiTopicCurriculum.is_active == True)
    if level:
        topic_query = topic_query.where(AiTopicCurriculum.level == level)
    if category:
        topic_query = topic_query.where(AiTopicCurriculum.category == category)
    topic_query = topic_query.order_by(AiTopicCurriculum.sequence_order)

    topics_result = await db.execute(topic_query)
    topics = topics_result.scalars().all()

    # Fetch coverage stats per topic
    coverage_result = await db.execute(
        select(
            UserConceptProgress.topic_id,
            func.count(UserConceptProgress.user_id).label("users_taught"),
            func.avg(UserConceptProgress.quality_score).label("avg_quality"),
            func.min(UserConceptProgress.quality_score).label("min_quality"),
            func.max(UserConceptProgress.quality_score).label("max_quality"),
            func.max(UserConceptProgress.taught_at).label("last_taught_at"),
        )
        .group_by(UserConceptProgress.topic_id)
    )
    coverage_map = {
        row.topic_id: {
            "users_taught": row.users_taught,
            "avg_quality": round(float(row.avg_quality or 0), 1),
            "min_quality": row.min_quality or 0,
            "max_quality": row.max_quality or 0,
            "last_taught_at": row.last_taught_at.isoformat() if row.last_taught_at else None,
        }
        for row in coverage_result.fetchall()
    }

    return {
        "total_topics": len(topics),
        "topics": [
            {
                "id": t.id,
                "slug": t.slug,
                "title": t.title,
                "level": t.level,
                "category": t.category,
                "sequence_order": t.sequence_order,
                "description": t.description,
                "learning_objectives": t.learning_objectives,
                "search_keywords": t.search_keywords,
                "coverage": coverage_map.get(t.id, {
                    "users_taught": 0,
                    "avg_quality": 0,
                    "min_quality": 0,
                    "max_quality": 0,
                    "last_taught_at": None,
                }),
            }
            for t in topics
        ],
    }


# ─── 2. Recent Daily Sessions Quality Review ──────────────────────────────────

@router.get("/daily-sessions")
async def get_recent_sessions_for_review(
    days: int = Query(7, ge=1, le=30, description="Look back N days"),
    min_quality: int = Query(0, ge=0, le=100, description="Filter sessions below this quality score"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """
    Returns recent Daily Sessions with their lesson data and quality scores
    for editorial review. Use min_quality=0 to see all, or min_quality=60
    to see only passing content.
    """
    since = datetime.utcnow() - timedelta(days=days)

    sessions_result = await db.execute(
        select(DailySession, User.full_name, User.email)
        .join(User, DailySession.user_id == User.id)
        .where(DailySession.date >= since)
        .order_by(desc(DailySession.date))
        .limit(limit)
    )
    rows = sessions_result.fetchall()

    sessions = []
    for session, full_name, email in rows:
        lesson = session.lesson_data or {}
        quality = lesson.get("quality_score", None)

        if min_quality > 0 and (quality is None or quality < min_quality):
            continue

        # Find the curriculum topic taught in this session
        topic_info = None
        progress_result = await db.execute(
            select(UserConceptProgress, AiTopicCurriculum)
            .join(AiTopicCurriculum, UserConceptProgress.topic_id == AiTopicCurriculum.id)
            .where(UserConceptProgress.session_id == session.id)
        )
        progress_row = progress_result.first()
        if progress_row:
            _, topic = progress_row
            topic_info = {
                "id": topic.id,
                "slug": topic.slug,
                "title": topic.title,
                "level": topic.level,
                "category": topic.category,
            }

        sessions.append({
            "session_id": session.id,
            "user": {"name": full_name, "email": email},
            "date": session.date.isoformat(),
            "topic": topic_info,
            "quality_score": quality,
            "news_completed": session.news_completed,
            "lesson_completed": session.lesson_completed,
            "quiz_completed": session.quiz_completed,
            "is_fully_completed": session.is_fully_completed,
            "lesson_preview": {
                "title": lesson.get("title"),
                "card_count": len(lesson.get("cards", [])),
                "practical_takeaway": lesson.get("practical_takeaway"),
                "learning_objectives": lesson.get("learning_objectives", []),
            },
        })

    return {
        "period_days": days,
        "total_sessions": len(sessions),
        "sessions": sessions,
    }


# ─── 3. Per-User Concept Learning Map ────────────────────────────────────────

@router.get("/user-progress/{user_id}")
async def get_user_concept_map(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """
    Full learning map for a specific user:
    - Which topics they've been taught (with quality scores and dates)
    - Which topics remain in the curriculum
    - Progress percentage by level
    """
    # Verify user exists
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalars().first()
    if not user:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="User not found")

    # Get all taught topics for this user
    taught_result = await db.execute(
        select(UserConceptProgress, AiTopicCurriculum)
        .join(AiTopicCurriculum, UserConceptProgress.topic_id == AiTopicCurriculum.id)
        .where(UserConceptProgress.user_id == user_id)
        .order_by(UserConceptProgress.taught_at)
    )
    taught_rows = taught_result.fetchall()
    taught_topic_ids = {progress.topic_id for progress, _ in taught_rows}

    # Get all curriculum topics
    all_topics_result = await db.execute(
        select(AiTopicCurriculum)
        .where(AiTopicCurriculum.is_active == True)
        .order_by(AiTopicCurriculum.sequence_order)
    )
    all_topics = all_topics_result.scalars().all()

    # Build progress map
    taught_map = {
        progress.topic_id: {
            "taught_at": progress.taught_at.isoformat(),
            "quality_score": progress.quality_score,
            "session_id": progress.session_id,
        }
        for progress, _ in taught_rows
    }

    # Group by level
    levels = ["Beginner", "Intermediate", "Advanced"]
    level_stats = {}
    for level in levels:
        level_topics = [t for t in all_topics if t.level == level]
        taught_in_level = [t for t in level_topics if t.id in taught_topic_ids]
        level_stats[level] = {
            "total": len(level_topics),
            "taught": len(taught_in_level),
            "progress_pct": round(len(taught_in_level) / len(level_topics) * 100, 1) if level_topics else 0,
        }

    curriculum_map = []
    for topic in all_topics:
        entry = {
            "id": topic.id,
            "slug": topic.slug,
            "title": topic.title,
            "level": topic.level,
            "category": topic.category,
            "sequence_order": topic.sequence_order,
            "status": "taught" if topic.id in taught_topic_ids else "pending",
        }
        if topic.id in taught_map:
            entry.update(taught_map[topic.id])
        curriculum_map.append(entry)

    total_taught = len(taught_topic_ids)
    total_topics = len(all_topics)

    return {
        "user": {
            "id": user.id,
            "name": user.full_name,
            "email": user.email,
        },
        "summary": {
            "total_topics": total_topics,
            "total_taught": total_taught,
            "overall_progress_pct": round(total_taught / total_topics * 100, 1) if total_topics else 0,
            "by_level": level_stats,
        },
        "curriculum": curriculum_map,
    }


# ─── 4. Curriculum Management ─────────────────────────────────────────────────

@router.get("/curriculum")
async def list_curriculum(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """List all curriculum topics with full detail."""
    result = await db.execute(
        select(AiTopicCurriculum).order_by(AiTopicCurriculum.sequence_order)
    )
    topics = result.scalars().all()
    return {
        "total": len(topics),
        "topics": [
            {
                "id": t.id,
                "slug": t.slug,
                "title": t.title,
                "description": t.description,
                "level": t.level,
                "category": t.category,
                "sequence_order": t.sequence_order,
                "search_keywords": t.search_keywords,
                "learning_objectives": t.learning_objectives,
                "is_active": t.is_active,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in topics
        ],
    }


# ─── 5. Quality Score Summary ─────────────────────────────────────────────────

@router.get("/quality-summary")
async def get_quality_summary(
    days: int = Query(30, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """
    Aggregate quality score statistics for the past N days.
    Shows overall distribution and per-level breakdown.
    """
    since = datetime.utcnow() - timedelta(days=days)

    result = await db.execute(
        select(
            UserConceptProgress.quality_score,
            AiTopicCurriculum.level,
        )
        .join(AiTopicCurriculum, UserConceptProgress.topic_id == AiTopicCurriculum.id)
        .where(UserConceptProgress.taught_at >= since)
    )
    rows = result.fetchall()

    def _stats(score_list: list) -> dict:
        if not score_list:
            return {"count": 0, "avg": 0, "min": 0, "max": 0, "pass_rate_pct": 0}
        return {
            "count": len(score_list),
            "avg": round(sum(score_list) / len(score_list), 1),
            "min": min(score_list),
            "max": max(score_list),
            "pass_rate_pct": round(sum(1 for s in score_list if s >= 60) / len(score_list) * 100, 1),
        }

    if not rows:
        empty_stats = {"count": 0, "avg": 0, "min": 0, "max": 0, "pass_rate_pct": 0}
        return {
            "period_days": days,
            "total_sessions": 0,
            "overall": empty_stats,
            "by_level": {
                "Beginner": empty_stats,
                "Intermediate": empty_stats,
                "Advanced": empty_stats,
            },
            "score_distribution": {
                "excellent_80_plus": 0,
                "good_60_79": 0,
                "poor_below_60": 0,
            },
            "message": "No content generated in this period.",
        }

    scores = [r.quality_score for r in rows if r.quality_score is not None]
    by_level: dict = {"Beginner": [], "Intermediate": [], "Advanced": []}
    for row in rows:
        level = row.level or "Beginner"
        if level not in by_level:
            by_level[level] = []
        if row.quality_score is not None:
            by_level[level].append(row.quality_score)

    return {
        "period_days": days,
        "overall": _stats(scores),
        "by_level": {level: _stats(level_scores) for level, level_scores in by_level.items()},
        "score_distribution": {
            "excellent_80_plus": sum(1 for s in scores if s >= 80),
            "good_60_79": sum(1 for s in scores if 60 <= s < 80),
            "poor_below_60": sum(1 for s in scores if s < 60),
        },
    }


# ─── 6. AI Topic CRUD — Detail ─────────────────────────────────────────────────

@router.get("/curriculum/{topic_id}", response_model=AiTopicDetailResponse)
async def get_topic_detail(
    topic_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Full detail for a single curriculum topic — every editable field.
    Used to prefill the admin edit modal."""
    topic = await _get_topic_or_404(topic_id, db)
    return await _serialize_topic(topic, db)


# ─── 7. AI Topic CRUD — Create ─────────────────────────────────────────────────

@router.post("/curriculum", response_model=AiTopicActionResponse, status_code=201)
async def create_topic(
    payload: AiTopicCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Create a new AI curriculum topic and materialize its Learning Feed content."""
    slug = _validate_slug(payload.slug)

    duplicate = await db.execute(select(AiTopicCurriculum).where(AiTopicCurriculum.slug == slug))
    if duplicate.scalars().first():
        raise HTTPException(status_code=409, detail=f"A topic with slug '{slug}' already exists.")

    max_order_result = await db.execute(select(func.max(AiTopicCurriculum.sequence_order)))
    max_order = max_order_result.scalar() or 0
    sequence_order = payload.sequence_order if payload.sequence_order > 0 else max_order + 1

    topic = AiTopicCurriculum(
        slug=slug,
        title=payload.title.strip(),
        description=payload.description.strip(),
        level=payload.level,
        category=payload.category,
        sequence_order=sequence_order,
        search_keywords=payload.search_keywords,
        learning_objectives=payload.learning_objectives,
        is_active=payload.is_active,
    )
    db.add(topic)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail=f"A topic with slug '{slug}' already exists.")

    try:
        await _materialize_learning_feed(topic, db)
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Topic saved but failed to materialize Learning Feed content.")

    await db.commit()
    return {
        "message": f"Topic '{topic.title}' created successfully.",
        "id": topic.id,
        "slug": topic.slug,
        "title": topic.title,
        "is_active": topic.is_active,
    }


# ─── 8. AI Topic CRUD — Full Update ──────────────────────────────────────────

@router.put("/curriculum/{topic_id}", response_model=AiTopicActionResponse)
async def update_topic(
    topic_id: int,
    payload: AiTopicUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Fully update any field of a curriculum topic.
    Also re-materializes the linked Learning Feed path/lesson so user-facing
    content stays in sync with the edit."""
    topic = await _get_topic_or_404(topic_id, db)

    old_slug = topic.slug
    if payload.slug is not None:
        new_slug = _validate_slug(payload.slug)
        if new_slug != old_slug:
            duplicate = await db.execute(
                select(AiTopicCurriculum).where(
                    AiTopicCurriculum.slug == new_slug,
                    AiTopicCurriculum.id != topic_id,
                )
            )
            if duplicate.scalars().first():
                raise HTTPException(status_code=409, detail=f"A topic with slug '{new_slug}' already exists.")

    # Apply provided fields (None = leave unchanged)
    if payload.slug is not None:
        topic.slug = new_slug
    if payload.title is not None:
        topic.title = payload.title.strip()
    if payload.description is not None:
        topic.description = payload.description.strip()
    if payload.level is not None:
        topic.level = payload.level
    if payload.category is not None:
        topic.category = payload.category
    if payload.sequence_order is not None:
        topic.sequence_order = payload.sequence_order
    if payload.search_keywords is not None:
        topic.search_keywords = payload.search_keywords
    if payload.learning_objectives is not None:
        topic.learning_objectives = payload.learning_objectives
    if payload.is_active is not None:
        topic.is_active = payload.is_active

    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Update conflicts with an existing topic (duplicate slug or sequence).")

    try:
        await _materialize_learning_feed(topic, db)
    except Exception:
        await db.rollback()
        raise HTTPException(status_code=500, detail="Topic updated but failed to refresh Learning Feed content.")

    await db.commit()
    return {
        "message": f"Topic '{topic.title}' updated successfully.",
        "id": topic.id,
        "slug": topic.slug,
        "title": topic.title,
        "is_active": topic.is_active,
    }


class DeleteTopicRequest(BaseModel):
    """Optional body for delete — confirms destructive intent.
    If provided, must equal 'DELETE'."""
    confirmation: Optional[str] = None


# ─── 9. AI Topic CRUD — Delete ──────────────────────────────────────────────

@router.delete("/curriculum/{topic_id}", response_model=AiTopicActionResponse)
async def delete_topic(
    topic_id: int,
    payload: Optional[DeleteTopicRequest] = None,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Permanently delete a curriculum topic.
    Cascade: removes the topic's user-concept progress rows and its materialized
    Learning Feed path/lessons (with user lesson progress). This cannot be undone.
    Pass {"confirmation": "DELETE"} to acknowledge the destructive intent."""
    if payload and payload.confirmation and payload.confirmation.strip().upper() != "DELETE":
        raise HTTPException(
            status_code=400,
            detail="Delete confirmation must be the word 'DELETE'.",
        )

    topic = await _get_topic_or_404(topic_id, db)

    # 1. Count + remove user progress rows referencing this topic
    progress_count_result = await db.execute(
        select(func.count()).select_from(UserConceptProgress).where(UserConceptProgress.topic_id == topic_id)
    )
    progress_count = progress_count_result.scalar() or 0
    await db.execute(sa_delete(UserConceptProgress).where(UserConceptProgress.topic_id == topic_id))

    # 2. Remove the materialized path/lessons for this slug (any source_type:
    # legacy topic paths may carry "curriculum" from before the separation fix)
    path_id_result = await db.execute(
        select(LearningPath.id).where(
            LearningPath.curriculum_slug == topic.slug,
        )
    )
    path_id = path_id_result.scalars().first()
    deleted_learning_path = False
    if path_id:
        deleted_learning_path = await _delete_learning_feed(path_id, db)

    # 3. Remove the topic itself
    await db.execute(sa_delete(AiTopicCurriculum).where(AiTopicCurriculum.id == topic_id))

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Cannot delete topic: still referenced by other records.")

    return {
        "message": f"Topic '{topic.title}' permanently deleted.",
        "id": topic_id,
        "slug": topic.slug,
        "title": topic.title,
        "deleted": True,
        "deleted_progress_rows": progress_count,
        "deleted_learning_path": deleted_learning_path,
    }


# ─── 10. AI Topic CRUD — Toggle Active (existing, kept for compatibility) ────

@router.patch("/curriculum/{topic_id}/toggle", response_model=AiTopicActionResponse)
async def toggle_topic_active(
    topic_id: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Enable or disable a curriculum topic from being taught."""
    topic = await _get_topic_or_404(topic_id, db)

    topic.is_active = not topic.is_active
    await db.commit()
    return {
        "message": f"Topic {'enabled' if topic.is_active else 'disabled'} successfully.",
        "id": topic.id,
        "slug": topic.slug,
        "title": topic.title,
        "is_active": topic.is_active,
    }
