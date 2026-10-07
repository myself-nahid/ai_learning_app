# -*- coding: utf-8 -*-
import sys, re
sys.stdout.reconfigure(encoding="utf-8")
path = sys.argv[1]
import openpyxl
wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
ws = wb.active
rows = [list(r) for r in ws.iter_rows(values_only=True)]
multi_q = 0; multi_corr = 0; opt_counts = {}
for r in rows[1:]:
    quiz = str(r[12] or "")
    nq = len(re.findall(r"^Question\s*$", quiz, re.M))
    nc = len(re.findall(r"^Correct Answer\s*$", quiz, re.M))
    no = len(re.findall(r"^Option ([A-Z])\s*$", quiz, re.M))
    if nq > 1: multi_q += 1
    if nc > 1: multi_corr += 1
    opt_counts[no] = opt_counts.get(no, 0) + 1
print("cells with >1 question:", multi_q, "| >1 correct:", multi_corr, "| option-count histogram:", opt_counts)
print()
print("===== LESSON 1 FULL TEXT =====")
r = rows[1]
for label, i in [("what_is_it",6),("how_does_it_work",7),("real_example",8),("practice",9),("remember",10)]:
    print(f"--- {label} ---")
    print(str(r[i]))
print("===== LESSON 30 (col 7,9,10 full) =====")
r = rows[30]
for label, i in [("what_is_it",6),("real_example",8),("practice",9)]:
    print(f"--- {label} ---")
    print(str(r[i]))
# structural lead-in words across all cells
import collections
lead = collections.Counter()
for r in rows[1:]:
    for i in (6,7,8,9,10):
        for m in re.finditer(r"^([A-Z][A-Za-z' ]{2,30}):\s*$", str(r[i] or ""), re.M):
            lead[m.group(1).strip()] += 1
print("=== colon lead-ins on their own line (candidates for bold) ===")
for k, v in lead.most_common(25):
    print(f"{k!r}: {v}")
wb.close()
