from __future__ import annotations

import json

from engineering_tools.verification import (
    hello_report_path,
    installation_for,
    load_installations,
    write_hello_report,
)


def test_missing_installations_is_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path))
    assert load_installations() == {"schema_version": 1, "components": {}}


def test_installation_lookup(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path))
    (tmp_path / "installations.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "components": {
                    "openfoam": {
                        "locator": "/opt/openfoam/bin/blockMesh",
                        "immutable_id": "sha256:abc",
                        "integrity_verified": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    data = load_installations()
    assert installation_for("openfoam", data)["integrity_verified"] is True


def test_report_write_is_complete_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path))
    report = {"schema_version": 1, "ok": False, "components": [], "products": []}
    path = write_hello_report(report)
    assert path == hello_report_path()
    assert json.loads(path.read_text(encoding="utf-8")) == report
    assert not list(tmp_path.glob(".hello-report.*.tmp"))
