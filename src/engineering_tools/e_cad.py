"""Phase E CAD B-rep identity import (mesh-independent).

Agents: entity_id and topology_version come from CAD identity, never from
mesh node counts. Path None loads data/e-demo/identity.json (CI without
FreeCAD). A .step file requires FreeCADCmd: extract_identity.py assigns
canonical IDs (body.gas/shell/lid, face.inner_wall). Missing FreeCAD is
missing — never damper hex writers. Changed STEP bytes bump topology_version;
remesh kwargs are ignored.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping

from engineering_tools.hello_probes import _find_freecad_cmd

# Packaged heated-vessel fixture (CI) and live STEP from Ubuntu FreeCAD export.
DEMO_IDENTITY_PATH = Path(__file__).resolve().parent / "data" / "e-demo" / "identity.json"
DEMO_STEP_PATH = Path(__file__).resolve().parent / "data" / "e-demo" / "vessel.step"
_EXTRACT_SCRIPT = Path(__file__).resolve().parent / "data" / "e-demo" / "extract_identity.py"


def fingerprint_bytes(data: bytes) -> str:
    """Stable SHA-256 hex digest of raw CAD or identity bytes."""
    return hashlib.sha256(data).hexdigest()


def freecad_available() -> bool:
    """True when a FreeCAD CLI is on PATH. Absence is missing, not a hex writer."""
    return _find_freecad_cmd() is not None


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
    """Prefer sibling STEP bytes when present; packaged fixture JSON hashes itself."""
    if identity_path.resolve() == DEMO_IDENTITY_PATH.resolve():
        return identity_path.read_bytes(), "identity.json"
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


def _identity_from_record(
    record: Mapping[str, Any],
    *,
    source_name: str,
    source_kind: str,
    cad_fingerprint: str,
    previous: Mapping[str, Any] | None,
) -> dict[str, Any]:
    entity_ids = _entity_ids(record)
    result = {
        "status": "ok",
        "detail": f"imported {source_name}",
        "source": source_kind,
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


def _extract_step_with_freecad(step: Path) -> dict[str, Any]:
    """Run packaged extract_identity.py under FreeCADCmd. Returns identity or missing/broken."""
    command = _find_freecad_cmd()
    if command is None:
        return _missing("FreeCAD not installed; cannot import STEP B-rep")
    if not _EXTRACT_SCRIPT.is_file():
        return _broken(f"extract script missing: {_EXTRACT_SCRIPT}")
    work = Path(tempfile.mkdtemp(prefix="etools-e-cad-"))
    out = work / "identity.json"
    env = os.environ.copy()
    env["ETOOLS_E_STEP"] = str(step.resolve())
    env["ETOOLS_E_OUT"] = str(out)
    try:
        proc = subprocess.run(
            [command, str(_EXTRACT_SCRIPT)],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _broken(f"FreeCAD STEP extract failed: {exc}")
    log = (proc.stdout or "") + "\n" + (proc.stderr or "")
    (work / "cad.log").write_text(log, encoding="utf-8")
    if not out.is_file():
        hint = log.strip().splitlines()[-1] if log.strip() else f"exit {proc.returncode}"
        return _broken(f"FreeCAD did not write identity JSON: {hint}")
    record = _load_identity_json(out)
    if record.get("status") == "broken":
        return _broken(str(record.get("detail") or "extract broken"))
    return dict(record)


def import_identity(
    path: str | Path | None = None,
    *,
    previous: Mapping[str, Any] | None = None,
    mesh: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Import B-rep identity. mesh is accepted and ignored so remesh cannot change IDs.

    path None → packaged e-demo fixture (used when FreeCAD is absent).
    path to .step/.stp without FreeCAD → status missing (not damper hex).
    path to .step/.stp with FreeCAD → extract_identity.py canonical IDs.
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
        record = _extract_step_with_freecad(source)
        if record.get("status") in {"missing", "broken"}:
            return record
        return _identity_from_record(
            record,
            source_name=source.name,
            source_kind="step",
            cad_fingerprint=fingerprint_bytes(source.read_bytes()),
            previous=previous,
        )

    if source.is_dir():
        candidate = source / "identity.json"
        if not candidate.is_file():
            return _broken(f"identity.json missing in {source}")
        source = candidate

    if not source.is_file():
        return _broken(f"identity file not found: {source}")

    record = _load_identity_json(source)
    raw, fp_kind = _fingerprint_source(source)
    source_kind = "fixture" if source.resolve() == DEMO_IDENTITY_PATH.resolve() else fp_kind
    return _identity_from_record(
        record,
        source_name=source.name,
        source_kind=source_kind,
        cad_fingerprint=fingerprint_bytes(raw),
        previous=previous,
    )


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
