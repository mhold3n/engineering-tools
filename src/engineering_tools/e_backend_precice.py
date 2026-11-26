"""Phase E compiler. A coupling policy becomes a preCICE 3 XML artifact.

Agents: the input is the policy from e_policy. This file only serializes.
Do not edit c_backend_precice.default_policy or tight_d_policy. Do not wrap
XML in <solver-interface>. Each <mesh> has dimensions="3". m2n uses
acceptor/connector, not from/to. No solver tags.

OpenFOAM-style force is data name Force, never Traction. Aitken lists only
policy["aitken_data"], already restricted to second-to-first writes in e_policy.

one-way and explicit two-way use coupling-scheme:serial-explicit. That scheme
has no max-iterations, no relative-convergence-measure, and no Aitken.
implicit two-way and multirate implicit use serial-implicit with those markers.
multirate adds substeps="true" on exchanges.
"""

from __future__ import annotations

from typing import Any
from xml.sax.saxutils import escape

# Same residual numeric as C/D so implicit windows stay comparable. Importing
# the private C constant would couple E to C's module layout; duplicate the
# literal instead. Do not call generate_precice_config from C here.
_RELATIVE_CONVERGENCE_LIMIT = "1.0e-4"


def generate_e_precice_config(policy: dict[str, Any]) -> str:
    """Build preCICE 3 XML from a compiled E policy.

    Agents: mesh ownership follows the participant name, not list index.
    Solid provides interface and interface-faces. Fluid provides
    interface-fluid and holds mappings. A write mapping is emitted only
    when Fluid writes that data. One-way Solid therefore has no write
    mapping. Heat-Flux lives on interface-faces. Displacement, Force, and
    Temperature stay on nodes mesh interface. Heat-Flux is never use-data
    or write/read on interface.
    """
    if policy.get("status") != "ok":
        raise ValueError(policy.get("detail") or "coupling policy is not ok")
    if policy.get("backend") != "precice":
        raise ValueError(f"E preCICE backend cannot emit {policy.get('backend')}")

    participants: list[dict[str, str]] = policy["participants"]
    exchanges: list[dict[str, Any]] = policy["exchanges"]
    time_window = float(policy["time_window"])
    max_iterations = int(policy["max_iterations"])
    max_time_windows = int(policy["max_time_windows"])
    first = participants[0]
    second = participants[1]
    first_name = escape(first["name"])
    second_name = escape(second["name"])
    mesh = escape(str(policy["mesh_name"]))
    second_mesh = escape(f"{policy['mesh_name']}-fluid")
    faces = "interface-faces"
    has_heat = any(str(ex["precice_name"]) == "Heat-Flux" for ex in exchanges)

    data_decls: list[tuple[str, str]] = []
    seen: set[str] = set()
    for ex in exchanges:
        name = str(ex["precice_name"])
        if name in seen:
            continue
        seen.add(name)
        data_decls.append((name, str(ex["rank"])))

    written_by = {first["name"]: set(), second["name"]: set()}
    read_by = {first["name"]: set(), second["name"]: set()}
    for ex in exchanges:
        written_by[ex["from"]].add(ex["precice_name"])
        read_by[ex["to"]].add(ex["precice_name"])

    node_names = [name for name, _rank in data_decls if name != "Heat-Flux"]

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<precice-configuration>",
    ]
    for name, rank in data_decls:
        lines.append(f'  <data:{rank} name="{escape(name)}"/>')

    def _mesh_block(mesh_xml_name: str, names: list[str]) -> list[str]:
        block = [f'  <mesh name="{mesh_xml_name}" dimensions="3">']
        for name in names:
            block.append(f'    <use-data name="{escape(name)}"/>')
        block.append("  </mesh>")
        return block

    lines.extend(_mesh_block(mesh, node_names))
    if has_heat:
        lines.extend(_mesh_block(faces, ["Heat-Flux"]))
    lines.extend(_mesh_block(second_mesh, [name for name, _rank in data_decls]))

    def _solid_mesh(name: str) -> str:
        return faces if name == "Heat-Flux" else mesh

    # List index is scheme order. Mesh ownership is the solver name.
    # One-way puts Fluid first, and the old index rule then handed Solid
    # the fluid mesh plus a write mapping Solid does not write.
    by_name = {participant["name"]: participant for participant in participants}
    solid = by_name.get("Solid", first)
    fluid = by_name.get("Fluid", second)
    solid_name = escape(solid["name"])
    fluid_name = escape(fluid["name"])

    lines.append(f'  <participant name="{solid_name}">')
    lines.append(f'    <provide-mesh name="{mesh}"/>')
    if has_heat:
        lines.append(f'    <provide-mesh name="{faces}"/>')
    for name, _rank in data_decls:
        if name in written_by[solid["name"]]:
            lines.append(f'    <write-data name="{escape(name)}" mesh="{_solid_mesh(name)}"/>')
        if name in read_by[solid["name"]]:
            lines.append(f'    <read-data name="{escape(name)}" mesh="{_solid_mesh(name)}"/>')
    lines.append("  </participant>")

    lines.append(f'  <participant name="{fluid_name}">')
    lines.append(f'    <provide-mesh name="{second_mesh}"/>')
    lines.append(f'    <receive-mesh name="{mesh}" from="{solid_name}"/>')
    if has_heat:
        lines.append(f'    <receive-mesh name="{faces}" from="{solid_name}"/>')
    for name, _rank in data_decls:
        if name in written_by[fluid["name"]]:
            lines.append(f'    <write-data name="{escape(name)}" mesh="{second_mesh}"/>')
        if name in read_by[fluid["name"]]:
            lines.append(f'    <read-data name="{escape(name)}" mesh="{second_mesh}"/>')
    fluid_writes = written_by[fluid["name"]]
    fluid_reads = read_by[fluid["name"]]
    if any(name != "Heat-Flux" for name in fluid_writes):
        lines.append(
            f'    <mapping:nearest-neighbor direction="write" '
            f'from="{second_mesh}" to="{mesh}" constraint="conservative"/>'
        )
    if "Heat-Flux" in fluid_writes:
        lines.append(
            f'    <mapping:nearest-neighbor direction="write" '
            f'from="{second_mesh}" to="{faces}" constraint="conservative"/>'
        )
    if any(name != "Heat-Flux" for name in fluid_reads):
        lines.append(
            f'    <mapping:nearest-neighbor direction="read" '
            f'from="{mesh}" to="{second_mesh}" constraint="consistent"/>'
        )
    lines.append("  </participant>")
    lines.append(
        f'  <m2n:sockets acceptor="{second_name}" connector="{first_name}" '
        f'exchange-directory=".."/>'
    )

    implicit = bool(policy.get("implicit"))
    scheme = "serial-implicit" if implicit else "serial-explicit"
    substeps = ' substeps="true"' if policy.get("multirate") else ""

    lines.append(f"  <coupling-scheme:{scheme}>")
    lines.append(f'    <participants first="{first_name}" second="{second_name}"/>')
    lines.append(f'      <max-time-windows value="{max_time_windows}"/>')
    lines.append(f'      <time-window-size value="{time_window}"/>')
    if implicit:
        lines.append(f'      <max-iterations value="{max_iterations}"/>')
        for name, _rank in data_decls:
            cmesh = faces if name == "Heat-Flux" else mesh
            lines.append(
                f'      <relative-convergence-measure data="{escape(name)}" '
                f'mesh="{cmesh}" limit="{_RELATIVE_CONVERGENCE_LIMIT}"/>'
            )
        aitken = [str(n) for n in policy.get("aitken_data") or []]
        if aitken:
            lines.append('      <min-iterations value="2"/>')
            lines.append("      <acceleration:aitken>")
            for name in aitken:
                amesh = faces if name == "Heat-Flux" else mesh
                lines.append(f'        <data name="{escape(name)}" mesh="{amesh}"/>')
            lines.append('        <initial-relaxation value="0.5"/>')
            lines.append("      </acceleration:aitken>")
    for ex in exchanges:
        ex_mesh = faces if str(ex["precice_name"]) == "Heat-Flux" else mesh
        lines.append(
            f'      <exchange data="{escape(ex["precice_name"])}" mesh="{ex_mesh}" '
            f'from="{escape(ex["from"])}" to="{escape(ex["to"])}"{substeps}/>'
        )
    lines.append(f"  </coupling-scheme:{scheme}>")
    lines.append("</precice-configuration>")
    lines.append("")
    return "\n".join(lines)
