"""CAD-face coupling map for E: entity identity → preCICE meshes and constraints.

Agents: interfaces couple by face.inner_wall, not coincident node numbers.
Fluid writes Force with conservative mapping; Displacement is consistent.
Traction as a preCICE data name is illegal (OpenFOAM adapter).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from engineering_tools.e_adapter_calculix import prepare_e_solid_participant
from engineering_tools.e_adapter_openfoam import prepare_e_fluid_participant
from engineering_tools.e_backend_precice import generate_e_precice_config
from engineering_tools.e_policy import compile_coupling_policy

CAD_FACE = "face.inner_wall"


def compile_cad_interface_mapping(
    identity: dict[str, Any],
    *,
    solid_nset: str,
    fluid_patch: str,
    solid_nodes: int,
    fluid_nodes: int,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind CAD face to Solid NSET + Fluid patch and emit preCICE XML."""
    ids = set(identity.get("entity_ids") or [])
    if CAD_FACE not in ids:
        return {"status": "broken", "detail": f"identity missing {CAD_FACE}"}
    if not solid_nset or not fluid_patch:
        return {"status": "broken", "detail": "solid_nset and fluid_patch required"}
    topo = int(identity.get("topology_version") or 1)
    pol = policy if policy is not None else compile_coupling_policy(
        kind="implicit two-way",
        require_checkpoint=True,
        aitken_data=["Force", "Heat-Flux"],
        region_physics=["compressible_fluid", "deformable_solid"],
    )
    if pol.get("status") != "ok":
        return {"status": "broken", "detail": pol.get("detail")}
    xml = generate_e_precice_config(pol)
    if "Traction" in xml:
        return {"status": "broken", "detail": "preCICE XML must not use Traction"}
    if 'constraint="conservative"' not in xml:
        return {"status": "broken", "detail": "Fluid write mapping must be conservative"}
    if "Force" not in xml or "Displacement" not in xml:
        return {"status": "broken", "detail": "XML missing Force or Displacement"}
    return {
        "status": "ok",
        "entity_id": CAD_FACE,
        "topology_version": topo,
        "solid": {"nset": solid_nset, "precice_mesh": pol["mesh_name"], "node_count": int(solid_nodes)},
        "fluid": {
            "patch": fluid_patch,
            "precice_mesh": f"{pol['mesh_name']}-fluid",
            "node_count": int(fluid_nodes),
        },
        "mapping": {
            "write_from_fluid": "conservative",
            "read_to_fluid": "consistent",
            "force_data": "Force",
            "displacement_data": "Displacement",
        },
        "conformal": int(solid_nodes) == int(fluid_nodes),
        "xml": xml,
    }


def write_e_coupling_bundle(out_dir: Any, identity: dict[str, Any]) -> dict[str, Any]:
    """Solid INP + Fluid case + mapping XML under out_dir. No solver launch."""

    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    xml_path = root / "precice-config.xml"
    pol = compile_coupling_policy(
        kind="implicit two-way",
        require_checkpoint=True,
        aitken_data=["Force", "Heat-Flux"],
        region_physics=["compressible_fluid", "deformable_solid"],
    )
    if pol.get("status") != "ok":
        return {"status": "broken", "detail": pol.get("detail")}
    xml_path.write_text(generate_e_precice_config(pol), encoding="utf-8")
    solid = prepare_e_solid_participant(root / "e-solid", xml_path, identity)
    fluid = prepare_e_fluid_participant(root / "e-fluid", xml_path, identity)
    if solid.get("status") != "ok":
        return solid
    if fluid.get("status") != "ok":
        return fluid
    mapped = compile_cad_interface_mapping(
        identity,
        solid_nset=str(solid["nset"]),
        fluid_patch=str(fluid["patch"]),
        solid_nodes=len(solid.get("node_ids") or []),
        fluid_nodes=4,
        policy=pol,
    )
    if mapped.get("status") != "ok":
        return mapped
    (root / "e-interface-map.json").write_text(
        json.dumps({k: v for k, v in mapped.items() if k != "xml"}, indent=2),
        encoding="utf-8",
    )
    return {
        "status": "ok",
        "detail": str(root),
        "solid": solid,
        "fluid": fluid,
        "mapping": mapped,
        "precice_xml": str(xml_path),
    }
