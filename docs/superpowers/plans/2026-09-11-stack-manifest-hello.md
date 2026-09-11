# Stack Manifest and Exhaustive `hello` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a packaged provisional Dassault inventory/replacement manifest, rewrite `etools hello` as exhaustive and intentionally failing Alpha verification, and complete OpenFOAM mesh verification/custom execution without falsely covering SIMULIA CFD.

**Architecture:** A packaged JSON manifest normalizes proprietary inventory, open-source components, and exactly-one replacement mappings. Small standard-library modules load/validate that manifest, read local installation evidence, execute trusted probe functions, aggregate component and product states, and atomically persist one report. Existing CalculiX and FreeCAD probes move behind the same result contract; OpenFOAM gains a `blockMesh` component probe and custom case runner, while its CFD product probe remains explicitly unimplemented.

**Tech Stack:** Python 3.10+, standard library (`json`, `hashlib`, `importlib.resources`, `pathlib`, `shutil`, `subprocess`, `tempfile`), argparse, setuptools package data, pytest, GitHub Actions.

## Global Constraints

- Reference platform is Ubuntu 24.04 LTS on x86-64.
- Runtime remains standard-library-only; add no dependency.
- Third-party source, binaries, archives, images, installed trees, and generated engineering data stay outside Git.
- Every provisional proprietary inventory row has exactly one replacement mapping; a fixed composite is one solution, not alternatives.
- Inventory remains `provisional`; Alpha cannot pass until independent audit freezes it.
- Missing, broken, misconfigured, unverified, invalid-pointer, probe-unimplemented, capability-failed, inventory-unfrozen, and invalid-manifest states remain non-success.
- `hello` evaluates every component and mapping; no preference or early return.
- Component success never implies product coverage. OpenFOAM `blockMesh` success leaves SIMULIA Fluid Dynamics Engineer red until a real solver probe lands.
- Package size never affects inclusion or pass/fail.
- Implement behavior test-first. Preserve unrelated user changes.

**Origin:** `docs/superpowers/specs/2026-09-11-open-source-stack-manifest-hello-design.md`

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `src/engineering_tools/data/stack.json` | Packaged provisional inventory, component catalog, and replacement mappings. |
| `src/engineering_tools/manifest.py` | Load packaged/override manifest, validate invariants, compute canonical digest. |
| `src/engineering_tools/verification.py` | Load local installation receipts and atomically persist `hello-report.json`. |
| `src/engineering_tools/hello_probes.py` | Trusted CalculiX, FreeCAD, and OpenFOAM component probe implementations. |
| `src/engineering_tools/hello.py` | Exhaustive manifest evaluation and product-state aggregation. |
| `src/engineering_tools/cli.py` | Stable text/JSON `hello` output and per-result project job logging. |
| `src/engineering_tools/run.py` | Add OpenFOAM custom case staging, `blockMesh`, artifact collection, and job result. |
| `src/engineering_tools/run_cli.py` | Existing run dispatch; only error handling needed for directory inputs. |
| `src/engineering_tools/jobs.py` | Reused append-only job contract; no schema redesign. |
| `pyproject.toml` | Package JSON and recursive OpenFOAM fixture; bump release to `0.4.0`. |
| `tests/test_manifest.py` | Manifest loading, normalization, and validation tests. |
| `tests/test_verification.py` | Installation receipt and atomic report tests. |
| `tests/test_hello.py` | Exhaustive engine, aggregation, failure-state, and JSON contract tests. |
| `tests/test_freecad_hello.py` | Existing FreeCAD fixture/probe compatibility tests. |
| `tests/test_openfoam_hello.py` | Direct and `foamExec` OpenFOAM component probe tests. |
| `tests/test_run.py` | OpenFOAM custom run tests alongside existing CalculiX/FreeCAD tests. |
| `tests/test_plm.py` | Per-component/per-mapping `hello --project` job-history assertions. |
| `.github/workflows/ci.yml` | Hosted orchestration/manifest test workflow; does not certify Alpha. |
| `README.md` | New `hello` semantics, expected red state, OpenFOAM custom run. |
| `STRATEGY.md` | Alpha/Beta boundary and provisional-inventory audit gate. |

---

### Task 1: Package and validate provisional stack manifest

**Files:**

- Create: `src/engineering_tools/data/stack.json`
- Create: `src/engineering_tools/manifest.py`
- Create: `tests/test_manifest.py`
- Modify: `pyproject.toml:34-35`

**Interfaces:**

- Produces: `ManifestError(errors: tuple[str, ...])`
- Produces: `load_manifest(path: str | Path | None = None) -> dict[str, Any]`
- Produces: `validate_manifest(data: object) -> tuple[str, ...]`
- Produces: `manifest_digest(data: dict[str, Any]) -> str`
- Consumed by: Tasks 2, 4, and 7.

- [ ] **Step 1: Write manifest loader and invariant tests**

Create `tests/test_manifest.py` with focused fixtures rather than copying full production manifest into each test:

```python
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
    assert data["inventory_state"] == "provisional"


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


def test_manifest_digest_is_canonical() -> None:
    first = valid_manifest()
    second = json.loads(json.dumps(first, sort_keys=True))
    assert manifest_digest(first) == manifest_digest(second)
    assert len(manifest_digest(first)) == 64
```

- [ ] **Step 2: Run manifest tests and verify red state**

Run:

```bash
pytest tests/test_manifest.py -q
```

Expected: collection error because `engineering_tools.manifest` does not exist.

- [ ] **Step 3: Add exact provisional manifest**

Create `src/engineering_tools/data/stack.json` with these top-level keys and no others:

```json
{
  "schema_version": 1,
  "inventory_state": "provisional",
  "inventory": [],
  "components": [],
  "mappings": []
}
```

Populate `inventory` and `mappings` from every row in `docs/superpowers/specs/2026-09-11-open-source-stack-manifest-hello-design.md` under “Provisional Proprietary Inventory and Replacement Map.” Use lowercase kebab-case IDs. Split each selected response into deduplicated component IDs; `+` means all listed components are required. Use these exact lifecycle rules:

- Every inventory row: `audit_state = "provisional"` and `evidence = {"state": "audit-pending", "source": "2026-09-11 design input"}`. Independent inventory audit replaces this with official product evidence.
- Every component without immutable artifact research: `source.state = "source-unresolved"`; include a known official homepage/repository when already documented, otherwise use JSON `null` rather than inventing a version, URL, or digest.
- Every missing installer: `install_recipe.state = "recipe-unimplemented"`.
- CalculiX: `probe = {"state": "implemented", "id": "calculix-hello-beam"}`.
- FreeCAD: `probe = {"state": "implemented", "id": "freecad-hello-box"}`.
- OpenFOAM: `probe = {"state": "implemented", "id": "openfoam-block-mesh"}`.
- All other components: `probe.state = "probe-unimplemented"` with stable component-specific probe IDs.
- Every mapping probe: `probe.state = "probe-unimplemented"`. This includes SIMULIA Fluid Dynamics Engineer; `blockMesh` does not prove CFD.
- `execution.type` must be one of `binary`, `python`, `container`, `java`, `service`, or `other` and each locator must be nonempty.
- Preserve one mapping per inventory ID. Never encode choices with `/`, `or`, or arrays of alternative solution objects.

Use exact selections in design spec. In particular: Abaqus solver maps to Code_Aster; SOLIDWORKS Simulation maps to CalculiX; TURBOMOLE maps to Psi4; ENOVIA maps to fixed Git LFS + PostgreSQL + Nextcloud + ERPNext composition.

- [ ] **Step 4: Implement manifest loader and validation**

Create `src/engineering_tools/manifest.py`:

```python
"""Load and validate packaged open-source stack expectations."""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from pathlib import Path
from typing import Any

EXECUTION_TYPES = {"binary", "python", "container", "java", "service", "other"}
AUDIT_STATES = {"provisional", "audited"}
SOURCE_STATES = {"resolved", "source-unresolved"}
INSTALL_RECIPE_STATES = {"implemented", "recipe-unimplemented"}
PROBE_STATES = {"implemented", "probe-unimplemented"}


class ManifestError(ValueError):
    def __init__(self, errors: tuple[str, ...]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _read_packaged_manifest() -> str:
    root = resources.files("engineering_tools")
    return (root / "data" / "stack.json").read_text(encoding="utf-8")


def load_manifest(path: str | Path | None = None) -> dict[str, Any]:
    try:
        text = (
            Path(path).expanduser().read_text(encoding="utf-8")
            if path is not None
            else _read_packaged_manifest()
        )
        data = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError((f"manifest could not be loaded: {exc}",)) from exc
    errors = validate_manifest(data)
    if errors:
        raise ManifestError(errors)
    return data


def _ids(rows: object, section: str, errors: list[str]) -> set[str]:
    if not isinstance(rows, list):
        errors.append(f"{section} must be a list")
        return set()
    found: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
            errors.append(f"{section}[{index}] requires a nonempty id")
            continue
        if row["id"] in found:
            errors.append(f"{section} contains duplicate id {row['id']!r}")
        found.add(row["id"])
    return found


def validate_manifest(data: object) -> tuple[str, ...]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ("manifest root must be an object",)
    if data.get("schema_version") != 1:
        errors.append("schema_version must equal 1")
    if data.get("inventory_state") not in AUDIT_STATES:
        errors.append("inventory_state must be provisional or audited")
    inventory = data.get("inventory")
    components = data.get("components")
    mappings = data.get("mappings")
    inventory_ids = _ids(inventory, "inventory", errors)
    component_ids = _ids(components, "components", errors)
    _ids(mappings, "mappings", errors)

    if isinstance(inventory, list):
        for row in inventory:
            if isinstance(row, dict) and row.get("audit_state") not in AUDIT_STATES:
                errors.append(f"inventory {row.get('id')!r} has invalid audit state")

    mapped: list[str] = []
    if isinstance(mappings, list):
        for row in mappings:
            if not isinstance(row, dict):
                continue
            inventory_id = row.get("inventory_id")
            if inventory_id not in inventory_ids:
                errors.append(f"mapping {row.get('id')!r} references unknown inventory")
            elif inventory_id in mapped:
                errors.append(f"inventory {inventory_id!r} has multiple mappings")
            else:
                mapped.append(inventory_id)
            required = row.get("components")
            if not isinstance(required, list) or not required:
                errors.append(f"mapping {row.get('id')!r} components must not be empty")
            elif unknown := sorted(set(required) - component_ids):
                errors.append(f"mapping {row.get('id')!r} references unknown component {unknown[0]!r}")

    for inventory_id in sorted(inventory_ids - set(mapped)):
        errors.append(f"inventory entry has no mapping: {inventory_id!r}")

    if isinstance(components, list):
        for row in components:
            if not isinstance(row, dict):
                continue
            execution = row.get("execution")
            execution_type = execution.get("type") if isinstance(execution, dict) else None
            locator = execution.get("locator") if isinstance(execution, dict) else None
            if execution_type not in EXECUTION_TYPES:
                errors.append(f"component {row.get('id')!r} has unsupported execution type")
            if not isinstance(locator, list) or not locator or not all(
                isinstance(item, str) and item for item in locator
            ):
                errors.append(f"component {row.get('id')!r} requires nonempty locator list")
            source = row.get("source")
            source_state = source.get("state") if isinstance(source, dict) else None
            if source_state not in SOURCE_STATES:
                errors.append(f"component {row.get('id')!r} has invalid source state")
            if source_state == "resolved":
                identity = source.get("identity")
                identity_type = identity.get("type") if isinstance(identity, dict) else None
                valid_identity = (
                    identity_type == "artifact"
                    and isinstance(identity.get("url"), str)
                    and isinstance(identity.get("sha256"), str)
                ) or (
                    identity_type == "container"
                    and isinstance(identity.get("digest"), str)
                    and identity["digest"].startswith("sha256:")
                ) or (
                    identity_type == "source"
                    and isinstance(identity.get("repository"), str)
                    and isinstance(identity.get("commit"), str)
                )
                if not valid_identity:
                    errors.append(f"component {row.get('id')!r} has malformed immutable identity")
            install_recipe = row.get("install_recipe")
            install_state = (
                install_recipe.get("state") if isinstance(install_recipe, dict) else None
            )
            if install_state not in INSTALL_RECIPE_STATES:
                errors.append(f"component {row.get('id')!r} has invalid install recipe state")
            probe = row.get("probe")
            probe_state = probe.get("state") if isinstance(probe, dict) else None
            if probe_state not in PROBE_STATES:
                errors.append(f"component {row.get('id')!r} has invalid probe state")

    if isinstance(mappings, list):
        for row in mappings:
            if not isinstance(row, dict):
                continue
            if not isinstance(row.get("replacement"), str) or not row["replacement"].strip():
                errors.append(f"mapping {row.get('id')!r} requires one replacement label")
            probe = row.get("probe")
            probe_state = probe.get("state") if isinstance(probe, dict) else None
            if probe_state not in PROBE_STATES:
                errors.append(f"mapping {row.get('id')!r} has invalid probe state")

    return tuple(sorted(set(errors)))


def manifest_digest(data: dict[str, Any]) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
```

- [ ] **Step 5: Package manifest and recursive OpenFOAM fixture**

Change `pyproject.toml` package data to:

```toml
[tool.setuptools.package-data]
engineering_tools = [
  "data/stack.json",
  "data/calculix/*.inp",
  "data/freecad/*.py",
  "data/openfoam/hello_cavity/README.md",
  "data/openfoam/hello_cavity/0/*",
  "data/openfoam/hello_cavity/constant/*",
  "data/openfoam/hello_cavity/system/*",
]
```

- [ ] **Step 6: Run manifest tests**

Run:

```bash
pytest tests/test_manifest.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit manifest foundation**

```bash
git add src/engineering_tools/data/stack.json src/engineering_tools/manifest.py tests/test_manifest.py pyproject.toml
git commit -m "feat: add provisional stack manifest"
```

---

### Task 2: Persist installation evidence and atomic hello report

**Files:**

- Create: `src/engineering_tools/verification.py`
- Create: `tests/test_verification.py`

**Interfaces:**

- Consumes: `registry.etools_home()` and `manifest.manifest_digest()`.
- Produces: `load_installations() -> dict[str, Any]`
- Produces: `installation_for(component_id: str, installations: dict[str, Any]) -> dict[str, Any] | None`
- Produces: `hello_report_path() -> Path`
- Produces: `write_hello_report(report: dict[str, Any]) -> Path`
- Consumed by: Task 4.

- [ ] **Step 1: Write failing local-state tests**

Create `tests/test_verification.py`:

```python
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
```

- [ ] **Step 2: Verify tests fail**

Run `pytest tests/test_verification.py -q`.

Expected: collection error because `engineering_tools.verification` does not exist.

- [ ] **Step 3: Implement local-state helpers**

Create `src/engineering_tools/verification.py`:

```python
"""Machine-local installation evidence and hello reports."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .registry import etools_home


def installations_path() -> Path:
    return etools_home() / "installations.json"


def hello_report_path() -> Path:
    return etools_home() / "hello-report.json"


def load_installations() -> dict[str, Any]:
    path = installations_path()
    if not path.is_file():
        return {"schema_version": 1, "components": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "components": {}}
    if not isinstance(data, dict) or not isinstance(data.get("components"), dict):
        return {"schema_version": 1, "components": {}}
    return data


def installation_for(
    component_id: str,
    installations: dict[str, Any],
) -> dict[str, Any] | None:
    value = installations.get("components", {}).get(component_id)
    return value if isinstance(value, dict) else None


def write_hello_report(report: dict[str, Any]) -> Path:
    destination = hello_report_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix=".hello-report.", suffix=".tmp", dir=destination.parent)
    temporary = Path(raw_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return destination
```

- [ ] **Step 4: Run local-state tests**

Run `pytest tests/test_verification.py -q`.

Expected: 3 tests pass.

- [ ] **Step 5: Commit verification storage**

```bash
git add src/engineering_tools/verification.py tests/test_verification.py
git commit -m "feat: persist hello verification evidence"
```

---

### Task 3: Normalize CalculiX, FreeCAD, and OpenFOAM component probes

**Files:**

- Create: `src/engineering_tools/hello_probes.py`
- Create: `tests/test_openfoam_hello.py`
- Modify: `tests/test_hello.py`
- Modify: `tests/test_freecad_hello.py`
- Modify: `src/engineering_tools/hello.py`
- Modify: `src/engineering_tools/run.py:11`

**Interfaces:**

- Produces: `probe_calculix(project: str | Path | None = None) -> dict[str, Any]`
- Produces: `probe_freecad(project: str | Path | None = None) -> dict[str, Any]`
- Produces: `probe_openfoam(project: str | Path | None = None) -> dict[str, Any]`
- Produces: `COMPONENT_PROBES: dict[str, Callable[..., dict[str, Any]]]`
- Each probe result contains exact keys: `id`, `name`, `status`, `message`, `locator`, `workdir`, `outputs`, `credit`, and `returncode`.
- Consumed by: Task 4 and `run.py`.

- [ ] **Step 1: Rewrite existing probe tests around normalized results**

Update `tests/test_hello.py` to test `probe_calculix` directly. Keep sample-content assertion, then assert fake `ccx` returns `status == "ok"`, `.frd` output, and nonzero fake execution returns `status == "broken"` rather than success. Update `tests/test_freecad_hello.py` the same way for `probe_freecad`.

Use this result assertion shape in both files:

```python
result = probe_calculix(project=tmp_path / "project")
assert result["id"] == "calculix"
assert result["status"] == "ok"
assert result["locator"]
assert result["credit"]
assert any(path.endswith(".frd") for path in result["outputs"])
```

For missing binaries, isolate `PATH` and assert:

```python
assert probe_calculix()["status"] == "missing"
assert probe_freecad()["status"] == "missing"
```

- [ ] **Step 2: Add failing OpenFOAM probe tests**

Create `tests/test_openfoam_hello.py` with helpers that create executable shell scripts. Direct `blockMesh` should create expected mesh output relative to current case directory:

```python
from __future__ import annotations

import os
from pathlib import Path

from engineering_tools.hello_probes import probe_openfoam


def executable(path: Path, body: str) -> Path:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


def test_openfoam_probe_runs_direct_block_mesh(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(
        binary_dir / "blockMesh",
        'mkdir -p constant/polyMesh\nprintf points > constant/polyMesh/points\n',
    )
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    result = probe_openfoam(project=tmp_path / "project")
    assert result["status"] == "ok"
    assert result["locator"].endswith("blockMesh")
    assert any(path.endswith("constant/polyMesh/points") for path in result["outputs"])


def test_openfoam_probe_falls_back_to_foam_exec(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(
        binary_dir / "foamExec",
        'test "$1" = blockMesh || exit 9\nmkdir -p constant/polyMesh\ntouch constant/polyMesh/points\n',
    )
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    result = probe_openfoam()
    assert result["status"] == "ok"
    assert "foamExec" in result["locator"]


def test_openfoam_probe_requires_mesh_artifact(tmp_path, monkeypatch) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    executable(binary_dir / "blockMesh", "exit 0\n")
    monkeypatch.setenv("PATH", str(binary_dir) + os.pathsep + "/usr/bin:/bin")
    result = probe_openfoam()
    assert result["status"] == "broken"
    assert "constant/polyMesh/points" in result["message"]


def test_openfoam_probe_missing_is_typed(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/nonexistent-etools-path")
    result = probe_openfoam()
    assert result["status"] == "missing"
    assert result["outputs"] == []
```

- [ ] **Step 3: Run probe tests and verify failure**

Run:

```bash
pytest tests/test_hello.py tests/test_freecad_hello.py tests/test_openfoam_hello.py -q
```

Expected: import errors for `hello_probes` and normalized probe functions.

- [ ] **Step 4: Move component-specific work into `hello_probes.py`**

Move existing sample loading, binary resolution, work-directory creation, subprocess calls, credits, and artifact collection from `hello.py` into `hello_probes.py`. Preserve existing timeout values. Correct existing semantic bug: nonzero CalculiX/FreeCAD process return codes produce `broken`, not successful pulse.

Add exact OpenFOAM constants and command resolver:

```python
OPENFOAM_CREDIT = (
    "OpenFOAM (GPL-3.0-or-later) - https://openfoam.org/ - called as an "
    "upstream solver, not vendored"
)


def _openfoam_command() -> tuple[list[str], str] | None:
    if block_mesh := shutil.which("blockMesh"):
        return [block_mesh], block_mesh
    if foam_exec := shutil.which("foamExec"):
        return [foam_exec, "blockMesh"], f"{foam_exec} blockMesh"
    return None
```

Copy packaged directory resources without assuming they are filesystem `Path` objects:

```python
def _copy_resource_tree(source, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        target = destination / child.name
        if child.is_dir():
            _copy_resource_tree(child, target)
        else:
            target.write_bytes(child.read_bytes())
```

`probe_openfoam` stages `data/openfoam/hello_cavity` into `artifacts/openfoam-hello` for project runs or a temporary directory otherwise, executes command with `cwd=work`, and requires `constant/polyMesh/points`. Return `broken` on nonzero process, timeout, OS error, or missing artifact. Return `missing` only when neither command form resolves.

End module with:

```python
COMPONENT_PROBES = {
    "calculix-hello-beam": probe_calculix,
    "freecad-hello-box": probe_freecad,
    "openfoam-block-mesh": probe_openfoam,
}
```

Replace `hello.py` temporarily with imports/re-exports needed by existing callers; Task 4 will add orchestration. Update `run.py` to import credits and resolver from `hello_probes.py`.

- [ ] **Step 5: Run probe tests**

Run:

```bash
pytest tests/test_hello.py tests/test_freecad_hello.py tests/test_openfoam_hello.py -q
```

Expected: all component probe tests pass.

- [ ] **Step 6: Commit normalized probes**

```bash
git add src/engineering_tools/hello.py src/engineering_tools/hello_probes.py src/engineering_tools/run.py tests/test_hello.py tests/test_freecad_hello.py tests/test_openfoam_hello.py
git commit -m "refactor: normalize component hello probes"
```

---

### Task 4: Make `hello` exhaustive, product-aware, persistable, and loggable

**Files:**

- Modify: `src/engineering_tools/hello.py`
- Modify: `src/engineering_tools/cli.py:46-69,166-169`
- Modify: `tests/test_hello.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_plm.py`

**Interfaces:**

- Consumes: `load_manifest`, `manifest_digest`, `load_installations`, `installation_for`, `write_hello_report`, `COMPONENT_PROBES`, `append_job`, and `touch_project`.
- Produces: `run_hello(project: str | Path | None = None, manifest_path: str | Path | None = None) -> dict[str, Any]`.
- Produces: `PRODUCT_PROBES: dict[str, Callable[[dict[str, dict[str, Any]]], dict[str, Any]]]`, initially empty because no mapping capability probe is complete.
- Report keys: `schema_version`, `ok`, `status`, `created`, `manifest_digest`, `git_revision`, `inventory_state`, `project`, `components`, `products`, and `counts`.
- Component result keys follow Task 3 plus `kind = "component"`.
- Product result keys: `kind`, `id`, `name`, `status`, `replacement`, `components`, `blocked_by`, and `message`.

- [ ] **Step 1: Write failing exhaustive-engine tests**

Extend `tests/test_hello.py` with a helper that writes a reduced manifest and installation receipts. Monkeypatch `engineering_tools.hello.COMPONENT_PROBES` with deterministic functions so orchestration is isolated from subprocess behavior.

Use exact helpers and scenarios:

```python
import json
from pathlib import Path

from engineering_tools.hello import run_hello
from engineering_tools.verification import hello_report_path


def reduced_manifest(
    *,
    inventory_state: str = "audited",
    mapping_probe_state: str = "probe-unimplemented",
) -> dict:
    audit_state = "audited" if inventory_state == "audited" else "provisional"
    components = []
    for component_id in ("first", "second"):
        components.append(
            {
                "id": component_id,
                "name": component_id.title(),
                "source": {
                    "state": "resolved",
                    "homepage": None,
                    "repository": None,
                    "identity": {
                        "type": "source",
                        "repository": f"https://example.test/{component_id}.git",
                        "commit": "0123456789abcdef",
                    },
                },
                "license": "MIT",
                "install_recipe": {"state": "implemented", "id": component_id},
                "execution": {"type": "binary", "locator": [component_id]},
                "probe": {"state": "implemented", "id": f"probe-{component_id}"},
                "expected_signal": {"kind": "exit-zero"},
                "attribution": "THIRD_PARTY.md",
            }
        )
    return {
        "schema_version": 1,
        "inventory_state": inventory_state,
        "inventory": [
            {
                "id": "closed-product",
                "name": "Closed Product",
                "portfolio": "Test",
                "granularity": "product",
                "audit_state": audit_state,
                "evidence": {"state": "audited", "source": "test"},
            }
        ],
        "components": components,
        "mappings": [
            {
                "id": "closed-product-to-open-solution",
                "inventory_id": "closed-product",
                "replacement": "Open Solution",
                "fit": "A",
                "components": ["first", "second"],
                "probe": {"state": mapping_probe_state, "id": "mapping-ok"},
                "expected_signal": {"kind": "capability"},
            }
        ],
    }


def write_reduced_manifest(tmp_path, **kwargs) -> Path:
    path = tmp_path / "stack.json"
    path.write_text(json.dumps(reduced_manifest(**kwargs)), encoding="utf-8")
    return path


def write_receipts(tmp_path, monkeypatch, *component_ids: str) -> None:
    state_home = tmp_path / "state"
    state_home.mkdir(exist_ok=True)
    monkeypatch.setenv("ETOOLS_HOME", str(state_home))
    receipts = {
        component_id: {
            "locator": f"/test/{component_id}",
            "immutable_id": "source:0123456789abcdef",
            "integrity_verified": True,
        }
        for component_id in component_ids
    }
    (state_home / "installations.json").write_text(
        json.dumps({"schema_version": 1, "components": receipts}),
        encoding="utf-8",
    )


def probe_result(component_id: str, status: str) -> dict:
    return {
        "id": component_id,
        "name": component_id.title(),
        "status": status,
        "message": status,
        "locator": f"/test/{component_id}",
        "workdir": None,
        "outputs": [],
        "credit": None,
        "returncode": 0 if status == "ok" else 1,
    }


def test_hello_evaluates_every_component_after_failure(tmp_path, monkeypatch) -> None:
    write_receipts(tmp_path, monkeypatch, "first", "second")
    called = []

    def first_probe(project=None):
        called.append("first")
        return probe_result("first", "broken")

    def second_probe(project=None):
        called.append("second")
        return probe_result("second", "ok")

    monkeypatch.setattr(
        "engineering_tools.hello.COMPONENT_PROBES",
        {"probe-first": first_probe, "probe-second": second_probe},
    )
    report = run_hello(manifest_path=write_reduced_manifest(tmp_path))
    assert called == ["first", "second"]
    assert report["ok"] is False
    assert report["counts"]["components"]["broken"] == 1
    assert report["counts"]["components"]["ok"] == 1


def test_component_ok_product_probe_unimplemented_stays_red(tmp_path, monkeypatch) -> None:
    write_receipts(tmp_path, monkeypatch, "first", "second")
    monkeypatch.setattr(
        "engineering_tools.hello.COMPONENT_PROBES",
        {
            "probe-first": lambda project=None: probe_result("first", "ok"),
            "probe-second": lambda project=None: probe_result("second", "ok"),
        },
    )
    report = run_hello(manifest_path=write_reduced_manifest(tmp_path))
    assert report["products"][0]["status"] == "probe-unimplemented"
    assert report["ok"] is False


def test_provisional_inventory_prevents_success(tmp_path, monkeypatch) -> None:
    write_receipts(tmp_path, monkeypatch, "first", "second")
    monkeypatch.setattr(
        "engineering_tools.hello.COMPONENT_PROBES",
        {
            "probe-first": lambda project=None: probe_result("first", "ok"),
            "probe-second": lambda project=None: probe_result("second", "ok"),
        },
    )
    monkeypatch.setattr(
        "engineering_tools.hello.PRODUCT_PROBES",
        {"mapping-ok": lambda results: {"status": "covered", "message": "covered"}},
    )
    path = write_reduced_manifest(
        tmp_path,
        inventory_state="provisional",
        mapping_probe_state="implemented",
    )
    report = run_hello(manifest_path=path)
    assert report["products"][0]["status"] == "covered"
    assert report["status"] == "inventory-unfrozen"
    assert report["ok"] is False


def test_missing_installation_is_reported_not_silently_skipped(tmp_path, monkeypatch) -> None:
    write_receipts(tmp_path, monkeypatch)
    monkeypatch.setattr("engineering_tools.hello.COMPONENT_PROBES", {})
    report = run_hello(manifest_path=write_reduced_manifest(tmp_path))
    assert [item["status"] for item in report["components"]] == ["missing", "missing"]
    assert report["ok"] is False


def test_hello_persists_manifest_digest(tmp_path, monkeypatch) -> None:
    write_receipts(tmp_path, monkeypatch)
    path = write_reduced_manifest(tmp_path)
    report = run_hello(manifest_path=path)
    persisted = json.loads(hello_report_path().read_text(encoding="utf-8"))
    assert persisted["manifest_digest"] == report["manifest_digest"]
    assert persisted["git_revision"] == report["git_revision"]
    assert persisted["components"] == report["components"]
    assert persisted["products"] == report["products"]
```

Add invalid-manifest case asserting all validation errors are included and no probes execute.

- [ ] **Step 2: Write failing CLI and project-log tests**

Update `tests/test_cli.py` so `main(["hello", "--json"])` emits only parseable JSON and returns `1` for packaged provisional manifest.

Update `tests/test_plm.py` to invoke reduced manifest through `run_hello`, then call the CLI logging helper directly if CLI does not expose `--manifest`. Assert one `jobs.jsonl` row for each component and product, including `missing` and `probe-unimplemented`, and assert registry timestamp is touched once after batch.

- [ ] **Step 3: Verify orchestration tests fail**

Run:

```bash
pytest tests/test_hello.py tests/test_cli.py tests/test_plm.py -q
```

Expected: failures because current engine returns one backend and current CLI prints mixed text/JSON.

- [ ] **Step 4: Implement exhaustive component evaluation**

In `hello.py`, add:

```python
SUCCESS_STATES = {"ok", "covered"}


def _unavailable_component(component: dict[str, Any], status: str, message: str) -> dict[str, Any]:
    return {
        "kind": "component",
        "id": component["id"],
        "name": component["name"],
        "status": status,
        "message": message,
        "locator": None,
        "workdir": None,
        "outputs": [],
        "credit": None,
        "returncode": None,
    }
```

Evaluation order follows manifest array order. For each component:

1. If `source.state != "resolved"`, report `invalid-pointer`.
2. If installation recipe is unresolved, retain `invalid-pointer` when source is invalid; otherwise report `unverified`.
3. If local receipt is absent, report `missing`.
4. If receipt has no verified immutable identity, report `unverified`.
5. If probe state is not implemented, report `probe-unimplemented`.
6. Resolve probe ID in `COMPONENT_PROBES`; unknown implemented ID is `invalid-manifest`.
7. Execute probe and append normalized result.

Continue evaluating all components after every result. Do not mutate manifest or installation receipt.

- [ ] **Step 5: Implement product aggregation without false coverage**

For each mapping, gather required component results. If any component is not `ok`, product result inherits a deterministic blocking state and lists every failing component ID in `blocked_by`. If all components pass but mapping probe state is not implemented, return `probe-unimplemented`. No product returns `covered` until a trusted mapping probe executes and returns a valid capability signal.

The first increment may define an empty `PRODUCT_PROBES` mapping. That is intentional: every product remains red, including SIMULIA CFD.

After evaluation, aggregate counts by status under separate `counts.components` and `counts.products` objects. Set:

```python
inventory_frozen = manifest["inventory_state"] == "audited" and all(
    item["audit_state"] == "audited" for item in manifest["inventory"]
)
all_covered = bool(products) and all(item["status"] == "covered" for item in products)
report["ok"] = inventory_frozen and all_covered
report["status"] = "covered" if report["ok"] else (
    "inventory-unfrozen" if not inventory_frozen else "incomplete"
)
```

Write report atomically before returning it.

Resolve `git_revision` best-effort with `git rev-parse HEAD` from the current checkout. Use `None` when running from an installed distribution or when Git is unavailable; report generation must never fail solely because revision discovery fails.

- [ ] **Step 6: Implement stable CLI rendering and per-result logging**

Change `_cmd_hello`:

- `--json` prints only `json.dumps(report, indent=2)`.
- Text output prints component section, product section, counts, report path, and final status.
- Return `0` only when `report["ok"]` is true; otherwise `1`.

Replace `_record_hello_job` with `_record_hello_jobs(project, report)`. Append component rows using `tool=f"component:{id}"`; append product rows using `tool=f"product:{id}"`; preserve exact result status. Call `touch_project(project)` once after all appends.

Update hello help to: `Verify every declared stack component and product mapping`.

- [ ] **Step 7: Run orchestration tests**

Run:

```bash
pytest tests/test_hello.py tests/test_cli.py tests/test_plm.py -q
```

Expected: all tests pass; packaged `hello --json` returns `1` with `inventory-unfrozen` or a more specific incomplete result, never `0`.

- [ ] **Step 8: Commit exhaustive hello**

```bash
git add src/engineering_tools/hello.py src/engineering_tools/cli.py tests/test_hello.py tests/test_cli.py tests/test_plm.py
git commit -m "feat: make hello an exhaustive stack ledger"
```

---

### Task 5: Add custom OpenFOAM `blockMesh` execution

**Files:**

- Modify: `src/engineering_tools/run.py`
- Modify: `src/engineering_tools/cli.py:131-147,202-244`
- Modify: `src/engineering_tools/run_cli.py:38-47`
- Modify: `tests/test_run.py`

**Interfaces:**

- Extends: `SUPPORTED_TOOLS` to `("calculix", "freecad", "openfoam")`.
- Extends: `run_deck(...)` so OpenFOAM accepts a case directory while existing tools keep file inputs.
- Produces same existing run-result dictionary and jobs schema.

- [ ] **Step 1: Add failing OpenFOAM run tests**

Append to `tests/test_run.py`:

```python
def _fake_block_mesh(tmp_path: Path, monkeypatch) -> None:
    fake_bin = tmp_path / "openfoam-bin"
    fake_bin.mkdir()
    block_mesh = fake_bin / "blockMesh"
    block_mesh.write_text(
        "#!/bin/sh\nmkdir -p constant/polyMesh\ntouch constant/polyMesh/points\n",
        encoding="utf-8",
    )
    block_mesh.chmod(0o755)
    monkeypatch.setenv("PATH", str(fake_bin) + os.pathsep + "/usr/bin:/bin")


def _openfoam_case(path: Path) -> Path:
    (path / "system").mkdir(parents=True)
    (path / "constant").mkdir()
    (path / "0").mkdir()
    (path / "system" / "controlDict").write_text("application icoFoam;\n", encoding="utf-8")
    return path


def test_run_openfoam_logs_mesh_artifact(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "etools-home"))
    _fake_block_mesh(tmp_path, monkeypatch)
    project = init_project(tmp_path / "foam-project")
    case = _openfoam_case(tmp_path / "case")
    code = main(["run", "openfoam", str(case), "--project", str(project)])
    assert code == 0
    job = read_jobs(project)[0]
    assert job["tool"] == "openfoam"
    assert job["status"] == "ok"
    assert any(path.endswith("constant/polyMesh/points") for path in job["outputs"])


def test_run_openfoam_rejects_case_without_system(tmp_path: Path, monkeypatch) -> None:
    project = init_project(tmp_path / "foam-project")
    case = tmp_path / "bad-case"
    case.mkdir()
    code = main(["run", "openfoam", str(case), "--project", str(project)])
    assert code == 2


def test_run_openfoam_missing_block_mesh_logs_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ETOOLS_HOME", str(tmp_path / "etools-home"))
    monkeypatch.setenv("PATH", "/nonexistent-etools-path")
    project = init_project(tmp_path / "foam-project")
    case = _openfoam_case(tmp_path / "case")
    code = main(["run", "--tool", "openfoam", "--input", str(case), "--project", str(project)])
    assert code == 1
    assert read_jobs(project)[0]["status"] == "fail"
```

- [ ] **Step 2: Verify OpenFOAM run tests fail**

Run:

```bash
pytest tests/test_run.py -q
```

Expected: argparse rejects `openfoam` and run layer rejects directory input.

- [ ] **Step 3: Implement directory-aware OpenFOAM run**

In `run.py`:

- Add `openfoam` to `SUPPORTED_TOOLS`.
- Validate CalculiX/FreeCAD inputs with `is_file()`; validate OpenFOAM with `is_dir()` and `(src / "system").is_dir()`.
- Use `shutil.copytree(src, work, dirs_exist_ok=True)` to stage case.
- Use `_openfoam_command()` from `hello_probes.py`.
- Execute command with `cwd=work`, existing 600-second timeout, captured text, and no shell.
- Collect every regular file under `constant/polyMesh/` as outputs, sorted by path.
- Return success only on process return code zero and presence of `constant/polyMesh/points`.
- Call existing `_log_and_touch` exactly once on every post-validation success/failure path.

Dispatch explicitly:

```python
if tool_key == "calculix":
    return _run_calculix(root, src, work, run_id, result)
if tool_key == "freecad":
    return _run_freecad(root, src, work, run_id, result)
return _run_openfoam(root, src, work, run_id, result)
```

Update CLI usage and help so both flag and positional forms list `openfoam`, and describe OpenFOAM input as case directory.

- [ ] **Step 4: Run run-layer tests**

Run:

```bash
pytest tests/test_run.py -q
```

Expected: all CalculiX, FreeCAD, and OpenFOAM run tests pass.

- [ ] **Step 5: Commit OpenFOAM custom run**

```bash
git add src/engineering_tools/run.py src/engineering_tools/run_cli.py src/engineering_tools/cli.py tests/test_run.py
git commit -m "feat: run OpenFOAM mesh cases"
```

---

### Task 6: Document release contract and add hosted orchestration CI

**Files:**

- Create: `.github/workflows/ci.yml`
- Modify: `README.md`
- Modify: `STRATEGY.md`
- Modify: `SOURCE_MAP.md`
- Modify: `src/engineering_tools/__init__.py:3`
- Modify: `pyproject.toml:7`

**Interfaces:**

- Consumes: final CLI behavior from Tasks 4 and 5.
- Produces: release metadata `0.4.0` and hosted test workflow.

- [ ] **Step 1: Add GitHub-hosted unit workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
  pull_request:

jobs:
  orchestration:
    runs-on: ubuntu-24.04
    strategy:
      matrix:
        python-version: ["3.10", "3.12"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: python -m pip install -e ".[dev]"
      - run: pytest -q
```

Do not run packaged `etools hello` as a passing hosted-CI gate: inventory is provisional and hosted runner is not reference installation. Unit tests assert intentional red state.

- [ ] **Step 2: Update human documentation**

Update README Quickstart:

```text
etools doctor          # discover execution locators
etools hello           # verify every declared component and product mapping; currently expected red
etools hello --json    # machine-readable completion ledger
etools run openfoam ./case --project ./my-part
```

Document result-state meanings and `~/.engineering-tools/hello-report.json`. State explicitly that `blockMesh` can make OpenFOAM component healthy but cannot cover SIMULIA CFD.

Update `STRATEGY.md` with exact boundary:

```text
ALPHA = completeness + installability + independent functional verification
BETA  = interoperability + workflow quality + system-level integration
```

State that inventory/map remains provisional pending independent audit before mass installation. Update `SOURCE_MAP.md` to point at packaged manifest and design spec; do not present old abbreviated table as complete canonical inventory.

- [ ] **Step 3: Bump package version**

Set both `pyproject.toml` project version and `src/engineering_tools/__init__.py` `__version__` to `0.4.0`.

- [ ] **Step 4: Run full verification**

Run:

```bash
pytest -q
python -m engineering_tools.cli --version
python -m engineering_tools.cli hello --json
```

Expected:

- Full pytest suite passes.
- Version output is `etools 0.4.0` or equivalent program-name prefix under module invocation.
- `hello --json` exits `1`, emits valid JSON, reports `inventory_state = "provisional"`, contains every component and product mapping, and writes `~/.engineering-tools/hello-report.json` unless `ETOOLS_HOME` is overridden for manual verification.

Avoid overwriting real user state during automated verification. For reproducible manual command use a temporary explicit value:

```bash
verification_home="$(mktemp -d)"
ETOOLS_HOME="$verification_home" python -m engineering_tools.cli hello --json
test "$?" -eq 1
```

- [ ] **Step 5: Inspect package contents**

Build a wheel using installed project tooling if available and inspect archive names. Verify `engineering_tools/data/stack.json` and every OpenFOAM case file appear. If `build` is unavailable, install no new dependency; use editable-resource tests as current limitation and report it.

- [ ] **Step 6: Commit docs and CI**

```bash
git add .github/workflows/ci.yml README.md STRATEGY.md SOURCE_MAP.md src/engineering_tools/__init__.py pyproject.toml
git commit -m "docs: define red alpha verification contract"
```

---

### Task 7: Final regression and contract audit

**Files:**

- Test: all files under `tests/`
- Inspect: all files changed by Tasks 1-6

**Interfaces:**

- Consumes: completed implementation.
- Produces: verified first increment with no additional feature work.

- [ ] **Step 1: Run full suite from clean process**

```bash
pytest -q
```

Expected: all tests pass with no test depending on actual workstation tools.

- [ ] **Step 2: Prove exhaustive behavior explicitly**

Run targeted tests:

```bash
pytest tests/test_manifest.py tests/test_verification.py tests/test_hello.py tests/test_openfoam_hello.py tests/test_run.py tests/test_plm.py -q
```

Expected: all targeted tests pass, including continuation after early failures and product-red-after-component-green behavior.

- [ ] **Step 3: Verify repository hygiene**

```bash
git status --short
git diff --check HEAD~6..HEAD
git ls-files | rg -i '\.(appimage|deb|rpm|iso|img|sif|squashfs|fcstd|frd)$'
```

Expected: clean status, no whitespace errors, and no tracked third-party or generated binary payloads. Owned fixture extensions already approved by project policy should be reviewed rather than blindly removed.

- [ ] **Step 4: Audit design traceability**

Confirm all acceptance criteria in `docs/superpowers/specs/2026-09-11-open-source-stack-manifest-hello-design.md` are either implemented by this increment or explicitly remain red by contract. Specifically verify:

- Inventory is complete as provisional input but not claimed audited.
- `inventory-unfrozen` prevents Alpha success.
- Every proprietary inventory ID has one mapping.
- Every mapping references real component IDs.
- All three implemented component probes run through manifest dispatch.
- SIMULIA CFD cannot become covered from `blockMesh`.
- Packaged default `hello` fails honestly.
- No reference-environment Alpha certification is claimed.

- [ ] **Step 5: Handle audit corrections through their owning task**

If final audit exposes a defect, return to Task 1-6 that owns it, add a regression test there, apply the smallest correction, rerun that task’s exact verification command, and use that task’s exact file-scoped commit step. If no correction is needed, create no empty commit.

## Definition of Done

- Provisional full map is represented in packaged machine-readable form.
- Manifest validation and exactly-one mapping invariant are enforced.
- `hello` reports every component and proprietary product mapping in text and JSON.
- Local report writes atomically and project runs log every result.
- CalculiX, FreeCAD, and OpenFOAM component probes share normalized semantics.
- OpenFOAM mesh check and custom `run` path pass controlled tests.
- SIMULIA CFD remains red until microscopic real-solver capability probe exists.
- Current default `hello` returns nonzero as expected.
- Hosted CI proves orchestration only; it makes no Alpha certification claim.
- Documentation and version metadata describe `0.4.0` behavior accurately.
- Full existing and new pytest suite passes.
