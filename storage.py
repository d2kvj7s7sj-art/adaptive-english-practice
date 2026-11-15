"""Project CSV locations: keep new data tidy, keep old records readable.

Does not move or delete legacy CSV files.  Python standard library only.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RESPONSES_DIR = DATA_DIR / "responses"
DECISIONS_DIR = DATA_DIR / "decisions"
REPORTS_DIR = ROOT / "reports"

_STUDENT_ID = re.compile(r"[A-Za-z0-9_-]{1,20}\Z")
_SESSION_ID = re.compile(r"\d{8}_\d{6}(?:_\d{6})?\Z")


def ensure_dirs() -> None:
    RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
    DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def create_session_paths(student_id: str, session_id: str) -> tuple[Path, Path]:
    """Return paths for a *new* practice session; never overwrite old logs."""
    if not _STUDENT_ID.fullmatch(student_id):
        raise ValueError("Student ID 格式不正確。")
    if not _SESSION_ID.fullmatch(session_id):
        raise ValueError("Session ID 格式不正確。")
    ensure_dirs()
    response = RESPONSES_DIR / f"practice_{student_id}_{session_id}.csv"
    decision = DECISIONS_DIR / f"decisions_{student_id}_{session_id}.csv"
    if response.exists() or decision.exists():
        raise FileExistsError(f"此 session 已有紀錄，拒絕覆蓋：{session_id}")
    return response, decision


def _identical(a: Path, b: Path) -> bool:
    if a.stat().st_size != b.stat().st_size:
        return False

    def digest(p: Path) -> bytes:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for part in iter(lambda: f.read(1024 * 1024), b""):
                h.update(part)
        return h.digest()

    return digest(a) == digest(b)


def response_files() -> list[Path]:
    """Find new and legacy response CSVs; identical copies appear only once.

    If an identical filename contains different data in two locations, fail
    loudly instead of silently choosing one as the source of truth.
    """
    candidates = [*RESPONSES_DIR.glob("practice_*.csv"), *ROOT.glob("practice_*.csv")]
    unique: dict[str, Path] = {}
    for p in candidates:
        other = unique.get(p.name)
        if other is None:
            unique[p.name] = p
        elif not _identical(other, p):
            raise ValueError(f"同名作答檔內容不同，請核對：{other} 與 {p}")
    return list(unique.values())


def _resolve_pair(candidates: list[Path]) -> Path:
    existing = [p for p in candidates if p.is_file()]
    if not existing:
        return candidates[0]
    if len(existing) > 1 and not _identical(existing[0], existing[1]):
        raise ValueError(f"同名決策／作答檔內容不一致：{existing[0]} 與 {existing[1]}")
    return existing[0]


def decision_for_response(response_path: Path, student_id: str, session_id: str) -> Path:
    """Prefer the decision next to the new response location, then old root."""
    name = f"decisions_{student_id}_{session_id}.csv"
    return _resolve_pair([DECISIONS_DIR / name, ROOT / name])


def response_for_decision(decision_path: Path) -> Path:
    """Used by legacy verification scripts after migration, if needed."""
    if not decision_path.name.startswith("decisions_"):
        raise ValueError("非決策檔名稱")
    name = decision_path.name.replace("decisions_", "practice_", 1)
    return _resolve_pair([RESPONSES_DIR / name, ROOT / name])
