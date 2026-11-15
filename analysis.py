
import csv
from adaptive import choose_allocation

with open("responses.csv", encoding="utf-8") as file:
    responses = list(csv.DictReader(file))

scores = []
ready = True

for tense in ["present", "past", "future"]:
    records = []

    for response in responses:
        if response["tense"] == tense:
            records.append(response["is_correct"] == "True")

    recent = records[-4:]

    print(tense, ":", sum(recent), "/", len(recent))

    if len(recent) < 4:
        ready = False

    scores.append(sum(recent))


if ready:
    round_index = max(0, (len(responses) - 12) // 6)
    print("Next round:", choose_allocation(scores, round_index))
else:
    print("Not enough data: need 4 answers per tense.")


# ===== Round Accuracy Comparison =====

from collections import Counter
from pathlib import Path
import csv
import matplotlib.pyplot as plt

# 示範學生
COMPARE_STUDENTS = {
    "non_adaptive": "S904",
    "adaptive": "S905",
}

# 目前展示三輪；改成 6 就能展示六輪
COMPARE_ROUNDS = 3

ROOT = Path(__file__).resolve().parent
TENSES = ["present", "past", "future"]


# 1. 找到學生最新的完整作答紀錄
def find_practice(student_id, condition):

    files = []

    for folder in [ROOT / "data" / "responses", ROOT]:
        files.extend(
            folder.glob(f"practice_{student_id}_*.csv")
        )

    files.sort(
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    for path in files:

        with path.open(
            encoding="utf-8-sig", newline=""
        ) as f:
            rows = list(csv.DictReader(f))

        if not rows:
            continue

        # 確認學生及實驗條件
        if any(
            r.get("student_id", "").upper() != student_id
            or r.get("condition", "") != condition
            for r in rows
        ):
            continue

        # 確認每題都有有效的正誤紀錄
        if any(
            r.get("is_correct", "").lower()
            not in ["true", "false"]
            for r in rows
        ):
            continue

        try:
            counts = Counter(
                int(r["round_no"]) for r in rows
            )
        except (KeyError, ValueError):
            continue

        # 每輪六題，且輪次不能缺漏
        if sorted(counts) != list(
            range(1, len(counts) + 1)
        ):
            continue

        if any(n != 6 for n in counts.values()):
            continue

        if len(counts) < COMPARE_ROUNDS:
            continue

        if len(set(
            r["question_id"] for r in rows
        )) != len(rows):
            continue

        return path, rows

    raise FileNotFoundError(
        f"找不到 {student_id} 的完整 {condition} 作答紀錄"
    )


# 2. 計算每輪及每種時態的正確率
def calculate_accuracy(student_id, condition, rows):

    results = []

    for round_no in range(1, COMPARE_ROUNDS + 1):

        round_rows = [
            r for r in rows
            if int(r["round_no"]) == round_no
        ]

        for tense in ["overall"] + TENSES:

            if tense == "overall":
                selected = round_rows
            else:
                selected = [
                    r for r in round_rows
                    if r["tense"] == tense
                ]

            total = len(selected)

            correct = sum(
                r["is_correct"].lower() == "true"
                for r in selected
            )

            accuracy = (
                round(correct / total * 100, 1)
                if total else 0
            )

            results.append({
                "student_id": student_id,
                "condition": condition,
                "round_no": round_no,
                "tense": tense,
                "correct": correct,
                "total": total,
                "accuracy_pct": accuracy,
            })

    return results


# 3. 讀取資料並產生比較圖
def compare_accuracy():

    all_results = []

    for condition, student_id in COMPARE_STUDENTS.items():

        path, rows = find_practice(
            student_id, condition
        )

        print("讀取紀錄：", path.name)

        results = calculate_accuracy(
            student_id, condition, rows
        )

        all_results.extend(results)

    # 儲存數據摘要
    output_folder = ROOT / "reports"
    output_folder.mkdir(exist_ok=True)

    csv_path = (
        output_folder / "round_accuracy_comparison.csv"
    )

    with csv_path.open(
        "w", encoding="utf-8-sig", newline=""
    ) as f:

        writer = csv.DictWriter(
            f, fieldnames=all_results[0].keys()
        )

        writer.writeheader()
        writer.writerows(all_results)

    # 四個圖：整體、現在、過去、未來
    fig, axes = plt.subplots(
        2, 2, figsize=(11, 7)
    )

    chart_names = [
        "overall", "present", "past", "future"
    ]

    for ax, tense in zip(axes.flat, chart_names):

        for condition, student_id in COMPARE_STUDENTS.items():

            data = [
                r for r in all_results
                if r["condition"] == condition
                and r["tense"] == tense
            ]

            rounds = [r["round_no"] for r in data]
            accuracy = [r["accuracy_pct"] for r in data]

            ax.plot(
                rounds,
                accuracy,
                marker="o" if condition == "adaptive" else "s",
                label=f"{condition} ({student_id})"
            )

        ax.set_title(tense.title() + " Accuracy")
        ax.set_xlabel("Practice Round")
        ax.set_ylabel("Accuracy (%)")
        ax.set_xticks(
            range(1, COMPARE_ROUNDS + 1)
        )
        ax.set_ylim(0, 105)
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8)

    fig.suptitle(
        "Practice Accuracy by Round (Demo Data)",
        fontsize=14
    )

    plt.tight_layout()

    image_path = (
        output_folder / "round_accuracy_comparison.png"
    )

    plt.savefig(image_path, dpi=200)
    plt.show()

    print("圖表已儲存：", image_path)
    print("數據已儲存：", csv_path)


# 4. 執行比較
if __name__ == "__main__":
    compare_accuracy()
