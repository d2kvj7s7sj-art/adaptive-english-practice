"""English Grammar Practice: six-round research data summary.

Place this file next to app.py, practice_*.csv and decisions_*.csv.

Run:
    python3 teacher_report.py                 # newest session
    python3 teacher_report.py --student S904  # newest session for S904
    python3 teacher_report.py --all           # every detected session

Results are saved in the reports/ folder. Standard library only.
"""

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
import re

from storage import response_files, decision_for_response

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "reports"
TENSES = ("present", "past", "future")
SESSION_FILENAME = re.compile(
    r"^practice_(?P<student>[A-Za-z0-9_-]+)_(?P<session>\d{8}_\d{6}(?:_\d{6})?)\.csv$"
)
REQUIRED_RESPONSE_FIELDS = {
    "student_id", "session_id", "round_no", "question_id",
    "tense", "is_correct", "response_seconds",
}
REQUIRED_DECISION_FIELDS = {
    "student_id", "session_id", "round_no", "phase",
    "present_score", "past_score", "future_score",
    "planned_present", "planned_past", "planned_future",
}


def read_csv(path):
    with path.open("r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        return list(reader), set(reader.fieldnames or ())


def write_csv(path, rows, columns):
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def number(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def correct_value(value):
    value = str(value).strip().lower()
    if value in ("true", "1"):
        return True
    if value in ("false", "0"):
        return False
    return None


def response_time(value):
    try:
        seconds = float(value)
        return seconds if 0 <= seconds < float("inf") else None
    except (TypeError, ValueError):
        return None


def fmt_percentage(success, total):
    return f"{100 * success / total:.1f}%" if total else "無資料"


def fmt_float(value):
    return f"{value:.1f}" if isinstance(value, (int, float)) else "無資料"


def stats(rows):
    valid = [correct_value(r.get("is_correct", "")) for r in rows]
    observed = [answer for answer in valid if answer is not None]
    seconds = [response_time(r.get("response_seconds", "")) for r in rows]
    seconds = [s for s in seconds if s is not None]
    return {
        "questions": len(rows),
        "correct": sum(observed),
        "accuracy_pct": round(100 * sum(observed) / len(observed), 1) if observed else "",
        "average_seconds": round(mean(seconds), 1) if seconds else "",
        "median_seconds": round(median(seconds), 1) if seconds else "",
        "valid_answers": len(observed),
    }


def find_sessions(student=None, session=None):
    found = []
    for path in response_files():
        m = SESSION_FILENAME.fullmatch(path.name)
        if not m:
            continue
        if student and m["student"].upper() != student.upper():
            continue
        if session and m["session"] != session:
            continue
        found.append((path, m["student"], m["session"]))
    return sorted(found, key=lambda item: item[0].stat().st_mtime, reverse=True)


def question_bank():
    path = ROOT / "questions.csv"
    if not path.exists():
        return {}
    rows, columns = read_csv(path)
    if "question_id" not in columns:
        return {}
    return {row.get("question_id", ""): row for row in rows}


def inspect_session(path, student_id, session_id, expected_rounds, items_per_round, bank):
    responses, response_fields = read_csv(path)
    missing = REQUIRED_RESPONSE_FIELDS - response_fields
    if missing:
        raise ValueError(f"{path.name} 缺少作答欄位：{', '.join(sorted(missing))}")

    decision_file = decision_for_response(path, student_id, session_id)
    if decision_file.exists():
        decisions, decision_fields = read_csv(decision_file)
        missing = REQUIRED_DECISION_FIELDS - decision_fields
        if missing:
            raise ValueError(f"{decision_file.name} 缺少決策欄位：{', '.join(sorted(missing))}")
    else:
        decisions = []

    issues = []
    ids = [r.get("question_id", "").strip() for r in responses]
    if any(not x for x in ids):
        issues.append("存在空白 question_id")
    duplicates = [q for q, count in Counter(ids).items() if q and count > 1]
    if duplicates:
        issues.append(f"重複題目 ID：{', '.join(duplicates[:8])}")

    conditions = {
        r.get("condition", "").strip().lower()
        for r in responses + decisions if r.get("condition", "").strip()
    }
    if len(conditions) > 1:
        issues.append("作答／決策檔的 condition 不一致")
    condition = next(iter(conditions)) if len(conditions) == 1 else "unknown"
    if condition == "unknown":
        issues.append("找不到 condition，無法確認組別")
    elif condition not in ("adaptive", "non_adaptive"):
        issues.append(f"不認得的 condition：{condition}")

    if any(r.get("student_id") != student_id for r in responses + decisions):
        issues.append("檔案內 student_id 與檔名不一致")
    if any(r.get("session_id") != session_id for r in responses + decisions):
        issues.append("檔案內 session_id 與檔名不一致")

    if len(responses) != expected_rounds * items_per_round:
        issues.append(
            f"作答筆數 {len(responses)}，預期 {expected_rounds * items_per_round} 筆（可能尚未完成）"
        )
    if len(decisions) != expected_rounds:
        issues.append(f"決策筆數 {len(decisions)}，預期 {expected_rounds} 筆")
    if not decision_file.exists():
        issues.append("找不到同一 session 的 decisions CSV")

    response_by_round = defaultdict(list)
    for i, r in enumerate(responses, start=2):
        rno = number(r.get("round_no"))
        if rno is None or rno < 1 or rno > expected_rounds:
            issues.append(f"作答檔第 {i} 行 round_no 不合法")
        else:
            response_by_round[rno].append(r)
        if r.get("tense", "") not in TENSES:
            issues.append(f"作答檔第 {i} 行 tense 不合法")
        if correct_value(r.get("is_correct")) is None:
            issues.append(f"作答檔第 {i} 行 is_correct 無法判讀")
        seconds = response_time(r.get("response_seconds"))
        if seconds is None:
            issues.append(f"作答檔第 {i} 行 response_seconds 無效")
        elif seconds >= 120:
            issues.append(f"作答檔第 {i} 行反應時間 {seconds:g} 秒偏長（保留原始資料，請核對）")

    decision_by_round = {}
    for i, row in enumerate(decisions, start=2):
        rno = number(row.get("round_no"))
        if rno is None or rno < 1 or rno > expected_rounds:
            issues.append(f"決策檔第 {i} 行 round_no 不合法")
        elif rno in decision_by_round:
            issues.append(f"Round {rno} 有重複決策紀錄")
        else:
            decision_by_round[rno] = row

    round_rows = []
    for rno in range(1, expected_rounds + 1):
        answers = response_by_round[rno]
        decision = decision_by_round.get(rno, {})
        actual = Counter(r.get("tense", "") for r in answers)
        overview = stats(answers)
        planned = {t: number(decision.get(f"planned_{t}", "")) for t in TENSES}
        phase = decision.get("phase", "")
        score_logged = {t: number(decision.get(f"{t}_score", "")) for t in TENSES}
        score_recomputed = {}
        for tense in TENSES:
            previous = [
                correct_value(row.get("is_correct"))
                for previous_round in range(1, rno)
                for row in response_by_round[previous_round]
                if row.get("tense") == tense
            ]
            recent = previous[-4:]
            score_recomputed[tense] = (
                sum(recent) if len(recent) == 4 and all(v is not None for v in recent)
                else None
            )

        if len(answers) != items_per_round:
            issues.append(f"Round {rno} 實際作答 {len(answers)} 題，預期 {items_per_round} 題")
        if not decision:
            issues.append(f"Round {rno} 找不到決策紀錄")
        else:
            expected_phase = "baseline" if rno <= 2 else condition
            if condition in ("adaptive", "non_adaptive") and phase != expected_phase:
                issues.append(f"Round {rno} phase={phase}，預期 {expected_phase}")
            if any(v is None for v in planned.values()):
                issues.append(f"Round {rno} planned_* 缺少數值")
            else:
                if sum(planned.values()) != items_per_round or min(planned.values()) < 1:
                    issues.append(f"Round {rno} 預定分配不符合每輪 {items_per_round} 題、各時態至少一題")
                if any(planned[t] != actual[t] for t in TENSES):
                    issues.append(f"Round {rno} 預定分配與實際出題數不一致")
                if condition == "non_adaptive" and planned != dict.fromkeys(TENSES, 2):
                    issues.append(f"Round {rno} 非適性組不是 2/2/2")
                if rno <= 2 and planned != dict.fromkeys(TENSES, 2):
                    issues.append(f"Round {rno} 基線階段不是 2/2/2")

            if rno > 2:
                for tense in TENSES:
                    if score_logged[tense] is None:
                        issues.append(f"Round {rno} 缺少 {tense}_score")
                    elif score_recomputed[tense] != score_logged[tense]:
                        issues.append(
                            f"Round {rno} {tense}_score 檔案值 {score_logged[tense]}，"
                            f"依之前最近四次作答重新計算為 {score_recomputed[tense]}"
                        )

        row = {
            "student_id": student_id, "session_id": session_id,
            "condition": condition, "round_no": rno, "phase": phase,
            "questions": overview["questions"], "correct": overview["correct"],
            "accuracy_pct": overview["accuracy_pct"],
            "average_seconds": overview["average_seconds"],
            "median_seconds": overview["median_seconds"],
        }
        for t in TENSES:
            part = stats([a for a in answers if a.get("tense") == t])
            row[f"actual_{t}"] = part["questions"]
            row[f"correct_{t}"] = part["correct"]
            row[f"accuracy_{t}_pct"] = part["accuracy_pct"]
            row[f"planned_{t}"] = planned[t] if planned[t] is not None else ""
            row[f"score_{t}_of_4"] = score_logged[t] if score_logged[t] is not None else ""
        row["planned_matches_actual"] = (
            all(planned[t] == actual[t] for t in TENSES)
            if all(planned[t] is not None for t in TENSES) else ""
        )
        round_rows.append(row)

    overall = stats(responses)
    summary = {
        "student_id": student_id, "session_id": session_id, "condition": condition,
        "expected_rounds": expected_rounds,
        "completed_rounds": sum(len(response_by_round[r]) == items_per_round for r in range(1, expected_rounds + 1)),
        "total_questions": overall["questions"],
        "correct": overall["correct"], "accuracy_pct": overall["accuracy_pct"],
        "average_seconds": overall["average_seconds"],
        "median_seconds": overall["median_seconds"],
        "unique_questions": len(set(q for q in ids if q)),
        "decision_rows": len(decisions),
    }
    for t in TENSES:
        part = stats([r for r in responses if r.get("tense") == t])
        summary[f"questions_{t}"] = part["questions"]
        summary[f"correct_{t}"] = part["correct"]
        summary[f"accuracy_{t}_pct"] = part["accuracy_pct"]
        summary[f"average_seconds_{t}"] = part["average_seconds"]

    summary["quality_status"] = "CHECK" if issues else "PASS"
    summary["quality_issue_count"] = len(issues)

    lines = [
        "=== 六輪練習研究資料摘要 | Teacher Research Report ===",
        f"Student ID: {student_id}", f"Session ID: {session_id}",
        f"Condition: {condition}",
        f"作答檔: {path.name}",
        f"決策檔: {decision_file.name if decision_file.exists() else '缺少'}",
        "",
        "=== Overall Practice Performance（練習表現，不等於學習成效）===",
        f"已完成輪數: {summary['completed_rounds']} / {expected_rounds}",
        f"作答題數: {overall['questions']} / {expected_rounds * items_per_round}",
        f"答對題數: {overall['correct']} / {overall['valid_answers']}",
        f"練習正確率: {fmt_percentage(overall['correct'], overall['valid_answers'])}",
        f"平均作答時間: {fmt_float(overall['average_seconds'])} 秒",
        f"作答時間中位數: {fmt_float(overall['median_seconds'])} 秒",
        f"不重複題目數: {summary['unique_questions']}",
        "",
        "=== Performance by Tense ===",
    ]
    for t in TENSES:
        part = stats([r for r in responses if r.get("tense") == t])
        lines.append(
            f"{t:8s}  {part['correct']}/{part['valid_answers']} 正確  "
            f"接觸 {part['questions']} 題  正確率 {fmt_percentage(part['correct'], part['valid_answers'])}  "
            f"平均 {fmt_float(part['average_seconds'])} 秒"
        )

    lines.extend(["", "=== Performance by Round & Allocation ==="])
    for row in round_rows:
        actual_s = "/".join(str(row[f"actual_{t}"]) for t in TENSES)
        planned_s = "/".join(str(row[f"planned_{t}"]) for t in TENSES)
        logged_s = "/".join(str(row[f"score_{t}_of_4"]) for t in TENSES)
        lines.append(
            f"Round {row['round_no']}: {row['phase'] or 'unknown':12s} "
            f"答對 {row['correct']}/{row['questions']}; "
            f"planned={planned_s}, actual={actual_s}, "
            f"recent_scores={logged_s}; avg={fmt_float(row['average_seconds'])}s"
        )

    mistakes = [r for r in responses if correct_value(r.get("is_correct")) is False]
    lines.extend(["", f"=== Mistakes to Review（共 {len(mistakes)} 筆，顯示前 10 筆）==="])
    if not mistakes:
        lines.append("已記錄的作答中沒有答錯題目。")
    else:
        for r in mistakes[:10]:
            q = bank.get(r.get("question_id", ""), {})
            lines.append(
                f"Round {r.get('round_no', '?')} | {r.get('tense', '?')} | "
                f"{r.get('question_id', '?')}"
            )
            if q.get("sentence"):
                lines.append(f"  題目: {q['sentence']}")
            lines.append(f"  學生答案: {r.get('student_answer', '')}")
            if q.get("correct_answer"):
                lines.append(f"  正確答案: {q['correct_answer']}")
            if q.get("explanation"):
                lines.append(f"  解說: {q['explanation']}")
        if len(mistakes) > 10:
            lines.append(f"另外 {len(mistakes) - 10} 筆錯誤未在文字摘要逐題列出；原始 CSV 均保留。")

    lines.extend(["", "=== Data Quality ==="])
    if issues:
        lines.append(f"CHECK：{len(issues)} 項待核對（不會默默刪除異常資料）")
        for issue in issues:
            lines.append("- " + issue)
    else:
        lines.append("PASS：題數、題目唯一性、各輪分配及最近四次作答分數核對通過。")
    lines.extend([
        "",
        "註：本報告為練習歷程描述，不能取代兩組共同的前測、立即後測或延遲後測。",
        "練習時態分配不同，兩組各時態原始答對題數不能直接當作學習效果比較。",
    ])
    return summary, round_rows, "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="產生六輪英語練習研究資料摘要")
    parser.add_argument("--student", help="指定學生，例如 S904（預設取最新一筆）")
    parser.add_argument("--session", help="指定 session_id")
    parser.add_argument("--all", action="store_true", help="產生全部可識別紀錄及合併表")
    parser.add_argument("--rounds", type=int, default=6, help="預期輪數，預設 6")
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("--rounds 至少要 1")

    sessions = find_sessions(args.student, args.session)
    if not sessions:
        parser.error("找不到符合條件的 practice_學生ID_日期時間.csv；請把本檔放在專案資料夾。")
    if not args.all:
        sessions = sessions[:1]

    OUTPUT_DIR.mkdir(exist_ok=True)
    bank = question_bank()
    summaries, rounds = [], []
    failures = []
    for path, student, session in sessions:
        try:
            summary, round_rows, report_text = inspect_session(
                path, student, session, args.rounds, 6, bank
            )
        except (ValueError, OSError, KeyError) as exc:
            failures.append(f"{path.name}: {exc}")
            continue
        name = f"{student}_{session}"
        report_path = OUTPUT_DIR / f"teacher_report_{name}.txt"
        report_path.write_text(report_text, encoding="utf-8")
        write_csv(OUTPUT_DIR / f"session_summary_{name}.csv", [summary], list(summary))
        write_csv(OUTPUT_DIR / f"round_summary_{name}.csv", round_rows, list(round_rows[0]))
        summaries.append(summary)
        rounds.extend(round_rows)
        if not args.all:
            print(report_text)
            print("\n產生檔案：")
            print("  " + str(report_path.relative_to(ROOT)))
            print("  " + f"reports/session_summary_{name}.csv")
            print("  " + f"reports/round_summary_{name}.csv")
        else:
            print(f"{name}: {summary['condition']} | {summary['quality_status']}")

    if args.all and summaries:
        write_csv(OUTPUT_DIR / "all_session_summaries.csv", summaries, list(summaries[0]))
        write_csv(OUTPUT_DIR / "all_round_summaries.csv", rounds, list(rounds[0]))
        print("\n已產生 reports/all_session_summaries.csv、reports/all_round_summaries.csv")
        print("注意：--all 包含測試與未完成紀錄，不能不經清理就用於正式研究比較。")
    for failure in failures:
        print(f"無法處理：{failure}")
    if not summaries:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
