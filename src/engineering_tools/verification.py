"""Machine-local installation evidence and hello reports."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .registry import etools_home


def installations_path() -> Path:
    return etools_home() / "installations.json"


def hello_report_path() -> Path:
    return etools_home() / "hello-report.json"


def load_installations() -> dict[str, Any]:
    path = installations_path()
    if not path.is_file():
        return {"schema_version": 1, "components": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"schema_version": 1, "components": {}}
    if not isinstance(data, dict) or not isinstance(data.get("components"), dict):
        return {"schema_version": 1, "components": {}}
    return data


def installation_for(
    component_id: str,
    installations: dict[str, Any],
) -> dict[str, Any] | None:
    value = installations.get("components", {}).get(component_id)
    return value if isinstance(value, dict) else None


def write_installations(data: dict[str, Any]) -> Path:
    """Atomically persist the full installations ledger under ETOOLS_HOME."""
    destination = installations_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(
        prefix=".installations.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(raw_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def upsert_installation(component_id: str, receipt: dict[str, Any]) -> Path:
    """Merge one component receipt into installations.json and write atomically."""
    data = load_installations()
    components = dict(data.get("components") or {})
    components[component_id] = dict(receipt)
    data = {"schema_version": 1, "components": components}
    return write_installations(data)


def write_hello_report(report: dict[str, Any]) -> Path:
    destination = hello_report_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=".hello-report.", suffix=".tmp", dir=destination.parent)
    temporary = Path(raw_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination
