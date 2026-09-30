# engineering-tools MIT — FreeCAD STEP → canonical E identity JSON.
# Agents: run via e_cad with env ETOOLS_E_STEP and ETOOLS_E_OUT.
# Labels body.gas / body.shell / body.lid are preferred. If STEP dropped
# labels, solids are classified by volume (max=gas, min=lid, rest=shell).
# Faces: inner_wall = shell cylindrical face with smaller radius;
# outer_wall = shell cylindrical face with larger radius;
# lid_inner = lid planar face with smaller CenterOfMass.z.
# Do not mint IDs from mesh or from raw OCCT face numbers.

import json
import os
from pathlib import Path

import FreeCAD as App
import Import

STEP = os.environ["ETOOLS_E_STEP"]
OUT = os.environ["ETOOLS_E_OUT"]

doc = App.newDocument("EImport")
Import.insert(STEP, doc.Name)
doc.recompute()

solids = []
for obj in doc.Objects:
    if getattr(obj, "TypeId", "") != "Part::Feature":
        continue
    shape = getattr(obj, "Shape", None)
    if shape is None or shape.isNull():
        continue
    label = str(getattr(obj, "Label", "") or "")
    if label.startswith("body_"):
        label = "body." + label[len("body_") :]
    parts = list(shape.Solids) if getattr(shape, "Solids", None) else [shape]
    for solid in parts:
        if solid.isNull() or float(solid.Volume) <= 0:
            continue
        solids.append({"label": label, "shape": solid, "volume": float(solid.Volume)})

if len(solids) < 3:
    Path(OUT).write_text(
        json.dumps({"status": "broken", "detail": f"expected 3 solids, got {len(solids)}"}),
        encoding="utf-8",
    )
    raise SystemExit(0)

wanted = {"body.gas", "body.shell", "body.lid"}
labeled = {row["label"]: row for row in solids if row["label"] in wanted}
if set(labeled) == wanted:
    gas_s = labeled["body.gas"]["shape"]
    shell_s = labeled["body.shell"]["shape"]
    lid_s = labeled["body.lid"]["shape"]
else:
    ordered = sorted(solids, key=lambda row: row["volume"], reverse=True)
    gas_s = ordered[0]["shape"]
    lid_s = ordered[-1]["shape"]
    shell_s = ordered[1]["shape"]


def _cyl_faces(shape):
    faces = []
    for face in shape.Faces:
        surf = face.Surface
        if not hasattr(surf, "Radius"):
            continue
        try:
            radius = float(surf.Radius)
        except Exception:
            continue
        faces.append((radius, face))
    return faces


def _planar_faces(shape):
    out = []
    for face in shape.Faces:
        surf = face.Surface
        if hasattr(surf, "Radius"):
            continue
        com = face.CenterOfMass
        out.append((float(com.z), face))
    return out


cyl = sorted(_cyl_faces(shell_s), key=lambda item: item[0])
if len(cyl) < 2:
    Path(OUT).write_text(
        json.dumps({"status": "broken", "detail": "shell has fewer than 2 cylindrical faces"}),
        encoding="utf-8",
    )
    raise SystemExit(0)
inner_face = cyl[0][1]
outer_face = cyl[-1][1]
lid_planes = sorted(_planar_faces(lid_s), key=lambda item: item[0])
lid_inner = lid_planes[0][1]

entities = [
    {"entity_id": "asm.heated_vessel", "kind": "assembly", "topology_version": 1},
    {"entity_id": "body.shell", "kind": "body", "parent_id": "asm.heated_vessel", "topology_version": 1},
    {"entity_id": "body.lid", "kind": "body", "parent_id": "asm.heated_vessel", "topology_version": 1},
    {"entity_id": "body.gas", "kind": "body", "parent_id": "asm.heated_vessel", "topology_version": 1},
    {
        "entity_id": "face.inner_wall",
        "kind": "face",
        "parent_id": "body.shell",
        "role": "heated_wall",
        "area_mm2": float(inner_face.Area),
        "com_mm": [float(inner_face.CenterOfMass.x), float(inner_face.CenterOfMass.y), float(inner_face.CenterOfMass.z)],
        "topology_version": 1,
    },
    {
        "entity_id": "face.outer_wall",
        "kind": "face",
        "parent_id": "body.shell",
        "role": "ambient",
        "area_mm2": float(outer_face.Area),
        "com_mm": [float(outer_face.CenterOfMass.x), float(outer_face.CenterOfMass.y), float(outer_face.CenterOfMass.z)],
        "topology_version": 1,
    },
    {
        "entity_id": "face.lid_inner",
        "kind": "face",
        "parent_id": "body.lid",
        "area_mm2": float(lid_inner.Area),
        "com_mm": [float(lid_inner.CenterOfMass.x), float(lid_inner.CenterOfMass.y), float(lid_inner.CenterOfMass.z)],
        "topology_version": 1,
    },
    {
        "entity_id": "iface.fluid_solid",
        "kind": "interface",
        "parent_id": "face.inner_wall",
        "topology_version": 1,
    },
]
payload = {
    "status": "ok",
    "schema_version": 1,
    "topology_version": 1,
    "entity_id": "asm.heated_vessel",
    "entities": entities,
    "lineage": [],
    "rebinding": {},
}
Path(OUT).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"engineering-tools: e-cad extract OK -> {OUT}")
