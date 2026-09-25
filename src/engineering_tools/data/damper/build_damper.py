# engineering-tools MIT sample — headless parametric damper
# Calls FreeCAD (LGPL); this script itself is MIT (c) 2026 mhold3n
# Usage: FreeCADCmd build_damper.py   (cwd must contain damper-params.json)
# Extra CLI args are treated as documents to open; do not pass the JSON path.
# Probe XYZ must match engineering_tools.damper_params.probes_from_params;
# the orchestrator overwrites probes.json after this script runs.

import json
from pathlib import Path

OUT = Path(".").resolve()
cfg = json.loads((OUT / "damper-params.json").read_text(encoding="utf-8"))

import FreeCAD as App
import Part

OUT.mkdir(parents=True, exist_ok=True)
doc = App.newDocument("DamperKeyway")
length = float(cfg["length_mm"])
od = float(cfg["housing_od_mm"])
inner = float(cfg["housing_id_mm"])
shaft = float(cfg["shaft_od_mm"])
kw = float(cfg["key_width_mm"])
kh = float(cfg["key_height_mm"])
kl = float(cfg["key_length_mm"])
chamber_len = float(cfg["chamber_length_mm"])

outer = Part.makeCylinder(od / 2.0, length)
bore = Part.makeCylinder(inner / 2.0, length)
housing = outer.cut(bore)
shaft_solid = Part.makeCylinder(shaft / 2.0, length)
key = Part.makeBox(kh, kw, kl)
key.translate(App.Vector(shaft / 2.0 - 0.1, -kw / 2.0, (length - kl) / 2.0))
solid = housing.fuse(shaft_solid).fuse(key)
fluid = Part.makeCylinder(inner / 2.0, chamber_len)
fluid.translate(App.Vector(0, 0, (length - chamber_len) / 2.0))

solid_obj = doc.addObject("Part::Feature", "Solid")
solid_obj.Shape = solid
fluid_obj = doc.addObject("Part::Feature", "Fluid")
fluid_obj.Shape = fluid
doc.recompute()

fcstd = str(OUT / "damper.FCStd")
doc.saveAs(fcstd)
solid.exportStep(str(OUT / "solid.step"))
fluid.exportStep(str(OUT / "fluid.step"))

shaft_r = shaft / 2.0
housing_id_r = inner / 2.0
housing_od_r = od / 2.0
probes = {
    "key_fillet": [shaft_r, 0.0, 0.0],
    "keyway_root": [housing_id_r, 0.0, 0.0],
    "belt_land": [housing_od_r, 0.0, 0.0],
    "chamber_center": [0.0, 0.0, 0.0],
    "chamber_wall": [housing_id_r, 0.0, 0.0],
}
(OUT / "probes.json").write_text(json.dumps(probes, indent=2), encoding="utf-8")
print(f"engineering-tools: damper CAD OK -> {fcstd}")
