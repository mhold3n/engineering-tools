"""User-level project registry (stdlib JSON, no database)."""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


REGISTRY_VERSION = 1


def etools_home() -> Path:
    """Root for user-level engineering-tools state.

    Override with ``ETOOLS_HOME`` so tests never touch ``~/.engineering-tools``.
    """
    override = os.environ.get("ETOOLS_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".engineering-tools").resolve()


def registry_path() -> Path:
    return etools_home() / "registry.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _empty_registry() -> dict[str, Any]:
    return {"version": REGISTRY_VERSION, "projects": []}


def load_registry() -> dict[str, Any]:
    path = registry_path()
    if not path.is_file():
        return _empty_registry()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_registry()
    if not isinstance(data, dict):
        return _empty_registry()
    data.setdefault("version", REGISTRY_VERSION)
    projects = data.get("projects")
    if not isinstance(projects, list):
        data["projects"] = []
    return data


def save_registry(data: dict[str, Any]) -> Path:
    path = registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": int(data.get("version", REGISTRY_VERSION)),
        "projects": list(data.get("projects") or []),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _slug_id(name: str, path: Path) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "project"
    return f"{base}-{uuid.uuid4().hex[:8]}"


def register_project(
    project_path: str | Path,
    name: Optional[str] = None,
) -> dict[str, Any]:
    """Register or update a project by resolved path. Returns the project entry."""
    root = Path(project_path).expanduser().resolve()
    display = name or root.name
    now = _utc_now_iso()
    data = load_registry()
    projects: list[dict[str, Any]] = data["projects"]

    for entry in projects:
        try:
            existing = Path(entry.get("path", "")).expanduser().resolve()
        except (OSError, TypeError):
            continue
        if existing == root:
            entry["name"] = display
            entry["path"] = str(root)
            entry["updated"] = now
            if "id" not in entry:
                entry["id"] = _slug_id(display, root)
            if "created" not in entry:
                entry["created"] = now
            save_registry(data)
            return entry

    entry = {
        "id": _slug_id(display, root),
        "name": display,
        "path": str(root),
        "created": now,
        "updated": now,
    }
    projects.append(entry)
    save_registry(data)
    return entry


def touch_project(project_path: str | Path) -> Optional[dict[str, Any]]:
    """Bump ``updated`` if the path is already registered; otherwise return None."""
    root = Path(project_path).expanduser().resolve()
    data = load_registry()
    now = _utc_now_iso()
    for entry in data["projects"]:
        try:
            existing = Path(entry.get("path", "")).expanduser().resolve()
        except (OSError, TypeError):
            continue
        if existing == root:
            entry["updated"] = now
            save_registry(data)
            return entry
    return None


def list_projects() -> list[dict[str, Any]]:
    data = load_registry()
    projects = list(data.get("projects") or [])
    projects.sort(key=lambda p: p.get("updated") or p.get("created") or "", reverse=True)
    return projects


def find_project_by_path(project_path: str | Path) -> Optional[dict[str, Any]]:
    root = Path(project_path).expanduser().resolve()
    for entry in list_projects():
        try:
            if Path(entry.get("path", "")).expanduser().resolve() == root:
                return entry
        except (OSError, TypeError):
            continue
    return None
