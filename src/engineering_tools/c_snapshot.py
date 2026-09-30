"""Immutable A/B snapshot freeze for C parity checks.

Comments for other agents: freeze_ab_snapshot copies product-state.json and
scenario-report.json from src into dest without modifying src. The returned
digest is SHA-256 hex over raw product-state.json bytes, a single newline (0x0A),
then raw scenario-report.json bytes — not a JSON merge. Missing either source
file raises FileNotFoundError (callers map to C broken).
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

_PRODUCT_STATE = "product-state.json"
_SCENARIO_REPORT = "scenario-report.json"


def freeze_ab_snapshot(src: Path, dest: Path) -> str:
    """Copy A/B JSON pair into dest and return canonical listing SHA-256 hex."""
    product_path = src / _PRODUCT_STATE
    scenario_path = src / _SCENARIO_REPORT
    if not product_path.is_file():
        raise FileNotFoundError(product_path)
    if not scenario_path.is_file():
        raise FileNotFoundError(scenario_path)

    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(product_path, dest / _PRODUCT_STATE)
    shutil.copy2(scenario_path, dest / _SCENARIO_REPORT)

    product_bytes = product_path.read_bytes()
    scenario_bytes = scenario_path.read_bytes()
    digest = hashlib.sha256(product_bytes + b"\n" + scenario_bytes).hexdigest()
    return digest
