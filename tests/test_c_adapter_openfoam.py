"""OpenFOAM Fluid participant files. No live pimpleFoam or precice."""

from __future__ import annotations

from pathlib import Path

from engineering_tools.c_fsi_meshes import write_c_fluid_case
from engineering_tools.damper_params import load_params


def test_prepare_fluid_participant_writes_adapter_and_function_object(tmp_path: Path) -> None:
    """write_c_fluid_case plus prepare stages Fluid, not a finished standalone job.

    Agents: the yml names participant Fluid, reads Displacement, writes
    Traction, and points at precice-config.xml. controlDict loads the
    OpenFOAM-preCICE function object. pRef, pointDisplacement, and
    cellDisplacement stay in the case. This test never launches a solver.
    """
    from engineering_tools.c_adapter_openfoam import prepare_fluid_participant

    case = tmp_path / "c-fluid"
    write_c_fluid_case(load_params(), case)
    config_xml = tmp_path / "precice-config.xml"
    config_xml.write_text("<precice-configuration/>\n", encoding="utf-8")

    prepare_fluid_participant(case, config_xml)

    adapter_path = case / "precice-adapter-config.yml"
    assert adapter_path.is_file()
    adapter = adapter_path.read_text(encoding="utf-8")
    assert "participant: Fluid" in adapter or "participant:Fluid" in adapter
    assert "Fluid" in adapter
    assert "Displacement" in adapter
    assert "Traction" in adapter or "Stress" in adapter
    assert str(config_xml) in adapter or "precice-config.xml" in adapter

    control = (case / "system" / "controlDict").read_text(encoding="utf-8")
    assert "functions" in control
    assert "preciceAdapter" in control
    assert "libpreciceAdapterFunctionObject.so" in control
    assert "preciceAdapterFunctionObject" in control

    solution = (case / "system" / "fvSolution").read_text(encoding="utf-8")
    assert "pRefCell" in solution
    assert "pRefValue" in solution
    assert "cellDisplacement" in solution
    point = (case / "0" / "pointDisplacement").read_text(encoding="utf-8")
    assert "pointDisplacement" in point
