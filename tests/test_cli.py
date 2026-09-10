"""CLI smoke tests via engineering_tools.cli.main."""

from __future__ import annotations

from pathlib import Path

from engineering_tools.cli import main


def test_doctor_returns_int() -> None:
    code = main(["doctor"])
    assert code in (0, 1)


def test_profile_alias() -> None:
    code = main(["profile"])
    assert code in (0, 1)


def test_init_creates_project(tmp_path: Path) -> None:
    target = tmp_path / "cli-part"
    code = main(["init", str(target), "--name", "CLI Part"])
    assert code == 0
    assert (target / ".engineering-tools.json").is_file()
    assert (target / "jobs").is_dir()
    assert (target / "artifacts").is_dir()


def test_hello_returns_int() -> None:
    code = main(["hello"])
    assert code in (0, 1)


def test_hello_with_project(tmp_path: Path) -> None:
    proj = tmp_path / "p"
    proj.mkdir()
    code = main(["hello", "--project", str(proj)])
    assert code in (0, 1)
