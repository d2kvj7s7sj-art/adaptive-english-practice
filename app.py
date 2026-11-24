"""Configurable Streamlit practice: two baseline rounds, then dynamic rounds.

Place this file next to questions.csv and adaptive.py. Start using:
    python3 -m streamlit run app.py
"""
import csv
import random
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import streamlit as st
from adaptive import choose_allocation

from storage import create_session_paths
from cloud_records import (
    cloud_ready,
    save_record,
    get_used_question_ids,
    get_recent_first_attempt_results,
    has_sufficient_recent_history,
    teacher_sidebar,
)
ROOT = Path(__file__).resolve().parent
TENSES = ["present", "past", "future"]
CONDITIONS = ["adaptive", "non_adaptive"]

# 主要設定：正式研究預設六輪；開發測試時也可在首頁選擇 3–12 輪。
DEFAULT_ROUNDS = 6
MIN_ROUNDS = 3
MAX_ROUNDS = 12
BASELINE_ROUNDS = 2
QUESTIONS_PER_ROUND = 6
RECENT_ANSWERS = 4

# True: 本機功能測試可手動選組。正式研究請改為 False，並提供 assignments.csv。
TEST_MODE = True
RESPONSE_FIELDS = [
    "student_id", "session_id", "round_no", "question_id",
    "tense", "student_answer", "is_correct", "response_seconds", "condition",
]
DECISION_FIELDS = [
    "student_id", "session_id", "round_no", "phase",
    "present_score", "past_score", "future_score",
    "planned_present", "planned_past", "planned_future", "condition",
]

st.set_page_config(page_title="English Grammar Practice", page_icon="📚")

QUESTION_FILE = ROOT / "questions_v2.csv"


def read_questions():
    with QUESTION_FILE.open(
        encoding="utf-8-sig",
        newline=""
    ) as file:
        questions = list(csv.DictReader(file))

    required = {
        "question_id",
        "tense",
        "sentence",
        "base_verb",
        "correct_answer",
        "explanation",
    }

    if not questions or not required.issubset(questions[0]):
        raise ValueError(
            f"{QUESTION_FILE.name} 缺少必要欄位或沒有題目。"
        )

    ids = [q["question_id"] for q in questions]

    if len(ids) != len(set(ids)):
        raise ValueError(
            f"{QUESTION_FILE.name} 有重複的 question_id。"
        )

    for q in questions:
        if q["tense"] not in TENSES:
            raise ValueError(
                f"題目 {q['question_id']} 的 tense 必須是 "
                "present、past 或 future。"
            )

        if any(not q[key].strip() for key in required):
            raise ValueError(
                f"題目 {q['question_id']} 有必要欄位留白。"
            )

    return questions


def required_questions_per_tense(rounds, condition):
    """最保守的題庫容量：確保任一合法適性分配都不會用到重複題。"""
    if condition == "non_adaptive":
        return rounds * 2
    # 前兩輪各時態各 2 題；之後每輪某時態可能最多分配 3 題。
    return BASELINE_ROUNDS * 2 + (rounds - BASELINE_ROUNDS) * 3


def validate_question_capacity(
    questions,
    rounds,
    condition,
    has_prior_history=False,
):
    if not MIN_ROUNDS <= rounds <= MAX_ROUNDS:
        raise ValueError(
            f"輪數需介於 {MIN_ROUNDS} 與 {MAX_ROUNDS} 之間。"
        )

    if condition == "non_adaptive":
        required = rounds * 2

    elif has_prior_history:
        required = rounds * 3

    else:
        baseline_rounds = min(BASELINE_ROUNDS, rounds)
        adaptive_rounds = max(0, rounds - baseline_rounds)

        required = (
            baseline_rounds * 2
            + adaptive_rounds * 3
        )

    shortages = []

    for tense in TENSES:
        available = sum(
            q["tense"] == tense
            for q in questions
        )

        if available < required:
            shortages.append(
                f"{tense}: 現有 {available}、至少需要 {required} "
                f"(缺 {required - available})"
            )

    if shortages:
        stage = "後續練習" if has_prior_history else "第一次練習"

        raise ValueError(
            f"{rounds} 輪 {condition} {stage}的題庫容量不足。"
            "為避免題目重複：\n"
            + "\n".join(shortages)
        )


def save_csv_header(path, fields):
    with path.open("w", newline="", encoding="utf-8") as file:
        csv.DictWriter(file, fieldnames=fields).writeheader()


def append_csv_row(path, fields, row):
    # 雲端先成功保存，才寫本機備用 CSV。
    save_record(fields, row)
    with path.open("a", newline="", encoding="utf-8") as file:
        csv.DictWriter(file, fieldnames=fields).writerow(row)


@st.cache_resource(ttl=7200, max_entries=256)
def _answer_lock(session_id: str):
    """One lock per practice session, shared across Streamlit reruns."""
    return threading.Lock()


def save_answer_once(practice, result, row):
    """Check and store one (round, question) under the same lock."""
    key = (result["round_no"], result["question_id"])
    with _answer_lock(practice["session_id"]):
        previous = next(
            (
                answer for answer in practice["all_answers"]
                if (answer["round_no"], answer["question_id"]) == key
            ),
            None,
        )
        if previous is not None:
            print("Duplicate submission blocked:", key, flush=True)
            return previous

        # 第一次真正提交本輪答案時，才儲存本輪 adaptive decision
        if not practice.get("decision_saved", False):
            append_csv_row(
                practice["decision_file"],
                DECISION_FIELDS,
                practice["pending_decision"],
            )
            practice["decision_saved"] = True

        # Preserve cloud-first persistence; do not advance on failed save.
        append_csv_row(practice["response_file"], RESPONSE_FIELDS, row)

        practice["all_answers"].append(result)
        practice["round_answers"].append(result)

        return result


def read_assignment(student_id):
    """正式研究：讀取事先隨機分派的組別，不讓學生自行選擇。"""
    path = ROOT / "assignments.csv"
    if not path.exists():
        raise ValueError("正式模式需要 assignments.csv（student_id,condition）。")
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    matching = [r for r in rows if r.get("student_id", "").strip().upper() == student_id]
    if len(matching) != 1:
        raise ValueError(f"Student ID {student_id} 找不到唯一的預先分組紀錄。")
    condition = matching[0].get("condition", "").strip().lower()
    if condition not in CONDITIONS:
        raise ValueError(f"Student ID {student_id} 的 condition 不正確：{condition}")
    return condition


def begin_round(practice):
    round_no = practice["round_no"]

    if not 1 <= round_no <= practice["total_rounds"]:
        raise ValueError(f"不合法的輪次：{round_no}")

    has_prior_history = practice.get("has_prior_history", False)

    if not has_prior_history and round_no <= BASELINE_ROUNDS:
        allocation = [2, 2, 2]
        scores = ["", "", ""]
        phase = "baseline"

    elif practice["condition"] == "adaptive":
        scores = []

        if has_prior_history:
            prior_recent = get_recent_first_attempt_results(
                practice["student_id"],
                per_tense=RECENT_ANSWERS,
                exclude_session_id=practice["session_id"],
            )
        else:
            prior_recent = {
                "present": [],
                "past": [],
                "future": [],
            }

        for tense in TENSES:
            current_recent = [
                a["is_correct"]
                for a in practice["all_answers"]
                if a["tense"] == tense
            ]

            combined = prior_recent[tense] + current_recent
            recent = combined[-RECENT_ANSWERS:]

            if len(recent) < RECENT_ANSWERS:
                raise ValueError(
                    f"{tense} 尚未有 {RECENT_ANSWERS} 次作答；"
                    "無法進入適性階段。"
                )

            scores.append(sum(recent))

        allocation = choose_allocation(
            scores,
            max(0, round_no - BASELINE_ROUNDS - 1),
        )
        phase = "adaptive"

    else:
        allocation = [2, 2, 2]

        scores = []

        for tense in TENSES:
            recent = [
                a["is_correct"]
                for a in practice["all_answers"]
                if a["tense"] == tense
            ][-RECENT_ANSWERS:]

            scores.append(sum(recent) if recent else "")

        phase = "non_adaptive"

    if len(allocation) != 3 or sum(allocation) != QUESTIONS_PER_ROUND or min(allocation) < 1 or max(allocation) > 3:
        raise ValueError(f"適性分配需滿足每輪 {QUESTIONS_PER_ROUND} 題、各時態 1–3 題：{allocation}")

    selected = []
    for tense, count in zip(TENSES, allocation):
        if len(practice["pools"][tense]) < count:
            raise ValueError(f"{tense} 題庫不足，無法選出 {count} 題。")
        selected.extend(practice["pools"][tense][:count])
        practice["pools"][tense] = practice["pools"][tense][count:]
    random.shuffle(selected)

    practice["pending_decision"] = {
        "student_id": practice["student_id"],
        "session_id": practice["session_id"],
        "round_no": round_no,
        "phase": phase,
        "present_score": scores[0],
        "past_score": scores[1],
        "future_score": scores[2],
        "planned_present": allocation[0],
        "planned_past": allocation[1],
        "planned_future": allocation[2],
        "condition": practice["condition"],
    }

    practice["decision_saved"] = False

    practice["round_questions"] = selected
    practice["round_answers"] = []
    practice["question_index"] = 0
    practice["status"] = "question"
    practice["last_result"] = None
    practice["started_at"] = time.perf_counter()
    practice["allocation"] = allocation
    practice["scores"] = scores



def new_practice(student_id, questions, condition, total_rounds=DEFAULT_ROUNDS):
    if condition not in CONDITIONS:
        raise ValueError(f"不支援的實驗條件：{condition}")

    # 1. 從 Supabase 查詢這位學生以前答過的題目
    used_ids = get_used_question_ids(student_id)

    # 2. 排除已經作答的題目
    available_questions = [
        q for q in questions
        if q["question_id"] not in used_ids
    ]

       # 3. 判斷是否已有足夠的前次練習紀錄
    has_prior_history = has_sufficient_recent_history(student_id)

    # 4. 檢查剩餘題庫是否足夠
    validate_question_capacity(
        available_questions,
        total_rounds,
        condition,
        has_prior_history=has_prior_history,
    )

    # 5. 建立新的練習場次
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    # 6. 使用剩餘題目建立各時態題池
    pools = {}

    for tense in TENSES:
        pools[tense] = [
            q for q in available_questions
            if q["tense"] == tense
        ]

        random.shuffle(pools[tense])

    # 7. 建立本次 session 的本機 CSV 路徑
    response_file, decision_file = create_session_paths(
        student_id,
        session_id,
    )

    save_csv_header(
        response_file,
        RESPONSE_FIELDS,
    )

    save_csv_header(
        decision_file,
        DECISION_FIELDS,
    )

    # 8. 建立本次練習狀態
    practice = {
        "student_id": student_id,
        "session_id": session_id,
        "condition": condition,
        "total_rounds": total_rounds,
        "round_no": 1,
        "pools": pools,
        "response_file": response_file,
        "decision_file": decision_file,
        "all_answers": [],
        "has_prior_history": has_prior_history,
    }

    begin_round(practice)

    return practice


def normalize(text):
    return " ".join(text.casefold().split())


st.title("📚 English Grammar Practice")
if not cloud_ready():
    st.error("尚未設定雲端資料庫，為避免遺失紀錄，暫不開放練習。")
    st.stop()
if st.secrets.get("ENABLE_TEACHER_EXPORT", False):
    if teacher_sidebar():
        st.stop()

# 更新程式時不沿用舊版三輪的 session_state，避免缺少 total_rounds。
if "practice" in st.session_state and "total_rounds" not in st.session_state["practice"]:
    del st.session_state["practice"]
    st.info("練習版本已更新，請重新開始新的練習場次。舊場次 CSV 不會刪除。")

try:
    questions = read_questions()
except (OSError, ValueError, RuntimeError) as exc:
    st.error(str(exc))
    st.stop()

if "practice" not in st.session_state:
    st.write(f"預設 {DEFAULT_ROUNDS} 輪、每輪 {QUESTIONS_PER_ROUND} 題；前兩輪固定，後續依組別決定是否適性分配。")
    counts = {t: sum(q["tense"] == t for q in questions) for t in TENSES}
    st.caption("目前題庫：" + "、".join(f"{t} {counts[t]} 題" for t in TENSES))
    with st.form("start_form"):
        student_code = st.text_input("Student ID", value="S001")
        if TEST_MODE:
            selected_rounds = int(st.number_input(
                "練習輪數（開發測試）", min_value=MIN_ROUNDS,
                max_value=MAX_ROUNDS, value=DEFAULT_ROUNDS, step=1,
            ))
            selected_condition = st.radio(
                "測試組別（僅限開發測試）", CONDITIONS,
                format_func=lambda x: "適性組 Adaptive" if x == "adaptive" else "非適性組 Non-Adaptive",
            )
        start = st.form_submit_button("Start Practice", type="primary")

    if start:
        student_code = student_code.strip().upper()
        if not re.fullmatch(r"[A-Z0-9_-]{1,20}", student_code):
            st.error("Student ID 請使用 1–20 個英文字母、數字、- 或 _。")
        else:
            try:
                condition = selected_condition if TEST_MODE else read_assignment(student_code)
                total_rounds = selected_rounds if TEST_MODE else DEFAULT_ROUNDS
                st.session_state.practice = new_practice(student_code, questions, condition, total_rounds)
                st.rerun()
            except (OSError, ValueError) as exc:
                st.error(str(exc))
    st.stop()

p = st.session_state.practice
total_rounds = p["total_rounds"]
total_questions = total_rounds * QUESTIONS_PER_ROUND
round_no = p["round_no"]
status = p["status"]
index = p["question_index"]

st.caption(f"Student: {p['student_id']}  |  Round {round_no} / {total_rounds}")
if TEST_MODE:
    st.caption(f"Testing condition: {p['condition']}")

completed = len(p["all_answers"])

unique_count = len({
    (a["round_no"], a["question_id"])
    for a in p["all_answers"]
})


if completed != unique_count or completed > total_questions:
    keys = [
        (a["round_no"], a["question_id"])
        for a in p["all_answers"]
    ]

    duplicates = [
        key for key in set(keys)
        if keys.count(key) > 1
    ]

    print(
        "Progress error:",
        "completed=", completed,
        "unique=", unique_count,
        "duplicates=", duplicates,
        "round=", round_no,
        "index=", index,
        "status=", status,
        flush=True
    )

    st.error("練習進度異常，請通知老師。")
    st.stop()

st.progress(
    completed / total_questions,
    text=f"Completed: {completed} / {total_questions}"
)
st.divider()

if status == "review":
    st.subheader(f"Round {round_no} · Learning Review")
    answers = p["round_answers"]
    correct_count = sum(a["is_correct"] for a in answers)
    st.write(f"This round: **{correct_count} / {QUESTIONS_PER_ROUND}**")

    st.markdown("**Performance by Tense**")
    for tense in TENSES:
        records = [a for a in answers if a["tense"] == tense]
        score = sum(a["is_correct"] for a in records)
        st.write(f"{tense.capitalize()}: {score} / {len(records)}")

    st.markdown("**Mistakes to Review**")
    mistakes = [a for a in answers if not a["is_correct"]]
    if not mistakes:
        st.success("Great! No mistakes in this round.")
    for item in mistakes:
        st.write("**Question:**", item["sentence"])
        st.write("Your answer:", item["student_answer"])
        st.write("Correct answer:", item["correct_answer"])
        st.info(item["explanation"])
        st.divider()

    if round_no < total_rounds:
        if round_no == BASELINE_ROUNDS:
            st.info("Next round will use the assigned practice condition.")
        if st.button(f"Continue to Round {round_no + 1} →", type="primary"):
            p["round_no"] += 1
            begin_round(p)
            st.rerun()
    else:
        total_correct = sum(a["is_correct"] for a in p["all_answers"])
        st.success(f"All {total_questions} questions completed! Total: {total_correct} / {total_questions}")
        st.caption("Your answers and the planned allocations have been saved as CSV files.")
        if st.button("Start Another Practice"):
            del st.session_state["practice"]
            st.rerun()

else:
    q = p["round_questions"][index]
    st.write(f"Question {index + 1} / {QUESTIONS_PER_ROUND}")
    st.subheader(q["sentence"])
    st.write("Verb:", q["base_verb"])

    if status == "question":
        with st.form(f"answer_{p['session_id']}_{round_no}_{index}"):
            answer = st.text_input("Your answer:")
            submitted = st.form_submit_button("Check Answer")


        if submitted:
            # 檢查同一輪的同一道題是否已提交
            previous = next(
                (
                    a for a in p["all_answers"]
                    if a["round_no"] == round_no
                    and a["question_id"] == q["question_id"]
                ),
                None
            )

            if previous is not None:
                p["last_result"] = previous
                p["status"] = "feedback"
                st.rerun()

            raw_answer = answer.strip()

            if not raw_answer:
                st.warning("Please enter your answer.")
            else:
                seconds = round(time.perf_counter() - p["started_at"], 1)
                is_correct = normalize(raw_answer) == normalize(q["correct_answer"])
                result = {
                    "round_no": round_no,
                    "question_id": q["question_id"],
                    "tense": q["tense"],
                    "sentence": q["sentence"],
                    "student_answer": raw_answer,
                    "correct_answer": q["correct_answer"],
                    "explanation": q["explanation"],
                    "is_correct": is_correct,
                }
                result = save_answer_once(p, result, {
                    "student_id": p["student_id"],
                    "session_id": p["session_id"],
                    "round_no": round_no,
                    "question_id": q["question_id"],
                    "tense": q["tense"],
                    "student_answer": raw_answer,
                    "is_correct": str(is_correct),
                    "response_seconds": seconds,
                    "condition": p["condition"],
                })
                p["last_result"] = result
                p["status"] = "feedback"
                st.rerun()

    elif status == "feedback":
        result = p["last_result"]
        if result["is_correct"]:
            st.success("Correct! 🎉")
        else:
            st.error("Incorrect!")
            st.write("Correct answer:", result["correct_answer"])
            st.info(result["explanation"])

        button_text = "Next Question →" if index < QUESTIONS_PER_ROUND - 1 else "View Learning Review →"
        if st.button(button_text, type="primary"):
            if index < QUESTIONS_PER_ROUND - 1:
                p["question_index"] += 1
                p["status"] = "question"
                p["started_at"] = time.perf_counter()
            else:
                p["status"] = "review"
            st.rerun()
