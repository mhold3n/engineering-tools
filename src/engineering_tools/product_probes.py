"""Product capability probes for proprietary→OSS mappings.

Slice 1 reuses component hello outcomes from the same `etools hello` run
(see docs/superpowers/specs/2026-09-23-product-capability-probes-slice1-design.md).
"""

from __future__ import annotations

from typing import Any, Callable


def make_reuse_component_product_probe(
    component_id: str,
    *,
    product_label: str,
) -> Callable[[dict[str, dict[str, Any]]], dict[str, Any]]:
    """
    Mark a product covered when its primary component already reported ok.

    Independent re-execution of CAD/solver jobs is deferred to later slices.
    """

    def probe(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
        row = results.get(component_id) or {}
        status = row.get("status")
        if status == "ok":
            detail = row.get("message") or "ok"
            return {
                "status": "covered",
                "message": (
                    f"{product_label} covered via component {component_id} "
                    f"(reused hello: {detail})"
                ),
            }
        return {
            "status": "capability-failed",
            "message": (
                f"{product_label} expected component {component_id} status ok, "
                f"got {status!r}"
            ),
        }

    return probe


# First-slice CAD / FEA / system mappings (single-component, strong component hellos).
PRODUCT_PROBES: dict[str, Callable[[dict[str, dict[str, Any]]], dict[str, Any]]] = {
    "catia-capability": make_reuse_component_product_probe(
        "freecad", product_label="CATIA→FreeCAD"
    ),
    "solidworks-capability": make_reuse_component_product_probe(
        "freecad", product_label="SolidWorks→FreeCAD"
    ),
    "draftsight-capability": make_reuse_component_product_probe(
        "librecad", product_label="DraftSight→LibreCAD"
    ),
    "solidworks-simulation-capability": make_reuse_component_product_probe(
        "calculix", product_label="SolidWorks Simulation→CalculiX"
    ),
    "abaqus-style-simpler-solver-workflows-capability": make_reuse_component_product_probe(
        "calculix", product_label="Abaqus-style simple workflows→CalculiX"
    ),
    "dymola-capability": make_reuse_component_product_probe(
        "openmodelica", product_label="Dymola→OpenModelica"
    ),
}
