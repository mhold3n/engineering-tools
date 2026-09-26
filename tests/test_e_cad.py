"""Phase E CAD identity tests. IDs come from B-rep identity, not mesh."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from engineering_tools.e_cad import (
    DEMO_IDENTITY_PATH,
    fingerprint_bytes,
    import_identity,
    rebind_entities,
)


def _write_identity(path: Path, *, extra_face: str | None = None) -> Path:
    entities = [
        {"entity_id": "asm.heated_vessel", "kind": "assembly", "topology_version": 1},
        {"entity_id": "body.shell", "kind": "body", "topology_version": 1},
        {"entity_id": "face.inner_wall", "kind": "face", "topology_version": 1},
        {"entity_id": "face.outer_wall", "kind": "face", "topology_version": 1},
        {"entity_id": "face.lid_inner", "kind": "face", "topology_version": 1},
        {"entity_id": "iface.fluid_solid", "kind": "interface", "topology_version": 1},
    ]
    if extra_face:
        entities.append({"entity_id": extra_face, "kind": "face", "topology_version": 1})
    payload = {
        "schema_version": 1,
        "topology_version": 1,
        "entity_id": "asm.heated_vessel",
        "entities": entities,
        "lineage": [],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def test_fingerprint_bytes_is_sha256_hex() -> None:
    digest = fingerprint_bytes(b"same-bytes")
    assert digest == fingerprint_bytes(b"same-bytes")
    assert digest != fingerprint_bytes(b"other-bytes")
    assert len(digest) == 64
    assert all(ch in "0123456789abcdef" for ch in digest)


def test_identical_geometry_imports_deterministically(tmp_path: Path) -> None:
    identity = _write_identity(tmp_path / "identity.json")
    first = import_identity(identity)
    second = import_identity(identity)
    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert first["entity_ids"] == second["entity_ids"]
    assert first["cad_fingerprint"] == second["cad_fingerprint"]
    assert first["topology_version"] == second["topology_version"] == 1


def test_remesh_does_not_change_entity_ids(tmp_path: Path) -> None:
    identity = _write_identity(tmp_path / "identity.json")
    coarse = import_identity(identity, mesh={"element_size_m": 0.02})
    fine = import_identity(identity, mesh={"element_size_m": 0.002, "algorithm": "tet"})
    assert coarse["status"] == "ok"
    assert fine["status"] == "ok"
    assert coarse["entity_ids"] == fine["entity_ids"]
    assert coarse["cad_fingerprint"] == fine["cad_fingerprint"]


def test_changed_geometry_bumps_topology_version(tmp_path: Path) -> None:
    original = _write_identity(tmp_path / "v1.json")
    first = import_identity(original)
    changed = _write_identity(tmp_path / "v2.json", extra_face="face.nozzle")
    second = import_identity(changed, previous=first)
    assert first["status"] == "ok"
    assert second["status"] == "ok"
    assert second["cad_fingerprint"] != first["cad_fingerprint"]
    assert second["topology_version"] == first["topology_version"] + 1
    assert second["lineage"]


def test_unresolved_entity_rebinding_fails_closed(tmp_path: Path) -> None:
    identity = _write_identity(tmp_path / "identity.json")
    imported = import_identity(identity)
    rebound = rebind_entities(imported, {"face.inner_wall": "face.does_not_exist"})
    assert rebound["status"] == "broken"
    assert "unresolved" in str(rebound["detail"]).lower() or "face.does_not_exist" in str(
        rebound["detail"]
    )


def test_step_without_freecad_is_missing_not_hex_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr("engineering_tools.e_cad.freecad_available", lambda: False)
    step = tmp_path / "vessel.step"
    step.write_bytes(b"ISO-10303-21;HEADER;ENDSEC;DATA;ENDSEC;\n")
    result = import_identity(step)
    assert result["status"] == "missing"
    assert "freecad" in str(result["detail"]).lower()


def test_missing_freecad_loads_demo_fixture(monkeypatch) -> None:
    monkeypatch.setattr("engineering_tools.e_cad.freecad_available", lambda: False)
    result = import_identity()
    assert result["status"] == "ok"
    assert result["source"] == "fixture"
    assert DEMO_IDENTITY_PATH.is_file()
    assert "face.inner_wall" in result["entity_ids"]
    assert result["cad_fingerprint"] == fingerprint_bytes(DEMO_IDENTITY_PATH.read_bytes())


def test_sibling_step_file_fingerprints_step_bytes(tmp_path: Path) -> None:
    identity = _write_identity(tmp_path / "identity.json")
    step = tmp_path / "vessel.step"
    step.write_bytes(b"ISO-10303-21;HEADER;ENDSEC;DATA;ENDSEC;\n")
    result = import_identity(identity)
    assert result["status"] == "ok"
    assert result["cad_fingerprint"] == fingerprint_bytes(step.read_bytes())
    assert result["cad_fingerprint"] != fingerprint_bytes(identity.read_bytes())


def test_e_cad_does_not_call_damper_hex_writers() -> None:
    import engineering_tools.e_cad as e_cad

    source = inspect.getsource(e_cad)
    assert "d_fsi_meshes" not in source
    assert "write_d_solid_inp" not in source
    assert "from engineering_tools.d_" not in source
