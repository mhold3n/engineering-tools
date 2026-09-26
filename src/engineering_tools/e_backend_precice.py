"""Phase E compiler: coupling policy → preCICE 3 XML artifact.

Agents: policy is source of truth (e_policy). This file only serializes.
Do not edit c_backend_precice.default_policy or tight_d_policy. Do not wrap
XML in <solver-interface>. Each <mesh> has dimensions="3". m2n uses
acceptor/connector (not from/to). No <solver:…/> tags.

OpenFOAM-style force is data name Force, never Traction. Aitken lists only
policy["aitken_data"], already restricted to second→first in e_policy.

one-way / explicit two-way → coupling-scheme:serial-explicit (no
max-iterations, no relative-convergence-measure, no Aitken).
implicit two-way / multirate implicit → serial-implicit with those markers.
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

    Raises ValueError if the policy is not status ok. Callers should compile
    first; this function does not invent a weaker scheme on failure.
    """
    if policy.get("status") != "ok":
        raise ValueError(policy.get("detail") or "coupling policy is not ok")
    if policy.get("backend") != "precice":
        raise ValueError(f"E preCICE backend cannot emit {policy.get('backend')}")

    participants: list[dict[str, str]] = policy["participants"]
    mesh_name = str(policy["mesh_name"])
    exchanges: list[dict[str, Any]] = policy["exchanges"]
    time_window = float(policy["time_window"])
    max_iterations = int(policy["max_iterations"])
    max_time_windows = int(policy["max_time_windows"])
    first = participants[0]
    second = participants[1]
    first_name = escape(first["name"])
    second_name = escape(second["name"])
    mesh = escape(mesh_name)
    second_mesh = escape(f"{mesh_name}-fluid")

    # Unique (precice_name, rank) in exchange order.
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

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<precice-configuration>",
    ]
    for name, rank in data_decls:
        ename = escape(name)
        lines.append(f'  <data:{rank} name="{ename}"/>')

    def _mesh_block(mesh_xml_name: str) -> list[str]:
        block = [f'  <mesh name="{mesh_xml_name}" dimensions="3">']
        for name, _rank in data_decls:
            block.append(f'    <use-data name="{escape(name)}"/>')
        block.append("  </mesh>")
        return block

    lines.extend(_mesh_block(mesh))
    lines.extend(_mesh_block(second_mesh))

    lines.append(f'  <participant name="{first_name}">')
    lines.append(f'    <provide-mesh name="{mesh}"/>')
    for name, _rank in data_decls:
        if name in written_by[first["name"]]:
            lines.append(f'    <write-data name="{escape(name)}" mesh="{mesh}"/>')
        if name in read_by[first["name"]]:
            lines.append(f'    <read-data name="{escape(name)}" mesh="{mesh}"/>')
    lines.append("  </participant>")

    lines.append(f'  <participant name="{second_name}">')
    lines.append(f'    <provide-mesh name="{second_mesh}"/>')
    lines.append(f'    <receive-mesh name="{mesh}" from="{first_name}"/>')
    for name, _rank in data_decls:
        if name in written_by[second["name"]]:
            lines.append(f'    <write-data name="{escape(name)}" mesh="{second_mesh}"/>')
        if name in read_by[second["name"]]:
            lines.append(f'    <read-data name="{escape(name)}" mesh="{second_mesh}"/>')
    # Conservative on extensive writes (Force, Heat-Flux); consistent on reads.
    lines.append(
        f'    <mapping:nearest-neighbor direction="write" '
        f'from="{second_mesh}" to="{mesh}" constraint="conservative"/>'
    )
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
            lines.append(
                f'      <relative-convergence-measure data="{escape(name)}" '
                f'mesh="{mesh}" limit="{_RELATIVE_CONVERGENCE_LIMIT}"/>'
            )
        aitken = [str(n) for n in policy.get("aitken_data") or []]
        if aitken:
            lines.append('      <min-iterations value="2"/>')
            lines.append("      <acceleration:aitken>")
            for name in aitken:
                lines.append(f'        <data name="{escape(name)}" mesh="{mesh}"/>')
            lines.append('        <initial-relaxation value="0.5"/>')
            lines.append("      </acceleration:aitken>")
    for ex in exchanges:
        lines.append(
            f'      <exchange data="{escape(ex["precice_name"])}" mesh="{mesh}" '
            f'from="{escape(ex["from"])}" to="{escape(ex["to"])}"{substeps}/>'
        )
    lines.append(f"  </coupling-scheme:{scheme}>")
    lines.append("</precice-configuration>")
    lines.append("")
    return "\n".join(lines)
