# -*- coding: utf-8 -*-
"""Post-import verification: quiz coverage, takeaway structure, QuizSet mirror."""
import asyncio
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from sqlalchemy import func, select  # noqa: E402

from app.db.models import (  # noqa: E402
    LearningPath,
    Lesson,
    QuizQuestion,
    QuizSet,
)
from app.db.session import SessionLocal  # noqa: E402


async def main() -> None:
    async with SessionLocal() as db:
        # Excel lessons
        res = await db.execute(
            select(Lesson)
            .join(LearningPath, Lesson.path_id == LearningPath.id)
            .where(LearningPath.curriculum_slug.like("excel-block-%"))
            .order_by(Lesson.id)
        )
        lessons = res.scalars().all()
        print(f"excel-block lessons: {len(lessons)}")

        with_quiz = [l for l in lessons if isinstance(l.quiz_data, list) and l.quiz_data]
        print(f"lessons with authored quiz: {len(with_quiz)}")

        # QuizSet mirror
        res = await db.execute(
            select(func.count(QuizSet.id)).where(QuizSet.curriculum_lesson_id.isnot(None))
        )
        print("QuizSets mirrored:", res.scalar())
        res = await db.execute(
            select(QuizSet.category, func.count(QuizSet.id))
            .where(QuizSet.curriculum_lesson_id.isnot(None))
            .group_by(QuizSet.category)
        )
        print("by category:", res.all())
        res = await db.execute(
            select(func.count(QuizQuestion.id)).where(
                QuizQuestion.quiz_set_id.in_(
                    select(QuizSet.id).where(QuizSet.curriculum_lesson_id.isnot(None))
                )
            )
        )
        print("mirrored questions:", res.scalar())

        # Sample one
        l1 = lessons[0]
        print("sample lesson:", l1.id, l1.title)
        q = (l1.quiz_data or [{}])[0]
        print("  quiz correct:", q.get("correct_option_key"), "| opts:", len(q.get("options") or {}))
        c4 = next((c for c in (l1.cards_data or []) if c.get("cardType") == "takeaway"), {})
        print("  takeaway body:", repr((c4.get("bodyText") or "")[:60]))
        print("  takeaway extra keys:", sorted(set(c4.keys()) - {"id", "cardType", "section", "title", "bodyText"}))

        # No None leakage
        bad = 0
        for l in lessons:
            for c in (l.cards_data or []):
                body = str(c.get("bodyText") or "")
                if any(word == "None" for word in body.split()):
                    bad += 1
        print("cards containing literal None word:", bad)

        # takeawayData present?
        with_td = sum(
            1 for l in lessons
            for c in (l.cards_data or [])
            if c.get("cardType") == "takeaway" and isinstance(c.get("takeawayData"), dict)
        )
        print("takeaway cards with takeawayData:", with_td)


if __name__ == "__main__":
    asyncio.run(main())
