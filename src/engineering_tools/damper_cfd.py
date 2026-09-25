"""Stage a short OpenFOAM chamber case for the damper scenario."""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path
from typing import Any

from .hello_probes import _copy_resource_tree


def write_chamber_case(params: dict[str, Any], work: Path) -> None:
    """Copy hello_cavity; chamber params pin the product state, not a new mesh this sprint."""
    del params
    root = resources.files("engineering_tools")
    _copy_resource_tree(root / "data" / "openfoam" / "hello_cavity", work)


def parse_internal_field_p(text: str) -> float:
    """Parse `internalField uniform <scalar>;` from an OpenFOAM p file."""
    match = re.search(r"internalField\s+uniform\s+([-+0-9.eE]+)\s*;", text)
    if not match:
        raise ValueError("internalField uniform scalar not found")
    return float(match.group(1))
