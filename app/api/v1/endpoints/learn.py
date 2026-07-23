from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from datetime import datetime, timedelta
import math

from app.api.deps import get_db, get_current_user
from app.db.models import User, LearningPath, Lesson, UserLessonProgress, WeeklyActivity
from app.schemas.learn import (
    LearnDashboardResponse, PathDetailResponse, LessonContentResponse
)

router = APIRouter(prefix="/learn", tags=["Learn Section"])

# 1. GET LEARN DASHBOARD (Screen 1)
@router.get("/dashboard", response_model=LearnDashboardResponse)
async def get_learn_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Fetch Weekly Activity (Mocked calculation for brevity)
    # In production, find the current week's Monday and fetch WeeklyActivity
    weekly_stats = {
        "lessons_completed": 4,
        "minutes_spent": 28,
        "streak_days": 4,
        "days_active": {"mon": True, "tue": True, "wed": True, "thu": True, "fri": False, "sat": False, "sun": False}
    }

    # Fetch "Continue Learning" (Most recently accessed in_progress lesson)
    prog_res = await db.execute(
        select(UserLessonProgress)
        .filter(UserLessonProgress.user_id == current_user.id, UserLessonProgress.status == "in_progress")
        .order_by(UserLessonProgress.last_accessed.desc())
    )
    active_progress = prog_res.scalars().first()
    
    continue_learning = None
    if active_progress:
        # Load associated lesson and path
        lesson_res = await db.execute(select(Lesson).filter(Lesson.id == active_progress.lesson_id))
        lesson = lesson_res.scalars().first()
        path_res = await db.execute(select(LearningPath).filter(LearningPath.id == active_progress.path_id))
        path = path_res.scalars().first()
        
        total_cards = len(lesson.cards_data)
        continue_learning = {
            "lesson_id": lesson.id,
            "path_title": path.title,
            "lesson_title": lesson.title,
            "progress_percentage": int((active_progress.cards_completed / total_cards) * 100),
            "cards_completed": active_progress.cards_completed,
            "total_cards": total_cards,
            "minutes_remaining": max(1, lesson.estimated_minutes - int((active_progress.cards_completed/total_cards)*lesson.estimated_minutes)),
            "image_url": path.image_url
        }

    # Fetch Paths
    paths_res = await db.execute(select(LearningPath))
    paths = paths_res.scalars().all()
    
    # Format Paths (In production, calculate progress per path)
    learning_paths = []
    for p in paths:
        learning_paths.append({
            "path_id": p.id, "title": p.title, "level": p.level,
            "total_lessons": p.total_lessons, "total_minutes": p.total_minutes,
            "progress_percentage": 40, # Mocked
            "image_url": p.image_url
        })

    return {
        "weekly_stats": weekly_stats,
        "continue_learning": continue_learning,
        "learning_paths": learning_paths,
        "recommended_lessons": []
    }

# 2. GET PATH DETAILS (Screen 2)
@router.get("/paths/{path_id}", response_model=PathDetailResponse)
async def get_path_details(
    path_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    path_res = await db.execute(select(LearningPath).options(selectinload(LearningPath.lessons)).filter(LearningPath.id == path_id))
    path = path_res.scalars().first()
    if not path: raise HTTPException(status_code=404)

    # Get user progress for all lessons in this path
    prog_res = await db.execute(select(UserLessonProgress).filter(UserLessonProgress.user_id == current_user.id, UserLessonProgress.path_id == path_id))
    progress_map = {p.lesson_id: p for p in prog_res.scalars().all()}

    formatted_lessons = []
    for lesson in path.lessons:
        prog = progress_map.get(lesson.id)
        # Default status logic: Lesson 1 is unlocked, others are locked
        status = "locked"
        cards_done = 0
        if prog:
            status = prog.status
            cards_done = prog.cards_completed
        elif lesson.sequence_order == 1:
            status = "in_progress" # Auto-unlock first lesson

        formatted_lessons.append({
            "lesson_id": lesson.id,
            "sequence_order": lesson.sequence_order,
            "title": lesson.title,
            "description": lesson.description,
            "total_cards": len(lesson.cards_data),
            "cards_completed": cards_done,
            "estimated_minutes": lesson.estimated_minutes,
            "status": status
        })

    return {
        "path_id": path.id, "title": path.title, "description": path.description,
        "level": path.level, "progress_percentage": 40,
        "lessons": formatted_lessons
    }

# 3. START/RESUME LESSON (Screens 3-8)
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
    
    # Ensure progress tracking exists
    prog_res = await db.execute(
        select(UserLessonProgress).filter(
            UserLessonProgress.user_id == current_user.id, 
            UserLessonProgress.lesson_id == lesson_id
        )
    )
    progress = prog_res.scalars().first()
    
    if not progress:
        progress = UserLessonProgress(
            user_id=current_user.id, 
            lesson_id=lesson.id, 
            path_id=lesson.path_id, 
            status="in_progress"
        )
        db.add(progress)
        await db.commit()
        
        # --- FIX ADDED HERE ---
        # Reload the objects so they aren't 'expired' by the commit!
        await db.refresh(lesson)
        await db.refresh(progress)
        # ----------------------

    return {
        "lesson_id": lesson.id,
        "title": lesson.title,
        "total_cards": len(lesson.cards_data),
        "current_card_index": progress.cards_completed,
        "cards": lesson.cards_data
    }

# 4. SAVE CARD PROGRESS (As user taps "Continue")
@router.post("/lessons/{lesson_id}/progress")
async def update_lesson_progress(
    lesson_id: int,
    card_index: int, # The index of the card they just finished reading
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    prog_res = await db.execute(select(UserLessonProgress).filter(UserLessonProgress.user_id == current_user.id, UserLessonProgress.lesson_id == lesson_id))
    progress = prog_res.scalars().first()
    
    if progress and progress.cards_completed < card_index:
        progress.cards_completed = card_index
        progress.last_accessed = datetime.utcnow()
        await db.commit()
    
    return {"status": "saved"}

# 5. COMPLETE LESSON (Screen 8 action)
@router.post("/lessons/{lesson_id}/complete")
async def complete_lesson(
    lesson_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # Mark current lesson as completed
    prog_res = await db.execute(select(UserLessonProgress).filter(UserLessonProgress.user_id == current_user.id, UserLessonProgress.lesson_id == lesson_id))
    progress = prog_res.scalars().first()
    progress.status = "completed"
    
    # Unlock Next Lesson Logic
    lesson_res = await db.execute(select(Lesson).filter(Lesson.id == lesson_id))
    current_lesson = lesson_res.scalars().first()
    
    next_lesson_res = await db.execute(
        select(Lesson).filter(Lesson.path_id == current_lesson.path_id, Lesson.sequence_order == current_lesson.sequence_order + 1)
    )
    next_lesson = next_lesson_res.scalars().first()
    
    if next_lesson:
        new_prog = UserLessonProgress(user_id=current_user.id, lesson_id=next_lesson.id, path_id=next_lesson.path_id, status="in_progress")
        db.add(new_prog)

    # In production: Update WeeklyActivity and XP/Streak here!

    await db.commit()
    return {"status": "success", "message": "Lesson completed and next lesson unlocked!"}


@router.post("/test/seed-learn-data")
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