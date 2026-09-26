# -*- coding: utf-8 -*-
"""
excel_import_service.py

Parses uploaded Excel curriculum files (same 11-column layout as
TodAI_Lessons_1-98 Optimized.xlsx) and upserts them into the database.

Blocks/lessons are matched by block number + lesson number, so re-uploading
an updated file refreshes existing rows instead of duplicating them. Blocks
are stored with the "excel-block-" slug prefix, which keeps them grouped with
the authoritative Excel curriculum (listed first in the admin UI, prioritized
in the Learning Feed, editable in the Lesson Content tab).

Parsing strategy: openpyxl when available; otherwise a dependency-free
fallback that reads the .xlsx directly (it is a zip of XML files), so Excel
upload works on any server environment.
"""
import io
import logging
import re
import zipfile
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

# Same column layout as the original file (1-based indices).
_COL_BLOCK_NUM = 1
_COL_BLOCK_TITLE = 2
_COL_LESSON_NUM = 3
_COL_LESSON_TITLE = 4
_COL_LEVEL = 5
_COL_LEARNING_GOAL = 6
_COL_WHAT_IS_IT = 7
_COL_HOW_DOES_IT_WORK = 8
_COL_REAL_EXAMPLE = 9
_COL_PRACTICE_EXERCISE = 10
_COL_WHAT_SHOULD_I_REMEMBER = 11

_EXCEL_SLUG_PREFIX = "excel-block-"


def _str(val) -> str:
    if val is None:
        return ""
    return str(val).strip()


# ── Row extraction (openpyxl first, stdlib fallback second) ─────────────────


def _rows_via_openpyxl(file_bytes: bytes) -> List[List[Any]]:
    import openpyxl

    wb = openpyxl.load_workbook(
        io.BytesIO(file_bytes), read_only=True, data_only=True
    )
    ws = wb.active
    rows = [list(row) for row in ws.iter_rows(values_only=True)]
    wb.close()
    return rows


_COL_LETTER_RE = re.compile(r"^([A-Z]+)")


def _col_index_from_ref(ref: str) -> int:
    """'BC12' -> 55 (1-based column index from the cell reference)."""
    m = _COL_LETTER_RE.match(ref or "")
    if not m:
        return 0
    idx = 0
    for ch in m.group(1):
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx


def _rows_via_stdlib(file_bytes: bytes) -> List[List[Any]]:
    """
    Minimal .xlsx reader using only the standard library.

    A workbook is a zip: shared strings live in xl/sharedStrings.xml and the
    first worksheet in xl/worksheets/sheet1.xml. Cell values are resolved
    (shared/inline/formula/number/bool) into plain Python values.
    """
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel_ns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    pkg_rel_ns = "{http://schemas.openxmlformats.org/package/2006/relationships}"

    with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
        # Shared strings
        shared: List[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{ns}si"):
                # Rich text: concatenate all <t> descendants.
                parts = [t.text or "" for t in si.iter(f"{ns}t")]
                shared.append("".join(parts))

        # First worksheet: resolve via workbook.xml + rels when possible,
        # else fall back to sheet1.xml / first worksheet part.
        sheet_target: Optional[str] = None
        try:
            wb_root = ElementTree.fromstring(z.read("xl/workbook.xml"))
            first_sheet = wb_root.find(f"{ns}sheets/{ns}sheet")
            if first_sheet is not None:
                rid = first_sheet.attrib.get(f"{rel_ns}id")
                if rid:
                    rels_root = ElementTree.fromstring(z.read("xl/_rels/workbook.xml.rels"))
                    for rel in rels_root.findall(f"{pkg_rel_ns}Relationship"):
                        if rel.attrib.get("Id") == rid:
                            target = rel.attrib.get("Target", "")
                            target = target.lstrip("/")
                            if not target.startswith("xl/"):
                                target = f"xl/{target}"
                            sheet_target = target
                            break
        except (KeyError, ElementTree.ParseError):
            pass

        if not sheet_target:
            candidates = sorted(
                n for n in z.namelist()
                if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)
            )
            if not candidates:
                raise ValueError("The workbook contains no worksheets.")
            sheet_target = candidates[0]

        sheet_root = ElementTree.fromstring(z.read(sheet_target))

        rows: List[List[Any]] = []
        for row_el in sheet_root.iter(f"{ns}row"):
            row_cells: Dict[int, Any] = {}
            for c in row_el.findall(f"{ns}c"):
                ref = c.attrib.get("r", "")
                idx = _col_index_from_ref(ref)
                ctype = c.attrib.get("t", "n")

                value: Any = None
                if ctype == "inlineStr":
                    is_el = c.find(f"{ns}is")
                    if is_el is not None:
                        value = "".join(t.text or "" for t in is_el.iter(f"{ns}t"))
                else:
                    v_el = c.find(f"{ns}v")
                    raw = v_el.text if v_el is not None else None
                    if raw is not None:
                        if ctype == "s":
                            try:
                                value = shared[int(raw)]
                            except (ValueError, IndexError):
                                value = raw
                        elif ctype == "str":
                            value = raw
                        elif ctype == "b":
                            value = bool(int(raw)) if raw.isdigit() else raw
                        else:  # numeric
                            try:
                                num = float(raw)
                                value = int(num) if num.is_integer() else num
                            except ValueError:
                                value = raw
                if idx:
                    row_cells[idx] = value

            if row_cells:
                width = max(row_cells.keys())
                rows.append([row_cells.get(i) for i in range(1, width + 1)])
            else:
                rows.append([])

        return rows


def _extract_rows(file_bytes: bytes) -> List[List[Any]]:
    """Try openpyxl; fall back to the stdlib zip/XML reader."""
    try:
        return _rows_via_openpyxl(file_bytes)
    except ImportError:
        logger.warning("openpyxl unavailable — using stdlib xlsx reader.")
    except Exception:
        # openpyxl present but rejected the file — try stdlib before failing,
        # so slightly unusual (but valid) workbooks still import.
        logger.warning("openpyxl failed to read the workbook — trying stdlib reader.")
    return _rows_via_stdlib(file_bytes)


# ── Card building (same shape as seed_excel_curriculum) ─────────────────────


def _build_cards(row: Dict[str, str]) -> List[Dict[str, Any]]:
    """Same 4-card structure as seed_excel_curriculum._build_lesson_cards."""
    what_is_it = row.get("what_is_it", "")
    how = row.get("how_does_it_work", "")
    example = row.get("real_example", "")
    practice = row.get("practice_exercise", "")
    remember = row.get("what_should_i_remember", "")

    if example and practice:
        example_body = f"{example}\n\n---\n\n**Practice Exercise**\n{practice}"
    elif example:
        example_body = example
    elif practice:
        example_body = practice
    else:
        example_body = "Apply what you've learned to a real scenario."

    return [
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
            "bodyText": how or "Understand the mechanics behind this concept.",
        },
        {
            "id": "card_3",
            "cardType": "example",
            "section": "real_example",
            "title": "Real Example / Practice Exercise",
            "bodyText": example_body,
            "exampleData": {"practiceExercise": practice},
        },
        {
            "id": "card_4",
            "cardType": "takeaway",
            "section": "remember",
            "title": "What Should I Remember?",
            "bodyText": remember or "Reflect on the key insight from this lesson.",
        },
    ]


# ── Workbook → lesson dicts ──────────────────────────────────────────────────


def parse_uploaded_workbook(file_bytes: bytes) -> List[Dict[str, Any]]:
    """
    Parse an uploaded .xlsx file (bytes) into the same lesson-dict shape as
    parse_excel_curriculum(). Raises ValueError with a user-friendly message
    if the file is not a readable Excel workbook.
    """
    try:
        rows = _extract_rows(file_bytes)
    except zipfile.BadZipFile:
        raise ValueError(
            "The file is not a valid Excel workbook (.xlsx). "
            "Re-save it from Excel as 'Excel Workbook (*.xlsx)' and try again."
        )
    except ElementTree.ParseError as e:
        raise ValueError(f"The workbook's XML is malformed: {e}")

    lessons: List[Dict[str, Any]] = []
    for row in rows[1:]:  # skip the header row
        def cell(idx: int) -> Any:
            return row[idx - 1] if len(row) >= idx else None

        lesson_title = _str(cell(_COL_LESSON_TITLE))
        if not lesson_title:
            continue

        block_num_raw = cell(_COL_BLOCK_NUM)
        try:
            block_num = int(float(str(block_num_raw)))
        except (TypeError, ValueError):
            block_num = 0

        lesson_num_raw = cell(_COL_LESSON_NUM)
        try:
            lesson_num = int(float(str(lesson_num_raw)))
        except (TypeError, ValueError):
            lesson_num = 0

        row_data = {
            "what_is_it": _str(cell(_COL_WHAT_IS_IT)),
            "how_does_it_work": _str(cell(_COL_HOW_DOES_IT_WORK)),
            "real_example": _str(cell(_COL_REAL_EXAMPLE)),
            "practice_exercise": _str(cell(_COL_PRACTICE_EXERCISE)),
            "what_should_i_remember": _str(cell(_COL_WHAT_SHOULD_I_REMEMBER)),
        }

        lessons.append(
            {
                "block_number": block_num,
                "block_title": _str(cell(_COL_BLOCK_TITLE)) or f"Block {block_num}",
                "lesson_number": lesson_num,
                "lesson_title": lesson_title,
                "level": _str(cell(_COL_LEVEL)) or "Beginner",
                "learning_goal": _str(cell(_COL_LEARNING_GOAL)),
                "cards": _build_cards(row_data),
            }
        )

    if not lessons:
        raise ValueError(
            "No lesson rows found. Expected column A=Block#, B=Block Title, "
            "C=Lesson#, D=Lesson Title, E=Level, F=Learning Goal, G-K=the four "
            "card texts (same layout as the original curriculum file)."
        )
    return lessons


# ── Database upsert ──────────────────────────────────────────────────────────


async def upsert_lessons(
    db,
    lessons: List[Dict[str, Any]],
) -> Dict[str, int]:
    """
    Upsert parsed lessons into LearningPath/Lesson tables.

    Matching: block number -> LearningPath with slug "excel-block-{n}"
    (created if missing); lesson number -> Lesson with that sequence_order
    (created if missing). Returns summary counts.
    """
    from sqlalchemy import select
    from app.db.models import LearningPath, Lesson

    blocks: Dict[int, Dict[str, Any]] = {}
    for l in lessons:
        bn = l["block_number"]
        if bn not in blocks:
            blocks[bn] = {
                "title": l["block_title"],
                "level": l["level"],
                "lessons": [],
            }
        blocks[bn]["lessons"].append(l)

    paths_upserted = 0
    lessons_upserted = 0

    for block_num in sorted(blocks.keys()):
        block = blocks[block_num]
        slug = f"{_EXCEL_SLUG_PREFIX}{block_num}"
        block_lessons = block["lessons"]
        total_minutes = len(block_lessons) * 5  # 5 min per lesson

        path_res = await db.execute(
            select(LearningPath).where(LearningPath.curriculum_slug == slug)
        )
        path = path_res.scalars().first()

        if not path:
            path = LearningPath(
                title=block["title"],
                description=f"A structured learning block covering {block['title']}.",
                level=block["level"] or "Beginner",
                total_lessons=len(block_lessons),
                total_minutes=total_minutes,
                source_type="curriculum",
                curriculum_slug=slug,
            )
            db.add(path)
            await db.flush()
            paths_upserted += 1
        else:
            path.title = block["title"]
            path.level = block["level"] or "Beginner"
            path.source_type = "curriculum"
            path.total_lessons = max(path.total_lessons or 0, len(block_lessons))
            path.total_minutes = max(path.total_minutes or 0, total_minutes)

        for lesson_data in block_lessons:
            seq = lesson_data["lesson_number"] or (lessons_upserted + 1)
            lesson_res = await db.execute(
                select(Lesson).where(
                    Lesson.path_id == path.id,
                    Lesson.sequence_order == seq,
                )
            )
            lesson = lesson_res.scalars().first()

            if not lesson:
                lesson = Lesson(
                    path_id=path.id,
                    sequence_order=seq,
                    cards_data=[],
                )
                db.add(lesson)

            lesson.title = lesson_data["lesson_title"]
            lesson.description = f"Lesson {seq} of {block['title']}."
            lesson.learning_goal = lesson_data["learning_goal"] or None
            lesson.estimated_minutes = 5
            lesson.cards_data = lesson_data["cards"]
            lessons_upserted += 1

    await db.flush()

    return {
        "paths_upserted": paths_upserted,
        "lessons_upserted": lessons_upserted,
        "blocks": len(blocks),
    }
