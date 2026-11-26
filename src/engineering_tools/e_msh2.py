"""MSH2 helpers for CAD-tagged interface surfaces.

Agents: Physical Surface name face.inner_wall is the CAD entity. Do not
infer the FSI set from a radius band when the physical group is present.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path


def physical_volume_tag(text: str, name: str) -> int | None:
    """Return the MSH2 physical tag for a named 3-D group."""
    if "$PhysicalNames" not in text:
        return None
    body = text.split("$PhysicalNames", 1)[1].split("$EndPhysicalNames", 1)[0]
    quoted = re.escape(name)
    match = re.search(rf"^\s*3\s+(\d+)\s+\"{quoted}\"", body, re.M)
    if match:
        return int(match.group(1))
    return None


def physical_surface_tag(text: str, name: str) -> int | None:
    """Return the MSH2 physical tag for a named 2-D group."""
    if "$PhysicalNames" not in text:
        return None
    body = text.split("$PhysicalNames", 1)[1].split("$EndPhysicalNames", 1)[0]
    quoted = re.escape(name)
    match = re.search(rf"^\s*2\s+(\d+)\s+\"{quoted}\"", body, re.M)
    if match:
        return int(match.group(1))
    return None


def interface_nodes_from_physical(text: str, name: str = "face.inner_wall") -> list[int]:
    """Unique vertex ids on triangles in Physical Surface `name`."""
    tag = physical_surface_tag(text, name)
    if tag is None or "$Elements" not in text:
        return []
    found: set[int] = set()
    elem_body = text.split("$Elements", 1)[1].split("$EndElements", 1)[0].strip().splitlines()
    for line in elem_body[1:]:
        parts = line.split()
        if len(parts) < 6:
            continue
        if int(parts[1]) != 2:
            continue
        ntags = int(parts[2])
        if ntags < 1:
            continue
        phys = int(parts[3])
        if phys != tag:
            continue
        for nid in parts[3 + ntags :]:
            found.add(int(nid))
    return sorted(found)


def interface_triangles(text: str, name: str = "face.inner_wall") -> list[tuple[int, int, int]]:
    """Node triples of type-2 triangles in Physical Surface `name`."""
    tag = physical_surface_tag(text, name)
    if tag is None or "$Elements" not in text:
        return []
    tris: list[tuple[int, int, int]] = []
    elem_body = text.split("$Elements", 1)[1].split("$EndElements", 1)[0].strip().splitlines()
    for line in elem_body[1:]:
        parts = line.split()
        if len(parts) < 6 or int(parts[1]) != 2:
            continue
        ntags = int(parts[2])
        if ntags < 1 or int(parts[3]) != tag:
            continue
        nids = [int(p) for p in parts[3 + ntags :]]
        if len(nids) == 3:
            tris.append((nids[0], nids[1], nids[2]))
    return tris


def interface_triangle_count(text: str, name: str = "face.inner_wall") -> int:
    """Number of type-2 triangles in Physical Surface `name` (OF faceCenters)."""
    return len(interface_triangles(text, name))


def interface_vertex_xyz(text: str, name: str = "face.inner_wall") -> list[list[float]]:
    """XYZ of unique Physical Surface vertices, sorted by node id."""
    nodes, _tets = parse_msh2_volume(text)
    xyz = []
    for nid in interface_nodes_from_physical(text, name):
        if nid in nodes:
            xyz.append([nodes[nid][0], nodes[nid][1], nodes[nid][2]])
    return xyz


def interface_facecenter_xyz(text: str, name: str = "face.inner_wall") -> list[list[float]]:
    """Triangle centroids on Physical Surface `name` (OpenFOAM faceCenters)."""
    tag = physical_surface_tag(text, name)
    nodes, _tets = parse_msh2_volume(text)
    if tag is None or "$Elements" not in text:
        return []
    centers: list[list[float]] = []
    elem_body = text.split("$Elements", 1)[1].split("$EndElements", 1)[0].strip().splitlines()
    for line in elem_body[1:]:
        parts = line.split()
        if len(parts) < 6 or int(parts[1]) != 2:
            continue
        ntags = int(parts[2])
        if ntags < 1 or int(parts[3]) != tag:
            continue
        nids = [int(p) for p in parts[3 + ntags :]]
        pts = [nodes[i] for i in nids if i in nodes]
        if len(pts) != 3:
            continue
        centers.append(
            [
                (pts[0][0] + pts[1][0] + pts[2][0]) / 3.0,
                (pts[0][1] + pts[1][1] + pts[2][1]) / 3.0,
                (pts[0][2] + pts[1][2] + pts[2][2]) / 3.0,
            ]
        )
    return centers


def msh_content_id(path: Path) -> str:
    """sha256 of msh bytes. Not a label derived from h_max."""
    raw = Path(path).read_bytes()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def parse_msh2_volume(
    text: str,
) -> tuple[dict[int, tuple[float, float, float]], list[tuple[int, int, int, int]]]:
    """MSH 2 nodes and type-4 tets."""
    nodes: dict[int, tuple[float, float, float]] = {}
    tets: list[tuple[int, int, int, int]] = []
    if "$Nodes" not in text or "$Elements" not in text:
        return nodes, tets
    node_body = text.split("$Nodes", 1)[1].split("$EndNodes", 1)[0].strip().splitlines()
    for line in node_body[1:]:
        parts = line.split()
        if len(parts) >= 4:
            nodes[int(parts[0])] = (float(parts[1]), float(parts[2]), float(parts[3]))
    elem_body = text.split("$Elements", 1)[1].split("$EndElements", 1)[0].strip().splitlines()
    for line in elem_body[1:]:
        parts = line.split()
        if len(parts) < 8:
            continue
        if int(parts[1]) != 4:
            continue
        ntags = int(parts[2])
        nids = [int(p) for p in parts[3 + ntags :]]
        if len(nids) == 4:
            tets.append((nids[0], nids[1], nids[2], nids[3]))
    return nodes, tets


def tets_from_physical_volume(text: str, name: str) -> list[tuple[int, int, int, int]]:
    """Type-4 tets whose first physical tag is named volume `name`."""
    tag = physical_volume_tag(text, name)
    if tag is None or "$Elements" not in text:
        return []
    tets: list[tuple[int, int, int, int]] = []
    elem_body = text.split("$Elements", 1)[1].split("$EndElements", 1)[0].strip().splitlines()
    for line in elem_body[1:]:
        parts = line.split()
        if len(parts) < 8 or int(parts[1]) != 4:
            continue
        ntags = int(parts[2])
        if ntags < 1 or int(parts[3]) != tag:
            continue
        nids = [int(p) for p in parts[3 + ntags :]]
        if len(nids) == 4:
            tets.append((nids[0], nids[1], nids[2], nids[3]))
    return tets
