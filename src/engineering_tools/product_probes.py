"""Product capability probes for proprietary→OSS mappings.

Most probes reuse component hello outcomes from the same `etools hello` run.
Fluid Dynamics reuses the OpenFOAM component after that probe has run icoFoam.
GEOVIA MineSched, Whittle, and Surpac re-check the in-process numeric models.
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

def _numeric_product_probe(check, *, label: str) -> Callable[[dict[str, dict[str, Any]]], dict[str, Any]]:
    """Run an in-process numeric stand-in after required components are already ok."""

    def probe(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
        del results
        try:
            ok, detail = check()
        except Exception as exc:
            return {"status": "capability-failed", "message": f"{label} numeric check raised {exc}"}
        if ok:
            return {"status": "covered", "message": f"{label} covered: {detail}"}
        return {"status": "capability-failed", "message": f"{label} numeric check failed: {detail}"}

    return probe


def _minesched_ok() -> tuple[bool, str]:
    from .geovia_models import mine_schedule

    result = mine_schedule([{"tonnage": 0.5}, {"tonnage": 0.5}], periods=2)
    ok = result["scheduled"] == 2 and result["objective"] == 1.0
    return ok, f"scheduled={result['scheduled']} objective={result['objective']}"


def _whittle_ok() -> tuple[bool, str]:
    from .geovia_models import pit_optimize

    result = pit_optimize([{"value": 5, "cost": 1}, {"value": 1, "cost": 4}], cutoff=0.0)
    ok = result["count"] == 1 and result["objective"] == 4.0
    return ok, f"count={result['count']} objective={result['objective']}"


def _surpac_ok() -> tuple[bool, str]:
    from .geovia_models import grade_above_cutoff

    result = grade_above_cutoff([{"grade": 2.0}, {"grade": 0.4}], cutoff=1.0)
    ok = result["count"] == 1 and result["mean_grade"] == 2.0
    return ok, f"count={result['count']} mean_grade={result['mean_grade']}"


PRODUCT_PROBES: dict[str, Callable[[dict[str, dict[str, Any]]], dict[str, Any]]] = {
    probe_id: make_reuse_component_product_probe(component_id, product_label=label)
    for probe_id, (component_id, label) in _REUSE_COMPONENT_BY_PROBE.items()
}
PRODUCT_PROBES["simulia-fluid-dynamics-engineer-capability"] = make_reuse_component_product_probe(
    "openfoam", product_label="SIMULIA Fluid Dynamics→OpenFOAM icoFoam cavity"
)
PRODUCT_PROBES["geovia-minesched-capability"] = _numeric_product_probe(
    _minesched_ok, label="GEOVIA MineSched"
)
PRODUCT_PROBES["geovia-whittle-capability"] = _numeric_product_probe(
    _whittle_ok, label="GEOVIA Whittle"
)
PRODUCT_PROBES["geovia-surpac-capability"] = _numeric_product_probe(
    _surpac_ok, label="GEOVIA Surpac"
)
