"""Exclusive install waves for non-3DEXPERIENCE mapping components."""

from __future__ import annotations

# Wave names are stable CLI tokens (etools install --wave <name>).
INSTALL_WAVES: dict[str, tuple[str, ...]] = {
    "1-cad-viz": (
        "freecad",
        "freecad-cam",
        "librecad",
        "open-cascade-technology",
        "blender",
        "sweet-home-3d",
    ),
    "2-cae-core": (
        "calculix",
        "openfoam",
        "paraview",
        "openmodelica",
        "openmdao",
        "code-aster",
        "salome-meca",
        "elmer-fem",
        "project-chrono",
        "openlb",
        "opencfs",
        "openems",
        "pylife",
        "topopt-jl",
    ),
    "3-electrical": (
        "qelectrotech",
        "kicad",
        "kicad-stepup",
    ),
    "4-science": (
        "knime-analytics-platform",
        "ase",
        "lammps",
        "quantum-espresso",
        "rdkit",
        "gromacs",
        "autodock-vina",
        "psi4",
        "elabftw",
        "senaite",
    ),
    "5-mbse-plm-light": (
        "eclipse-papyrus",
        "git-lfs",
        "dvc",
        "pyomo",
        "frepple",
        "postgresql",
        "nextcloud",
        "erpnext",
        "erpnext-manufacturing",
        "opensearch",
        "apache-superset",
        "libreclinica",
        "qgis",
        "gempy",
    ),
    "6-mega-ops": (
        "ros-2",
        "moveit",
        "gazebo",
        "openstack",
    ),
    "7-first-party": (
        "first-party-mine-scheduling-model",
        "first-party-pit-optimization-model",
    ),
}


def all_wave_component_ids() -> tuple[str, ...]:
    """Ordered unique component ids across every install wave."""
    seen: list[str] = []
    for names in INSTALL_WAVES.values():
        for component_id in names:
            if component_id not in seen:
                seen.append(component_id)
    return tuple(seen)


def wave_component_ids(wave: str) -> tuple[str, ...]:
    if wave not in INSTALL_WAVES:
        raise KeyError(wave)
    return INSTALL_WAVES[wave]
