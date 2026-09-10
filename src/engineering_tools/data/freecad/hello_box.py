# engineering-tools MIT sample — headless FreeCAD 10mm box
# Calls FreeCAD (LGPL); this script itself is MIT (c) 2026 mhold3n
# Usage: FreeCADCmd hello_box.py [optional_output.FCStd]
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else None

import FreeCAD as App
import Part

doc = App.newDocument("EngineeringToolsHello")
box = doc.addObject("Part::Box", "HelloBox")
box.Length = 10.0
box.Width = 10.0
box.Height = 10.0
doc.recompute()

if OUT:
    doc.saveAs(OUT)
    print(f"engineering-tools: FreeCAD hello_box OK -> {OUT}")
else:
    print("engineering-tools: FreeCAD hello_box OK (in-memory)")
