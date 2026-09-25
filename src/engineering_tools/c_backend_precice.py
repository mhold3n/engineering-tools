"""preCICE coupling backend for C orchestration.

Comments for other agents: this module is the Python preCICE **backend** adapter,
not the C language runtime. It turns a coupling policy dict into preCICE XML and
locates the `precice` CLI on PATH. Generation is pure string assembly from policy;
it never reads an on-disk precice-config.xml as input.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


def default_policy() -> dict[str, Any]:
    """Return the default C coupling policy for Solid/Fluid FSI."""
    return {
        "participants": [
            {"name": "Solid", "solver": "calculix"},
            {"name": "Fluid", "solver": "openfoam"},
        ],
        "mesh_name": "interface",
        "read_by_fluid": "Displacement",
        "read_by_solid": "Traction",
        "time_window": 0.01,
        "max_iterations": 100,
    }


def find_precice() -> Path | None:
    """Locate the preCICE driver binary named `precice` on PATH."""
    found = shutil.which("precice")
    if found is None:
        return None
    return Path(found)


def generate_precice_config(policy: dict[str, Any]) -> str:
    """Build preCICE configuration XML from a coupling policy dict."""
    participants: list[dict[str, str]] = policy["participants"]
    mesh_name = str(policy["mesh_name"])
    read_by_fluid = str(policy["read_by_fluid"])
    read_by_solid = str(policy["read_by_solid"])
    time_window = float(policy["time_window"])
    max_iterations = int(policy["max_iterations"])

    solid = participants[0]
    fluid = participants[1]
    solid_name = escape(solid["name"])
    fluid_name = escape(fluid["name"])
    solid_solver = escape(solid["solver"])
    fluid_solver = escape(fluid["solver"])
    mesh = escape(mesh_name)
    fluid_data = escape(read_by_fluid)
    solid_data = escape(read_by_solid)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<precice-configuration>",
        f'  <mesh name="{mesh}">',
        f'    <use-mesh name="{mesh}" provide="{solid_name}"/>',
        "  </mesh>",
        f'  <participant name="{solid_name}">',
        f"    <solver:{solid_solver}/>",
        f'    <write-data name="{solid_data}"/>',
        f'    <read-data name="{fluid_data}"/>',
        f'    <use-mesh name="{mesh}" provide="yes"/>',
        "  </participant>",
        f'  <participant name="{fluid_name}">',
        f"    <solver:{fluid_solver}/>",
        f'    <write-data name="{fluid_data}"/>',
        f'    <read-data name="{solid_data}"/>',
        f'    <use-mesh name="{mesh}" from="{solid_name}"/>',
        "  </participant>",
        "  <coupling-scheme:parallel-explicit>",
        f'    <time-window-size value="{time_window}"/>',
        f'    <max-time value="{time_window * max_iterations}"/>',
        f'    <participants first="{solid_name}" second="{fluid_name}"/>',
        (
            f'    <exchange data1="{solid_data}" mesh1="{mesh}" '
            f'from1="{fluid_name}" to1="{solid_name}"/>'
        ),
        (
            f'    <exchange data2="{fluid_data}" mesh2="{mesh}" '
            f'from2="{solid_name}" to2="{fluid_name}"/>'
        ),
        "  </coupling-scheme:parallel-explicit>",
        "</precice-configuration>",
        "",
    ]
    return "\n".join(lines)
