"""Hobbyist bill-of-materials (BOM-lite) stored per project."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .project import PROJECT_DIR

BOM_VERSION = 1
BOM_FILENAME = "bom.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def bom_path(project: str | Path) -> Path:
    return Path(project).expanduser().resolve() / PROJECT_DIR / BOM_FILENAME


def empty_bom() -> dict[str, Any]:
    return {"version": BOM_VERSION, "items": []}


def load_bom(project: str | Path) -> dict[str, Any]:
    path = bom_path(project)
    if not path.is_file():
        return empty_bom()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_bom()
    if not isinstance(data, dict):
        return empty_bom()
    data.setdefault("version", BOM_VERSION)
    items = data.get("items")
    if not isinstance(items, list):
        data["items"] = []
    return data


def save_bom(project: str | Path, data: dict[str, Any]) -> Path:
    root = Path(project).expanduser().resolve()
    meta = root / PROJECT_DIR
    meta.mkdir(parents=True, exist_ok=True)
    path = bom_path(root)
    payload = {
        "version": int(data.get("version", BOM_VERSION)),
        "items": list(data.get("items") or []),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def ensure_bom(project: str | Path) -> dict[str, Any]:
    """Load bom.json, creating an empty file if missing."""
    path = bom_path(project)
    if not path.is_file():
        data = empty_bom()
        save_bom(project, data)
        return data
    return load_bom(project)


def list_items(project: str | Path) -> list[dict[str, Any]]:
    return list(load_bom(project).get("items") or [])


def add_item(
    project: str | Path,
    *,
    part: str,
    qty: float | int,
    unit: str = "ea",
    material: str = "",
    source: str = "",
    notes: str = "",
) -> dict[str, Any]:
    """Append one BOM line item. Returns the new item."""
    if not part or not str(part).strip():
        raise ValueError("part name is required")
    data = ensure_bom(project)
    item: dict[str, Any] = {
        "id": uuid.uuid4().hex[:12],
        "part": str(part).strip(),
        "qty": qty,
        "unit": unit or "ea",
        "material": material or "",
        "source": source or "",
        "notes": notes or "",
        "updated": _utc_now_iso(),
    }
    data["items"].append(item)
    save_bom(project, data)
    return item


def remove_item(
    project: str | Path,
    *,
    item_id: Optional[str] = None,
    part: Optional[str] = None,
) -> dict[str, Any]:
    """Remove one item by id or exact part name. Raises KeyError if not found."""
    if not item_id and not part:
        raise ValueError("provide --id or --part to remove")
    data = ensure_bom(project)
    items: list[dict[str, Any]] = list(data.get("items") or [])
    removed: Optional[dict[str, Any]] = None
    kept: list[dict[str, Any]] = []
    for item in items:
        if removed is None:
            if item_id and item.get("id") == item_id:
                removed = item
                continue
            if part is not None and item.get("part") == part:
                removed = item
                continue
        kept.append(item)
    if removed is None:
        hint = f"id={item_id}" if item_id else f"part={part!r}"
        raise KeyError(f"BOM item not found ({hint})")
    data["items"] = kept
    save_bom(project, data)
    return removed
