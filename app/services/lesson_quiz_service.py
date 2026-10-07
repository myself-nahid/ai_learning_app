# -*- coding: utf-8 -*-
"""
Shared upkeep for per-lesson (curriculum) quizzes.

Both the admin API (authoring via the bashboard) and the Excel curriculum
import write the same shape:
  Lesson.quiz_data = [{question_text, options: {"A": ..}, correct_option_key, explanation?}]
  + a mirrored QuizSet (curriculum_lesson_id=lesson.id) + QuizQuestion rows.

Mirroring into QuizSet/QuizQuestion is what the mobile app already knows how
to serve, score and award XP for (POST /quiz-tab/start/{id} etc.).
"""
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LearningPath, Lesson, QuizAttempt, QuizQuestion, QuizSet


async def sync_lesson_quiz_set(db: AsyncSession, lesson: Lesson) -> Optional[int]:
    """Create/update (or remove) the QuizSet linked to a curriculum lesson.

    Returns the QuizSet id, or None when the lesson has no authored quiz.
    """
    path_res = await db.execute(select(LearningPath).filter(LearningPath.id == lesson.path_id))
    path = path_res.scalars().first()

    qs_res = await db.execute(select(QuizSet).filter(QuizSet.curriculum_lesson_id == lesson.id))
    quiz_set = qs_res.scalars().first()

    questions = lesson.quiz_data if isinstance(lesson.quiz_data, list) else []
    if not questions:
        if quiz_set:
            # Quiz cleared — remove questions + set so the app stops serving it
            old_q_res = await db.execute(
                select(QuizQuestion).filter(QuizQuestion.quiz_set_id == quiz_set.id)
            )
            for old_q in old_q_res.scalars().all():
                await db.delete(old_q)
            await db.delete(quiz_set)
        return None

    level = (path.level if path else None) or "Beginner"
    title = f"Lesson Quiz: {(lesson.title or 'Lesson')[:70]}"
    est_minutes = max(2, int(len(questions) * 1.5))
    xp_reward = 10 + len(questions) * 2

    if not quiz_set:
        quiz_set = QuizSet(
            category="Curriculum",
            title=title,
            description=(lesson.learning_goal or f"Check your understanding of '{lesson.title}'.")[:300],
            level=level,
            total_questions=len(questions),
            estimated_minutes=est_minutes,
            xp_reward=xp_reward,
            curriculum_lesson_id=lesson.id,
        )
        db.add(quiz_set)
        await db.flush()
    else:
        quiz_set.title = title
        quiz_set.level = level
        quiz_set.total_questions = len(questions)
        quiz_set.estimated_minutes = est_minutes
        quiz_set.xp_reward = xp_reward

    # Recreate question rows only when the authored content actually changed,
    # so repeated imports (and the startup seeder) don't churn QuizQuestion ids
    # that completed attempts reference in their stored user_answers.
    new_rows = [
        (
            q["question_text"],
            q["options"],
            q["correct_option_key"],
            q.get("explanation"),
        )
        for q in questions
    ]
    old_q_res = await db.execute(
        select(QuizQuestion)
        .filter(QuizQuestion.quiz_set_id == quiz_set.id)
        .order_by(QuizQuestion.id)
    )
    old_rows = [
        (q.question_text, q.options, q.correct_option_key, q.explanation)
        for q in old_q_res.scalars().all()
    ]
    if new_rows == old_rows:
        return quiz_set.id

    for old_q in old_q_res.scalars().all():
        await db.delete(old_q)
    await db.flush()

    for q in questions:
        db.add(QuizQuestion(
            quiz_set_id=quiz_set.id,
            question_text=q["question_text"],
            options=q["options"],
            correct_option_key=q["correct_option_key"],
            explanation=q.get("explanation"),
        ))
    return quiz_set.id


async def delete_quiz_sets_for_lessons(db: AsyncSession, lesson_ids: List[int]) -> None:
    """Remove per-lesson QuizSets (and their questions/attempts) for lessons
    that are being deleted. Attempt rows hold a NOT NULL FK to quiz_sets,
    so they are removed explicitly first."""
    if not lesson_ids:
        return
    qs_res = await db.execute(
        select(QuizSet).filter(QuizSet.curriculum_lesson_id.in_(lesson_ids))
    )
    for quiz_set in qs_res.scalars().all():
        q_res = await db.execute(
            select(QuizQuestion).filter(QuizQuestion.quiz_set_id == quiz_set.id)
        )
        for q in q_res.scalars().all():
            await db.delete(q)
        # Attempts hold a NOT NULL FK to quiz_sets — remove them too.
        await db.execute(
            QuizAttempt.__table__.delete().where(
                QuizAttempt.quiz_set_id == quiz_set.id
            )
        )
        await db.delete(quiz_set)
