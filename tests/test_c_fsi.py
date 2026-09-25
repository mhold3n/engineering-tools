"""C-FSI mesh and façade session tests.

Agents: mesh tests pin metres from damper-params probes and the shared
interface name. Most façade tests monkeypatch adapter sample_c_probes.
test_run_c_fsi_persists_session_from_adapter_files does not: the fake
ccx_preCICE copies an FRD and the fake pimpleFoam writes kinematic p, and
the real adapters must read those files. Solid and Fluid are Popen'd
together; damper_scenario.py never launches a process named precice.
"""

import json
import os
from pathlib import Path

import pytest

from engineering_tools.c_fsi_meshes import canonical_xyz_m, write_c_fluid_case, write_c_solid_inp
from engineering_tools.c_parity import load_c_fsi_bands
from engineering_tools.damper_params import load_params


def test_canonical_xyz_matches_params_in_metres() -> None:
    params = load_params()
    xyz = canonical_xyz_m(params)
    wall = xyz["housing.wall.pressure"]
    assert wall[0] == pytest.approx(-float(params["housing_id_mm"]) / 2000.0)


def test_c_solid_and_fluid_share_interface_name(tmp_path: Path) -> None:
    params = load_params()
    write_c_solid_inp(params, tmp_path / "c-solid.inp")
    write_c_fluid_case(params, tmp_path / "c-foam")
    inp = (tmp_path / "c-solid.inp").read_text(encoding="utf-8")
    foam = (tmp_path / "c-foam" / "constant" / "polyMesh" / "blockMeshDict").read_text(encoding="utf-8")
    assert "interface" in inp.lower() or "INTERFACE" in inp
    assert "interface" in foam
    # Named interface is the chamber_wall −X plane (mm in the deck, m in blockMesh).
    assert "-25.000000" in inp
    start = foam.index("\n    interface\n")
    iface = foam[start:foam.index("\n    walls\n", start)]
    assert "(0 4 7 3)" in iface


def test_sample_c_probes_reads_interface_face_centre(tmp_path: Path) -> None:
    """Non-zero p on a write_c_fluid_case mesh lands on chamber_wall.

    Agents: parenthesized blockMesh vertices must not collapse to vertex 0.
    Face (0 4 7 3) is the −X interface; its centre is
    canonical_xyz_m(...)["housing.wall.pressure"]. Do not substitute that
    canonical point for key.root, and do not launch precice here.
    """
    from engineering_tools.c_adapter_openfoam import sample_c_probes
    from engineering_tools.damper_params import kinematic_to_pa, require_density

    params = load_params()
    case = tmp_path / "c-foam"
    write_c_fluid_case(params, case)
    kinematic = 2.0
    time_dir = case / "0.1"
    time_dir.mkdir()
    (time_dir / "p").write_text(
        "FoamFile\n{\n    object      p;\n}\ninternalField uniform 2.0;\n",
        encoding="utf-8",
    )
    probes = sample_c_probes(case)
    wall = canonical_xyz_m(params)["housing.wall.pressure"]
    expected_pa = kinematic_to_pa(kinematic, require_density(params))
    assert probes["housing.wall.pressure"]["xyz_m"] == pytest.approx(wall)
    assert probes["housing.wall.traction"]["xyz_m"] == pytest.approx(wall)
    assert probes["housing.wall.pressure"]["value"] == pytest.approx(expected_pa)
    assert probes["housing.wall.traction"]["value"] == pytest.approx(abs(expected_pa))
    assert "key.root.von_mises" not in probes


def _executable(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


def _c_tools(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    precice: bool = True,
    solid_frd: Path | None = None,
) -> None:
    """PATH: ccx_preCICE + pimpleFoam print two window completions; optional coupler.

    Agents: pimpleFoam always writes kinematic 2.0 into 0.1/p. When solid_frd
    is set, ccx_preCICE copies that file to c-solid.frd in the solid cwd so
    sample_c_probes can read DISP and STRESS. Leave solid_frd unset for tests
    that monkeypatch the samplers.
    """
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    # Real newline after printf. A trailing \n inside the Python string is only
    # another printf argument, so mkdir never runs and 0.1/p is never written.
    windows = "printf 'Time window completed\\nTime window completed\\n'\n"
    copy_frd = ""
    if solid_frd is not None:
        copy_frd = f"cp '{solid_frd}' c-solid.frd\n"
    _executable(binary_dir / "ccx", "exit 0\n")
    _executable(binary_dir / "ccx_preCICE", copy_frd + windows + "exit 0\n")
    _executable(
        binary_dir / "pimpleFoam",
        windows + "mkdir -p 0.1\nprintf 'internalField uniform 2.0;\\n' > 0.1/p\nexit 0\n",
    )
    _executable(binary_dir / "blockMesh", "mkdir -p constant/polyMesh\ntouch constant/polyMesh/points\nexit 0\n")
    if precice:
        _executable(binary_dir / "precice-tools", "exit 0\n")
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")


def _ab_snapshot_source(path: Path) -> None:
    """Minimal A/B pair whose B wall Pa and key-root MPa match the C fake probes."""
    path.mkdir(parents=True, exist_ok=True)
    product = {
        "probes": {
            "chamber_wall": {"cfd": {"p": 56.62}},
            "keyway_root": {"fea_mapped": {"von_mises": 10.07}},
        }
    }
    (path / "product-state.json").write_text(json.dumps(product) + "\n", encoding="utf-8")
    (path / "scenario-report.json").write_text('{"a_ok": true, "b_ok": true}\n', encoding="utf-8")


def _matching_probes() -> dict:
    canonical = canonical_xyz_m(load_params())
    return {
        "housing.wall.pressure": {"value": 56.62, "xyz_m": canonical["housing.wall.pressure"]},
        "key.root.von_mises": {"value": 10.07e6, "xyz_m": canonical["key.root.von_mises"]},
        "housing.wall.displacement": {"value": 1e-6, "xyz_m": canonical["housing.wall.displacement"]},
        "housing.wall.traction": {"value": 56.62, "xyz_m": canonical["housing.wall.traction"]},
    }


def _patch_samples(monkeypatch: pytest.MonkeyPatch, probes: dict) -> None:
    """Both adapters return the same SI probe dict; the façade merges them."""

    def _sample(_out: Path) -> dict:
        return probes

    monkeypatch.setattr("engineering_tools.c_adapter_calculix.sample_c_probes", _sample)
    monkeypatch.setattr("engineering_tools.c_adapter_openfoam.sample_c_probes", _sample)


_C_SESSION_ARTIFACT_KEYS = frozenset(
    {"status", "steps", "probes", "parity", "snapshot_digest", "backend", "c_ok"}
)


def test_c_session_json_persists_artifact_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reviewer lock: c-session.json always exposes the C artifact field set."""
    from engineering_tools.c_facade import run_c_fsi

    _c_tools(tmp_path, monkeypatch)
    ab = tmp_path / "ab"
    _ab_snapshot_source(ab)
    _patch_samples(monkeypatch, _matching_probes())
    out = tmp_path / "c-fsi"
    run_c_fsi(ab_dir=ab, out=out, params=load_params())
    persisted = json.loads((out / "c-session.json").read_text(encoding="utf-8"))
    assert set(persisted) >= _C_SESSION_ARTIFACT_KEYS
    assert persisted["backend"] == "precice"
    assert isinstance(persisted["steps"], list)
    assert isinstance(persisted["probes"], dict)
    assert isinstance(persisted["parity"], list)
    assert isinstance(persisted["snapshot_digest"], str)
    assert isinstance(persisted["status"], str)
    assert isinstance(persisted["c_ok"], bool)


def test_run_c_fsi_persists_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engineering_tools.c_facade import run_c_fsi

    _c_tools(tmp_path, monkeypatch)
    ab = tmp_path / "ab"
    _ab_snapshot_source(ab)
    _patch_samples(monkeypatch, _matching_probes())
    out = tmp_path / "c-fsi"
    session = run_c_fsi(ab_dir=ab, out=out, params=load_params())
    persisted = json.loads((out / "c-session.json").read_text(encoding="utf-8"))
    assert session["status"] == "ok"
    assert persisted["status"] == "ok"
    assert persisted["c_ok"] is True
    assert persisted["backend"] == "precice"
    n_steps = int(load_c_fsi_bands()["n_steps"])
    assert len(persisted["steps"]) == n_steps
    assert all(step["converged"] is True for step in persisted["steps"])
    for name, row in _matching_probes().items():
        assert persisted["probes"][name]["value"] == pytest.approx(row["value"])
    assert persisted["parity"]
    assert all(row["ok"] is True for row in persisted["parity"])
    assert len(persisted["snapshot_digest"]) == 64


def _frd_disp_stress_from_deck_nodes(nodes: dict[int, tuple[float, float, float]]) -> str:
    """FRD a fake ccx_preCICE copies: deck *NODE rows, interface DISP, nodal STRESS.

    Agents: same 2C / DISP / STRESS layout as
    test_coupling_c_ab_success_reports_c_ok_with_fakes. Coordinates are the
    C deck, not canonical_xyz_m. DISP 1e-3 is millimetres (1e-6 m after the
    adapter). SXX 40 is MPa; the sampler turns von Mises into pascals.
    """
    from engineering_tools.c_fsi_meshes import interface_node_ids

    lines = ["    2C"]
    for nid, xyz in nodes.items():
        lines.append(f" -1         {nid} {xyz[0]:.5e} {xyz[1]:.5e} {xyz[2]:.5e}")
    lines.append(" -3")
    lines.append(" -4  DISP        4    1")
    for nid in interface_node_ids():
        lines.append(f" -1         {nid} 1.00000e-03 0.00000e+00 0.00000e+00")
    lines.append(" -3")
    lines.append(" -4  STRESS      6    1")
    for nid in nodes:
        lines.append(
            f" -1         {nid} 4.00000e+01 0.00000e+00 0.00000e+00 0.00000e+00 0.00000e+00 0.00000e+00"
        )
    lines.append(" -3")
    return "\n".join(lines) + "\n"


def test_run_c_fsi_persists_session_from_adapter_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """c-session.json is c_ok when adapters read the fake FRD and kinematic p.

    Agents: do not monkeypatch sample_c_probes. The façade must pick up
    housing.wall.pressure from 0.1/p, key.root.von_mises from the STRESS
    block, and housing.wall.displacement above the motion floor from DISP.
    """
    from engineering_tools.c_facade import run_c_fsi

    params = load_params()
    preview = tmp_path / "c-preview.inp"
    write_c_solid_inp(params, preview)
    nodes = _inp_nodes(preview.read_text(encoding="utf-8"))
    frd = tmp_path / "generated.frd"
    frd.write_text(_frd_disp_stress_from_deck_nodes(nodes), encoding="utf-8")
    _c_tools(tmp_path, monkeypatch, solid_frd=frd)
    ab = tmp_path / "ab"
    _ab_snapshot_source(ab)
    out = tmp_path / "c-fsi"
    run_c_fsi(ab_dir=ab, out=out, params=params)
    persisted = json.loads((out / "c-session.json").read_text(encoding="utf-8"))
    assert persisted["c_ok"] is True
    assert persisted["steps"]
    assert all(step["converged"] is True for step in persisted["steps"])
    probes = persisted["probes"]
    assert "housing.wall.pressure" in probes
    assert "key.root.von_mises" in probes
    floor = float(load_c_fsi_bands()["motion_floor_m"])
    assert abs(float(probes["housing.wall.displacement"]["value"])) > floor


def test_run_c_fsi_missing_without_precice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engineering_tools.c_facade import run_c_fsi

    _c_tools(tmp_path, monkeypatch, precice=False)
    out = tmp_path / "c-fsi"
    session = run_c_fsi(ab_dir=tmp_path / "ab", out=out, params=load_params())
    assert session["status"] == "missing"
    assert session["evaluated"] is True
    assert session["c_ok"] is False
    persisted = json.loads((out / "c-session.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "missing"


def test_run_c_fsi_broken_when_backend_step_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engineering_tools.c_facade import run_c_fsi

    _c_tools(tmp_path, monkeypatch)
    _ab_snapshot_source(tmp_path / "ab")
    _patch_samples(monkeypatch, _matching_probes())
    monkeypatch.setattr(
        "engineering_tools.c_facade.run_coupled_participants",
        lambda **_kwargs: {"ok": False, "steps": [], "detail": "forced"},
    )
    session = run_c_fsi(ab_dir=tmp_path / "ab", out=tmp_path / "c-fsi", params=load_params())
    assert session["status"] == "broken"
    assert session["c_ok"] is False


def test_run_c_fsi_broken_when_displacement_is_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engineering_tools.c_facade import run_c_fsi

    probes = _matching_probes()
    probes["housing.wall.displacement"] = dict(probes["housing.wall.displacement"])
    probes["housing.wall.displacement"]["value"] = 0.0
    _c_tools(tmp_path, monkeypatch)
    _ab_snapshot_source(tmp_path / "ab")
    _patch_samples(monkeypatch, probes)
    session = run_c_fsi(ab_dir=tmp_path / "ab", out=tmp_path / "c-fsi", params=load_params())
    assert session["status"] == "broken"
    assert session["c_ok"] is False


def test_run_c_fsi_broken_when_pressure_out_of_band(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engineering_tools.c_facade import run_c_fsi

    probes = _matching_probes()
    probes["housing.wall.pressure"] = dict(probes["housing.wall.pressure"])
    probes["housing.wall.pressure"]["value"] = 1e20
    _c_tools(tmp_path, monkeypatch)
    _ab_snapshot_source(tmp_path / "ab")
    _patch_samples(monkeypatch, probes)
    session = run_c_fsi(ab_dir=tmp_path / "ab", out=tmp_path / "c-fsi", params=load_params())
    assert session["status"] == "broken"
    assert session["c_ok"] is False
    assert any(row["ok"] is False for row in session["parity"])


def test_scenario_module_does_not_spawn_precice() -> None:
    text = Path("src/engineering_tools/damper_scenario.py").read_text(encoding="utf-8")
    assert "precice" not in text.lower()


def _inp_nodes(text: str) -> dict[int, tuple[float, float, float]]:
    """Parse *NODE rows from a CalculiX deck. Stops at the next keyword."""
    nodes: dict[int, tuple[float, float, float]] = {}
    in_nodes = False
    for line in text.splitlines():
        if line.startswith("*NODE"):
            in_nodes = True
            continue
        if in_nodes and line.startswith("*"):
            break
        if not in_nodes or not line.strip():
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 4:
            continue
        nodes[int(parts[0])] = (float(parts[1]), float(parts[2]), float(parts[3]))
    return nodes


def _frd_from_mesh_nodes(nodes: dict[int, tuple[float, float, float]], mises: float) -> str:
    """FRD whose 2C coordinates are the deck nodes, with a STRESS block.

    Agents: this is a live sample input. Do not plant canonical xyz here;
    the sampler must discover keyway_root from these node coordinates.
    """
    lines = ["    2C"]
    for nid, xyz in nodes.items():
        lines.append(f" -1         {nid} {xyz[0]:.5e} {xyz[1]:.5e} {xyz[2]:.5e}")
    lines.append(" -3")
    lines.append(" -4  STRESS      6    1")
    for nid in nodes:
        lines.append(
            f" -1         {nid} {mises:.5e} 0.00000e+00 0.00000e+00 0.00000e+00 0.00000e+00 0.00000e+00"
        )
    lines.append(" -3")
    return "\n".join(lines) + "\n"


def test_live_sample_c_probes_key_root_within_geometric_tolerance(tmp_path: Path) -> None:
    """key.root.von_mises xyz comes from a mesh node near keyway_root (+X).

    Agents: no monkeypatch of xyz. The FRD is built only from *NODE rows
    written by write_c_solid_inp. Substituting canonical_xyz_m would still
    sit on the pin; the returned point must be one of those mesh nodes and
    lie inside geometric_tolerance_m of the pin.
    """
    from engineering_tools.c_adapter_calculix import sample_c_probes
    from engineering_tools.c_contract import mm_to_m
    from engineering_tools.damper_params import probes_from_params

    params = load_params()
    deck = tmp_path / "c-solid.inp"
    write_c_solid_inp(params, deck)
    nodes = _inp_nodes(deck.read_text(encoding="utf-8"))
    work = tmp_path / "c-solid"
    work.mkdir()
    (work / "c-solid.frd").write_text(_frd_from_mesh_nodes(nodes, 10.07), encoding="utf-8")
    probes = sample_c_probes(work)
    row = probes["key.root.von_mises"]
    target = mm_to_m(probes_from_params(params)["keyway_root"])
    tolerance = float(load_c_fsi_bands()["geometric_tolerance_m"])
    distance = sum((row["xyz_m"][i] - target[i]) ** 2 for i in range(3)) ** 0.5
    assert distance <= tolerance
    mesh_m = [mm_to_m(list(xyz)) for xyz in nodes.values()]
    assert any(row["xyz_m"] == pytest.approx(point) for point in mesh_m)


def test_fluid_case_writes_pressure_reference_and_point_motion(tmp_path: Path) -> None:
    """Moving-mesh dicts name the pressure reference and the displacement fields.

    Agents: this does not launch pimpleFoam. It only checks the files
    write_c_fluid_case plus _CASE_FILES would hand a real solver.
    """
    from engineering_tools.c_adapter_openfoam import _stage_solver_dicts

    case = tmp_path / "c-foam"
    write_c_fluid_case(load_params(), case)
    _stage_solver_dicts(case, 0)
    solution = (case / "system" / "fvSolution").read_text(encoding="utf-8")
    assert "pRefCell" in solution
    assert "pRefValue" in solution
    assert "cellDisplacement" in solution
    point = (case / "0" / "pointDisplacement").read_text(encoding="utf-8")
    assert "pointDisplacement" in point


def test_solid_inp_dload_when_wall_pressure_set(tmp_path: Path) -> None:
    """*DLOAD carries B wall pressure when the façade passes wall_pressure_pa."""
    path = tmp_path / "c-solid.inp"
    write_c_solid_inp(load_params(), path, wall_pressure_pa=1700.0)
    text = path.read_text(encoding="utf-8")
    # Keyword line, not the deck comment that mentions the card name.
    assert "\n*DLOAD\n" in text
    bare = tmp_path / "bare.inp"
    write_c_solid_inp(load_params(), bare)
    assert "\n*DLOAD\n" not in bare.read_text(encoding="utf-8")


def test_run_c_fsi_broken_when_snapshot_json_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Binaries present, A/B JSON absent: freeze failure is C broken.

    Agents: do not label this missing. Dependencies resolved; the snapshot
    contract failed. c-session.json still records the attempt.
    """
    from engineering_tools.c_facade import run_c_fsi

    _c_tools(tmp_path, monkeypatch)
    ab = tmp_path / "ab"
    ab.mkdir()
    (ab / "damper.FCStd").write_text("cad", encoding="utf-8")
    (ab / "solid.step").write_text("solid", encoding="utf-8")
    session = run_c_fsi(ab_dir=ab, out=tmp_path / "c-fsi", params=load_params())
    assert session["status"] == "broken"
    assert session["c_ok"] is False
    assert session["evaluated"] is True
    persisted = json.loads((tmp_path / "c-fsi" / "c-session.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "broken"
