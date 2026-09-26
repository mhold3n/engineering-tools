"""CLI smoke tests via engineering_tools.cli.main."""

from __future__ import annotations

import json
import os
from pathlib import Path

from engineering_tools.cli import main
from engineering_tools.project import init_project


def test_doctor_returns_int() -> None:
    code = main(["doctor"])
    assert code in (0, 1)


def test_doctor_mentions_c_fsi_ubuntu_stack(capsys) -> None:
    """doctor names the C locators; it does not start FSI."""
    main(["doctor"])
    out = capsys.readouterr().out
    assert "C-FSI" in out
    assert "pimpleFoam" in out
    assert "ccx_preCICE" in out
    assert "openfoam2512" in out


def test_profile_alias() -> None:
    code = main(["profile"])
    assert code in (0, 1)


def test_init_creates_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "etools-home"))
    target = tmp_path / "cli-part"
    code = main(["init", str(target), "--name", "CLI Part"])
    assert code == 0
    assert (target / ".engineering-tools.json").is_file()
    assert (target / ".engineering-tools").is_dir()
    assert (target / "jobs").is_dir()
    assert (target / "artifacts").is_dir()


def test_hello_json_is_parseable_and_packaged_manifest_is_red(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "state"))
    code = main(["hello", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert code == 1
    # Inventory is audited; Alpha stays red until product capability probes cover mappings.
    assert report["inventory_state"] == "audited"
    # Inventory is audited; Alpha stays red until product capability probes cover mappings.
    assert report["status"] == "incomplete"
    assert report["ok"] is False

def test_hello_with_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "etools-home"))
    proj = tmp_path / "p"
    proj.mkdir()
    code = main(["hello", "--project", str(proj)])
    assert code in (0, 1)
    # Even without init, hello --project should append a job log when project given
    assert (proj / ".engineering-tools" / "jobs.jsonl").is_file()


def test_scenario_damper_keyway_logs_job(tmp_path: Path, monkeypatch) -> None:
    """etools scenario damper-keyway appends command=scenario and tool=damper-keyway."""
    from tests.test_damper_scenario import _fake_cad_script, _seed_frd, _write_agreed_probes, executable

    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "etools-home"))
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    probes_path = tmp_path / "probes.json"
    _write_agreed_probes(probes_path)
    executable(binary_dir / "FreeCADCmd", _fake_cad_script(probes_path))
    pass1 = tmp_path / "pass1.frd"
    pass2 = tmp_path / "pass2.frd"
    _seed_frd(pass1, 15.5)
    _seed_frd(pass2, 40.0)
    executable(
        binary_dir / "ccx",
        f"""case "$1" in
  solid) cp '{pass1}' solid.frd; printf 'Mises  15.5\\n' > solid.dat ;;
  solid-map) cp '{pass2}' solid-map.frd ;;
esac
exit 0
""",
    )
    executable(binary_dir / "blockMesh", "mkdir -p constant/polyMesh\ntouch constant/polyMesh/points\nexit 0\n")
    executable(
        binary_dir / "icoFoam",
        "mkdir -p 0.1\nprintf 'internalField uniform 2.0;\\n' > 0.1/p\nexit 0\n",
    )
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    project = init_project(tmp_path / "part", name="Damper")
    code = main(["scenario", "damper-keyway", "--project", str(project)])
    assert code == 0
    jobs = [
        json.loads(line)
        for line in (project / ".engineering-tools" / "jobs.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert jobs[-1]["command"] == "scenario"
    assert jobs[-1]["tool"] == "damper-keyway"


def test_fsi_and_coupling_c_call_scenario_with_coupling_c(tmp_path: Path, monkeypatch) -> None:
    """--fsi and --coupling c both reach run_damper_keyway with coupling='c'.

    Agents: this monkeypatches the scenario entry. It does not run solvers.
    The CLI must pass the token through; parsing alone is not the lock.
    """
    seen: list[str | None] = []

    def _fake(project, coupling=None):
        seen.append(coupling)
        return {
            "ok": True,
            "status": "ok",
            "message": "damper-keyway A+B+C passed",
            "workdir": str(project),
            "outputs": [],
        }

    monkeypatch.setattr("engineering_tools.damper_scenario.run_damper_keyway", _fake)
    project = init_project(tmp_path / "part", name="Damper")
    assert main(["scenario", "damper-keyway", "--fsi", "--project", str(project)]) == 0
    assert main(["scenario", "damper-keyway", "--coupling", "c", "--project", str(project)]) == 0
    assert seen == ["c", "c"]


def test_unknown_coupling_exits_before_scenario(tmp_path: Path, capsys) -> None:
    """Unknown --coupling is broken before CAD or solvers run."""
    project = tmp_path / "part"
    project.mkdir()
    code = main(["scenario", "damper-keyway", "--coupling", "nope", "--project", str(project)])
    assert code == 1
    assert "unknown coupling" in capsys.readouterr().err
    assert not (project / "artifacts" / "scenario-damper-keyway").exists()
