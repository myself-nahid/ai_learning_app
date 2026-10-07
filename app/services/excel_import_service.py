# -*- coding: utf-8 -*-
"""
excel_import_service.py

Parses uploaded Excel curriculum files (TodAI_Lessons_1-98 Optimized.xlsx
layout: 11 content columns + a per-lesson Quiz column) and upserts them into
the database.

Column layout (1-based):
  1  Block Number          2  Block Title            3  Lesson Number
  4  Lesson Title          5  Level                  6  Learning Goal
  7  What is it?           8  How does it work?      9  Real Example
  10 Practice Exercise     11 What should I remember?
  13 Quiz     (12 unused; the Quiz header cell sits in column 13)

Upsert semantics are unchanged: blocks/lessons are matched by block number +
lesson number, so re-uploading an updated file refreshes existing rows instead
of duplicating them. Blocks are stored with the "excel-block-" slug prefix,
which keeps them grouped with the authoritative Excel curriculum (listed first
in the admin UI, prioritized in the Learning Feed, editable in the Lesson
Content tab).

The Quiz cell ("Question / Option A..D / Correct Answer / Explanation") is
stored on Lesson.quiz_data and mirrored into QuizSet/QuizQuestion via
app.services.lesson_quiz_service, so the mobile app serves it through the
existing quiz endpoints (including the Daily Pulse quiz stage).

Parsing strategy: openpyxl when available; otherwise a dependency-free
fallback that reads the .xlsx directly (it is a zip of XML files), so Excel
upload works on any server environment.
"""
import io
import logging
import re
import zipfile
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

# Column layout of TodAI_Lessons_1-98 Optimized.xlsx (1-based indices).
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
_COL_QUIZ = 13

# Header aliases accepted for the Quiz column (the authoritative file uses
# "Quiz"; be tolerant of trimmed/cased variants).
_QUIZ_HEADER_RE = re.compile(r"^\s*quiz\b", re.IGNORECASE)

_EXCEL_SLUG_PREFIX = "excel-block-"

# "Use AI / Hugging Face" style label prefixes that collide with the exported
# e.g. "None" empty-cell marker. Kept as data (not filtered).
_VERBATIM_NONE = re.compile(r"^\s*None\s*$")


def _str(val) -> str:
    if val is None:
        return ""
    return str(val).strip()


# ── Tabular cell cleaning ────────────────────────────────────────────────────


def _prettify_cell(raw: str, *, strip_leading_rule: bool = False) -> str:
    """
    Normalize one tabular Excel cell used verbatim on the user's screen:
      - trim the leading blank line ("Situation\\r\\n Sam has ..." artifacts
        come from the exporter, not from the author's intent);
      - trim each line's leading spaces (Excel wraps them for readability);
      - drop verbatim "None" lines (the exporter's empty marker);
      - collapse 3+ consecutive blank lines to two.

    `strip_leading_rule` also removes a leading "---" divider (exporter pads
    it before e.g. an injected Lead-ins section).
    """
    text = str(raw or "")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    cleaned: List[str] = []
    for line in lines:
        stripped = line.strip()
        if _VERBATIM_NONE.match(stripped):
            continue
        cleaned.append(stripped.rstrip())

    if strip_leading_rule:
        while cleaned and set(cleaned[0]) <= {"-"}:
            cleaned.pop(0)

    while cleaned and not cleaned[0]:
        cleaned.pop(0)

    # Collapse triples of blank lines into two (keeps intentional spacing).
    collapsed: List[str] = []
    blanks = 0
    for line in cleaned:
        if not line:
            blanks += 1
            if blanks > 2:
                continue
        else:
            blanks = 0
        collapsed.append(line)
    while collapsed and not collapsed[-1]:
        collapsed.pop()

    return "\n".join(collapsed).strip()


# ── Quiz-cell parsing ────────────────────────────────────────────────────────

_QUIZ_SECTION_RE = re.compile(r"^(Question|Option ([A-Z])|Correct Answer|Explanation)\s*$", re.IGNORECASE)


def _parse_quiz_cell(raw: Any, lesson_label: str = "lesson") -> Optional[Dict[str, Any]]:
    """
    Parse the exported quiz text of one lesson into the Lesson.quiz_data shape:
      [{"question_text", "options": {"A": ..}, "correct_option_key", "explanation"?}]

    Cells must contain exactly one Question (<- the file's Validation sheet
    guarantees one question per lesson); blank or "None" cells return None.
    """
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip() or _VERBATIM_NONE.match(text.strip()):
        return None

    sections: List[Tuple[str, Optional[str], List[str]]] = []  # (label, option_letter, lines)
    current: Optional[Tuple[str, Optional[str], List[str]]] = None
    for line in text.split("\n"):
        m = _QUIZ_SECTION_RE.match(line.strip())
        if m:
            label = m.group(1).lower()
            # Caveat: re.Match.lastindex does not report nested participating
            # groups reliably here (stays 1 even for 'Option A'), so read
            # group(2) directly — it is the option letter for 'Option A..D'
            # headers and None for Question/Correct Answer/Explanation.
            letter = (m.group(2) or "").upper() or None
            current = (label, letter, [])
            sections.append(current)
            continue
        if current is not None:
            current[2].append(line)

    # Collect the parsed fields (sections never repeat in this layout except
    # options; count duplicates to fail loudly on malformed cells).
    question_text = ""
    options: Dict[str, str] = {}
    correct = ""
    explanation = ""
    section_counts: Dict[str, int] = {}
    for label, letter, lines in sections:
        section_counts[label] = section_counts.get(label, 0) + 1
        value = "\n".join(lines).strip()
        if not value:
            continue
        if label == "question":
            question_text = value
        elif letter:  # Option A..D (label normalizes to "option a" etc.)
            options[letter] = value
        elif label == "correct answer":
            correct = value.strip().upper()[:1]
        elif label == "explanation":
            explanation = value

    n_questions = section_counts.get("question", 0)
    if n_questions == 0:
        raise ValueError(f"{lesson_label}: quiz cell has no 'Question' header.")
    if n_questions > 1:
        raise ValueError(
            f"{lesson_label}: quiz cell has {n_questions} 'Question' "
            "headers; one question per lesson is expected (split into separate "
            "cells or author the remaining questions via the admin lesson editor)."
        )
    if len(options) < 2:
        raise ValueError(f"{lesson_label}: quiz cell has fewer than 2 labeled options.")
    if not correct:
        raise ValueError(f"{lesson_label}: quiz cell is missing a 'Correct Answer'.")
    if correct not in options:
        raise ValueError(
            f"{lesson_label}: correct answer '{correct}' is not one of the "
            f"labeled options ({', '.join(sorted(options))})."
        )

    question: Dict[str, Any] = {
        "question_text": question_text,
        "options": {k: options[k] for k in sorted(options)},
        "correct_option_key": correct,
    }
    if explanation:
        question["explanation"] = explanation
    return question


# ── "What Should I Remember?" restructuring ────────────────────────────────

_BULLET_RE = re.compile(r"^[•\-*]\s*", re.MULTILINE)
_REMEMBER_HEADER_RE = re.compile(r"^(Key Takeaways|Golden Rule|Next Step)\s*$", re.IGNORECASE)


def _restructure_remember(raw: str) -> Dict[str, Any]:
    """
    The exported 'What Should I Remember?' cell repeats its three internal
    headers on screen ("Key Takeaways", "Golden Rule", "Next Step") and the
    takeaway card previously rendered those headers as body bullets too.
    Strip the exported headers, keep exactly the three bullet lines, and
    expose the rest as structured fields the runner renders as separate
    sections (mirrors the seed_excel / import_curriculum card format).
    """
    lines = [ln.strip() for ln in str(raw or "").replace("\r\n", "\n").split("\n")]
    bullets: List[str] = []
    golden_rule = ""
    next_step = ""

    i = 0
    while i < len(lines):
        header = _REMEMBER_HEADER_RE.match(lines[i])
        if header:
            kind = header.group(1).lower()
            i += 1
            if kind == "golden rule":
                while i < len(lines) and not _REMEMBER_HEADER_RE.match(lines[i]):
                    if lines[i]:
                        golden_rule = lines[i] if not golden_rule else f"{golden_rule} {lines[i]}"
                    i += 1
                continue
            if kind == "next step":
                while i < len(lines) and not _REMEMBER_HEADER_RE.match(lines[i]):
                    if lines[i]:
                        next_step = lines[i] if not next_step else f"{next_step} {lines[i]}"
                    i += 1
                continue
            # 'Key Takeaways': consume the bullet block right after it.
            while i < len(lines):
                ln = lines[i]
                if _REMEMBER_HEADER_RE.match(ln):
                    break
                if _BULLET_RE.match(ln):
                    bullets.append(_BULLET_RE.sub("", ln).strip())
                i += 1
            continue
        if _BULLET_RE.match(lines[i]):
            bullets.append(_BULLET_RE.sub("", lines[i]).strip())
        i += 1

    bullets = [b for b in bullets if b]
    if len(bullets) != 3:
        # Padded/blank bullets are still three by contract in this file —
        # reject anything else loudly instead of sending a broken card up.
        raise ValueError(
            f"'What Should I Remember?' must have exactly 3 bullet takeaways "
            f"(found {len(bullets)}); check the exported Excel cell."
        )
    if not golden_rule:
        raise ValueError("'What Should I Remember?' is missing a 'Golden Rule' entry.")
    if not next_step:
        raise ValueError("'What Should I Remember?' is missing a 'Next Step' entry.")

    remember_body = "\n".join(bullets)
    # Section-split reflected in the user-facing sentence.
    remember_summary = f"{remember_body}\n\n**Golden Rule**\n{golden_rule}\n\n**Next Step**\n{next_step}"
    return {
        "body": remember_body,
        "summary": remember_summary,
        "_bullets": bullets,
        "_rule": golden_rule,
        "_next": next_step,
    }


# ── Row extraction (openpyxl first, stdlib fallback second) ─────────────────


def _rows_via_openpyxl(file_bytes: bytes) -> List[List[Any]]:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
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


# ── Card building ────────────────────────────────────────────────────────────


def _build_cards(
    row_data: Dict[str, str],
    remember_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Build the fixed 4-card structure (structured takeaway data rides on card 4)."""
    what_is_it = row_data.get("what_is_it", "")
    how = row_data.get("how_does_it_work", "")
    example = row_data.get("real_example", "")
    practice = row_data.get("practice_exercise", "")

    if example and practice:
        # Merged form: the runner/admin split this back at the marker.
        example_body = f"{example}\n\n---\n\n**Practice Exercise**\n{practice}"
    elif example:
        example_body = example
    elif practice:
        # Practice-only lesson: keep the content in exampleData.practiceExercise
        # only (rendered as the teal Practice box). Duplicating it into bodyText
        # too would show the same text twice on one screen.
        example_body = ""
    else:
        example_body = "Apply what you've learned to a real scenario."

    cards: List[Dict[str, Any]] = [
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
            "bodyText": remember_data["body"],
            "takeawayData": {
                "keyTakeaways": remember_data["_bullets"],
                "goldenRule": remember_data["_rule"],
                "nextStep": remember_data["_next"],
            },
        },
    ]
    return cards


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

    if not rows:
        raise ValueError("No rows found in the uploaded workbook.")

    # Header row: detect the quiz column and sanity-check the layout.
    header = rows[0]
    quiz_col = _COL_QUIZ
    header_quiz = _str(header[quiz_col - 1]) if len(header) >= quiz_col else ""
    if not _QUIZ_HEADER_RE.match(header_quiz):
        # Column 13 must be the quiz column for the authoritative layout; if
        # it isn't, look at col 12 (older exporter variant) and otherwise
        # scan for a quiz-ish header within the first 15 columns.
        scanned = False
        for idx in range(12, min(len(header), 15) + 1):
            h = _str(header[idx - 1]) if len(header) >= idx else ""
            if _QUIZ_HEADER_RE.match(h):
                quiz_col = idx
                scanned = True
                break
        if not scanned:
            logger.warning(
                "No explicit Quiz header found; assuming quiz column %d.", quiz_col
            )

    lessons: List[Dict[str, Any]] = []
    quiz_errors: List[str] = []
    for row_num, row in enumerate(rows[1:], start=2):
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

        label = f"lesson {lesson_num or row_num} '{lesson_title[:50]}'"

        row_data = {
            "what_is_it": _prettify_cell(_str(cell(_COL_WHAT_IS_IT))),
            "how_does_it_work": _prettify_cell(_str(cell(_COL_HOW_DOES_IT_WORK))),
            "real_example": _prettify_cell(_str(cell(_COL_REAL_EXAMPLE))),
            "practice_exercise": _prettify_cell(
                _str(cell(_COL_PRACTICE_EXERCISE)), strip_leading_rule=True
            ),
            "what_should_i_remember": _prettify_cell(
                _str(cell(_COL_WHAT_SHOULD_I_REMEMBER))
            ),
        }

        try:
            remember_data = _restructure_remember(row_data["what_should_i_remember"])
        except ValueError as e:
            raise ValueError(f"{label}: {e}")

        quiz_raw = cell(quiz_col)
        quiz_question: Optional[Dict[str, Any]] = None
        try:
            quiz_question = _parse_quiz_cell(quiz_raw, lesson_label=label)
        except ValueError as e:
            quiz_errors.append(str(e))

        cards = _build_cards(row_data, remember_data)

        entry = {
            "block_number": block_num,
            "block_title": _str(cell(_COL_BLOCK_TITLE)) or f"Block {block_num}",
            "lesson_number": lesson_num,
            "lesson_title": lesson_title,
            "level": _str(cell(_COL_LEVEL)) or "Beginner",
            "learning_goal": _str(cell(_COL_LEARNING_GOAL)),
            "cards": cards,
        }
        if quiz_question is not None:
            entry["quiz"] = [quiz_question]
        lessons.append(entry)

    if not lessons:
        raise ValueError(
            "No lesson rows found. Expected the TodAI curriculum layout: "
            "A=Block#, B=Block Title, C=Lesson#, D=Lesson Title, E=Level, "
            "F=Learning Goal, G-K=the four card texts, M=Quiz."
        )
    if quiz_errors:
        # Fail loudly — a half-imported quiz file would leave lessons running
        # with the old quiz_data and be very hard to debug afterwards.
        preview = "; ".join(quiz_errors[:5])
        raise ValueError(
            f"{len(quiz_errors)} quiz cell(s) could not be parsed "
            f"(showing up to 5): {preview}"
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
    from app.services.lesson_quiz_service import sync_lesson_quiz_set

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
    quizzes_synced = 0

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
            path.description = f"A structured learning block covering {block['title']}."
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

            new_cards = lesson_data["cards"]
            if not lesson:
                lesson = Lesson(
                    path_id=path.id,
                    sequence_order=seq,
                    cards_data=new_cards,
                )
                db.add(lesson)
            else:
                lesson.cards_data = new_cards

            lesson.title = lesson_data["lesson_title"]
            lesson.description = f"Lesson {seq} of {block['title']}."
            lesson.learning_goal = lesson_data["learning_goal"] or None
            lesson.estimated_minutes = 5
            # Lesson quiz (authored in the Excel): mirror into QuizSet rows so
            # the app serves it through POST /quiz-tab/start/{id}.
            if lesson_data.get("quiz"):
                lesson.quiz_data = lesson_data["quiz"]
            else:
                lesson.quiz_data = []
            await sync_lesson_quiz_set(db, lesson)
            quizzes_synced += 1
            lessons_upserted += 1

    await db.flush()

    return {
        "paths_upserted": paths_upserted,
        "lessons_upserted": lessons_upserted,
        "blocks": len(blocks),
        "quizzes_synced": quizzes_synced,
    }
