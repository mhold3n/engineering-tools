"""Phase E CAD B-rep identity import (mesh-independent).

Agents: entity_id and topology_version come from CAD identity, never from
mesh node counts. Missing FreeCAD is status missing — load data/e-demo/identity.json
for the heated-vessel fixture. Do not import Phase D FSI mesh builders or
solid INP hex writers. Changed STEP/identity bytes bump topology_version;
remesh kwargs are ignored. Unresolved rebind targets fail closed (broken).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

# Packaged heated-vessel fixture used when FreeCAD is not installed.
DEMO_IDENTITY_PATH = Path(__file__).resolve().parent / "data" / "e-demo" / "identity.json"


def fingerprint_bytes(data: bytes) -> str:
    """Stable SHA-256 hex digest of raw CAD or identity bytes."""
    return hashlib.sha256(data).hexdigest()


def freecad_available() -> bool:
    """True only when FreeCADCmd is on PATH. Absence is missing, not a hex writer."""
    return shutil.which("FreeCADCmd") is not None


def _ok(detail: str, **fields: Any) -> dict[str, Any]:
    payload = {"status": "ok", "detail": detail}
    payload.update(fields)
    return payload


def _missing(detail: str) -> dict[str, Any]:
    return {"status": "missing", "detail": detail}


def _broken(detail: str) -> dict[str, Any]:
    return {"status": "broken", "detail": detail}


def _is_step(path: Path) -> bool:
    return path.suffix.lower() in {".step", ".stp"}


def _fingerprint_source(identity_path: Path) -> tuple[bytes, str]:
    """Prefer sibling STEP bytes when present; otherwise hash identity.json."""
    if identity_path.is_file() and _is_step(identity_path):
        data = identity_path.read_bytes()
        return data, "step"
    directory = identity_path.parent if identity_path.is_file() else identity_path
    step_files = sorted(
        p for p in directory.iterdir() if p.is_file() and _is_step(p)
    )
    if step_files:
        return step_files[0].read_bytes(), "step"
    return identity_path.read_bytes(), "identity.json"


def _load_identity_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _entity_ids(record: Mapping[str, Any]) -> list[str]:
    ids = [str(ent["entity_id"]) for ent in record.get("entities") or []]
    root = record.get("entity_id")
    if root and str(root) not in ids:
        ids.insert(0, str(root))
    return ids


def _apply_previous(current: dict[str, Any], previous: Mapping[str, Any] | None) -> None:
    """Keep topology_version when fingerprint matches; bump and record lineage when it changes."""
    if previous is None:
        current.setdefault("topology_version", int(current.get("topology_version") or 1))
        current.setdefault("lineage", list(current.get("lineage") or []))
        return
    prev_fp = previous.get("cad_fingerprint")
    prev_ver = int(previous.get("topology_version") or 1)
    if prev_fp == current["cad_fingerprint"]:
        current["topology_version"] = prev_ver
        current["lineage"] = list(previous.get("lineage") or [])
        return
    new_ver = prev_ver + 1
    current["topology_version"] = new_ver
    lineage = list(previous.get("lineage") or [])
    lineage.append(
        {
            "from_topology_version": prev_ver,
            "to_topology_version": new_ver,
            "from_fingerprint": prev_fp,
            "to_fingerprint": current["cad_fingerprint"],
            "rebinding": dict(previous.get("rebinding") or {}),
        }
    )
    current["lineage"] = lineage


def import_identity(
    path: str | Path | None = None,
    *,
    previous: Mapping[str, Any] | None = None,
    mesh: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Import B-rep identity. mesh is accepted and ignored so remesh cannot change IDs.

    path None → packaged e-demo fixture (used when FreeCAD is absent).
    path to .step/.stp without FreeCAD → status missing (not damper hex).
    """
    del mesh  # identity is CAD-only; discretization must not mint entity_id
    if path is None:
        path = DEMO_IDENTITY_PATH
    source = Path(path)

    if _is_step(source):
        if not source.is_file():
            return _broken(f"STEP file not found: {source}")
        if not freecad_available():
            return _missing("FreeCAD not installed; cannot import STEP B-rep")
        return _broken("FreeCAD STEP import is not wired in this unit")

    if source.is_dir():
        candidate = source / "identity.json"
        if not candidate.is_file():
            return _broken(f"identity.json missing in {source}")
        source = candidate

    if not source.is_file():
        return _broken(f"identity file not found: {source}")

    record = _load_identity_json(source)
    raw, fp_kind = _fingerprint_source(source)
    cad_fingerprint = fingerprint_bytes(raw)
    entity_ids = _entity_ids(record)
    result = {
        "status": "ok",
        "detail": f"imported {source.name}",
        "source": "fixture" if source.resolve() == DEMO_IDENTITY_PATH.resolve() else fp_kind,
        "entity_id": record.get("entity_id") or (entity_ids[0] if entity_ids else None),
        "entity_ids": entity_ids,
        "entities": list(record.get("entities") or []),
        "cad_fingerprint": cad_fingerprint,
        "topology_version": int(record.get("topology_version") or 1),
        "lineage": list(record.get("lineage") or []),
        "rebinding": dict(record.get("rebinding") or {}),
    }
    _apply_previous(result, previous)
    return result


def rebind_entities(
    identity: Mapping[str, Any], mapping: Mapping[str, str]
) -> dict[str, Any]:
    """Apply explicit lineage rebinding. Unknown targets fail closed."""
    known = set(_entity_ids(identity))
    for source_id, target_id in mapping.items():
        if target_id not in known:
            return _broken(f"unresolved entity rebinding {source_id}->{target_id}")
        if source_id not in known:
            return _broken(f"unresolved entity rebinding source {source_id}")
    rebound = dict(identity)
    rebound["status"] = "ok"
    rebound["detail"] = "rebound"
    rebound["rebinding"] = {**dict(identity.get("rebinding") or {}), **dict(mapping)}
    rebound["lineage"] = list(identity.get("lineage") or []) + [
        {"rebinding": dict(mapping), "topology_version": identity.get("topology_version")}
    ]
    return rebound
