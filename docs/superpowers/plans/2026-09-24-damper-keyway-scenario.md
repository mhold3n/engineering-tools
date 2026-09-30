# Damper Keyway Scenario Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `etools scenario damper-keyway`: headless parametric CAD, independent CalculiX and OpenFOAM solves, and named point-value relations in one product-state file.

**Architecture:** Shared `damper-params.json` drives probe coordinates, a FreeCADCmd script, a one-element CalculiX deck, and a short OpenFOAM chamber case. An orchestrator writes artifacts under the project, evaluates A (files + finite nonzero stress and finite pressure) and B (shared-frame, named-coverage, traction order-of-magnitude), and logs `jobs.jsonl`. CI uses fake binaries; no MCP.

**Tech Stack:** Python 3.10+ stdlib, pytest, packaged data under `src/engineering_tools/data/damper/`, existing FreeCADCmd / ccx / OpenFOAM locators.

## Global Constraints

- Reference platform is Ubuntu 24.04 LTS on x86-64.
- Runtime remains standard-library-only; add no dependency.
- Third-party source, binaries, archives, images, installed trees, and generated engineering data stay outside Git.
- Approach A this sprint: sequential CAD then independent FEA and CFD; solvers do not exchange fields.
- Approach B this sprint: point-value relations in `product-state.json` only; not FSI, not mesh motion, not live continuity.
- Approach C is out of scope.
- MCP is out of scope.
- 3DEXPERIENCE GUI is out of scope.
- Mesh this sprint: shared parameters drive CAD solids and solver decks; do not tet-mesh STEP with Gmsh/SALOME.
- Toy parametric damper (mm); not a production viscous-damper drawing.
- CLI: `etools scenario damper-keyway [--project DIR] [--json]`.
- Implement behavior test-first. Preserve unrelated user changes.

**Origin:** `docs/superpowers/specs/2026-09-24-damper-keyway-scenario-design.md`

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `src/engineering_tools/data/damper/damper-params.json` | Pinned dimensions and belt-land traction. |
| `src/engineering_tools/data/damper/build_damper.py` | Headless FreeCAD script: solids, STEP, FCStd, `probes.json`. |
| `src/engineering_tools/damper_params.py` | Load params, digest, probe XYZ, required names. |
| `src/engineering_tools/damper_relations.py` | B relations: shared-frame, named-coverage, traction ratio. |
| `src/engineering_tools/damper_fea.py` | Write CalculiX `.inp` from params; parse stress from `.dat`/`.frd`. |
| `src/engineering_tools/damper_cfd.py` | Write short OpenFOAM chamber case; parse `p`. |
| `src/engineering_tools/damper_scenario.py` | Orchestrate CAD + FEA + CFD + B; write reports. |
| `src/engineering_tools/cli.py` | `scenario` subcommand. |
| `pyproject.toml` | Package `data/damper/*`. |
| `tests/test_damper_scenario.py` | Params, relations, fake-tool orchestration, negatives. |
| `README.md` | Document `etools scenario damper-keyway`. |

---

### Task 1: Params, probes, digest

**Files:**
- Create: `src/engineering_tools/data/damper/damper-params.json`
- Create: `src/engineering_tools/damper_params.py`
- Test: `tests/test_damper_scenario.py`
- Modify: `pyproject.toml` (add `"data/damper/*"` to `tool.setuptools.package-data.engineering_tools`)

**Interfaces:**
- Consumes: nothing
- Produces: `REQUIRED_PROBES: tuple[str, ...]`, `SOLID_PROBES`, `FLUID_PROBES`, `load_params() -> dict[str, Any]`, `params_digest(params: dict[str, Any]) -> str`, `probes_from_params(params: dict[str, Any]) -> dict[str, list[float]]`

- [ ] **Step 1: Write the failing test**

```python
from engineering_tools.damper_params import (
    FLUID_PROBES,
    REQUIRED_PROBES,
    SOLID_PROBES,
    load_params,
    params_digest,
    probes_from_params,
)


def test_packaged_params_define_required_probes() -> None:
    params = load_params()
    probes = probes_from_params(params)
    assert set(REQUIRED_PROBES) <= set(probes)
    assert set(SOLID_PROBES) == {"key_fillet", "keyway_root", "belt_land"}
    assert set(FLUID_PROBES) == {"chamber_center", "chamber_wall"}
    for xyz in probes.values():
        assert len(xyz) == 3
        assert all(isinstance(v, float) for v in xyz)
    assert len(params_digest(params)) == 64
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_damper_scenario.py::test_packaged_params_define_required_probes -v`

Expected: FAIL with `ModuleNotFoundError: damper_params`

- [ ] **Step 3: Write minimal implementation**

`damper-params.json`:

```json
{
  "units": {"length": "mm", "force": "N", "stress": "MPa", "pressure": "Pa"},
  "housing_od_mm": 80.0,
  "housing_id_mm": 50.0,
  "length_mm": 60.0,
  "shaft_od_mm": 20.0,
  "key_width_mm": 6.0,
  "key_height_mm": 6.0,
  "key_length_mm": 20.0,
  "chamber_length_mm": 40.0,
  "belt_land_traction_mpa": 2.0,
  "youngs_mpa": 210000.0,
  "poisson": 0.3
}
```

`damper_params.py`: load via `importlib.resources.files("engineering_tools") / "data" / "damper" / "damper-params.json"`. Probe XYZ from params (housing axis +Z through origin): `key_fillet` at shaft OD on +X; `keyway_root` at housing ID on +X; `belt_land` at housing OD on +X; `chamber_center` at origin; `chamber_wall` at housing ID on +X, z=0. Digest = sha256 of canonical `json.dumps(params, sort_keys=True, separators=(",", ":"))`.

Add `"data/damper/*"` to package-data.

- [ ] **Step 4: Run the test and make sure it passes**

Run: `pytest tests/test_damper_scenario.py::test_packaged_params_define_required_probes -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/engineering_tools/data/damper/damper-params.json src/engineering_tools/damper_params.py tests/test_damper_scenario.py pyproject.toml
git commit -m "feat: pin damper scenario params and probe frame"
```

---

### Task 2: B relation checks

**Files:**
- Create: `src/engineering_tools/damper_relations.py`
- Test: `tests/test_damper_scenario.py`

**Interfaces:**
- Consumes: `REQUIRED_PROBES`, `SOLID_PROBES`, `FLUID_PROBES` from `damper_params`
- Produces: `evaluate_relations(*, probes: dict[str, list[float]], state_probes: dict[str, Any], belt_land_traction_mpa: float) -> list[dict[str, Any]]` where each item is `{"id": str, "ok": bool, "detail": str}` with ids `shared-frame`, `named-coverage`, `order-of-magnitude-traction`

- [ ] **Step 1: Write the failing tests**

```python
from engineering_tools.damper_params import load_params, probes_from_params
from engineering_tools.damper_relations import evaluate_relations


def test_relations_pass_when_frame_and_scalars_align() -> None:
    params = load_params()
    probes = probes_from_params(params)
    state = {
        name: {
            "xyz_mm": list(xyz),
            "fea": {"von_mises": 12.0} if name in {"key_fillet", "keyway_root", "belt_land"} else None,
            "cfd": {"p": 1000.0} if name in {"chamber_center", "chamber_wall"} else None,
        }
        for name, xyz in probes.items()
    }
    rows = evaluate_relations(
        probes=probes,
        state_probes=state,
        belt_land_traction_mpa=params["belt_land_traction_mpa"],
    )
    assert {row["id"]: row["ok"] for row in rows} == {
        "shared-frame": True,
        "named-coverage": True,
        "order-of-magnitude-traction": True,
    }


def test_relations_fail_on_xyz_mismatch() -> None:
    params = load_params()
    probes = probes_from_params(params)
    state = {
        name: {"xyz_mm": [0.0, 0.0, 0.0], "fea": {"von_mises": 1.0}, "cfd": {"p": 1.0}}
        for name in probes
    }
    rows = evaluate_relations(probes=probes, state_probes=state, belt_land_traction_mpa=2.0)
    assert next(row for row in rows if row["id"] == "shared-frame")["ok"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_damper_scenario.py::test_relations_pass_when_frame_and_scalars_align tests/test_damper_scenario.py::test_relations_fail_on_xyz_mismatch -v`

Expected: FAIL with `ModuleNotFoundError: damper_relations`

- [ ] **Step 3: Write minimal implementation**

`shared-frame`: each `state_probes[name]["xyz_mm"]` equals `probes[name]` (float equality). `named-coverage`: every `SOLID_PROBES` name has `fea.von_mises` that is a finite `float`; every `FLUID_PROBES` name has `cfd.p` that is a finite `float`. `order-of-magnitude-traction`: `p_wall = abs(state_probes["chamber_wall"]["cfd"]["p"])`, `t = abs(belt_land_traction_mpa) * 1e6` (MPa→Pa), `ratio = p_wall / t` if `t` else fail; `ok` if `1e-6 <= ratio <= 1e6`.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `pytest tests/test_damper_scenario.py::test_relations_pass_when_frame_and_scalars_align tests/test_damper_scenario.py::test_relations_fail_on_xyz_mismatch -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/engineering_tools/damper_relations.py tests/test_damper_scenario.py
git commit -m "feat: compare damper probe frames and scalar coverage"
```

---

### Task 3: CalculiX deck and stress parse

**Files:**
- Create: `src/engineering_tools/damper_fea.py`
- Test: `tests/test_damper_scenario.py`

**Interfaces:**
- Consumes: `load_params()` values `belt_land_traction_mpa`, `youngs_mpa`, `poisson`
- Produces: `write_solid_inp(params: dict[str, Any], destination: Path) -> Path`, `parse_von_mises(dat_text: str) -> float`

Reuse the hello_beam C3D8 brick (10×1×1 mm) with `*CLOAD` on nodes 2,3,6,7 of `belt_land_traction_mpa * 25` N each (same pattern as hello_beam 25 N). One element: assign the parsed Mises to both `key_fillet` and `keyway_root`. Parse `.dat` for the first `SXX`/`Mises` number: if the file contains `Mises`, take the last float on that line; else take the maximum absolute float on lines containing `SXX`.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
from engineering_tools.damper_fea import parse_von_mises, write_solid_inp
from engineering_tools.damper_params import load_params


def test_write_solid_inp_contains_c3d8_and_cload(tmp_path: Path) -> None:
    path = write_solid_inp(load_params(), tmp_path / "solid.inp")
    text = path.read_text(encoding="utf-8")
    assert "*ELEMENT, TYPE=C3D8" in text
    assert "*CLOAD" in text


def test_parse_von_mises_reads_dat_sample() -> None:
    sample = " forces\n SXX,SYY,SZZ\n  12.0  0.1  0.1\n Mises  15.5\n"
    assert parse_von_mises(sample) == 15.5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_damper_scenario.py::test_write_solid_inp_contains_c3d8_and_cload tests/test_damper_scenario.py::test_parse_von_mises_reads_dat_sample -v`

Expected: FAIL `damper_fea`

- [ ] **Step 3: Implement `write_solid_inp` and `parse_von_mises` as specified**

- [ ] **Step 4: Run the tests and make sure they pass**

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/engineering_tools/damper_fea.py tests/test_damper_scenario.py
git commit -m "feat: generate damper CalculiX deck from params"
```

---

### Task 4: OpenFOAM chamber case and pressure parse

**Files:**
- Create: `src/engineering_tools/damper_cfd.py`
- Test: `tests/test_damper_scenario.py`

**Interfaces:**
- Consumes: `chamber_length_mm`, `housing_id_mm` from params
- Produces: `write_chamber_case(params: dict[str, Any], work: Path) -> None` (writes `system/controlDict`, `system/blockMeshDict`, `system/fvSchemes`, `system/fvSolution`, `constant/transportProperties`, `constant/turbulenceProperties`, `0/U`, `0/p`), `parse_internal_field_p(text: str) -> float` (first uniform or first scalar after `internalField`)

Copy the hello_cavity file set from `engineering_tools/data/openfoam/hello_cavity` via the same `_copy_resource_tree` pattern as `hello_probes.probe_openfoam`, then set `controlDict` `endTime` to `0.1` (already packaged). Do not retune fv schemes in this task. `parse_internal_field_p`: if `internalField uniform X;` parse `X`; else fail with `ValueError`.

- [ ] **Step 1: Write the failing test**

```python
from pathlib import Path
from engineering_tools.damper_cfd import parse_internal_field_p, write_chamber_case
from engineering_tools.damper_params import load_params


def test_write_chamber_case_has_control_dict(tmp_path: Path) -> None:
    work = tmp_path / "foam"
    write_chamber_case(load_params(), work)
    assert (work / "system" / "controlDict").is_file()
    assert (work / "0" / "p").is_file()


def test_parse_internal_field_p_uniform() -> None:
    assert parse_internal_field_p("internalField uniform 101325;\n") == 101325.0
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: FAIL `damper_cfd`

- [ ] **Step 3: Implement copy + parsers**

- [ ] **Step 4: Run the tests and make sure they pass**

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/engineering_tools/damper_cfd.py tests/test_damper_scenario.py
git commit -m "feat: stage damper chamber OpenFOAM case from params"
```

---

### Task 5: FreeCAD build script

**Files:**
- Create: `src/engineering_tools/data/damper/build_damper.py`
- Modify: `src/engineering_tools/damper_scenario.py` (CAD step only if Task 6 not started; otherwise wait — implement CAD runner inside Task 6). For this task only the script plus a test that the script file is packaged and mentions `Part`.

**Interfaces:**
- Consumes: params JSON path argv1, output directory argv2
- Produces: `damper.FCStd`, `solid.step`, `fluid.step`, `probes.json` when run under FreeCADCmd

Script (FreeCAD Python): read params JSON; fuse housing tube (OD/ID cylinder difference), shaft cylinder, key box at +X; cut keyway from housing; export fused solid STEP; export chamber cylinder as fluid STEP; write `probes.json` using the same XYZ formulas as `probes_from_params` (duplicate numbers in the FreeCAD script comments pointing at `damper_params.py` — orchestrator **overwrites** `probes.json` after CAD using `probes_from_params` so B shared-frame cannot drift). If FreeCAD import fails when the file is exec'd by CPython in pytest, do not import this module from pytest.

- [ ] **Step 1: Write the failing test**

```python
from importlib import resources


def test_build_damper_script_is_packaged() -> None:
    text = (resources.files("engineering_tools") / "data" / "damper" / "build_damper.py").read_text(encoding="utf-8")
    assert "import Part" in text
    assert "solid.step" in text
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL file missing

- [ ] **Step 3: Write `build_damper.py` as specified (argv: params.json outdir)**

- [ ] **Step 4: Run the test and make sure it passes**

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/engineering_tools/data/damper/build_damper.py tests/test_damper_scenario.py
git commit -m "feat: add headless FreeCAD damper builder script"
```

---

### Task 6: Orchestrator, CLI, fake-tool pytest, README

**Files:**
- Create: `src/engineering_tools/damper_scenario.py`
- Modify: `src/engineering_tools/cli.py` (add `scenario` subparser after `run`, `_cmd_scenario`)
- Modify: `README.md` (document the command)
- Test: `tests/test_damper_scenario.py`

**Interfaces:**
- Consumes: all Task 1–5 functions; `append_job`; `init_project` / `is_project`
- Produces: `run_damper_keyway(project: str | Path) -> dict[str, Any]` with keys `ok: bool`, `status: str` (`ok` | `missing` | `broken` | `capability-failed`), `message: str`, `workdir: str`, `outputs: list[str]`, `report: dict`

Orchestrator algorithm:

1. `out = Path(project)/"artifacts"/"scenario-damper-keyway"`; mkdir; copy packaged params to `out/damper-params.json`.
2. CAD: `shutil.which("FreeCADCmd")` or `freecad`; if missing return `status=missing`. Run `[cmd, str(script), str(params_copy), str(out)]` timeout 180. Require `damper.FCStd`, `solid.step`, `fluid.step`. Overwrite `probes.json` from `probes_from_params`.
3. FEA: `write_solid_inp` → `ccx` job name `solid` in `out`; timeout 180; require `solid.frd` or `solid.dat`; `von = parse_von_mises(dat)`; if not finite or `von <= 0` → `broken`.
4. CFD: `write_chamber_case` into `out/foam`; reuse `hello_probes._run_openfoam` + `_openfoam_tool("blockMesh")` then `icoFoam`; find first `*/p` whose parent is not `0`; parse `p`; if not finite → `broken`.
5. Build `product-state.json` (`schema_version` 1, `scenario` `damper-keyway`, `params_digest`, probes with xyz + fea/cfd as spec). `evaluate_relations`. If any relation not `ok` → `capability-failed`.
6. Write `scenario-report.json` `{ok, status, message, relations, von_mises, chamber_p}`. Return `ok=True` only if all pass.

CLI: require project like `etools run`. `append_job(..., tool="damper-keyway", command="scenario", status=...)`. `--json` prints the report dict. Exit 0 iff `ok`.

Fake-tool test: PATH with `FreeCADCmd` that `touch`es the three CAD files; `ccx` that writes `solid.dat` containing `Mises  15.5` and `solid.frd`; `blockMesh` that writes `constant/polyMesh/points`; `icoFoam` that writes `0.1/p` with `internalField uniform 101325;`. `init_project` then `run_damper_keyway`. Assert `ok is True` and B relations all true.

Negative: icoFoam writes empty `0.1/p` → not ok.

- [ ] **Step 1: Write fake-tool tests first (they fail)**

- [ ] **Step 2: Run pytest on those tests — expect fail**

- [ ] **Step 3: Implement orchestrator + CLI + README**

- [ ] **Step 4: `pytest tests/test_damper_scenario.py -v` and full `pytest -q`**

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/engineering_tools/damper_scenario.py src/engineering_tools/cli.py README.md tests/test_damper_scenario.py
git commit -m "feat: run damper-keyway CAD FEA CFD scenario from etools"
```

---

## Spec coverage

| Spec section | Task |
| --- | --- |
| Params + probes + artifacts layout | 1, 5, 6 |
| A CAD / FEA / CFD | 3, 4, 5, 6 |
| B relations | 2, 6 |
| CLI + jobs | 6 |
| CI fakes + negatives | 6 |
| Ubuntu real run / freeze numeric bands | Not a code task; operator after merge |
| MCP, GUI, FSI, Gmsh | Explicitly omitted |

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-24-damper-keyway-scenario.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
