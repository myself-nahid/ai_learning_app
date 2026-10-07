# -*- coding: utf-8 -*-
import sys, re, collections
sys.stdout.reconfigure(encoding="utf-8")
import openpyxl
wb = openpyxl.load_workbook(sys.argv[1], read_only=True, data_only=True)
ws = wb.active
rows = [list(r) for r in ws.iter_rows(values_only=True)]
def lead_map(ci, pat):
    c = collections.Counter()
    for r in rows[1:]:
        for m in re.finditer(pat, str(r[ci] or ""), re.M):
            c[m.group(1).strip()] += 1
    return c
# standalone lead-ins ending with ':' on their own line (example/practice)
ex = lead_map(8, r"^([^\na-z]{2,40}):$")
pr = lead_map(9, r"^([^\na-z]{2,40}):$")
print("example lead-ins:", dict(ex)); print()
print("practice lead-ins:", dict(pr)); print()
# short-uppercase lines (Situation/With AI/etc)
caps = collections.Counter()
for ci in (8,9):
    for r in rows[1:]:
        for line in str(r[ci] or "").split("\n"):
            s = line.strip()
            if 2 <= len(s) <= 25 and re.fullmatch(r"[A-Z][A-Za-z0-9' &?.!-]*", s) and (s.endswith("?") or re.match(r"^[A-Z][a-z]+( [A-Z][a-z]+)*$", s)):
                caps[s] += 1
for k, v in caps.most_common(30): print(repr(k), v)
print()
# remember: verify all 98 have exact Key Takeaways/Golden Rule/Next Step headers
bad = []
for idx, r in enumerate(rows[1:], 1):
    rem = str(r[10] or "")
    if not re.search(r"^Key Takeaways\s*$", rem, re.M): bad.append((idx, "no-KeyTakeaways"))
    if not re.search(r"^Golden Rule\s*$", rem, re.M): bad.append((idx, "no-GoldenRule"))
    if not re.search(r"^Next Step\s*$", rem, re.M): bad.append((idx, "no-NextStep"))
    if rem.count("Golden Rule") != 1 or rem.count("Next Step") != 1 or rem.count("Key Takeaways") != 1:
        bad.append((idx, "dup-headers"))
    # bullet regex check
    bullets = re.findall(r"^[•\-*]\s*(.+)$", rem, re.M)
    if len(bullets) != 3: bad.append((idx, f"bullets={len(bullets)}"))
print("remember-structure anomalies:", bad if bad else "NONE — all 98 well-formed")
# how_does_it_work step counts
steps = collections.Counter()
for r in rows[1:]:
    h = str(r[7] or ""); n = len(re.findall(r"^Step [0-4]:", h, re.M))
    steps[n] += 1
print("step-count histogram:", dict(steps))
wb.close()
