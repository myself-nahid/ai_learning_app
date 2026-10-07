# -*- coding: utf-8 -*-
"""
Run the shared excel importer directly against the live DB:
  python scripts/run_excel_import.py [workbook.xlsx]

Idempotent: block/lesson upserts match by slug + sequence order, and quiz
mirroring only rewrites question rows when authored content changed.
"""
import asyncio
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.services.excel_import_service import (  # noqa: E402
    parse_uploaded_workbook,
    upsert_lessons,
)

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "TodAI_Lessons_1-98 Optimized.xlsx"


async def main(workbook_path: Path) -> None:
    data = workbook_path.read_bytes()
    lessons = parse_uploaded_workbook(data)
    print(f"Parsed {len(lessons)} lessons from {workbook_path.name}")

    async with SessionLocal() as db:
        summary = await upsert_lessons(db, lessons)
        await db.commit()

    print("Summary:", summary)


if __name__ == "__main__":
    wb = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    asyncio.run(main(wb))
