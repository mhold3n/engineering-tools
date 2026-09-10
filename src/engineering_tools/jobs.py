"""Per-project append-only job history (JSONL)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .project import PROJECT_DIR


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def project_meta_dir(project: str | Path) -> Path:
    return Path(project).expanduser().resolve() / PROJECT_DIR


def jobs_log_path(project: str | Path) -> Path:
    return project_meta_dir(project) / "jobs.jsonl"


def append_job(
    project: str | Path,
    *,
    tool: Optional[str],
    command: str,
    status: str,
    workdir: Optional[str] = None,
    outputs: Optional[list[str]] = None,
    message: str = "",
    credit: Optional[str] = None,
    input_path: Optional[str] = None,
) -> dict[str, Any]:
    """Append one job record to ``<project>/.engineering-tools/jobs.jsonl``."""
    root = Path(project).expanduser().resolve()
    meta = project_meta_dir(root)
    meta.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "id": uuid.uuid4().hex,
        "tool": tool,
        "command": command,
        "status": status,
        "created": _utc_now_iso(),
        "workdir": workdir,
        "outputs": list(outputs or []),
        "message": message,
        "credit": credit,
        "input": input_path,
    }
    path = jobs_log_path(root)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def read_jobs(project: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    """Return the most recent job records (newest first), up to ``limit``."""
    path = jobs_log_path(project)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    rows.reverse()
    if limit is not None and limit > 0:
        return rows[:limit]
    return rows
