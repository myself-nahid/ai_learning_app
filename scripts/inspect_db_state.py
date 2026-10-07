# -*- coding: utf-8 -*-
"""Inspect curriculum/quiz DB state (dev utility). Usage: python scripts/inspect_db_state.py"""
import asyncio
import sys

sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import func, select

from app.db.models import LearningPath, Lesson, QuizSet
from app.db.session import SessionLocal


async def main():
    async with SessionLocal() as db:
        res = await db.execute(
            select(LearningPath.source_type, func.count(LearningPath.id)).group_by(LearningPath.source_type)
        )
        print("PATHS by source_type:", res.all())
        res = await db.execute(
            select(LearningPath)
            .filter(LearningPath.source_type == "curriculum")
            .order_by(LearningPath.id)
        )
        for p in res.scalars().all():
            les_res = await db.execute(select(func.count(Lesson.id)).filter(Lesson.path_id == p.id))
            print(
                f"  path {p.id:4d} slug={p.curriculum_slug!r:20s} title={p.title!r:45s} "
                f"level={p.level!r:12s} lessons={les_res.scalar()}"
            )

        res = await db.execute(select(func.count(Lesson.id)).filter(Lesson.quiz_data.isnot(None)))
        print("lessons with quiz_data non-null:", res.scalar())
        res = await db.execute(select(func.count(Lesson.id)))
        print("total lessons:", res.scalar())

        res = await db.execute(select(func.count(QuizSet.id)))
        print("total QuizSets:", res.scalar())
        res = await db.execute(
            select(func.count(QuizSet.id)).filter(QuizSet.curriculum_lesson_id.isnot(None))
        )
        print("QuizSets linked to curriculum lessons:", res.scalar())


if __name__ == "__main__":
    asyncio.run(main())
