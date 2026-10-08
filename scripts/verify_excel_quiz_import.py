# -*- coding: utf-8 -*-
"""One-off verification of the Excel quiz import against the real workbook."""
import io
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.excel_import_service import (
    _extract_rows,
    _parse_quiz_cell,
    _restructure_remember,
    parse_uploaded_workbook,
)

XLSX = Path(__file__).resolve().parents[2] / "TodAI_Lessons_1-98 Optimized.xlsx"
raw = XLSX.read_bytes()
print(f"file: {XLSX.name} ({len(raw)} bytes)")

# 1) stdlib vs openpyxl row equality
import openpyxl

wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
ws = wb.active
rows_op = [list(r) for r in ws.iter_rows(values_only=True)]
wb.close()
rows_st = _extract_rows(raw)

def norm(v):
    if v is None:
        return None
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v

assert len(rows_op) == len(rows_st), f"row count differs: {len(rows_op)} vs {len(rows_st)}"
diffs = 0
for i, (a, b) in enumerate(zip(rows_op, rows_st), 1):
    width = max(len(a), len(b))
    for j in range(width):
        va = norm(a[j]) if j < len(a) else None
        vb = norm(b[j]) if j < len(b) else None
        if va != vb:
            diffs += 1
            if diffs <= 5:
                print(f"  DIFF row {i} col {j+1}: openpyxl={va!r} stdlib={vb!r}")
print(f"reader parity: {'OK' if diffs == 0 else f'{diffs} cell diffs'} over {len(rows_op)} rows x {width} cols")

# 2) Header row
header = [norm(v) for v in rows_op[0]]
print("header:", {i + 1: h for i, h in enumerate(header) if h is not None})

# 3) Parse all lessons
lessons = parse_uploaded_workbook(raw)
print(f"lessons parsed: {len(lessons)}")

problems = []
levels = Counter()
blocks = Counter()
quiz_missing = []
remember_bad = []
quiz_len_bad = []

for l in lessons:
    levels[l["level"]] += 1
    blocks[l["block_number"]] += 1
    label = f"B{l['block_number']}.L{l['lesson_number']} {l['lesson_title'][:40]!r}"
    cards = l["cards"]
    types = [c["cardType"] for c in cards]
    if types != ["intro", "concept", "example", "takeaway"]:
        problems.append(f"{label}: cardTypes={types}")
    if "quiz" not in l or not l["quiz"]:
        quiz_missing.append(label)
        continue
    q = l["quiz"][0]
    if len(l["quiz"]) != 1:
        quiz_len_bad.append(label)
    if not q.get("question_text"):
        problems.append(f"{label}: empty question_text")
    opts = q.get("options", {})
    if set(opts.keys()) < {"A", "B", "C", "D"}:
        problems.append(f"{label}: options keys={sorted(opts.keys())}")
    if q.get("correct_option_key") not in opts:
        problems.append(f"{label}: correct={q.get('correct_option_key')!r} not in options")
    td = cards[3].get("takeawayData", {})
    if len(td.get("keyTakeaways", [])) != 3:
        remember_bad.append(f"{label}: {len(td.get('keyTakeaways', []))} takeaways")
    if not td.get("goldenRule"):
        remember_bad.append(f"{label}: missing goldenRule")
    if not td.get("nextStep"):
        remember_bad.append(f"{label}: missing nextStep")
    body = cards[3]["bodyText"]
    if "Golden Rule" in body or "Next Step" in body:
        remember_bad.append(f"{label}: headers leaked into bodyText")

print("levels:", dict(levels))
print("blocks:", dict(sorted(blocks.items())))
print(f"quiz present: {len(lessons) - len(quiz_missing)}/{len(lessons)}; missing: {quiz_missing[:5]}")
print(f"remember issues: {len(remember_bad)} -> {remember_bad[:5]}")
print(f"quiz_len issues: {quiz_len_bad[:5]}")
print(f"card problems: {len(problems)} -> {problems[:5]}")

# 4) Spot-check lesson 1 content
l1 = lessons[0]
print("\n--- LESSON 1 ---")
print("title:", l1["lesson_title"], "| level:", l1["level"], "| block:", l1["block_title"])
for c in l1["cards"]:
    body = c["bodyText"]
    print(f"  [{c['cardType']}] {c['title']!r} body[:80]={body[:80]!r} practice={bool(c.get('exampleData', {}).get('practiceExercise'))}")
print("quiz:", json.dumps(l1["quiz"], indent=2, ensure_ascii=False)[:600])
print("takeawayData:", json.dumps(l1["cards"][3]["takeawayData"], indent=2, ensure_ascii=False)[:500])

# 5) Re-parse determinism
lessons2 = parse_uploaded_workbook(raw)
print("determinism:", "OK" if lessons == lessons2 else "MISMATCH")

ok = not problems and not remember_bad and not quiz_len_bad and len(quiz_missing) == 0 and len(lessons) == 98
print("\nRESULT:", "ALL CHECKS PASSED" if ok else "ISSUES FOUND")
