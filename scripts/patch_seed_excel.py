# -*- coding: utf-8 -*-
"""One-time patch v3: make seed_excel_curriculum share excel_import_service's
parser (quiz + takeaway structure + cleaning), then sync lesson quizzes after
upsert so the Daily Pulse quiz survives every backend restart.

Robust against CRLF: every anchor is located in the ORIGINAL source before any
splice, and splices go back-to-front so earlier indices stay valid.
"""
import ast
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PATH = "app/db/seed_excel_curriculum.py"
src = open(PATH, "rb").read().decode("utf-8")

if "parse_uploaded_workbook" in src:
    print("Already patched; nothing to do.")
    sys.exit(0)


def find_unique(s: str, needle: str) -> int:
    n = s.count(needle)
    assert n == 1, f"anchor not unique ({n}): {needle[:60]!r}"
    return s.index(needle)


# Normalize: work on LF text, write back LF (git/django style; Python doesn't
# care about endings, and this avoids mixed-ending creep in a CRLF file).
lf = src.replace("\r\n", "\n")

# ---- Locate anchors in the LF original ----
const_anchor = "COL_WHAT_SHOULD_I_REMEMBER = 11"
const_idx = find_unique(lf, const_anchor)

def_marker = "def parse_excel_curriculum() -> list[dict]:"
def_idx = find_unique(lf, def_marker)
doc_start = lf.index('"""', def_idx)
doc_end = lf.index('"""', doc_start + 3) + 3

tail_marker = "\nasync def seed_excel_learning_paths(db_session_factory) -> None:"
tail_idx = find_unique(lf, tail_marker)

commit_anchor = ('        await db.commit()\n'
                 '        logger.info(\n'
                 '            "Excel curriculum seeding complete: %d blocks, %d total lessons.",\n'
                 '            len(blocks),\n'
                 '            len(lessons),\n'
                 '        )')
commit_idx = find_unique(lf, commit_anchor)
assert def_idx < doc_end < tail_idx < commit_idx, "anchor ordering unexpected"

new_parse = '''def parse_excel_curriculum() -> list[dict]:
    """
    Parse the Excel file into the shared importer's lesson-dict shape.

    Parsing (cards, quiz column, remember-card restructuring, cell cleaning)
    lives in app.services.excel_import_service, so the startup seeder, the
    admin Excel upload endpoint, and the import script always produce
    identical cards and quiz data.

    Returns: [
      {
        "block_number": 1,
        "block_title": "AI Foundations",
        "lesson_number": 1,
        "lesson_title": "Your First Real Task With AI",
        "level": "Beginner",
        "learning_goal": "...",
        "cards": [...],          # 4 fixed cards (quiz + structured takeaway)
        "quiz": [...],           # Lesson.quiz_data (absent when no quiz cell)
        "takeaway_data": {...},  # keyTakeaways / goldenRule / nextStep
      },
      ...
    ]
    """
    from app.services.excel_import_service import parse_uploaded_workbook

    try:
        raw_bytes = excel_path.read_bytes()
    except OSError as e:
        logger.warning("Could not read Excel curriculum file %s: %s", excel_path, e)
        return []

    parsed = parse_uploaded_workbook(raw_bytes)
    logger.info("Parsed %d lessons from Excel curriculum.", len(parsed))
    return parsed

'''

new_commit = '''        # Mirror every lesson's authored quiz into QuizSet/QuizQuestion so the
        # Daily Pulse quiz stage keeps working after restarts.
        from app.services.lesson_quiz_service import sync_lesson_quiz_set

        all_db_lessons_res = await db.execute(
            select(Lesson)
            .join(LearningPath, Lesson.path_id == LearningPath.id)
            .where(LearningPath.curriculum_slug.like("excel-block-%"))
        )
        synced = 0
        for db_lesson in all_db_lessons_res.scalars().all():
            try:
                await sync_lesson_quiz_set(db, db_lesson)
                synced += 1
            except Exception as e:  # noqa: BLE001 — keep seeding alive
                logger.warning(
                    "Quiz sync failed for lesson %s ('%s'): %s",
                    db_lesson.id, db_lesson.title, e,
                )

        await db.commit()
        logger.info(
            "Excel curriculum seeding complete: %d blocks, %d total lessons, "
            "%d quiz sync checks.",
            len(blocks),
            len(lessons),
            synced,
        )'''

# ---- Splice back-to-front (later indices first) ----
out = lf[:commit_idx] + new_commit + lf[commit_idx + len(commit_anchor):]
out = out[:def_idx] + new_parse + out[tail_idx:]
out = out.replace(const_anchor, const_anchor + "\nCOL_QUIZ = 13")

ast.parse(out)
open(PATH, "wb").write(out.encode("utf-8"))
print("seed_excel_curriculum.py patched (v3, LF) and parses OK")
