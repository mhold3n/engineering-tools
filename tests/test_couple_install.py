"""Couple requirements list and the Ubuntu-only install entry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engineering_tools.cli import main
from engineering_tools.couple_install import (
    VM_SMOKE,
    apt_commands,
    install_couple,
    load_couple_requirements,
    validate_couple_requirements,
)
from engineering_tools.install import InstallError
from engineering_tools.install_waves import INSTALL_WAVES, all_wave_component_ids
from engineering_tools.manifest import load_manifest

UBUNTU = {"system": "Linux", "id": "ubuntu", "version_id": "24.04"}
MAC = {"system": "Darwin", "id": "", "version_id": ""}


def test_couple_list_names_esi_precice_adapter_gmsh_and_mpi() -> None:
    data = load_couple_requirements()
    packages = {entry["package"] for entry in data["archive"]}
    packages.add(data["openfoam"]["package"])
    packages.update(entry["package"] for entry in data["debs"])
    assert "openfoam2512-default" in packages
    assert "gmsh" in packages
    assert "openmpi-bin" in packages
    assert "libprecice3" in packages
    assert "calculix-precice3" in packages
    adapter = next(entry for entry in data["debs"] if entry["id"] == "calculix-adapter")
    assert adapter["version"] == "2.20.2"
    assert "2.20.1" not in adapter["url"]
    assert "noble" in adapter["url"]
    precice = next(entry for entry in data["debs"] if entry["id"] == "precice")
    assert precice["locators"] == ["precice-tools", "binprecice", "precice"]
    assert data["openfoam"]["locators"] == ["rhoPimpleFoam", "gmshToFoam"]
    assert data["python_package"]["argv"] == ["pip", "install", "-e", ".[dev]"]
    assert VM_SMOKE == "not_run"


def test_couple_list_rejects_adapter_2_20_1() -> None:
    data = load_couple_requirements()
    adapter = next(entry for entry in data["debs"] if entry["id"] == "calculix-adapter")
    adapter["version"] = "2.20.1"
    adapter["url"] = adapter["url"].replace("2.20.2", "2.20.1")
    with pytest.raises(InstallError, match="2.20.2"):
        validate_couple_requirements(data)


def test_couple_list_rejects_empty_package_or_url() -> None:
    data = load_couple_requirements()
    data["debs"][0]["url"] = "  "
    with pytest.raises(InstallError, match="empty"):
        validate_couple_requirements(data)


def test_hello_recipes_stay_distro_packages() -> None:
    by_id = {item["id"]: item for item in load_manifest()["components"]}
    assert by_id["calculix"]["install_recipe"]["package"] == "calculix-ccx"
    assert by_id["openfoam"]["install_recipe"]["package"] == "openfoam"
    wave = INSTALL_WAVES["2-cae-core"]
    assert "calculix" in wave
    assert "openfoam" in wave
    assert "ubuntu-24.04-couple" not in all_wave_component_ids()


def test_couple_commands_are_apt_and_leave_the_bootstrap_unrun() -> None:
    data = load_couple_requirements()
    commands = apt_commands(data, [Path("/tmp/libprecice3.deb"), Path("/tmp/calculix-precice3.deb")])
    flat = [arg for argv in commands for arg in argv]
    assert commands[0][:4] == ["apt-get", "install", "-y", "gmsh"]
    assert "openmpi-bin" in commands[0]
    assert "openfoam2512-default" in commands[-1]
    assert "pip" not in flat
    assert "curl" not in flat
    assert "https://dl.openfoam.com/add-debian-repo.sh" not in flat
    bootstrap = data["openfoam"]["bootstrap"]
    assert bootstrap["executed_by_installer"] is False
    assert bootstrap["pubkey_url"] == "https://dl.openfoam.com/pubkey.gpg"
    assert bootstrap["source_line"] == "deb [arch=amd64] https://dl.openfoam.com/repos/deb noble main"


def test_macos_couple_does_not_call_apt(tmp_path: Path) -> None:
    calls: list[list[str]] = []
    result = install_couple(
        destination=tmp_path / "debs",
        worktree_root=tmp_path / "repo",
        host=MAC,
        runner=lambda argv: calls.append(argv) or 0,
    )
    assert result["status"] == "unavailable"
    assert result["apt_attempted"] is False
    assert calls == []
    assert result["python_package"] == ["pip", "install", "-e", ".[dev]"]
    assert result["vm_smoke"] == "not_run"


def test_couple_refuses_destination_inside_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(InstallError, match="inside git worktree"):
        install_couple(destination=repo / "debs", worktree_root=repo, host=UBUNTU)


def test_ubuntu_missing_locator_is_a_failed_install(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fetch(url: str, destination: Path) -> None:
        destination.write_bytes(b"deb")

    def runner(argv: list[str]) -> int:
        calls.append(argv)
        return 0

    result = install_couple(
        destination=tmp_path / "debs",
        worktree_root=tmp_path / "repo",
        host=UBUNTU,
        runner=runner,
        fetch=fetch,
        probe=lambda: {
            "rhoPimpleFoam": False,
            "gmshToFoam": False,
            "ccx_preCICE": False,
            "precice": False,
            "gmsh": False,
            "mpirun": False,
        },
    )
    assert result["status"] == "failed"
    assert result["apt_attempted"] is True
    assert result["missing"]
    assert calls
    assert all("pip" not in arg for argv in calls for arg in argv)


def test_ubuntu_success_writes_a_receipt_outside_the_worktree(tmp_path, monkeypatch) -> None:
    home = tmp_path / "home"
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("ETOOLS_HOME", str(home))

    def fetch(url: str, destination: Path) -> None:
        destination.write_bytes(b"deb")

    result = install_couple(
        destination=tmp_path / "debs",
        worktree_root=repo,
        host=UBUNTU,
        runner=lambda argv: 0,
        fetch=fetch,
        probe=lambda: {
            "rhoPimpleFoam": True,
            "gmshToFoam": True,
            "ccx_preCICE": True,
            "precice": True,
            "gmsh": True,
            "mpirun": True,
        },
    )
    assert result["status"] == "installed"
    receipt_path = Path(result["receipt_path"])
    assert home in receipt_path.parents
    assert repo not in receipt_path.parents
    from engineering_tools.verification import installation_for, load_installations

    receipt = installation_for("ubuntu-24.04-couple", load_installations())
    assert receipt is not None
    assert receipt["integrity_verified"] is True
    assert receipt["package"] == "openfoam2512-default"
    assert receipt["vm_smoke"] == "not_run"


def test_ubuntu_locator_failure_writes_no_receipt(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "home"))

    def fetch(url: str, destination: Path) -> None:
        destination.write_bytes(b"deb")

    result = install_couple(
        destination=tmp_path / "debs",
        worktree_root=tmp_path / "repo",
        host=UBUNTU,
        runner=lambda argv: 0,
        fetch=fetch,
        probe=lambda: {"rhoPimpleFoam": False},
    )
    assert result["status"] == "failed"
    from engineering_tools.verification import installation_for, load_installations

    assert installation_for("ubuntu-24.04-couple", load_installations()) is None


def test_cli_couple_on_macos_reports_unavailable(tmp_path, monkeypatch, capsys) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    monkeypatch.setattr(
        "engineering_tools.cli.current_host",
        lambda: MAC,
    )
    code = main(["install", "--couple", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "unavailable"
    assert payload["apt_attempted"] is False
