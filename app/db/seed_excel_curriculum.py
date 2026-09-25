"""
seed_excel_curriculum.py

Reads the TodAI Excel curriculum (Lessons 1-98) and seeds LearningPaths + Lessons
into the database. Each Excel 'Block' becomes a LearningPath; each 'Lesson' row
becomes a Lesson with the 4-card structure:
  1. What Is It?          (intro card)
  2. How Does It Work?    (concept card)
  3. Real Example / Practice Exercise (example card)
  4. What Should I Remember?          (takeaway card)

The Learning Goal is stored on the Lesson.learning_goal field and is NOT presented
as a user-facing card.

This module can be run standalone or imported and called from init_db.
"""
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

EXCEL_PATH = Path(__file__).parent.parent.parent.parent / "TodAI_Lessons_1-98 Optimized.xlsx"

# Col indices (1-based)
COL_BLOCK_NUM = 1
COL_BLOCK_TITLE = 2
COL_LESSON_NUM = 3
COL_LESSON_TITLE = 4
COL_LEVEL = 5
COL_LEARNING_GOAL = 6
COL_WHAT_IS_IT = 7
COL_HOW_DOES_IT_WORK = 8
COL_REAL_EXAMPLE = 9
COL_PRACTICE_EXERCISE = 10
COL_WHAT_SHOULD_I_REMEMBER = 11


def _str(val) -> str:
    """Safely convert a cell value to a clean string."""
    if val is None:
        return ""
    return str(val).strip()


def _build_lesson_cards(row_data: dict) -> list[dict]:
    """
    Build the 4-card structured lesson flow from a row of Excel data.
    The Learning Goal is excluded from card flow (stored separately).

    Cards follow the fixed structure:
      Card 1: What Is It?            (intro)
      Card 2: How Does It Work?      (concept)
      Card 3: Real Example / Practice Exercise (example)
      Card 4: What Should I Remember? (takeaway)
    """
    what_is_it = _str(row_data.get("what_is_it"))
    how_does_it_work = _str(row_data.get("how_does_it_work"))
    real_example = _str(row_data.get("real_example"))
    practice_exercise = _str(row_data.get("practice_exercise"))
    what_should_remember = _str(row_data.get("what_should_remember"))

    # Combine real_example + practice_exercise into one card body
    example_body = ""
    if real_example and practice_exercise:
        example_body = f"{real_example}\n\n---\n\n**Practice Exercise**\n{practice_exercise}"
    elif real_example:
        example_body = real_example
    elif practice_exercise:
        example_body = practice_exercise
    else:
        example_body = "Apply what you've learned to a real scenario."

    cards = [
        {
            "id": "card_1",
            "cardType": "intro",
            "section": "what_is_it",
            "title": "What Is It?",
            "bodyText": what_is_it or "Explore this concept.",
        },
        {
            "id": "card_2",
            "cardType": "concept",
            "section": "how_does_it_work",
            "title": "How Does It Work?",
            "bodyText": how_does_it_work or "Understand the mechanics behind this concept.",
        },
        {
            "id": "card_3",
            "cardType": "example",
            "section": "real_example",
            "title": "Real Example / Practice Exercise",
            "bodyText": example_body,
        },
        {
            "id": "card_4",
            "cardType": "takeaway",
            "section": "remember",
            "title": "What Should I Remember?",
            "bodyText": what_should_remember or "Reflect on the key insight from this lesson.",
        },
    ]
    return cards


def parse_excel_curriculum() -> list[dict]:
    """
    Parse the Excel file and return a list of lesson dicts grouped by block.
    Returns: [
      {
        "block_number": 1,
        "block_title": "AI Foundations",
        "lesson_number": 1,
        "lesson_title": "Your First Real Task With AI",
        "level": "Beginner",
        "learning_goal": "...",
        "cards": [...],
      },
      ...
    ]
    """
    try:
        import openpyxl
    except ImportError:
        logger.error(
            "openpyxl is not installed. Cannot seed Excel curriculum. "
            "Run: pip install openpyxl"
        )
        return []

    excel_path = EXCEL_PATH
    if not excel_path.exists():
        # Try relative from current working directory
        cwd_path = Path(os.getcwd()) / "TodAI_Lessons_1-98 Optimized.xlsx"
        if cwd_path.exists():
            excel_path = cwd_path
        else:
            logger.warning(
                "Excel curriculum file not found at %s. Skipping Excel seeding.",
                excel_path,
            )
            return []

    wb = openpyxl.load_workbook(excel_path, read_only=True, data_only=True)
    ws = wb.active

    lessons = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        block_num = row[COL_BLOCK_NUM - 1]
        block_title = row[COL_BLOCK_TITLE - 1]
        lesson_num = row[COL_LESSON_NUM - 1]
        lesson_title = row[COL_LESSON_TITLE - 1]
        level = row[COL_LEVEL - 1]
        learning_goal = row[COL_LEARNING_GOAL - 1]
        what_is_it = row[COL_WHAT_IS_IT - 1]
        how_does_it_work = row[COL_HOW_DOES_IT_WORK - 1]
        real_example = row[COL_REAL_EXAMPLE - 1]
        practice_exercise = row[COL_PRACTICE_EXERCISE - 1]
        what_should_remember = row[COL_WHAT_SHOULD_I_REMEMBER - 1]

        # Skip empty rows
        if not lesson_title:
            continue

        row_data = {
            "what_is_it": what_is_it,
            "how_does_it_work": how_does_it_work,
            "real_example": real_example,
            "practice_exercise": practice_exercise,
            "what_should_remember": what_should_remember,
        }

        cards = _build_lesson_cards(row_data)

        lessons.append(
            {
                "block_number": block_num,
                "block_title": _str(block_title),
                "lesson_number": int(lesson_num) if lesson_num else 0,
                "lesson_title": _str(lesson_title),
                "level": _str(level).strip(),
                "learning_goal": _str(learning_goal),
                "cards": cards,
            }
        )

    wb.close()
    logger.info("Parsed %d lessons from Excel curriculum.", len(lessons))
    return lessons


async def seed_excel_learning_paths(db_session_factory) -> None:
    """
    Seed LearningPaths and Lessons from the Excel curriculum file.

    - One LearningPath per Excel Block (identified by block_number + block_title).
    - One Lesson per row, with sequence_order = lesson_number within the block.
    - Each Lesson gets 4 structured cards.
    - Existing paths/lessons are UPDATED (not duplicated) based on curriculum_slug.
    - This is the authoritative source for the Learning Feed.
    """
    from sqlalchemy import select
    from app.db.models import LearningPath, Lesson

    lessons = parse_excel_curriculum()
    if not lessons:
        logger.warning("No lessons parsed from Excel. Skipping Excel curriculum seeding.")
        return

    # Group by block
    blocks: dict[int, dict] = {}
    for l in lessons:
        bn = l["block_number"]
        if bn not in blocks:
            blocks[bn] = {
                "title": l["block_title"],
                "level": l["level"],
                "lessons": [],
            }
        blocks[bn]["lessons"].append(l)

    async with db_session_factory() as db:
        for block_num, block_data in sorted(blocks.items()):
            slug = f"excel-block-{block_num}"
            block_title = block_data["title"]
            block_level = block_data["level"] or "Beginner"
            block_lessons = block_data["lessons"]
            total_lessons = len(block_lessons)
            total_minutes = total_lessons * 5  # 5 min per lesson

            # Find or create the LearningPath for this block
            path_res = await db.execute(
                select(LearningPath).where(LearningPath.curriculum_slug == slug)
            )
            path = path_res.scalars().first()

            if not path:
                path = LearningPath(
                    title=block_title,
                    description=f"A structured learning block covering {block_title}.",
                    level=block_level,
                    total_lessons=total_lessons,
                    total_minutes=total_minutes,
                    source_type="curriculum",
                    curriculum_slug=slug,
                )
                db.add(path)
                await db.flush()
                logger.info("Created LearningPath: [Block %d] %s", block_num, block_title)
            else:
                # Update metadata
                path.title = block_title
                path.level = block_level
                path.total_lessons = total_lessons
                path.total_minutes = total_minutes
                path.source_type = "curriculum"

            # Upsert lessons for this block
            for lesson_data in block_lessons:
                seq_order = lesson_data["lesson_number"]
                lesson_title = lesson_data["lesson_title"]
                learning_goal = lesson_data["learning_goal"]
                cards = lesson_data["cards"]
                level = lesson_data["level"] or block_level

                lesson_res = await db.execute(
                    select(Lesson).where(
                        Lesson.path_id == path.id,
                        Lesson.sequence_order == seq_order,
                    )
                )
                lesson = lesson_res.scalars().first()

                if not lesson:
                    lesson = Lesson(
                        path_id=path.id,
                        sequence_order=seq_order,
                    )
                    db.add(lesson)

                lesson.title = lesson_title
                lesson.description = learning_goal
                lesson.learning_goal = learning_goal
                lesson.estimated_minutes = 5
                lesson.cards_data = cards

        await db.commit()
        logger.info(
            "Excel curriculum seeding complete: %d blocks, %d total lessons.",
            len(blocks),
            len(lessons),
        )
