# C Contract + Damper C-FSI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a thin C orchestration façade and the first vertical: `etools scenario damper-keyway --coupling c` (alias `--fsi`) runs true partitioned FSI through that façade without mutating A/B.

**Architecture:** Scenario code never launches preCICE. After A/B succeeds, freeze an immutable snapshot, register C participants, generate preCICE config from C policy, run separate CalculiX + moving-mesh OpenFOAM workdirs, persist a session artifact, and gate on residual, fixture motion floor, and B-relative abs+rel parity.

**Tech Stack:** Python 3.10+ stdlib, pytest, packaged damper JSON, existing `ccx` / OpenFOAM locators, external `precice` + `pimpleFoam` on PATH for live C. CI uses fake binaries.

## Global Constraints

- Pointer-repo stdlib runtime; no new third-party Python dependencies.
- A/B solver paths must not change meaning when `--coupling c` is set; C uses separate workdirs.
- preCICE XML is generated from C policy, never the source of truth.
- Frame = CAD origin/orientation; C quantities are SI; mm→m at adapters.
- Canonical probe IDs (not solver node ids): `housing.wall.pressure`, `key.root.von_mises`, `housing.wall.displacement`, `housing.wall.traction`.
- Status: `ok` / `missing` / `broken`; A/B fail with C requested → C not evaluated (`prerequisite_not_ok`), not a fake C miss/break.
- Unknown `--coupling` token → `broken`. No reserved unimplemented CLI tokens yet.
- `--fsi` ≡ `--coupling c`; conflicting flags → `broken`.
- Ubuntu first `--coupling c` success is calibration only; freeze bands with provenance; a later run is acceptance.
- Comments on every new module for other agents. No MCP, 3DX GUI, tet of STEP, solids4Foam, checkpoint/multirate implementation.
- Specs: `docs/superpowers/specs/2026-09-25-c-orchestration-design.md`, `docs/superpowers/specs/2026-09-25-c-fsi-damper-design.md`.
- After implementation: `python3 -m pytest -q`. Live FSI only on Ubuntu when binaries exist.

## File map

| File | Responsibility |
| --- | --- |
| `src/engineering_tools/c_cli.py` | Normalize `--coupling` / `--fsi` into a request or `broken`. |
| `src/engineering_tools/c_contract.py` | Session dict helpers, capability table, SI/frame, fail-closed unavailable ops. |
| `src/engineering_tools/c_snapshot.py` | Copy A/B artifacts; digest; refuse in-place mutation. |
| `src/engineering_tools/c_parity.py` | Abs+rel compare; load packaged C-FSI bands. |
| `src/engineering_tools/c_backend_precice.py` | `generate_precice_config(policy) -> str`; locate `precice`. |
| `src/engineering_tools/c_fsi_meshes.py` | Params-driven C solid deck + moving-mesh foam case sharing housing ID wall. |
| `src/engineering_tools/c_adapter_calculix.py` | Resolve probes on C solid; invoke `ccx` in C workdir. |
| `src/engineering_tools/c_adapter_openfoam.py` | Resolve probes on C fluid; invoke `pimpleFoam` (not A `icoFoam`). |
| `src/engineering_tools/c_facade.py` | Register, advance, reconcile, write `c-session.json`. |
| `src/engineering_tools/data/damper/c-fsi-bands.json` | Motion floor, geometric tolerance, parity abs/rel, calibration note. |
| `src/engineering_tools/damper_scenario.py` | After A/B ok, optional C; never spawn preCICE here. |
| `src/engineering_tools/cli.py` | Flags; pass coupling into `run_damper_keyway`. |
| `tests/test_c_contract.py` | Contract, snapshot, parity, backend XML, CLI normalize. |
| `tests/test_c_fsi.py` | Fake C-FSI session artifact + negatives. |
| `tests/test_cli.py` | `--fsi` / `--coupling` semantics. |
| `README.md` | One extra scenario line. |

Do not put preCICE launch in `damper_scenario.py`. Do not edit A `icoFoam` / `solid.inp` writers for C physics.

---

### Task 1: Coupling CLI request

**Files:**
- Create: `src/engineering_tools/c_cli.py`
- Modify: `src/engineering_tools/cli.py`
- Test: `tests/test_c_contract.py`

**Interfaces:**
- Consumes: argparse strings
- Produces: `CouplingRequest` with fields `token: str | None`, `status: str | None`, `detail: str` where `status` is `None` when default (no C), `"ok"` when token is `c`, `"broken"` when invalid

- [ ] **Step 1: Write the failing test**

Create `tests/test_c_contract.py`:

```python
from engineering_tools.c_cli import parse_coupling_flags


def test_default_is_no_coupling() -> None:
    req = parse_coupling_flags(coupling=None, fsi=False)
    assert req.token is None
    assert req.status is None


def test_fsi_alias_is_c() -> None:
    assert parse_coupling_flags(coupling=None, fsi=True).token == "c"
    assert parse_coupling_flags(coupling="c", fsi=False).token == "c"
    assert parse_coupling_flags(coupling="c", fsi=True).token == "c"


def test_unknown_coupling_is_broken() -> None:
    req = parse_coupling_flags(coupling="thermal", fsi=False)
    assert req.status == "broken"
    assert req.token is None


def test_conflicting_flags_are_broken() -> None:
    req = parse_coupling_flags(coupling="c", fsi=True)
    # --fsi with --coupling c is not a conflict
    assert req.token == "c"
    bad = parse_coupling_flags(coupling="nope", fsi=True)
    assert bad.status == "broken"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_c_contract.py::test_default_is_no_coupling tests/test_c_contract.py::test_fsi_alias_is_c tests/test_c_contract.py::test_unknown_coupling_is_broken tests/test_c_contract.py::test_conflicting_flags_are_broken -v`

Expected: FAIL (module not found)

- [ ] **Step 3: Write minimal implementation**

`c_cli.py` — comments for agents: this module only normalizes flags; it does not run C.

```python
"""Normalize scenario --coupling / --fsi. Comments for other agents: unknown tokens are broken, not missing."""

from __future__ import annotations

from dataclasses import dataclass


IMPLEMENTED = frozenset({"c"})


@dataclass(frozen=True)
class CouplingRequest:
    token: str | None
    status: str | None
    detail: str


def parse_coupling_flags(*, coupling: str | None, fsi: bool) -> CouplingRequest:
    if fsi and coupling is not None and coupling != "c":
        return CouplingRequest(None, "broken", "conflicting --fsi and --coupling")
    token = "c" if fsi or coupling == "c" else coupling
    if token is None:
        return CouplingRequest(None, None, "c not requested")
    if token not in IMPLEMENTED:
        return CouplingRequest(None, "broken", f"unknown coupling: {token}")
    return CouplingRequest("c", "ok", "coupling c")
```

In `build_parser` scenario parser add:

```python
scenario.add_argument("--coupling", default=None, help="C analysis depth (c)")
scenario.add_argument("--fsi", action="store_true", help="Alias for --coupling c")
```

In `_cmd_scenario`, if parse status is `broken`, print detail, return 1 without running A/B **only when the request itself is invalid**. Invalid flags fail before A/B.

```python
from .c_cli import parse_coupling_flags
req = parse_coupling_flags(coupling=getattr(args, "coupling", None), fsi=bool(getattr(args, "fsi", False)))
if req.status == "broken":
    print(req.detail, file=sys.stderr)
    return 1
result = run_damper_keyway(root, coupling=req.token)
```

Change `run_damper_keyway` signature in this task to `run_damper_keyway(project, coupling: str | None = None)` and ignore `coupling` until Task 7 (kwargs must not crash existing callers).

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_c_contract.py tests/test_cli.py tests/test_damper_scenario.py -q`

Expected: PASS (existing scenario tests omit new flags)

- [ ] **Step 5: Commit**

```bash
git add src/engineering_tools/c_cli.py src/engineering_tools/cli.py src/engineering_tools/damper_scenario.py tests/test_c_contract.py
git commit -m "feat: parse --coupling c and --fsi without changing A/B"
```

---

### Task 2: C contract types and unavailable capabilities

**Files:**
- Create: `src/engineering_tools/c_contract.py`
- Test: `tests/test_c_contract.py`

**Interfaces:**
- Consumes: none
- Produces: `CAPABILITIES: dict[str, str]` values `"implemented"` or `"unavailable"`; `request_capability(name: str) -> dict` with `status` `ok`|`missing`|`broken`; `mm_to_m(xyz_mm: list[float]) -> list[float]`; `new_session(*, scenario: str, backend: str) -> dict`

- [ ] **Step 1: Write the failing test**

```python
from engineering_tools.c_contract import mm_to_m, new_session, request_capability


def test_mm_to_m_keeps_three_components() -> None:
    assert mm_to_m([25.0, 0.0, 0.0]) == [0.025, 0.0, 0.0]


def test_new_session_records_backend_and_empty_steps() -> None:
    session = new_session(scenario="damper-keyway", backend="precice")
    assert session["backend"] == "precice"
    assert session["steps"] == []
    assert session["evaluated"] is True


def test_unavailable_capability_is_missing() -> None:
    row = request_capability("checkpoint")
    assert row["status"] == "missing"


def test_unknown_capability_is_broken() -> None:
    row = request_capability("not-a-c-op")
    assert row["status"] == "broken"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_c_contract.py::test_mm_to_m_keeps_three_components tests/test_c_contract.py::test_unavailable_capability_is_missing -v`

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

`c_contract.py` — comments: frame identity is CAD; this module never stores mm in C field values.

```python
"""C orchestration contract helpers. Comments for other agents: unavailable names are missing; unknown names are broken."""

from __future__ import annotations

from typing import Any

CAPABILITIES: dict[str, str] = {
    "session": "implemented",
    "precice": "implemented",
    "checkpoint": "unavailable",
    "rollback": "unavailable",
    "multirate": "unavailable",
    "thermal": "unavailable",
    "cad-in-loop": "unavailable",
    "meshing-adapter": "unavailable",
    "assemblies": "unavailable",
}

CAD_FRAME_ID = "damper-cad"


def mm_to_m(xyz_mm: list[float]) -> list[float]:
    return [float(xyz_mm[0]) / 1000.0, float(xyz_mm[1]) / 1000.0, float(xyz_mm[2]) / 1000.0]


def request_capability(name: str) -> dict[str, Any]:
    state = CAPABILITIES.get(name)
    if state is None:
        return {"status": "broken", "detail": f"unknown capability: {name}"}
    if state == "unavailable":
        return {"status": "missing", "detail": f"specified/unavailable: {name}"}
    return {"status": "ok", "detail": name}


def new_session(*, scenario: str, backend: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "scenario": scenario,
        "backend": backend,
        "frame_id": CAD_FRAME_ID,
        "evaluated": True,
        "status": "ok",
        "participants": [],
        "interfaces": [],
        "probes": {},
        "parity": [],
        "snapshot_digest": None,
        "steps": [],
        "c_ok": False,
    }
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_c_contract.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/engineering_tools/c_contract.py tests/test_c_contract.py
git commit -m "feat: add C session helpers and fail-closed capabilities"
```

---

### Task 3: Immutable A/B snapshot

**Files:**
- Create: `src/engineering_tools/c_snapshot.py`
- Test: `tests/test_c_contract.py`

**Interfaces:**
- Consumes: paths to `product-state.json` and `scenario-report.json`
- Produces: `freeze_ab_snapshot(src: Path, dest: Path) -> str` SHA-256 of canonical listing; copying must not alter `src`

- [ ] **Step 1: Write the failing test**

```python
import json
from pathlib import Path

from engineering_tools.c_snapshot import freeze_ab_snapshot


def test_freeze_ab_snapshot_copies_and_digests(tmp_path: Path) -> None:
    src = tmp_path / "ab"
    src.mkdir()
    (src / "product-state.json").write_text('{"coupling":"weak-map"}\n', encoding="utf-8")
    (src / "scenario-report.json").write_text('{"a_ok":true,"b_ok":true}\n', encoding="utf-8")
    dest = tmp_path / "snap"
    digest = freeze_ab_snapshot(src, dest)
    assert len(digest) == 64
    assert (dest / "product-state.json").read_text(encoding="utf-8") == (src / "product-state.json").read_text(encoding="utf-8")
    (dest / "product-state.json").write_text("mutated", encoding="utf-8")
    assert (src / "product-state.json").read_text(encoding="utf-8") == '{"coupling":"weak-map"}\n'
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_c_contract.py::test_freeze_ab_snapshot_copies_and_digests -v`

Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

Copy `product-state.json` and `scenario-report.json` with `shutil.copy2`. Digest = sha256 of `product-state.json` bytes + newline + `scenario-report.json` bytes (document in comment). Raise `FileNotFoundError` if either source file is missing (caller maps to C `broken`).

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_c_contract.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/engineering_tools/c_snapshot.py tests/test_c_contract.py
git commit -m "feat: freeze immutable A/B snapshots for C parity"
```

---

### Task 4: Parity formula and packaged C-FSI bands

**Files:**
- Create: `src/engineering_tools/c_parity.py`
- Create: `src/engineering_tools/data/damper/c-fsi-bands.json`
- Test: `tests/test_c_contract.py`

**Interfaces:**
- Consumes: packaged bands JSON
- Produces: `load_c_fsi_bands() -> dict`; `in_band(c: float, b: float, abs_tol: float, rel_tol: float) -> bool` true iff `abs(c-b) <= abs_tol + rel_tol * abs(b)`; `mpa_to_pa(mpa: float) -> float`

- [ ] **Step 1: Write the failing test**

```python
from engineering_tools.c_parity import in_band, load_c_fsi_bands, mpa_to_pa


def test_in_band_abs_rel() -> None:
    assert in_band(10.0, 10.0, 0.0, 0.0) is True
    assert in_band(12.0, 10.0, 1.0, 0.0) is False
    assert in_band(12.0, 10.0, 1.0, 0.2) is True


def test_mpa_to_pa() -> None:
    assert mpa_to_pa(2.0) == 2.0e6


def test_packaged_c_fsi_bands_have_required_keys() -> None:
    bands = load_c_fsi_bands()
    assert bands["motion_floor_m"] > 0
    assert "housing.wall.pressure" in bands["parity"]
    assert bands["parity"]["housing.wall.pressure"]["abs"] >= 0
```

Packaged JSON for CI (wide until Ubuntu calibration; `calibration` explains that):

```json
{
  "calibration": "CI placeholder. Not Ubuntu acceptance. Freeze after a calibration run, then require a second clean Ubuntu --coupling c.",
  "motion_floor_m": 1e-12,
  "geometric_tolerance_m": 0.002,
  "n_steps": 2,
  "parity": {
    "housing.wall.pressure": {"abs": 1e9, "rel": 1e6},
    "key.root.von_mises": {"abs": 1e9, "rel": 1e6},
    "housing.wall.traction": {"abs": 1e9, "rel": 1e6}
  }
}
```

Do **not** include `housing.wall.displacement` in `parity` (motion floor only, per spec).

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_c_contract.py::test_in_band_abs_rel tests/test_c_contract.py::test_packaged_c_fsi_bands_have_required_keys -v`

Expected: FAIL

- [ ] **Step 3: Implement `c_parity.py` using `importlib.resources` like `load_a_bands`**

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_c_contract.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/engineering_tools/c_parity.py src/engineering_tools/data/damper/c-fsi-bands.json tests/test_c_contract.py
git commit -m "feat: add C-FSI abs-rel parity bands fixture"
```

---

### Task 5: preCICE config is generated from C policy

**Files:**
- Create: `src/engineering_tools/c_backend_precice.py`
- Test: `tests/test_c_contract.py`

**Interfaces:**
- Consumes: policy dict
- Produces: `default_policy() -> dict`; `generate_precice_config(policy: dict) -> str`; `find_precice() -> Path | None` via shutil.which `precice` **or** `precice-tools` — use `shutil.which("preciceAdapter")` is wrong. Spec: binary named `precice` missing → C missing. Locate with `shutil.which("precice")`; if absent, also try `which("binprecice")` only if documented. **Pin: `shutil.which("precice")` only** so missing is deterministic in CI.

Policy keys: `participants` list `[{"name":"Solid","solver":"calculix"},{"name":"Fluid","solver":"openfoam"}]`, `mesh_name` `"interface"`, `read_by_fluid` `"Displacement"`, `read_by_solid` `"Traction"`, `time_window` float, `max_iterations` int.

Generated XML **must** contain participant names from policy and must **not** be read back as policy. Test writes XML to a temp file then asserts `generate_precice_config` is independent of that file (delete file, generate again, same string).

- [ ] **Step 1: Write the failing test**

```python
from engineering_tools.c_backend_precice import default_policy, generate_precice_config


def test_generated_xml_uses_policy_names_not_a_checked_in_file() -> None:
    policy = default_policy()
    xml = generate_precice_config(policy)
    assert "<participant name=\"Solid\">" in xml or 'name="Solid"' in xml
    assert "Displacement" in xml
    assert "Traction" in xml
    policy["participants"][0]["name"] = "Steel"
    xml2 = generate_precice_config(policy)
    assert "Steel" in xml2
    assert "Steel" not in xml
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_c_contract.py::test_generated_xml_uses_policy_names_not_a_checked_in_file -v`

Expected: FAIL

- [ ] **Step 3: Implement a small XML string builder** (no lxml). Comment: this file is the preCICE **backend**, not C.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_c_contract.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/engineering_tools/c_backend_precice.py tests/test_c_contract.py
git commit -m "feat: generate preCICE XML from C coupling policy"
```

---

### Task 6: C-FSI meshes and probe resolution

**Files:**
- Create: `src/engineering_tools/c_fsi_meshes.py`
- Test: `tests/test_c_fsi.py`

**Interfaces:**
- Consumes: `load_params()`, `probes_from_params`, `mm_to_m`
- Produces: `write_c_solid_inp(params, path: Path) -> None`; `write_c_fluid_case(params, case: Path) -> None`; `canonical_xyz_m(params) -> dict[str, list[float]]` mapping the four C IDs; `interface_node_ids()` documented in comments

Geometry: C solid is a single layer of C3D8 through the housing wall at `x = housing_id_mm/2` (shared wall). C fluid `blockMesh` box from `-housing_id/2` to `+housing_id/2` in mm converted to metres in `blockMeshDict`, lid optional; **moving wall is the +X (or −X matching `chamber_wall`) patch named `interface`**. Do not reuse `write_chamber_case` from A (that is the static cavity).

`canonical_xyz_m`:
- `housing.wall.pressure` / `displacement` / `traction` ← `chamber_wall` mm
- `key.root.von_mises` ← `keyway_root` mm

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path

from engineering_tools.c_fsi_meshes import canonical_xyz_m, write_c_fluid_case, write_c_solid_inp
from engineering_tools.damper_params import load_params


def test_canonical_xyz_matches_params_in_metres() -> None:
    params = load_params()
    xyz = canonical_xyz_m(params)
    wall = xyz["housing.wall.pressure"]
    assert wall[0] == pytest.approx(-float(params["housing_id_mm"]) / 2000.0)


def test_c_solid_and_fluid_share_interface_name(tmp_path: Path) -> None:
    params = load_params()
    write_c_solid_inp(params, tmp_path / "c-solid.inp")
    write_c_fluid_case(params, tmp_path / "c-foam")
    inp = (tmp_path / "c-solid.inp").read_text(encoding="utf-8")
    foam = (tmp_path / "c-foam" / "constant" / "polyMesh" / "blockMeshDict").read_text(encoding="utf-8")
    assert "interface" in inp.lower() or "INTERFACE" in inp
    assert "interface" in foam
```

Add `import pytest` in that test file.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_c_fsi.py::test_canonical_xyz_matches_params_in_metres -v`

Expected: FAIL

- [ ] **Step 3: Implement writers** (minimal hex + blockMeshDict with patch `interface`). Comment: independent of A cavity and B sandwich.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_c_fsi.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/engineering_tools/c_fsi_meshes.py tests/test_c_fsi.py
git commit -m "feat: write params-driven C-FSI solid and moving-mesh fluid pair"
```

---

### Task 7: Façade run + scenario wire + persisted session

**Files:**
- Create: `src/engineering_tools/c_facade.py`
- Create: `src/engineering_tools/c_adapter_calculix.py`
- Create: `src/engineering_tools/c_adapter_openfoam.py`
- Modify: `src/engineering_tools/damper_scenario.py`
- Modify: `tests/test_c_fsi.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_damper_scenario.py` (A/B fail with coupling: C not evaluated)
- Modify: `README.md`

**Interfaces:**
- Consumes: Task 1–6
- Produces: `run_c_fsi(*, ab_dir: Path, out: Path, params: dict) -> dict` returning the session dict written to `out/c-session.json`; `run_damper_keyway(..., coupling=None)`

`run_c_fsi` algorithm:

1. If `find_precice()` is None or `_openfoam_tool("pimpleFoam")` is None or `ccx` missing → session `status=missing`, `evaluated=True`, `c_ok=False` (C **was** attempted; deps absent).
2. `freeze_ab_snapshot(ab_dir, out / "ab-snapshot")`.
3. `new_session`; register participants Solid/Fluid; `generate_precice_config` write `out/precice-config.xml`.
4. `write_c_solid_inp` / `write_c_fluid_case` under `out/c-solid` and `out/c-fluid`.
5. Launch order owned by façade: for `n_steps` from bands: run backend participant scripts **only from adapters**:
   - `c_adapter_calculix.run_step(workdir, step)`
   - `c_adapter_openfoam.run_step(workdir, step)`
   - `c_backend_precice.run_step(config_path, step)` which for CI fake `precice` is `subprocess.run(["precice", str(config_path)])` expecting exit 0
6. Each step append `{ "index": i, "converged": True }` if all three exit 0; else `status=broken`, stop.
7. Adapters must write probe samples into `workdir/c-probes.json` as SI floats. Fakes in tests write this file. Motion: `housing.wall.displacement` magnitude ≥ `motion_floor_m` else `broken`.
8. Load A/B `product-state.json` from **snapshot** only. B wall Pa = `probes.chamber_wall.cfd.p`. B key root MPa = `probes.keyway_root.fea_mapped.von_mises` then `mpa_to_pa`. Traction B = `abs(wall Pa)`. Compare C probes with `in_band`. Displacement has no parity row.
9. Geometric check: adapter may write `resolved_xyz_m`; façade checks vs `canonical_xyz_m` with `geometric_tolerance_m`.
10. Write `c-session.json` with status, backend `precice`, steps, probes, parity rows, snapshot_digest, `c_ok`.

`damper_scenario.py`: after A/B would return success, if `coupling == "c"`: call `run_c_fsi(ab_dir=out, out=out/"c-fsi", params=params)`. Merge into report: `c_ok`, `c` session summary. Exit 0 only if A/B and `c_ok`. If A/B failed earlier, return that report plus `"c": {"evaluated": false, "reason": "prerequisite_not_ok"}` and do not create `c-session.json`.

If `parse` already returned broken, CLI never calls run.

**Default A/B tests** must still pass without `precice` on PATH.

**Fake C test** (`test_c_fsi.py`): PATH with `precice`, `pimpleFoam`, `ccx` extras that:

- `precice`: exit 0
- `pimpleFoam`: write `c-probes.json` in C fluid workdir — façade should read probes from a **single** `out/c-probes.json` the façade writes after adapters return dicts. Simpler: adapters return probe dicts; fakes implemented as functions in tests by monkeypatching `c_adapter_calculix.run_step` to return SI probes. **Prefer monkeypatch adapters** so we do not depend on fake OpenFOAM writing JSON.

Plan for CI: `run_c_fsi` calls `sample_c_probes(out) -> dict` functions in adapters. Tests monkeypatch those to return:

```python
{
  "housing.wall.pressure": {"value": 56.62, "xyz_m": canonical["housing.wall.pressure"]},
  "key.root.von_mises": {"value": 10.07e6, "xyz_m": canonical["key.root.von_mises"]},
  "housing.wall.displacement": {"value": 1e-6, "xyz_m": canonical["housing.wall.displacement"]},
  "housing.wall.traction": {"value": 56.62, "xyz_m": canonical["housing.wall.traction"]},
}
```

and freeze snapshot from a minimal A/B product-state matching those B values.

Assert persisted `c-session.json`:

- `status`, `c_ok` True
- `len(steps)==n_steps` all `converged`
- canonical probe IDs + SI values
- parity rows all `ok`
- `snapshot_digest` 64 chars
- `backend == "precice"`

Negatives:

- no `precice` → `missing`
- monkeypatch `run_step` backend return False → `broken`
- displacement `0` → `broken`
- parity out of band (C pressure 1e20) → `broken`
- `run_damper_keyway` with coupling c and missing FreeCADCmd → `c.evaluated is False`

Grep test: `damper_scenario.py` must not contain the string `precice` except comments forbidding it — **zero subprocess to precice**. Enforce with:

```python
def test_scenario_module_does_not_spawn_precice() -> None:
    text = Path("src/engineering_tools/damper_scenario.py").read_text(encoding="utf-8")
    assert "precice" not in text.lower()
```

CLI test: `main(["scenario", "damper-keyway", "--fsi", "--project", ...])` with fakes including precice/pimpleFoam; or unit-test `parse_coupling_flags` already done — add `main(["scenario", "damper-keyway", "--coupling", "nope", "--project", p])` returns 1 without needing CAD.

README: document `etools scenario damper-keyway --coupling c`.

- [ ] **Step 1: Write failing tests listed above in `tests/test_c_fsi.py` and CLI unknown coupling**

- [ ] **Step 2: Run to verify fail**

Run: `python3 -m pytest tests/test_c_fsi.py tests/test_cli.py::test_unknown_coupling_exits_before_scenario -v`

Expected: FAIL

- [ ] **Step 3: Implement façade, adapters, scenario branch, README**

Adapter `run_step` for live Ubuntu: `ccx` on C deck; `blockMesh`+`pimpleFoam` in C case with `dynamicMeshDict` (velocityLaplacian or `displacementLaplacian`; keep dict minimal). If live solvers cannot yet sample probes, adapters parse FRD / `p` like A/B **in SI**. Displacement from FRD DISP if present; if CalculiX static has near-zero u, **do not fake motion in production** — the live deck must include a nonzero interface u (e.g. apply B wall Pa as *DLOAD so the wall moves a tiny amount). Comment the deck. If Ubuntu first run motion is below floor, that is calibration data: **lower floor only in a follow-up commit with provenance**, never by skipping the check.

- [ ] **Step 4: Run**

Run: `python3 -m pytest -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/engineering_tools/c_facade.py src/engineering_tools/c_adapter_calculix.py src/engineering_tools/c_adapter_openfoam.py src/engineering_tools/damper_scenario.py src/engineering_tools/cli.py tests/test_c_fsi.py tests/test_cli.py tests/test_damper_scenario.py README.md
git commit -m "feat: run damper C-FSI through the C facade"
```

---

### Task 8: Reviewer locks

**Files:** same as Task 7 if tests missed artifact keys

- [ ] **Step 1: Add a single integration test that loads `c-session.json` keys exactly:** `status`, `steps`, `probes`, `parity`, `snapshot_digest`, `backend`, `c_ok`

- [ ] **Step 2: Run `python3 -m pytest tests/test_c_fsi.py -q`**

Expected: PASS

- [ ] **Step 3: Confirm `rg precice src/engineering_tools/damper_scenario.py` is empty**

- [ ] **Step 4: Commit if anything changed**

```bash
git commit -m "test: persist full C-FSI session artifact fields"
```

Ubuntu (not CI, not this task's pytest):

1. `etools scenario damper-keyway` still A/B green.
2. `etools scenario damper-keyway --coupling c` — if deps missing, C `missing`.
3. First green FSI run is **calibration**; commit `c-fsi-bands.json` with calibration SHA and date; run **again** for acceptance.

---

## Self-review (plan vs spec)

| Spec item | Task |
| --- | --- |
| Two specs; façade only C I/O for scenario | 7 (`precice` not in damper_scenario) |
| Adapters may call solvers | 7 |
| Immutable A/B snapshot | 3, 7 |
| C policy → generated XML | 5 |
| Frame vs SI | 2 `mm_to_m`, 6 canonical xyz |
| Canonical probe IDs | 4, 6, 7 |
| `--coupling c` / `--fsi` | 1, 7 |
| missing vs broken vs not evaluated | 1, 2, 7 |
| Separate C fluid/solid | 6, 7 |
| Short transient N steps | 4 bands `n_steps`, 7 |
| B-relative abs+rel; no A kinematic bands | 4, 7 |
| Motion floor fixture-specific | 4, 7 |
| Displacement not B-parity | 4 |
| CLI unknown broken | 1, 7 |
| Unavailable capability missing | 2 |
| Artifact fields | 7, 8 |
| Calibration vs acceptance | 4 JSON note, Task 8 Ubuntu |
| No tet, no MCP, no OS | Global constraints |
