"""Mesh sync run for the heated vessel.

Agents: this module sequences existing owners. It does not mesh and it does
not start CalculiX, rhoPimpleFoam, or the coupled participant loop.
Intended result is mesh-sync.json. pair comes from mesh_e_reference.
calculix_mesh is the inp written from that solid msh. openfoam_mesh is
gmshToFoam on that fluid msh. sync is the shared CAD face plus the live
fluid-first XML. Observed status is the first stage that is not ok.
A missing gmshToFoam is missing. A converter that runs and fails is broken.
e_ok is true only when every stage is ok.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engineering_tools.e_adapter_calculix import _ninterface_ids, prepare_e_solid_participant
from engineering_tools.e_adapter_openfoam import (
    _e_openfoam_tool,
    mesh_e_fluid_participant,
    prepare_e_fluid_participant,
)
from engineering_tools.e_backend_precice import generate_e_precice_config
from engineering_tools.e_cad import import_identity
from engineering_tools.e_facade import _compile_live_policy
from engineering_tools.e_mesh_pair import INNER_WALL, mesh_e_reference

_STAGE_ORDER = ("pair", "calculix_mesh", "openfoam_mesh", "sync")


def _stage(status: str, detail: str, **extra: Any) -> dict[str, Any]:
    """One stage record. status is ok, missing, or broken."""
    record: dict[str, Any] = {"status": status, "detail": detail}
    record.update(extra)
    return record


def _overall(stages: dict[str, dict[str, Any]]) -> tuple[str, bool]:
    """First stage that is not ok. e_ok requires every named stage to be ok."""
    for name in _STAGE_ORDER:
        stage = stages.get(name)
        if stage is None:
            return "broken", False
        if stage["status"] != "ok":
            return str(stage["status"]), False
    return "ok", True


def _sync_stage(pair: dict[str, Any], xml: str) -> dict[str, Any]:
    """Same CAD face, same topology version, fluid-first XML, no solid displacement."""
    face = str(pair.get("canonical_face_id") or "")
    solid_tv = pair.get("solid", {}).get("topology_version")
    fluid_tv = pair.get("fluid", {}).get("topology_version")
    if face != INNER_WALL:
        return _stage("broken", f"canonical face is {face}")
    if solid_tv != fluid_tv:
        return _stage("broken", f"topology_version solid {solid_tv} fluid {fluid_tv}")
    if '<participants first="Fluid" second="Solid"/>' not in xml:
        return _stage("broken", "live XML is not Fluid first")
    # receive-mesh from="Solid" is mesh ownership. An exchange from Solid is a write.
    if 'from="Solid" to=' in xml or 'exchange data="Displacement"' in xml or 'write-data name="Displacement"' in xml:
        return _stage("broken", "live XML writes solid displacement")
    return _stage("ok", INNER_WALL, topology_version=solid_tv)


def _openfoam_stage(fluid_dir: Path) -> dict[str, Any]:
    """gmshToFoam when the tool exists. No tool is missing, not a passed mesh."""
    if _e_openfoam_tool("gmshToFoam") is None:
        return _stage("missing", "gmshToFoam not found")
    if not mesh_e_fluid_participant(fluid_dir):
        return _stage("broken", "gmshToFoam failed")
    boundary = fluid_dir / "constant" / "polyMesh" / "boundary"
    if not boundary.is_file():
        return _stage("broken", "constant/polyMesh/boundary is missing")
    text = boundary.read_text(encoding="utf-8", errors="replace")
    if INNER_WALL not in text:
        return _stage("broken", f"polyMesh boundary has no {INNER_WALL}")
    return _stage("ok", str(boundary))


def mesh_sync_run(
    out: Path,
    *,
    identity: dict[str, Any] | None = None,
    h_max: float = 0.012,
) -> dict[str, Any]:
    """Run pair, CalculiX deck, OpenFOAM mesh, and wall sync. Write mesh-sync.json.

    Stops before run_coupled_participants. Pass the pair msh into the deck
    writers so this function does not mesh a second time.
    """
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ident = identity if identity is not None else import_identity()
    stages: dict[str, dict[str, Any]] = {}

    if ident.get("status") in {"missing", "broken"}:
        stages["pair"] = _stage(str(ident.get("status") or "broken"), str(ident.get("detail") or "identity"))
    else:
        pair = mesh_e_reference(out / "meshes", identity=ident, h_max=h_max)
        solid_nodes = int(pair.get("solid_volume_nodes") or 0)
        fluid_nodes = int(pair.get("fluid_volume_nodes") or 0)
        if not pair.get("e_mesh_ok"):
            stages["pair"] = _stage(
                str(pair.get("status") or "broken"),
                str(pair.get("detail") or "mesh pair failed"),
            )
        elif solid_nodes <= 0 or fluid_nodes <= 0:
            stages["pair"] = _stage("broken", "volume node count is zero")
        else:
            stages["pair"] = _stage(
                "ok",
                str(pair.get("detail") or INNER_WALL),
                canonical_face_id=pair.get("canonical_face_id"),
                solid_volume_nodes=solid_nodes,
                fluid_volume_nodes=fluid_nodes,
            )
            policy = _compile_live_policy(windows=1, time_window=0.01)
            if policy.get("status") != "ok":
                stages["sync"] = _stage("broken", str(policy.get("detail") or "live policy"))
            else:
                xml = generate_e_precice_config(policy)
                xml_path = out / "precice-config.xml"
                xml_path.write_text(xml, encoding="utf-8")
                solid_dir = out / "e-solid"
                fluid_dir = out / "e-fluid"
                solid = prepare_e_solid_participant(
                    solid_dir,
                    xml_path,
                    ident,
                    msh=Path(str(pair["solid"]["artifact"])),
                )
                n_iface = len(_ninterface_ids(solid_dir)) if solid.get("status") == "ok" else 0
                if solid.get("status") != "ok":
                    stages["calculix_mesh"] = _stage(
                        str(solid.get("status") or "broken"),
                        str(solid.get("detail") or "solid deck failed"),
                    )
                elif n_iface <= 0:
                    stages["calculix_mesh"] = _stage("broken", "NinterfaceN is empty")
                else:
                    stages["calculix_mesh"] = _stage("ok", "NinterfaceN", n_interface_nodes=n_iface)
                fluid = prepare_e_fluid_participant(
                    fluid_dir,
                    xml_path,
                    ident,
                    msh=Path(str(pair["fluid"]["artifact"])),
                )
                if fluid.get("status") != "ok":
                    stages["openfoam_mesh"] = _stage(
                        str(fluid.get("status") or "broken"),
                        str(fluid.get("detail") or "fluid deck failed"),
                    )
                else:
                    stages["openfoam_mesh"] = _openfoam_stage(fluid_dir)
                if "sync" not in stages:
                    stages["sync"] = _sync_stage(pair, xml)

    status, e_ok = _overall(stages)
    report = {"status": status, "e_ok": e_ok, "stages": stages}
    (out / "mesh-sync.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report
