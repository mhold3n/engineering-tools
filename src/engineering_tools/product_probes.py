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


# Single-component mappings that reuse the component hello row.
# Deferred: 3DEXPERIENCE platform, microscopic CFD (Fluid Dynamics Engineer),
# and every multi-component mapping.
_REUSE_COMPONENT_BY_PROBE: dict[str, tuple[str, str]] = {
    "catia-capability": ("freecad", "CATIA→FreeCAD"),
    "solidworks-capability": ("freecad", "SolidWorks→FreeCAD"),
    "draftsight-capability": ("librecad", "DraftSight→LibreCAD"),
    "solidworks-simulation-capability": ("calculix", "SolidWorks Simulation→CalculiX"),
    "abaqus-style-simpler-solver-workflows-capability": (
        "calculix",
        "Abaqus-style simple workflows→CalculiX",
    ),
    "dymola-capability": ("openmodelica", "Dymola→OpenModelica"),
    "catia-magic-capability": ("eclipse-papyrus", "CATIA Magic→Papyrus"),
    "cameo-capability": ("eclipse-papyrus", "Cameo→Papyrus"),
    "spatial-acis-capability": ("open-cascade-technology", "ACIS→OCCT"),
    "cgm-capability": ("open-cascade-technology", "CGM→OCCT"),
    "abaqus-solver-capability": ("code-aster", "Abaqus solver→Code_Aster"),
    "powerflow-capability": ("openlb", "PowerFLOW→OpenLB"),
    "xflow-capability": ("openlb", "XFlow→OpenLB"),
    "cst-studio-suite-capability": ("openems", "CST→openEMS"),
    "opera-em-capability": ("elmer-fem", "Opera→Elmer"),
    "simpack-capability": ("project-chrono", "Simpack→Chrono"),
    "wave6-capability": ("opencfs", "Wave6→openCFS"),
    "fe-safe-capability": ("pylife", "fe-safe→pyLife"),
    "isight-capability": ("openmdao", "Isight→OpenMDAO"),
    "solidworks-cam-capability": ("freecad-cam", "SolidWorks CAM→FreeCAD CAM"),
    "solidworks-electrical-capability": ("qelectrotech", "SolidWorks Electrical→QElectroTech"),
    "solidworks-visualize-capability": ("blender", "SolidWorks Visualize→Blender"),
    "catia-composer-capability": ("blender", "CATIA Composer→Blender"),
    "solidworks-composer-capability": ("blender", "SolidWorks Composer→Blender"),
    "3dexcite-capability": ("blender", "3DEXCITE→Blender"),
    "delmia-apriso-capability": ("erpnext-manufacturing", "Apriso→ERPNext Manufacturing"),
    "delmia-ortems-capability": ("frepple", "Ortems→frePPLe"),
    "biovia-pipeline-pilot-capability": ("knime-analytics-platform", "Pipeline Pilot→KNIME"),
    "biovia-eln-capability": ("elabftw", "BIOVIA ELN→eLabFTW"),
    "biovia-lims-capability": ("senaite", "BIOVIA LIMS→SENAITE"),
    "turbomole-capability": ("psi4", "TURBOMOLE→Psi4"),
    "medidata-rave-edc-capability": ("libreclinica", "Rave EDC→LibreClinica"),
    "3dvia-homebyme-capability": ("sweet-home-3d", "HomeByMe→Sweet Home 3D"),
    "outscale-capability": ("openstack", "OUTSCALE→OpenStack"),
    "simulia-postprocessing-capability": ("paraview", "SIMULIA postprocessing→ParaView"),
}

PRODUCT_PROBES: dict[str, Callable[[dict[str, dict[str, Any]]], dict[str, Any]]] = {
    probe_id: make_reuse_component_product_probe(component_id, product_label=label)
    for probe_id, (component_id, label) in _REUSE_COMPONENT_BY_PROBE.items()
}
