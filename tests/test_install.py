"""Install runner: fetch, verify, install outside worktree, write receipts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from engineering_tools import install as install_module
from engineering_tools.install import (
    InstallError,
    install_component,
)
from engineering_tools.verification import installation_for, load_installations


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _component(
    *,
    component_id: str = "toy-tool",
    recipe_id: str = "toy-archive",
    url: str | None = None,
    sha256: str | None = None,
) -> dict:
    """Minimal resolved component for install tests."""
    return {
        "id": component_id,
        "name": "Toy Tool",
        "source": {
            "state": "resolved",
            "homepage": None,
            "repository": None,
            "identity": {
                "type": "artifact",
                "url": url or "file:///unused",
                "sha256": sha256 or "0" * 64,
            },
        },
        "license": "MIT",
        "install_recipe": {"state": "implemented", "id": recipe_id, "kind": "upstream-archive"},
        "execution": {"type": "binary", "locator": ["toy-tool"]},
        "probe": {"state": "probe-unimplemented", "id": "toy-probe"},
        "expected_signal": {"kind": "exit-zero"},
        "attribution": "THIRD_PARTY.md",
    }


def test_archive_install_writes_verified_receipt(tmp_path, monkeypatch) -> None:
    # RED then GREEN: known sha256 archive installs outside worktree with verified receipt.
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "state"))
    worktree = tmp_path / "repo"
    worktree.mkdir()
    install_root = tmp_path / "opt"
    archive = tmp_path / "toy.tar"
    payload = b"toy-payload-v1"
    archive.write_bytes(payload)
    digest = _sha256(payload)
    component = _component(url=archive.as_uri(), sha256=digest)

    result = install_component(
        component,
        install_root=install_root,
        worktree_root=worktree,
        force=False,
    )
    assert result["status"] == "installed"
    assert result["integrity_verified"] is True
    data = load_installations()
    receipt = installation_for("toy-tool", data)
    assert receipt is not None
    assert receipt["integrity_verified"] is True
    assert receipt["immutable_id"] == f"sha256:{digest}"
    assert receipt["recipe_id"] == "toy-archive"
    assert Path(receipt["locator"]).exists()
    assert worktree.resolve() not in Path(receipt["locator"]).resolve().parents
    assert Path(receipt["locator"]).resolve() != worktree.resolve()


def test_matching_receipt_skips_unless_force(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "state"))
    worktree = tmp_path / "repo"
    worktree.mkdir()
    install_root = tmp_path / "opt"
    archive = tmp_path / "toy.tar"
    payload = b"toy-payload-v1"
    archive.write_bytes(payload)
    digest = _sha256(payload)
    component = _component(url=archive.as_uri(), sha256=digest)

    first = install_component(component, install_root=install_root, worktree_root=worktree)
    assert first["status"] == "installed"
    second = install_component(component, install_root=install_root, worktree_root=worktree)
    assert second["status"] == "skipped"
    forced = install_component(
        component, install_root=install_root, worktree_root=worktree, force=True
    )
    assert forced["status"] == "installed"


def test_sha256_mismatch_writes_no_verified_receipt(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "state"))
    worktree = tmp_path / "repo"
    worktree.mkdir()
    install_root = tmp_path / "opt"
    archive = tmp_path / "toy.tar"
    archive.write_bytes(b"actual-bytes")
    component = _component(url=archive.as_uri(), sha256=_sha256(b"expected-other"))

    with pytest.raises(InstallError, match="digest mismatch"):
        install_component(component, install_root=install_root, worktree_root=worktree)

    data = load_installations()
    receipt = installation_for("toy-tool", data)
    assert receipt is None or receipt.get("integrity_verified") is not True


def test_install_destination_inside_worktree_is_refused(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "state"))
    worktree = tmp_path / "repo"
    worktree.mkdir()
    archive = tmp_path / "toy.tar"
    payload = b"toy"
    archive.write_bytes(payload)
    component = _component(url=archive.as_uri(), sha256=_sha256(payload))

    with pytest.raises(InstallError, match="inside git worktree"):
        install_component(
            component,
            install_root=worktree / "vendor",
            worktree_root=worktree,
        )

    assert installation_for("toy-tool", load_installations()) is None


def test_unsupported_recipe_kind_fails(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "state"))
    worktree = tmp_path / "repo"
    worktree.mkdir()
    component = _component()
    component["install_recipe"] = {
        "state": "implemented",
        "id": "bad-kind",
        "kind": "telepathy",
    }
    with pytest.raises(InstallError, match="unsupported recipe kind"):
        install_component(
            component,
            install_root=tmp_path / "opt",
            worktree_root=worktree,
        )
