from __future__ import annotations

import json
from pathlib import Path

import pytest

from engineering_tools.manifest import (
    ManifestError,
    load_manifest,
    manifest_digest,
    validate_manifest,
)


def valid_manifest() -> dict:
    return {
        "schema_version": 1,
        "inventory_state": "provisional",
        "inventory": [
            {
                "id": "simulia-fluid-dynamics-engineer",
                "name": "SIMULIA Fluid Dynamics Engineer",
                "portfolio": "SIMULIA",
                "granularity": "product",
                "audit_state": "provisional",
                "evidence": {"state": "audit-pending", "source": "2026-09-11 design input"},
            }
        ],
        "components": [
            {
                "id": "openfoam",
                "name": "OpenFOAM",
                "source": {
                    "state": "source-unresolved",
                    "homepage": "https://openfoam.org/",
                    "repository": "https://github.com/OpenFOAM/OpenFOAM-dev",
                },
                "license": "GPL-3.0-or-later",
                "install_recipe": {"state": "recipe-unimplemented", "id": "openfoam"},
                "execution": {"type": "binary", "locator": ["blockMesh", "foamExec"]},
                "probe": {"state": "implemented", "id": "openfoam-block-mesh"},
                "expected_signal": {"path": "constant/polyMesh/points"},
                "attribution": "THIRD_PARTY.md#openfoam",
            }
        ],
        "mappings": [
            {
                "id": "simulia-fluid-dynamics-engineer-to-openfoam",
                "inventory_id": "simulia-fluid-dynamics-engineer",
                "replacement": "OpenFOAM",
                "fit": "A",
                "components": ["openfoam"],
                "probe": {"state": "probe-unimplemented", "id": "cfd-solve"},
                "expected_signal": {"kind": "field-output"},
            }
        ],
    }


def test_packaged_manifest_covers_each_inventory_row_once() -> None:
    data = load_manifest()
    errors = validate_manifest(data)
    assert errors == ()
    inventory_ids = {item["id"] for item in data["inventory"]}
    mapped_ids = [item["inventory_id"] for item in data["mappings"]]
    assert set(mapped_ids) == inventory_ids
    assert len(mapped_ids) == len(set(mapped_ids))
    assert data["inventory_state"] == "audited"
    assert all(item["audit_state"] == "audited" for item in data["inventory"])


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda d: d["mappings"].clear(), "inventory entry has no mapping"),
        (lambda d: d["mappings"][0].update(components=[]), "components must not be empty"),
        (
            lambda d: d["mappings"][0].update(components=["unknown"]),
            "unknown component",
        ),
        (
            lambda d: d["components"][0]["execution"].update(type="telepathy"),
            "unsupported execution type",
        ),
        (
            lambda d: d["inventory"][0].update(audit_state="maybe"),
            "invalid audit state",
        ),
        (
            lambda d: d["components"][0]["source"].update(state="resolved"),
            "malformed immutable identity",
        ),
    ],
)
def test_validation_reports_deterministic_errors(mutation, message: str) -> None:
    data = valid_manifest()
    mutation(data)
    errors = validate_manifest(data)
    assert any(message in error for error in errors)
    assert errors == tuple(sorted(errors))


def test_load_manifest_raises_all_validation_errors(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    with pytest.raises(ManifestError) as exc:
        load_manifest(path)
    assert exc.value.errors


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda d: d["mappings"][0].update(replacement="OpenFOAM or OpenLB"),
            "must not encode alternatives",
        ),
        (
            lambda d: d["mappings"][0].update(
                alternatives=[{"replacement": "OpenLB", "components": ["openfoam"]}]
            ),
            "undeclared field",
        ),
        (
            lambda d: d["mappings"][0].update(
                choices=[{"replacement": "OpenLB", "components": ["openfoam"]}]
            ),
            "undeclared field",
        ),
        (
            lambda d: d["mappings"][0].update(
                solutions=[{"replacement": "OpenLB", "components": ["openfoam"]}]
            ),
            "undeclared field",
        ),
    ],
)
def test_validation_rejects_alternative_representations(mutation, message: str) -> None:
    data = valid_manifest()
    mutation(data)
    assert any(message in error for error in validate_manifest(data))


def test_validation_allows_fixed_composite_replacement_label() -> None:
    data = valid_manifest()
    data["mappings"][0]["replacement"] = "Git LFS + PostgreSQL + Nextcloud + ERPNext"
    assert validate_manifest(data) == ()


@pytest.mark.parametrize(
    "components",
    [[{"id": "openfoam"}], [["openfoam"]], [""]],
)
def test_mapping_components_must_be_nonempty_strings(
    components: list[object], tmp_path: Path
) -> None:
    data = valid_manifest()
    data["mappings"][0]["components"] = components
    errors = validate_manifest(data)
    assert any("components must contain only nonempty strings" in error for error in errors)

    path = tmp_path / "bad-components.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ManifestError) as exc:
        load_manifest(path)
    assert any("components must contain only nonempty strings" in error for error in exc.value.errors)


def test_manifest_digest_is_canonical() -> None:
    first = valid_manifest()
    second = json.loads(json.dumps(first, sort_keys=True))
    assert manifest_digest(first) == manifest_digest(second)
    assert len(manifest_digest(first)) == 64


@pytest.mark.parametrize(
    "mutation",
    [
        # Implemented component probe without id must fail validation, not crash hello.
        lambda d: d["components"][0]["probe"].pop("id"),
        lambda d: d["components"][0]["probe"].update(id=""),
        lambda d: d["components"][0]["probe"].update(id=None),
        # Implemented mapping probe without id must fail the same way.
        lambda d: (
            d["mappings"][0]["probe"].update(state="implemented"),
            d["mappings"][0]["probe"].pop("id"),
        ),
        lambda d: (
            d["mappings"][0]["probe"].update(state="implemented", id=""),
        ),
    ],
)
def test_implemented_probe_requires_nonempty_id(mutation) -> None:
    data = valid_manifest()
    mutation(data)
    errors = validate_manifest(data)
    assert any("requires nonempty probe id" in error for error in errors)
