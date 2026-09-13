"""Tests for packaged CalculiX sample and normalized probe."""

from __future__ import annotations

import os
import json
from pathlib import Path

import engineering_tools.hello as hello_module
from engineering_tools.hello import run_hello
from engineering_tools.hello_probes import load_calculix_sample, probe_calculix
from engineering_tools.verification import hello_report_path


def reduced_manifest(*, inventory_state="audited", mapping_probe_state="probe-unimplemented"):
    audit_state = "audited" if inventory_state == "audited" else "provisional"
    components = []
    for component_id in ("first", "second"):
        components.append({
            "id": component_id, "name": component_id.title(),
            "source": {"state": "resolved", "homepage": None, "repository": None,
                       "identity": {"type": "source", "repository": f"https://example.test/{component_id}.git", "commit": "0123456789abcdef"}},
            "license": "MIT", "install_recipe": {"state": "implemented", "id": component_id},
            "execution": {"type": "binary", "locator": [component_id]},
            "probe": {"state": "implemented", "id": f"probe-{component_id}"},
            "expected_signal": {"kind": "exit-zero"}, "attribution": "THIRD_PARTY.md",
        })
    return {"schema_version": 1, "inventory_state": inventory_state,
            "inventory": [{"id": "closed-product", "name": "Closed Product", "portfolio": "Test", "granularity": "product", "audit_state": audit_state, "evidence": {"state": "audited", "source": "test"}}],
            "components": components,
            "mappings": [{"id": "closed-product-to-open-solution", "inventory_id": "closed-product", "replacement": "Open Solution", "fit": "A", "components": ["first", "second"], "probe": {"state": mapping_probe_state, "id": "mapping-ok"}, "expected_signal": {"kind": "capability"}}]}


def write_reduced_manifest(tmp_path, **kwargs):
    path = tmp_path / "stack.json"
    path.write_text(json.dumps(reduced_manifest(**kwargs)), encoding="utf-8")
    return path


def write_receipts(tmp_path, monkeypatch, *component_ids):
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    monkeypatch.setenv("ETOOLS_HOME", str(state))
    receipts = {item: {"locator": f"/test/{item}", "immutable_id": "source:0123456789abcdef", "integrity_verified": True} for item in component_ids}
    (state / "installations.json").write_text(json.dumps({"schema_version": 1, "components": receipts}), encoding="utf-8")


def probe_result(component_id, status):
    return {"id": component_id, "name": component_id.title(), "status": status, "message": status, "locator": f"/test/{component_id}", "workdir": None, "outputs": [], "credit": None, "returncode": 0 if status == "ok" else 1}


def test_load_calculix_sample_contains_c3d8():
    text = load_calculix_sample()
    assert "*ELEMENT, TYPE=C3D8" in text
    assert "hello_beam" in text.lower() or "engineering-tools" in text.lower()


def test_calculix_probe_runs_fake_ccx(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ccx = fake_bin / "ccx"
    ccx.write_text(
        "#!/bin/sh\n"
        "# fake CalculiX: accept job name, write empty .frd\n"
        "job=\"$1\"\ntouch \"${job}.frd\" \"${job}.dat\"\nexit 0\n",
        encoding="utf-8",
    )
    ccx.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))

    result = probe_calculix(project=tmp_path / "project")
    assert result["id"] == "calculix"
    assert result["status"] == "ok"
    assert result["locator"]
    assert result["credit"]
    assert any(path.endswith(".frd") for path in result["outputs"])


def test_calculix_probe_marks_nonzero_execution_broken(tmp_path, monkeypatch):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ccx = fake_bin / "ccx"
    ccx.write_text("#!/bin/sh\nexit 7\n", encoding="utf-8")
    ccx.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + "/usr/bin:/bin")

    assert probe_calculix()["status"] == "broken"


def test_calculix_probe_missing_is_typed(monkeypatch):
    monkeypatch.setenv("PATH", "/nonexistent-etools-path")
    assert probe_calculix()["status"] == "missing"


def test_hello_evaluates_every_component_after_failure(tmp_path, monkeypatch):
    write_receipts(tmp_path, monkeypatch, "first", "second")
    called = []
    def first(project=None):
        called.append("first")
        return probe_result("first", "broken")
    def second(project=None):
        called.append("second")
        return probe_result("second", "ok")
    monkeypatch.setattr(hello_module, "COMPONENT_PROBES", {"probe-first": first, "probe-second": second})
    report = run_hello(manifest_path=write_reduced_manifest(tmp_path))
    assert called == ["first", "second"]
    assert report["counts"]["components"] == {"broken": 1, "ok": 1}
    assert report["ok"] is False


def test_component_ok_product_probe_unimplemented_stays_red(tmp_path, monkeypatch):
    write_receipts(tmp_path, monkeypatch, "first", "second")
    monkeypatch.setattr(hello_module, "COMPONENT_PROBES", {"probe-first": lambda project=None: probe_result("first", "ok"), "probe-second": lambda project=None: probe_result("second", "ok")})
    report = run_hello(manifest_path=write_reduced_manifest(tmp_path))
    assert report["products"][0]["status"] == "probe-unimplemented"
    assert report["ok"] is False


def test_provisional_inventory_prevents_success(tmp_path, monkeypatch):
    write_receipts(tmp_path, monkeypatch, "first", "second")
    monkeypatch.setattr(hello_module, "COMPONENT_PROBES", {"probe-first": lambda project=None: probe_result("first", "ok"), "probe-second": lambda project=None: probe_result("second", "ok")})
    monkeypatch.setattr(hello_module, "PRODUCT_PROBES", {"mapping-ok": lambda results: {"status": "covered", "message": "covered"}})
    path = write_reduced_manifest(tmp_path, inventory_state="provisional", mapping_probe_state="implemented")
    report = run_hello(manifest_path=path)
    assert report["products"][0]["status"] == "covered"
    assert report["status"] == "inventory-unfrozen"
    assert report["ok"] is False


def test_missing_installation_is_reported_not_skipped(tmp_path, monkeypatch):
    write_receipts(tmp_path, monkeypatch)
    monkeypatch.setattr(hello_module, "COMPONENT_PROBES", {})
    report = run_hello(manifest_path=write_reduced_manifest(tmp_path))
    assert [item["status"] for item in report["components"]] == ["missing", "missing"]


def test_hello_persists_manifest_digest(tmp_path, monkeypatch):
    write_receipts(tmp_path, monkeypatch)
    report = run_hello(manifest_path=write_reduced_manifest(tmp_path))
    persisted = json.loads(hello_report_path().read_text(encoding="utf-8"))
    assert persisted["manifest_digest"] == report["manifest_digest"]
    assert persisted["components"] == report["components"]
    assert persisted["products"] == report["products"]


def test_invalid_manifest_reports_all_errors_without_probes(tmp_path, monkeypatch):
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "state"))
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
    called = []
    monkeypatch.setattr(hello_module, "COMPONENT_PROBES", {"x": lambda project=None: called.append("x")})
    report = run_hello(manifest_path=path)
    assert report["status"] == "invalid-manifest"
    assert report["ok"] is False
    assert len(report["errors"]) > 1
    assert called == []
