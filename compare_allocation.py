import csv
from pathlib import Path
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent


def find_latest_decision(student_id):
    files = sorted(
        ROOT.glob(f"decisions_{student_id}_*.csv"),
        key=lambda p: p.stat().st_mtime
    )
    if not files:
        raise FileNotFoundError(f"找不到 {student_id} 的 decisions 檔案")
    return files[-1]


def read_decision_file(path):
    with path.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    rounds = []
    present = []
    past = []
    future = []
    condition = ""

    for row in rows:
        rounds.append(int(row["round_no"]))
        present.append(int(row["planned_present"]))
        past.append(int(row["planned_past"]))
        future.append(int(row["planned_future"]))
        condition = row.get("condition", "")

    return {
        "rounds": rounds,
        "present": present,
        "past": past,
        "future": future,
        "condition": condition,
        "filename": path.name
    }


def plot_condition(ax, data, title):
    rounds = data["rounds"]
    present = data["present"]
    past = data["past"]
    future = data["future"]

    ax.bar(rounds, present, label="Present")
    ax.bar(rounds, past, bottom=present, label="Past")
    ax.bar(
        rounds,
        future,
        bottom=[p + q for p, q in zip(present, past)],
        label="Future"
    )

    ax.set_title(title)
    ax.set_xlabel("Practice Round")
    ax.set_ylabel("Number of Questions")
    ax.set_xticks(rounds)
    ax.set_ylim(0, max([p + q + r for p, q, r in zip(present, past, future)]) + 1)

    for i, r in enumerate(rounds):
        total = present[i] + past[i] + future[i]
        ax.text(r, total + 0.05, f"{present[i]}/{past[i]}/{future[i]}",
                ha="center", va="bottom", fontsize=9)


def main():
    non_adaptive_file = find_latest_decision("S904")
    adaptive_file = find_latest_decision("S905")

    non_adaptive_data = read_decision_file(non_adaptive_file)
    adaptive_data = read_decision_file(adaptive_file)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)

    plot_condition(
        axes[0],
        non_adaptive_data,
        "Non-Adaptive Allocation"
    )
    plot_condition(
        axes[1],
        adaptive_data,
        "Adaptive Allocation"
    )

    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper center", ncol=3)

    fig.suptitle("Adaptive vs. Non-Adaptive Question Allocation", fontsize=14)
    plt.tight_layout(rect=[0, 0, 1, 0.92])

    output_path = ROOT / "adaptive_vs_non_adaptive.png"
    plt.savefig(output_path, dpi=200)
    plt.show()

    print("已輸出圖檔：", output_path)


if __name__ == "__main__":
    main()