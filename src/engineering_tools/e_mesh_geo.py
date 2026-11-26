"""Shared vessel.step geo header for solid and fluid Gmsh jobs.

Agents: STEP is millimetres (SI_UNIT MILLI METRE). Scale 0.001 once at the
origin before any BoundingBox. Geometry.OCCBoundsUseStl must be 1 before
Merge so BoundingBox is the tessellated cylinder, not the NURBS control
polygon. No Cylinder() fallback. Do not retune dx/dz inequalities.
"""

from __future__ import annotations

from engineering_tools.e_cad import DEMO_STEP_PATH

# After Dilate 0.001 and OCC STL bounds: gas dx=0.040, shell dx=0.050, lid dz=0.004.
_CLASSIFY_VOLUMES = r"""
vv() = Volume{:};
lidVols[] = {};
gasVols[] = {};
shellVols[] = {};
For i In {0:#vv()-1}
  v = vv(i);
  bb() = BoundingBox Volume {v};
  dx = bb(3)-bb(0); dy = bb(4)-bb(1); dz = bb(5)-bb(2);
  cz = (bb(2)+bb(5))/2;
  If (dz < 0.01 && cz > 0.03)
    lidVols[] += {v};
  EndIf
  If (dx < 0.045 && dz > 0.03)
    gasVols[] += {v};
  EndIf
  If (dx > 0.045 && dz > 0.03)
    shellVols[] += {v};
  EndIf
EndFor
If (#lidVols() != 1)
  Error("expected exactly one lid volume after millimetre scale");
EndIf
If (#gasVols() != 1)
  Error("expected exactly one gas volume after millimetre scale");
EndIf
If (#shellVols() != 1)
  Error("expected exactly one shell volume after millimetre scale");
EndIf
"""


def classified_vessel_step_geo() -> str | None:
    """Merge packaged vessel.step, scale millimeters to meters, classify lid, gas, and shell.

    Returns None when DEMO_STEP_PATH is not a file. Callers must not write
    a cylinder geo in that case.
    """
    if not DEMO_STEP_PATH.is_file():
        return None
    posix = DEMO_STEP_PATH.resolve().as_posix()
    return (
        'SetFactory("OpenCASCADE");\n'
        "Geometry.OCCBoundsUseStl = 1;\n"
        f'Merge "{posix}";\n'
        "Dilate {{0, 0, 0}, 0.001} { Volume{:}; }\n"
        + _CLASSIFY_VOLUMES
    )
