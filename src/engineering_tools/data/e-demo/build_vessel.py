# engineering-tools MIT — headless heated-vessel B-rep for Phase E identity.
# Calls FreeCAD (LGPL); this script is MIT. Usage: FreeCADCmd build_vessel.py
# cwd receives vessel.step. Three labeled solids: gas cylinder, housing tube, lid.
# Canonical entity_ids are object Labels (body.gas, body.shell, body.lid).
# Face roles are assigned geometrically in extract_identity.py, not OCCT indices.

from pathlib import Path

import FreeCAD as App
import Part
import Import

OUT = Path(".").resolve()
doc = App.newDocument("EHeatedVessel")

gas = Part.makeCylinder(20.0, 40.0)
shell_outer = Part.makeCylinder(25.0, 40.0)
shell_inner = Part.makeCylinder(20.0, 40.0)
shell = shell_outer.cut(shell_inner)
lid = Part.makeCylinder(25.0, 4.0)
lid.translate(App.Vector(0, 0, 40.0))

gas_obj = doc.addObject("Part::Feature", "body.gas")
gas_obj.Shape = gas
shell_obj = doc.addObject("Part::Feature", "body.shell")
shell_obj.Shape = shell
lid_obj = doc.addObject("Part::Feature", "body.lid")
lid_obj.Shape = lid
doc.recompute()

step_path = str(OUT / "vessel.step")
Import.export([gas_obj, shell_obj, lid_obj], step_path)
print(f"engineering-tools: e-demo vessel STEP OK -> {step_path}")
