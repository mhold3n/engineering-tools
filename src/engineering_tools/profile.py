"""Detect and summarize installed CAE/CAD tools on PATH."""

from __future__ import annotations

import os
import shutil
from dataclasses import asdict, dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class ToolSpec:
    """Declaration of a tool we know how to look for."""

    name: str
    binaries: tuple[str, ...]
    layer: str
    license_hint: str
    homepage: str


@dataclass(frozen=True)
class DetectedTool:
    """Result of looking for one ToolSpec on PATH."""

    name: str
    layer: str
    license_hint: str
    homepage: str
    found: bool
    binary: Optional[str]
    path: Optional[str]


BASE_PROFILE: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="FreeCAD",
        binaries=("FreeCADCmd", "freecadcmd", "freecad", "FreeCAD"),
        layer="cad",
        license_hint="LGPL-2.1+",
        homepage="https://www.freecad.org/",
    ),
    ToolSpec(
        name="CalculiX",
        binaries=("ccx", "cgx"),
        layer="fea",
        license_hint="GPL-2.0+",
        homepage="http://www.calculix.de/",
    ),
    ToolSpec(
        name="Code_Aster",
        binaries=("as_run", "aster"),
        layer="fea",
        license_hint="GPL-3.0+",
        homepage="https://code-aster.org/",
    ),
    ToolSpec(
        name="OpenFOAM",
        binaries=("blockMesh", "simpleFoam", "foamExec", "icoFoam"),
        layer="cfd",
        license_hint="GPL-3.0",
        homepage="https://openfoam.org/",
    ),
    ToolSpec(
        name="Elmer",
        binaries=("ElmerSolver", "ElmerGrid", "elmer"),
        layer="multiphysics",
        license_hint="GPL-2.0+",
        homepage="https://www.csc.fi/web/elmer",
    ),
    ToolSpec(
        name="OpenModelica",
        binaries=("omc", "OMEdit"),
        layer="system",
        license_hint="GPL-3.0 / OSMC-PL",
        homepage="https://openmodelica.org/",
    ),
    ToolSpec(
        name="Gmsh",
        binaries=("gmsh",),
        layer="mesh",
        license_hint="GPL-2.0+",
        homepage="https://gmsh.info/",
    ),
    ToolSpec(
        name="ParaView",
        binaries=("paraview", "pvpython", "pvbatch"),
        layer="viz",
        license_hint="BSD-3-Clause",
        homepage="https://www.paraview.org/",
    ),
)


def detect_tool(
    spec: ToolSpec,
    path_env: Optional[str] = None,
) -> DetectedTool:
    """Return whether any of ``spec.binaries`` is on PATH."""
    search_path = path_env if path_env is not None else os.environ.get("PATH", "")
    for binary in spec.binaries:
        resolved = shutil.which(binary, path=search_path)
        if resolved:
            return DetectedTool(
                name=spec.name,
                layer=spec.layer,
                license_hint=spec.license_hint,
                homepage=spec.homepage,
                found=True,
                binary=binary,
                path=resolved,
            )
    return DetectedTool(
        name=spec.name,
        layer=spec.layer,
        license_hint=spec.license_hint,
        homepage=spec.homepage,
        found=False,
        binary=None,
        path=None,
    )


def detect_profile(
    specs: Iterable[ToolSpec] = BASE_PROFILE,
    path_env: Optional[str] = None,
) -> list[DetectedTool]:
    """Detect every tool in ``specs`` against ``path_env`` (or process PATH)."""
    return [detect_tool(spec, path_env=path_env) for spec in specs]


def summarize_profile(detected: Iterable[DetectedTool]) -> dict:
    """Return counts and lists useful for doctor / hello output."""
    items = list(detected)
    found = [d for d in items if d.found]
    missing = [d for d in items if not d.found]
    by_layer: dict[str, list[str]] = {}
    for d in found:
        by_layer.setdefault(d.layer, []).append(d.name)
    return {
        "total": len(items),
        "found_count": len(found),
        "missing_count": len(missing),
        "found": [d.name for d in found],
        "missing": [d.name for d in missing],
        "by_layer": by_layer,
        "details": [asdict(d) for d in items],
    }
