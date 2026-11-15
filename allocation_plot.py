
import csv
from pathlib import Path
import matplotlib.pyplot as plt

# 想查看哪位學生的紀錄
STUDENT_ID = "S905"

# 尋找已儲存的決策紀錄
files = list(Path("data/decisions").glob(f"decisions_{STUDENT_ID}_*.csv"))
files += list(Path(".").glob(f"decisions_{STUDENT_ID}_*.csv"))
if not files:
    print("找不到學生的分配紀錄")
    raise SystemExit

# 使用最近修改的檔案
path = max(files, key=lambda f: f.stat().st_mtime)

with path.open(encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

rows.sort(key=lambda r: int(r["round_no"]))

rounds = [int(r["round_no"]) for r in rows]
present = [int(r["planned_present"]) for r in rows]
past = [int(r["planned_past"]) for r in rows]
future = [int(r["planned_future"]) for r in rows]

bottom = [a + b for a, b in zip(present, past)]

plt.figure(figsize=(9, 5))

plt.bar(rounds, present, label="Present")
plt.bar(rounds, past, bottom=present, label="Past")
plt.bar(rounds, future, bottom=bottom, label="Future")

plt.xticks(rounds)
plt.yticks(range(7))
plt.ylim(0, 7)

plt.xlabel("Practice Round")
plt.ylabel("Number of Questions")
plt.title(f"Question Allocation by Round - {STUDENT_ID}")
plt.legend()

# 儲存圖片
output = Path("reports")
output.mkdir(exist_ok=True)

filename = output / f"allocation_{STUDENT_ID}.png"

plt.tight_layout()
plt.savefig(filename, dpi=200)
plt.show()

print("Chart saved:", filename)
