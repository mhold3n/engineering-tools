"""Joint multi-tool product probes using fake tools on PATH."""

from __future__ import annotations

import os
from pathlib import Path

from engineering_tools.workflow_probes import (
    probe_abaqus_cae,
    probe_biovia_discovery,
    probe_biovia_materials,
    probe_catia_electrical,
    probe_delmia_quintiq,
    probe_delmia_robotics,
    probe_enovia,
    probe_exalead,
    probe_netvibes,
    probe_solidworks_pdm,
    probe_tosca,
)


def executable(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


def test_pdm_workflow_tracks_lfs_and_inits_dvc(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(binary_dir / "git", "exit 0\n")
    executable(
        binary_dir / "git-lfs",
        """
if [ "$1" = "track" ]; then
  printf '*.bin filter=lfs diff=lfs merge=lfs -text\\n' > .gitattributes
fi
exit 0
""",
    )
    executable(
        binary_dir / "python-standin",
        "mkdir -p .dvc\nprintf '[core]\\n' > .dvc/config\nexit 0\n",
    )
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    monkeypatch.setattr("engineering_tools.workflow_probes.sys.executable", str(binary_dir / "python-standin"))
    monkeypatch.setattr("engineering_tools.workflow_probes._receipt_locator", lambda _component: None)
    outcome = probe_solidworks_pdm({})
    assert outcome["status"] == "covered"
    assert ".dvc/config" in outcome["message"]


def test_quintiq_workflow_runs_frepple_and_pyomo(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(binary_dir / "frepple", "exit 0\n")
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    monkeypatch.setattr(
        "engineering_tools.hello_probes.probe_pyomo",
        lambda project=None: {"status": "ok", "message": "Pyomo tiny LP objective 1 via glpk"},
    )
    outcome = probe_delmia_quintiq({})
    assert outcome["status"] == "covered"
    assert "frepple" in outcome["message"]
    assert "glpk" in outcome["message"]


def test_robotics_workflow_reads_moveit_and_gazebo(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(
        binary_dir / "ros2",
        """
if [ "$1" = "pkg" ] && [ "$3" = "moveit_core" ]; then
  echo /opt/ros/jazzy
  exit 0
fi
exit 1
""",
    )
    executable(binary_dir / "gz", "echo 8.15.0\n")
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    outcome = probe_delmia_robotics({})
    assert outcome["status"] == "covered"
    assert "moveit_core" in outcome["message"]
    assert "8.15.0" in outcome["message"]


def test_materials_workflow_runs_ase_lammps_and_pwscf(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(binary_dir / "python-standin", "echo 2\n")
    executable(
        binary_dir / "lmp",
        """
log=""
while [ $# -gt 0 ]; do
  if [ "$1" = "-log" ]; then log=$2; shift 2; continue; fi
  shift
done
printf 'Total wall time: 0:00:00\\n' > "$log"
exit 0
""",
    )
    executable(binary_dir / "pw.x", "echo 'Program PWSCF v.test'\nexit 1\n")
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    monkeypatch.setattr("engineering_tools.workflow_probes.sys.executable", str(binary_dir / "python-standin"))
    monkeypatch.setattr("engineering_tools.workflow_probes._receipt_locator", lambda _component: None)
    outcome = probe_biovia_materials({})
    assert outcome["status"] == "covered"
    assert "PWSCF" in outcome["message"]


def test_discovery_workflow_runs_rdkit_gromacs_and_vina(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(binary_dir / "python-standin", "echo 3\n")
    executable(binary_dir / "gmx", "echo 'GROMACS version'\n")
    executable(binary_dir / "vina", "echo '  --receptor arg'\n")
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    monkeypatch.setattr("engineering_tools.workflow_probes.sys.executable", str(binary_dir / "python-standin"))
    monkeypatch.setattr("engineering_tools.workflow_probes._receipt_locator", lambda _component: None)
    outcome = probe_biovia_discovery({})
    assert outcome["status"] == "covered"
    assert "RDKit" in outcome["message"]


def _write_receipts(tmp_path, monkeypatch, **locators: str) -> None:
    home = tmp_path / "etools-home"
    home.mkdir()
    monkeypatch.setenv("ETOOLS_HOME", str(home))
    payload = {
        "schema_version": 1,
        "components": {
            component_id: {"locator": locator, "immutable_id": "test", "integrity_verified": True}
            for component_id, locator in locators.items()
        },
    }
    (home / "installations.json").write_text(__import__("json").dumps(payload), encoding="utf-8")


def _docker_script(tmp_path: Path, *, present: dict[str, str], run_text: str) -> Path:
    script = tmp_path / "bin" / "docker"
    mapping = repr(present)
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"PRESENT = {mapping}\n"
        f"RUN_TEXT = {run_text!r}\n"
        "args = sys.argv[1:]\n"
        "if args[:2] == ['image', 'ls']:\n"
        "    raise SystemExit(0)\n"
        "if args[:2] == ['image', 'inspect']:\n"
        "    raise SystemExit(0 if args[2] in PRESENT.values() or args[2] in PRESENT else 1)\n"
        "if args[:1] == ['images']:\n"
        "    tags = set(PRESENT.values())\n"
        "    tags.update(key for key in PRESENT if ':' in key)\n"
        "    needle = args[-1] if args[-1] and not args[-1].startswith('{{') else ''\n"
        "    for tag in sorted(tags):\n"
        "        if not needle or needle in tag or tag.startswith(needle):\n"
        "            print(tag)\n"
        "    raise SystemExit(0)\n"
        "if args[:1] == ['run']:\n"
        "    sys.stdout.write(RUN_TEXT)\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(9)\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def test_catia_electrical_joins_kicad_stepup_and_freecad(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(binary_dir / "kicad-cli", "echo 7.0.11\n")
    executable(binary_dir / "FreeCADCmd", "echo 42\n")
    stepup = tmp_path / "stepup"
    stepup.mkdir()
    (stepup / "InitGui.py").write_text("# stepup\n", encoding="utf-8")
    _write_receipts(tmp_path, monkeypatch, **{"kicad-stepup": str(stepup)})
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    outcome = probe_catia_electrical({})
    assert outcome["status"] == "covered"
    assert "InitGui.py" in outcome["message"]


def test_tosca_joins_topopt_and_code_aster(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(
        binary_dir / "as_run",
        'exec sudo docker run --rm -w /opt/aster negetem/codeaster:latest as_run "$@"\n',
    )
    _docker_script(
        tmp_path,
        present={"negetem/codeaster:latest": "negetem/codeaster:latest"},
        run_text="Usage: as_run action\n  Functions :\n",
    )
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    monkeypatch.setattr(
        "engineering_tools.hello_probes.probe_topopt_jl",
        lambda project=None: {"status": "ok", "message": "TopOpt.jl import ok"},
    )
    outcome = probe_tosca({})
    assert outcome["status"] == "covered"
    assert "as_run" in outcome["message"]


def test_abaqus_cae_fails_without_local_salome_image(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(
        binary_dir / "salome",
        'exec sudo docker run --rm ghcr.io/codeaster/salome-meca:latest "$@"\n',
    )
    executable(
        binary_dir / "as_run",
        'exec sudo docker run --rm negetem/codeaster:latest as_run "$@"\n',
    )
    _docker_script(tmp_path, present={"negetem/codeaster:latest": "negetem/codeaster:latest"}, run_text="Usage: as_run\n")
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    outcome = probe_abaqus_cae({})
    assert outcome["status"] == "capability-failed"
    assert "no local SALOME image" in outcome["message"]


def test_enovia_joins_lfs_psql_erpnext_and_nextcloud_php(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(binary_dir / "git-lfs", "echo git-lfs/3.4.1\n")
    executable(binary_dir / "psql", "echo 'psql (PostgreSQL) 16.15'\n")
    executable(binary_dir / "nextcloud", 'exec sudo docker run --rm nextcloud:latest "$@"\n')
    _docker_script(tmp_path, present={"nextcloud:latest": "nextcloud:latest"}, run_text="PHP 8.3.0\n")
    erpnext = tmp_path / "erpnext"
    (erpnext / "erpnext").mkdir(parents=True)
    (erpnext / "erpnext" / "hooks.py").write_text("# hooks\n", encoding="utf-8")
    _write_receipts(tmp_path, monkeypatch, erpnext=str(erpnext))
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    outcome = probe_enovia({})
    assert outcome["status"] == "covered"
    assert "PHP" in outcome["message"]


def test_netvibes_uses_local_opensearch_tag_without_pull(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(
        binary_dir / "opensearch",
        'exec sudo docker run --rm opensearchproject/opensearch:latest "$@"\n',
    )
    _docker_script(
        tmp_path,
        present={"opensearchproject/opensearch": "opensearchproject/opensearch:2"},
        run_text="Version: 2.19.6, Build: tar\n",
    )
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    monkeypatch.setattr("engineering_tools.workflow_probes.sys.executable", str(binary_dir / "python-standin"))
    executable(binary_dir / "python-standin", "echo ok\n")
    monkeypatch.setattr("engineering_tools.workflow_probes._receipt_locator", lambda _component: None)
    outcome = probe_netvibes({})
    assert outcome["status"] == "covered"
    assert "2.19.6" in outcome["message"]
    assert probe_exalead({})["status"] == "covered"


def test_abaqus_cae_accepts_any_local_salome_named_image(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(
        binary_dir / "salome",
        'exec sudo docker run --rm ghcr.io/codeaster/salome-meca:latest "$@"\n',
    )
    executable(
        binary_dir / "as_run",
        'exec sudo docker run --rm negetem/codeaster:latest as_run "$@"\n',
    )
    _docker_script(
        tmp_path,
        present={
            "tefe/salome-meca:latest": "tefe/salome-meca:latest",
            "negetem/codeaster:latest": "negetem/codeaster:latest",
        },
        run_text="Usage: as_run action\n  Functions :\n",
    )
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    outcome = probe_abaqus_cae({})
    assert outcome["status"] == "covered"
    assert "tefe/salome-meca" in outcome["message"]

