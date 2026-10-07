# -*- coding: utf-8 -*-
"""One-time patch: delegate admin.py quiz helpers to app.services.lesson_quiz_service."""
import ast
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

PATH = "app/api/v1/endpoints/admin.py"
src = open(PATH, "rb").read().decode("utf-8")

# ---- 1. Replace _delete_quiz_sets_for_lessons body with service delegation ----
pat_delete = re.compile(
    r"async def _delete_quiz_sets_for_lessons\(db: AsyncSession, lesson_ids: list\) -> None:\n(?:(?!\n\n\nasync def _sync_lesson_quiz_set).)*?\n(?=\n\nasync def _sync_lesson_quiz_set)",
    re.DOTALL,
)
new_delete = (
    "async def _delete_quiz_sets_for_lessons(db: AsyncSession, lesson_ids: list) -> None:\n"
    "    \"\"\"Remove the QuizSet (+ its questions) authored for the given lessons.\n"
    "\n"
    "    Prevents orphan quiz sets that would otherwise keep serving a deleted\n"
    "    lesson's quiz in the app (quiz sets are looked up by curriculum_lesson_id).\n"
    "    \"\"\"\n"
    "    from app.services.lesson_quiz_service import delete_quiz_sets_for_lessons\n"
    "    await delete_quiz_sets_for_lessons(db, lesson_ids)"
)
src, n_del = pat_delete.subn(new_delete, src)
print("delete-helper replacements:", n_del)
if n_del != 1:
    sys.exit("FAILED: delete helper anchor not found exactly once")

# ---- 2. Replace _sync_lesson_quiz_set body with service delegation ----
pat_sync = re.compile(
    r"async def _sync_lesson_quiz_set\(db: AsyncSession, lesson: Lesson\) -> Optional\[int\]:\n(?:(?!\n\n\n@router\.get\(\"/curriculum/lessons/\{lesson_id\}/quiz\"\)).)*",
    re.DOTALL,
)
new_sync = (
    "async def _sync_lesson_quiz_set(db: AsyncSession, lesson: Lesson) -> Optional[int]:\n"
    "    \"\"\"Create/update (or remove) the QuizSet linked to a curriculum lesson.\n"
    "\n"
    "    The linked QuizSet is what the mobile app already knows how to serve,\n"
    "    score, and award XP for (POST /quiz-tab/start/{id} etc.).\n"
    "    \"\"\"\n"
    "    from app.services.lesson_quiz_service import sync_lesson_quiz_set\n"
    "    return await sync_lesson_quiz_set(db, lesson)\n"
)
src, n_sync = pat_sync.subn(new_sync, src)
print("sync-helper replacements:", n_sync)
if n_sync != 1:
    sys.exit("FAILED: sync helper anchor not found exactly once")

open(PATH, "wb").write(src.encode("utf-8"))
ast.parse(src)
print("admin.py patched and parses OK")
