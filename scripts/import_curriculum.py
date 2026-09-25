"""Import the 98-lesson curriculum workbook into the Learning Feed."""

import argparse
import asyncio
import re
from importlib import import_module
from pathlib import Path
from typing import Any

from sqlalchemy import select, update

from app.db.models import AiTopicCurriculum, LearningPath, Lesson
from app.db.session import SessionLocal


HEADER_ALIASES = {
    "block number": "block_number",
    "block title": "block_title",
    "lesson number": "lesson_number",
    "lesson title": "lesson_title",
    "level": "level",
    "learning goal": "learning_goal",
    "what is it?": "what_is_it",
    "what is it": "what_is_it",
    "how does it work?": "how_does_it_work",
    "how does it work": "how_does_it_work",
    "real example": "real_example",
    "practice exercise": "practice_exercise",
    "what should i remember?": "what_should_i_remember",
    "what should i remember": "what_should_i_remember",
}


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _header_key(value: Any) -> str:
    return _clean(value).lower().replace("\n", " ")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _cards(row: dict[str, str]) -> list[dict[str, Any]]:
    return [
        {
            "id": "card_1",
            "cardType": "intro",
            "section": "what_is_it",
            "title": "What Is It?",
            "bodyText": row["what_is_it"],
        },
        {
            "id": "card_2",
            "cardType": "concept",
            "section": "how_does_it_work",
            "title": "How Does It Work?",
            "bodyText": row["how_does_it_work"],
        },
        {
            "id": "card_3",
            "cardType": "example",
            "section": "real_example_practice",
            "title": "Real Example / Practice Exercise",
            "bodyText": row["real_example"],
            "exampleData": {"practiceExercise": row["practice_exercise"]},
        },
        {
            "id": "card_4",
            "cardType": "takeaway",
            "section": "what_should_i_remember",
            "title": "What Should I Remember?",
            "bodyText": row["what_should_i_remember"],
        },
    ]


def read_rows(workbook_path: Path) -> list[dict[str, str]]:
    load_workbook = import_module("openpyxl").load_workbook
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    sheet = workbook.active
    values = list(sheet.values)
    if not values:
        raise ValueError("The workbook is empty.")

    headers = {}
    for index, value in enumerate(values[0]):
        key = HEADER_ALIASES.get(_header_key(value))
        if key:
            headers[key] = index

    required = set(HEADER_ALIASES.values())
    missing = sorted(required - set(headers))
    if missing:
        raise ValueError(f"Missing curriculum columns: {', '.join(missing)}")

    rows = []
    for values_row in values[1:]:
        row = {key: _clean(values_row[index] if index < len(values_row) else "") for key, index in headers.items()}
        if not row["lesson_number"] or not row["lesson_title"]:
            continue
        rows.append(row)

    lesson_numbers = [int(float(row["lesson_number"])) for row in rows]
    expected = list(range(1, 99))
    if sorted(lesson_numbers) != expected:
        raise ValueError("Expected exactly lesson numbers 1 through 98.")
    return rows


async def import_curriculum(workbook_path: Path) -> None:
    rows = read_rows(workbook_path)
    async with SessionLocal() as db:
        block_keys = set()
        for row in rows:
            lesson_number = int(float(row["lesson_number"]))
            block_number = int(float(row["block_number"]))
            block_key = f"block-{block_number}"
            block_keys.add(block_key)

            path_result = await db.execute(
                select(LearningPath).where(LearningPath.curriculum_slug == block_key)
            )
            path = path_result.scalars().first()
            if not path:
                path = LearningPath(curriculum_slug=block_key, source_type="curriculum")
                db.add(path)
                await db.flush()

            path.title = row["block_title"]
            path.description = f"{row['block_title']} curriculum"
            path.level = row["level"]
            path.source_type = "curriculum"

            lesson_result = await db.execute(
                select(Lesson).where(
                    Lesson.path_id == path.id,
                    Lesson.sequence_order == lesson_number,
                )
            )
            lesson = lesson_result.scalars().first()
            if not lesson:
                lesson = Lesson(path_id=path.id, sequence_order=lesson_number)
                db.add(lesson)

            lesson.title = row["lesson_title"]
            lesson.description = row["what_is_it"]
            lesson.learning_goal = row["learning_goal"]
            lesson.estimated_minutes = 5
            lesson.cards_data = _cards(row)

            topic_result = await db.execute(
                select(AiTopicCurriculum).where(
                    AiTopicCurriculum.sequence_order == lesson_number
                )
            )
            topic = topic_result.scalars().first()
            if not topic:
                topic = AiTopicCurriculum(
                    slug=f"curriculum-{lesson_number:03d}",
                    sequence_order=lesson_number,
                    search_keywords=[],
                    learning_objectives=[row["learning_goal"]],
                    is_active=True,
                )
                db.add(topic)
            topic.title = row["lesson_title"]
            topic.description = row["learning_goal"]
            topic.level = row["level"]
            topic.category = row["block_title"]
            topic.search_keywords = []
            topic.learning_objectives = [row["learning_goal"]]
            topic.is_active = True

        await db.flush()
        for block_key in block_keys:
            count_result = await db.execute(
                select(Lesson).join(LearningPath).where(LearningPath.curriculum_slug == block_key)
            )
            lessons = count_result.scalars().all()
            path_result = await db.execute(
                select(LearningPath).where(LearningPath.curriculum_slug == block_key)
            )
            path = path_result.scalars().first()
            path.total_lessons = len(lessons)
            path.total_minutes = len(lessons) * 5

        await db.execute(
            update(LearningPath)
            .where(
                LearningPath.source_type == "curriculum",
                LearningPath.curriculum_slug.notin_(block_keys),
            )
            .values(source_type="legacy")
        )
        await db.commit()

    print(f"Imported {len(rows)} curriculum lessons from {workbook_path}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    args = parser.parse_args()
    asyncio.run(import_curriculum(args.workbook))


if __name__ == "__main__":
    main()