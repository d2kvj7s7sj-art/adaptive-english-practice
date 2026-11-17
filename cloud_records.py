"""Supabase data persistence and password-gated teacher export for the prototype.

Server-only secret key. Never include this key in code, logs, or client UI.
"""
from __future__ import annotations

import re
import csv
import hmac
import io
import zipfile
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
import streamlit as st

COLUMNS = {
    "practice_responses": [
        "student_id", "session_id", "round_no", "question_id", "tense",
        "student_answer", "is_correct", "response_seconds", "condition", "created_at",
    ],
    "practice_decisions": [
        "student_id", "session_id", "round_no", "phase", "present_score",
        "past_score", "future_score", "planned_present", "planned_past",
        "planned_future", "condition", "created_at",
    ],
}

CONFLICT_KEYS = {
    "practice_responses": "student_id,session_id,round_no,question_id",
    "practice_decisions": "student_id,session_id,round_no",
}


def _secret(name: str) -> str:
    try:
        return str(st.secrets.get(name, "")).strip()
    except (FileNotFoundError, KeyError):
        return ""


def cloud_ready() -> bool:
    return bool(_secret("SUPABASE_URL") and _secret("SUPABASE_SECRET_KEY"))


def _endpoint(table: str) -> str:
    if table not in COLUMNS:
        raise ValueError("Unknown table")
    url = _secret("SUPABASE_URL").rstrip("/")
    if not url.startswith("https://") or not url.endswith(".supabase.co"):
        raise RuntimeError("SUPABASE_URL 格式不正確")
    return f"{url}/rest/v1/{table}"


def _headers() -> dict[str, str]:
    key = _secret("SUPABASE_SECRET_KEY")
    if not key.startswith("sb_secret_"):
        raise RuntimeError("請設定 Supabase 新版 sb_secret_ 開頭的伺服器金鑰")
    return {"apikey": key, "Content-Type": "application/json"}


def _check_response(resp: requests.Response) -> None:
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        # Do not accidentally print credentials or full request headers.
        raise RuntimeError(f"雲端資料庫回應 HTTP {resp.status_code}，請檢查資料表、權限與 Secrets。") from exc


def save_record(fields: list[str], row: dict) -> None:
    """Write a response/decision to Supabase FIRST, before local CSV is appended.

    The composite primary keys make retries idempotent.
    """
    if not cloud_ready():
        raise RuntimeError("尚未設定 Supabase，拒絕只寫入容易遺失的本機 CSV。")
    if "question_id" in fields:
        table = "practice_responses"
        data = {key: row[key] for key in COLUMNS[table] if key in row}
        data["round_no"] = int(data["round_no"])
        data["is_correct"] = str(data["is_correct"]).lower() == "true"
        data["response_seconds"] = float(data["response_seconds"])
    else:
        table = "practice_decisions"
        data = {key: row[key] for key in COLUMNS[table] if key in row}
        for key in ("round_no", "planned_present", "planned_past", "planned_future"):
            data[key] = int(data[key])
        for key in ("present_score", "past_score", "future_score"):
            data[key] = None if str(data.get(key, "")).strip() == "" else int(data[key])

    params = urlencode({"on_conflict": CONFLICT_KEYS[table]})
    headers = {**_headers(), "Prefer": "resolution=merge-duplicates,return=minimal"}
    try:
        response = requests.post(_endpoint(table) + "?" + params,
                                 json=data, headers=headers, timeout=12)
    except requests.RequestException as exc:
        raise RuntimeError("雲端連線失敗，作答尚未確認儲存，請稍後重試。") from exc
    _check_response(response)


def get_used_question_ids(student_id: str) -> set[str]:
    """查詢指定學生過去已提交作答的題目 ID。"""
    student_id = student_id.strip().upper()

    if not re.fullmatch(r"[A-Z0-9_-]{1,20}", student_id):
        raise ValueError("Student ID 格式不正確。")

    if not cloud_ready():
        raise RuntimeError("Supabase 尚未設定，無法檢查舊題。")

    used_ids = set()
    offset = 0
    page_size = 500

    while True:
        params = {
            "select": "question_id",
            "student_id": f"eq.{student_id}",
            "order": "session_id.asc,round_no.asc,question_id.asc",
            "limit": page_size,
            "offset": offset,
        }

        try:
            resp = requests.get(
                _endpoint("practice_responses"),
                headers=_headers(),
                params=params,
                timeout=20,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                "無法查詢學生過去的作答紀錄，已停止選題。"
            ) from exc

        _check_response(resp)

        try:
            rows = resp.json()
        except ValueError as exc:
            raise RuntimeError("Supabase 回傳的資料格式不正確。") from exc

        if not isinstance(rows, list):
            raise RuntimeError("Supabase 回傳的資料格式不正確。")

        used_ids.update(
            row["question_id"]
            for row in rows
            if isinstance(row, dict) and row.get("question_id")
        )

        if len(rows) < page_size:
            return used_ids

        offset += page_size

def _fetch_all(table: str) -> list[dict]:
    """Page over records rather than silently truncating at Supabase's default 1000."""
    all_rows: list[dict] = []
    offset = 0
    page_size = 500
    while True:
        params = {"select": ",".join(COLUMNS[table]),
                  "order": "student_id.asc,session_id.asc,round_no.asc" + (",question_id.asc" if table == "practice_responses" else ""),
                  "limit": page_size, "offset": offset}
        try:
            resp = requests.get(_endpoint(table), headers=_headers(),
                                params=params, timeout=20)
        except requests.RequestException as exc:
            raise RuntimeError("匯出時無法連接雲端資料庫。") from exc
        _check_response(resp)
        page = resp.json()
        if not isinstance(page, list):
            raise RuntimeError("雲端資料格式不正確")
        all_rows.extend(page)
        if len(page) < page_size:
            return all_rows
        offset += page_size


def _csv_bytes(columns: list[str], rows: list[dict]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def export_all_zip() -> tuple[bytes, dict[str, int]]:
    response_rows = _fetch_all("practice_responses")
    decision_rows = _fetch_all("practice_decisions")
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("practice_responses.csv", _csv_bytes(COLUMNS["practice_responses"], response_rows))
        archive.writestr("practice_decisions.csv", _csv_bytes(COLUMNS["practice_decisions"], decision_rows))
        archive.writestr("README.txt", "Contains pseudonymised prototype practice data. Store privately.\n")
    return data.getvalue(), {"responses": len(response_rows), "decisions": len(decision_rows)}


def teacher_sidebar() -> bool:
    """Returns True if teacher-only screen is shown (caller should st.stop())."""
    mode = st.sidebar.radio("網站模式", ["學生練習", "教師資料匯出"])
    if mode != "教師資料匯出":
        return False

    secret = _secret("TEACHER_EXPORT_PASSWORD")
    if len(secret) < 20:
        st.error("教師匯出密碼尚未設定，或密碼太短（至少 20 字元）。")
        return True

    if not st.session_state.get("teacher_authenticated", False):
        with st.form("teacher_login"):
            password = st.text_input("教師匯出密碼", type="password")
            submitted = st.form_submit_button("驗證")
        if submitted:
            if hmac.compare_digest(password, secret):
                st.session_state["teacher_authenticated"] = True
                st.rerun()
            else:
                st.error("密碼不正確。")
        return True

    st.subheader("教師資料匯出")
    st.caption("僅限授權教師使用；學生不應看到或下載他人的紀錄。")
    if st.button("登出教師模式"):
        st.session_state["teacher_authenticated"] = False
        st.session_state.pop("teacher_export_package", None)
        st.session_state.pop("teacher_export_counts", None)
        st.rerun()
    if st.button("準備匯出資料"):
        try:
            content, counts = export_all_zip()
        except Exception as exc:
            st.error(f"匯出失敗：{exc}")
        else:
            st.session_state["teacher_export_package"] = content
            st.session_state["teacher_export_counts"] = counts
    if "teacher_export_package" in st.session_state:
        counts = st.session_state["teacher_export_counts"]
        st.write(f"作答紀錄：{counts['responses']} 列；分配決策：{counts['decisions']} 列。")
        st.download_button("下載 CSV ZIP（ZIP 本身未加密）",
                           data=st.session_state["teacher_export_package"],
                           file_name=f"practice_export_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.zip",
                           mime="application/zip")
    return True
