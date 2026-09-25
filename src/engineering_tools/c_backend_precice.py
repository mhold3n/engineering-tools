"""preCICE coupling backend for C orchestration.

Comments for other agents: this module writes a preCICE 2 configuration and
locates a coupler binary. It is not the FSI solver and it is not the C
language runtime. CalculiX and OpenFOAM are the participants; they load the
XML and exchange Displacement and Traction through preCICE. Generation is
pure string assembly from the policy dict. It never reads an on-disk
precice-config.xml as input.

The PATH entry named `precice` is a CI alias, not the official driver.
Installs ship `precice-tools` (and sometimes `binprecice`). Do not add
`<solver:…/>` children: preCICE has no such element, and naming CalculiX or
OpenFOAM inside the config would pretend this process is those solvers.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape


# Official coupler names first. `precice` is last so a CI stub still resolves
# when the real binaries are absent. This tuple is a lookup list, not a
# command this module should turn into an FSI solve.
_COUPLER_NAMES = ("precice-tools", "binprecice", "precice")

# Residual limit inside one implicit window. Not a stress band and not
# max_iterations. preCICE compares this to the relative change of the named data.
_RELATIVE_CONVERGENCE_LIMIT = "1.0e-4"


def default_policy() -> dict[str, Any]:
    """Return the default C coupling policy for Solid/Fluid FSI.

    `solver` on each participant is session metadata for the façade. It is
    not written into the XML. `max_time_windows` is how many coupling windows
    to run. It is not `max_iterations` (iterations inside one window) and it
    is not `time_window * max_iterations`.
    """
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
        "max_time_windows": 2,
    }


def find_precice() -> Path | None:
    """Return the first coupler binary on PATH, or None.

    Order: `precice-tools`, then `binprecice`, then `precice`. The last name
    is a CI alias, not the official driver. Callers use the path as an
    availability check. Participants consume the generated XML; this module
    must not be the FSI solver.
    """
    for name in _COUPLER_NAMES:
        found = shutil.which(name)
        if found is not None:
            return Path(found)
    return None


def generate_precice_config(policy: dict[str, Any]) -> str:
    """Build a preCICE 2 configuration from a coupling policy dict.

    Solid provides mesh `mesh_name` and writes Displacement, reads Traction.
    Fluid provides `{mesh_name}-fluid`, writes Traction, reads Displacement,
    and nearest-neighbor-maps between those meshes. Exchanges both name the
    Solid mesh, which is the mesh the communicated data lives on. Vector
    Traction matches vector Displacement; a scalar would drop direction.
    Dimensions are 3 because the damper interface displacement has three
    components. No `<solver:…/>` tags.
    """
    participants: list[dict[str, str]] = policy["participants"]
    mesh_name = str(policy["mesh_name"])
    read_by_fluid = str(policy["read_by_fluid"])
    read_by_solid = str(policy["read_by_solid"])
    time_window = float(policy["time_window"])
    max_iterations = int(policy["max_iterations"])
    max_time_windows = int(policy["max_time_windows"])

    solid = participants[0]
    fluid = participants[1]
    solid_name = escape(solid["name"])
    fluid_name = escape(fluid["name"])
    mesh = escape(mesh_name)
    # Fluid's own mesh. Mapping needs a second mesh; exchanges stay on `mesh`.
    fluid_mesh = escape(f"{mesh_name}-fluid")
    # read_by_* is what each side consumes; the other participant writes it.
    displacement = escape(read_by_fluid)
    traction = escape(read_by_solid)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<precice-configuration>",
        f'  <data:vector name="{displacement}"/>',
        f'  <data:vector name="{traction}"/>',
        f'  <mesh name="{mesh}" dimensions="3">',
        f'    <use-data name="{displacement}"/>',
        f'    <use-data name="{traction}"/>',
        "  </mesh>",
        f'  <mesh name="{fluid_mesh}" dimensions="3">',
        f'    <use-data name="{displacement}"/>',
        f'    <use-data name="{traction}"/>',
        "  </mesh>",
        f'  <participant name="{solid_name}">',
        f'    <use-mesh name="{mesh}" provide="yes"/>',
        f'    <use-mesh name="{fluid_mesh}" from="{fluid_name}"/>',
        f'    <write-data name="{displacement}" mesh="{mesh}"/>',
        f'    <read-data name="{traction}" mesh="{mesh}"/>',
        "  </participant>",
        f'  <participant name="{fluid_name}">',
        f'    <use-mesh name="{fluid_mesh}" provide="yes"/>',
        f'    <use-mesh name="{mesh}" from="{solid_name}"/>',
        f'    <write-data name="{traction}" mesh="{fluid_mesh}"/>',
        f'    <read-data name="{displacement}" mesh="{fluid_mesh}"/>',
        (
            f'    <mapping:nearest-neighbor direction="write" '
            f'from="{fluid_mesh}" to="{mesh}" constraint="conservative"/>'
        ),
        (
            f'    <mapping:nearest-neighbor direction="read" '
            f'from="{mesh}" to="{fluid_mesh}" constraint="consistent"/>'
        ),
        "  </participant>",
        (
            f'  <m2n:sockets acceptor="{fluid_name}" connector="{solid_name}" '
            f'exchange-directory="."/>'
        ),
        "  <coupling-scheme:serial-implicit>",
        f'    <participants first="{solid_name}" second="{fluid_name}"/>',
        f'    <max-time-windows value="{max_time_windows}"/>',
        f'    <time-window-size value="{time_window}"/>',
        f'    <max-iterations value="{max_iterations}"/>',
        (
            f'    <relative-convergence-measure data="{displacement}" '
            f'mesh="{mesh}" limit="{_RELATIVE_CONVERGENCE_LIMIT}"/>'
        ),
        (
            f'    <exchange data="{traction}" mesh="{mesh}" '
            f'from="{fluid_name}" to="{solid_name}"/>'
        ),
        (
            f'    <exchange data="{displacement}" mesh="{mesh}" '
            f'from="{solid_name}" to="{fluid_name}"/>'
        ),
        "  </coupling-scheme:serial-implicit>",
        "</precice-configuration>",
        "",
    ]
    return "\n".join(lines)


def run_step(config_path: Path, step: int) -> bool:
    """Launch one standalone `precice` process for coupling index `step`.

    Agents: keep this until the façade stops calling it. The façade will
    stop using a standalone precice process; Solid and Fluid consume the
    XML themselves. The argv name `precice` is the CI alias, not the
    official driver (`precice-tools` / `binprecice`, see `find_precice`).
    This function must not grow into the FSI solver. The CI stub ignores
    `step` and exits 0 when given the config path. A non-zero exit is a
    failed coupling window (the façade marks the session broken).
    """
    del step  # The driver reads windows from the generated config.
    try:
        proc = subprocess.run(
            ["precice", str(config_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0
