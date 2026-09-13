"""Compatibility wrapper for component probes; exhaustive orchestration follows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .hello_probes import (
    CALCULIX_CREDIT,
    FREECAD_CREDIT,
    _find_freecad_cmd,
    load_calculix_sample,
    load_freecad_sample,
    probe_calculix,
    probe_freecad,
)


def run_hello(project: str | Path | None = None) -> dict[str, Any]:
    """Retain legacy single-result API until exhaustive engine replaces it."""
    for name, probe in (("CalculiX", probe_calculix), ("FreeCAD", probe_freecad)):
        result = probe(project=project)
        if result["status"] != "missing":
            return {
                "ok": result["status"] == "ok",
                "project": str(Path(project).expanduser().resolve()) if project else None,
                "message": result["message"],
                "backend": name,
                **{
                    key: value
                    for key, value in result.items()
                    if key not in {"id", "name", "status"}
                },
            }
    return {
        "ok": False,
        "project": str(Path(project).expanduser().resolve()) if project else None,
        "message": "No profile tools found on PATH.",
        "backend": None,
        "outputs": [],
    }


__all__ = [
    "CALCULIX_CREDIT",
    "FREECAD_CREDIT",
    "_find_freecad_cmd",
    "load_calculix_sample",
    "load_freecad_sample",
    "run_hello",
]
