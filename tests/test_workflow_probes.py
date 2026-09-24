"""Joint multi-tool product probes using fake tools on PATH."""

from __future__ import annotations

import os
from pathlib import Path

from engineering_tools.workflow_probes import (
    probe_biovia_discovery,
    probe_biovia_materials,
    probe_delmia_quintiq,
    probe_delmia_robotics,
    probe_solidworks_pdm,
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
