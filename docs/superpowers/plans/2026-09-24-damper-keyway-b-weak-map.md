# Damper B Weak-Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish damper-keyway B: store CFD `p` in Pa, compare traction in Pa, check CAD probes against params, and run a second CalculiX job with belt traction plus inner-wall loads from converted wall pressure.

**Architecture:** Keep A (CAD → `ccx solid` → icoFoam → A bands on pass-1 stress and **kinematic** center `p`). After that, `p_Pa = fluid_density_kg_m3 * p_kinematic`, write `solid-map.inp` (same C3D8 sandwich plus inward `*CLOAD` on the housing-ID node plane), run `ccx solid-map`, sample `fea_mapped`, evaluate four B relations. Not FSI; no Δσ floor.

**Tech Stack:** Python 3.10+ stdlib, pytest, packaged `data/damper/*`, existing FreeCADCmd / ccx / OpenFOAM locators. CI uses fake binaries.

## Global Constraints

- Pointer-repo stdlib runtime; no new third-party Python deps.
- CalculiX decks stay mm / N / MPa; mapped pressure in the deck is `p_Pa / 1e6` MPa.
- `cfd.p` is Pa; `cfd.p_kinematic` is the icoFoam number.
- `fluid_density_kg_m3` default **850** in `damper-params.json`.
- A `chamber_center_p.max_abs` applies only to **kinematic** center `p`.
- Two jobs: `solid` then `solid-map`. Pass 2 keeps belt `*CLOAD` and adds inner-wall loads.
- `weak-map` does not require `|σ_mapped − σ_pass1|` above a floor.
- Comments on modules for other agents. No MCP, GUI, FSI, Gmsh/SALOME tet of STEP.
- Work in `/Users/maxholden/engineering-tools/.worktrees/stack-manifest-hello` on `feat/damper-keyway-scenario`.
- After implementation: `python3 -m pytest -q` then Ubuntu `etools scenario damper-keyway`.
- Spec: `docs/superpowers/specs/2026-09-24-damper-keyway-b-weak-map-design.md`

## File map

| File | Responsibility |
| --- | --- |
| `src/engineering_tools/data/damper/damper-params.json` | Pin `fluid_density_kg_m3`. |
| `src/engineering_tools/damper_params.py` | `kinematic_to_pa`, `require_density`. |
| `src/engineering_tools/damper_relations.py` | Four relations including `fea_mapped`, `p_kinematic`, `weak-map`. |
| `src/engineering_tools/damper_fea.py` | `write_solid_map_inp`; inner-wall node ids. |
| `src/engineering_tools/damper_scenario.py` | CAD probe check; convert Pa; pass 2; `product-state` schema. |
| `tests/test_damper_scenario.py` | TDD for the above. |
| `README.md` | One-line scenario description. |

Do not split `damper_scenario.py` this plan.

---

### Task 1: Density pin and Pa conversion

**Files:**
- Modify: `src/engineering_tools/data/damper/damper-params.json`
- Modify: `src/engineering_tools/damper_params.py`
- Test: `tests/test_damper_scenario.py`

**Interfaces:**
- Consumes: `load_params()` object
- Produces: `kinematic_to_pa(p_kinematic: float, density_kg_m3: float) -> float`; `require_density(params: dict[str, Any]) -> float` raises `ValueError` if missing or not finite `> 0`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_damper_scenario.py`:

```python
from engineering_tools.damper_params import kinematic_to_pa, require_density


def test_packaged_params_include_fluid_density() -> None:
    assert load_params()["fluid_density_kg_m3"] == 850.0


def test_kinematic_to_pa_multiplies_density() -> None:
    assert kinematic_to_pa(0.067, 850.0) == 0.067 * 850.0


def test_require_density_rejects_missing() -> None:
    try:
        require_density({"housing_id_mm": 50.0})
    except ValueError as exc:
        assert "fluid_density_kg_m3" in str(exc)
    else:
        raise AssertionError("expected ValueError")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_damper_scenario.py::test_packaged_params_include_fluid_density tests/test_damper_scenario.py::test_kinematic_to_pa_multiplies_density tests/test_damper_scenario.py::test_require_density_rejects_missing -v`

Expected: FAIL (KeyError or import error)

- [ ] **Step 3: Write minimal implementation**

In `damper-params.json` add `"fluid_density_kg_m3": 850.0`.

In `damper_params.py` (comments for agents: conversion is the only CFD→Pa boundary):

```python
def require_density(params: dict[str, Any]) -> float:
    """Return pinned kg/m^3; missing or non-positive is a broken scenario pin."""
    raw = params.get("fluid_density_kg_m3")
    if not isinstance(raw, (int, float)) or not float(raw) > 0 or raw != raw:
        raise ValueError("fluid_density_kg_m3 must be a finite number > 0")
    return float(raw)


def kinematic_to_pa(p_kinematic: float, density_kg_m3: float) -> float:
    """icoFoam p is m^2/s^2; product-state cfd.p is Pa."""
    return float(p_kinematic) * float(density_kg_m3)
```

(`raw != raw` rejects NaN.)

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python3 -m pytest tests/test_damper_scenario.py::test_packaged_params_include_fluid_density tests/test_damper_scenario.py::test_kinematic_to_pa_multiplies_density tests/test_damper_scenario.py::test_require_density_rejects_missing -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/engineering_tools/data/damper/damper-params.json src/engineering_tools/damper_params.py tests/test_damper_scenario.py
git commit -m "feat: pin damper fluid density and convert icoFoam p to Pa"
```

---

### Task 2: B relations (coverage, Pa traction, weak-map)

**Files:**
- Modify: `src/engineering_tools/damper_relations.py`
- Modify: `tests/test_damper_scenario.py`

**Interfaces:**
- Consumes: `state_probes` with `fea`, `fea_mapped`, `cfd: {p, p_kinematic}`
- Produces: `evaluate_relations(*, probes, state_probes, belt_land_traction_mpa, mapped_deck_has_wall_cload: bool, mapped_frd_exists: bool) -> list[dict[str, Any]]` with ids `shared-frame`, `named-coverage`, `order-of-magnitude-traction`, `weak-map`

- [ ] **Step 1: Write the failing test**

Replace `test_relations_pass_when_frame_and_scalars_align` body so each solid row has `fea_mapped: {"von_mises": 12.1}` and each fluid `cfd` has `"p": 1000.0, "p_kinematic": 1000.0 / 850.0`. Call:

```python
    rows = evaluate_relations(
        probes=probes,
        state_probes=state,
        belt_land_traction_mpa=params["belt_land_traction_mpa"],
        mapped_deck_has_wall_cload=True,
        mapped_frd_exists=True,
    )
    assert {row["id"]: row["ok"] for row in rows} == {
        "shared-frame": True,
        "named-coverage": True,
        "order-of-magnitude-traction": True,
        "weak-map": True,
    }
```

Add:

```python
def test_relations_fail_when_cfd_p_is_kinematic_scale() -> None:
    params = load_params()
    probes = probes_from_params(params)
    state = {
        name: {
            "xyz_mm": list(xyz),
            "fea": {"von_mises": 12.0} if name in SOLID_PROBES else None,
            "fea_mapped": {"von_mises": 12.0} if name in SOLID_PROBES else None,
            "cfd": {"p": 0.067, "p_kinematic": 0.067} if name in FLUID_PROBES else None,
        }
        for name, xyz in probes.items()
    }
    rows = evaluate_relations(
        probes=probes,
        state_probes=state,
        belt_land_traction_mpa=2.0,
        mapped_deck_has_wall_cload=True,
        mapped_frd_exists=True,
    )
    assert next(r for r in rows if r["id"] == "order-of-magnitude-traction")["ok"] is False


def test_weak_map_fails_without_mapped_frd() -> None:
    params = load_params()
    probes = probes_from_params(params)
    state = {
        name: {
            "xyz_mm": list(xyz),
            "fea": {"von_mises": 12.0} if name in SOLID_PROBES else None,
            "fea_mapped": {"von_mises": 12.0} if name in SOLID_PROBES else None,
            "cfd": {"p": 1000.0, "p_kinematic": 1.0} if name in FLUID_PROBES else None,
        }
        for name, xyz in probes.items()
    }
    rows = evaluate_relations(
        probes=probes,
        state_probes=state,
        belt_land_traction_mpa=2.0,
        mapped_deck_has_wall_cload=True,
        mapped_frd_exists=False,
    )
    assert next(r for r in rows if r["id"] == "weak-map")["ok"] is False
```

Update `test_relations_fail_on_xyz_mismatch` to pass the two new kwargs (`True`, `True`) and include `fea_mapped` / `p_kinematic` so coverage is not the failure mode.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_damper_scenario.py::test_relations_pass_when_frame_and_scalars_align tests/test_damper_scenario.py::test_relations_fail_when_cfd_p_is_kinematic_scale tests/test_damper_scenario.py::test_weak_map_fails_without_mapped_frd -v`

Expected: FAIL (unexpected kwargs or missing `weak-map` / traction still true for 0.067)

- [ ] **Step 3: Write minimal implementation**

`evaluate_relations` in `damper_relations.py`:

```python
def evaluate_relations(
    *,
    probes: dict[str, list[float]],
    state_probes: dict[str, Any],
    belt_land_traction_mpa: float,
    mapped_deck_has_wall_cload: bool,
    mapped_frd_exists: bool,
) -> list[dict[str, Any]]:
    """B relations. wall cfd.p must already be Pa. Not FSI."""
```

Keep `shared-frame` as today (state `xyz_mm` vs `probes` dict).

`named-coverage`: for each `SOLID_PROBES`, finite `fea.von_mises` **and** `fea_mapped.von_mises`. For each `FLUID_PROBES`, finite `cfd.p` **and** `cfd.p_kinematic`.

`order-of-magnitude-traction`: `wall = chamber_wall cfd.p` (Pa); `traction_pa = abs(belt_land_traction_mpa) * 1e6`; `ratio = abs(wall) / traction_pa`; ok if `1e-6 <= ratio <= 1e6`.

`weak-map`: ok if `mapped_deck_has_wall_cload` and `mapped_frd_exists` and both `key_fillet` and `keyway_root` `fea_mapped.von_mises` are finite (Inf/NaN fail). Do not compare to pass 1.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python3 -m pytest tests/test_damper_scenario.py -q`

Expected: PASS (fix any other `evaluate_relations` call sites in this file)

- [ ] **Step 5: Commit**

```bash
git add src/engineering_tools/damper_relations.py tests/test_damper_scenario.py
git commit -m "feat: require Pa traction, mapped stresses, and weak-map relation"
```

---

### Task 3: `solid-map.inp` inner-wall CLOADs

**Files:**
- Modify: `src/engineering_tools/damper_fea.py`
- Modify: `tests/test_damper_scenario.py`

**Interfaces:**
- Consumes: `write_solid_inp(params, destination)`; `_radial_stations`; `_nid`
- Produces: `write_solid_map_inp(params: dict[str, Any], destination: Path, wall_p_pa: float) -> Path`; `mapped_deck_has_wall_cload(text: str) -> bool`

Inner-wall plane: `xs` from `_radial_stations`; `id_r = housing_id_mm/2`; `ix = xs.index(id_r)` (must be 2 with current stations). Four nodes `_nid(ix, iy, iz)`. Area `key_width_mm * key_length_mm`. Force each node: `-(wall_p_pa / 1e6) * area / 4.0` (direction **1**, negative = inward −X). Insert a comment line `** mapped chamber_wall Pa` immediately before those four `*CLOAD` lines.

- [ ] **Step 1: Write the failing test**

```python
from engineering_tools.damper_fea import mapped_deck_has_wall_cload, write_solid_map_inp


def test_write_solid_map_inp_adds_inward_wall_cload(tmp_path: Path) -> None:
    params = load_params()
    path = write_solid_map_inp(params, tmp_path / "solid-map.inp", wall_p_pa=56.0)
    text = path.read_text(encoding="utf-8")
    belt = write_solid_inp(params, tmp_path / "solid.inp").read_text(encoding="utf-8")
    assert "*CLOAD" in text
    assert ", 2, " in text
    assert "** mapped chamber_wall Pa" in text
    assert mapped_deck_has_wall_cload(text) is True
    assert mapped_deck_has_wall_cload(belt) is False
    assert text.count("*NODE") == belt.count("*NODE")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_damper_scenario.py::test_write_solid_map_inp_adds_inward_wall_cload -v`

Expected: FAIL import / missing marker

- [ ] **Step 3: Write minimal implementation**

```python
def mapped_deck_has_wall_cload(text: str) -> bool:
    """True when the pass-2 marker comment is present (agents: do not rely on force magnitude)."""
    return "** mapped chamber_wall Pa" in text


def write_solid_map_inp(params: dict[str, Any], destination: Path, wall_p_pa: float) -> Path:
    """Pass-1 deck plus inward CLOAD on housing-ID nodes from wall_p_pa."""
    write_solid_inp(params, destination)
    text = destination.read_text(encoding="utf-8")
    xs, _ys, _zs = _radial_stations(params)
    id_r = float(params["housing_id_mm"]) / 2.0
    ix = xs.index(id_r)
    area = float(params["key_width_mm"]) * float(params["key_length_mm"])
    force = -(float(wall_p_pa) / 1e6) * area / 4.0
    extra = ["** mapped chamber_wall Pa"] + [f"{_nid(ix, iy, iz)}, 1, {force}" for iy in range(2) for iz in range(2)]
    needle = "*CLOAD\n"
    at = text.index(needle) + len(needle)
    # Skip existing belt CLOAD lines until *NODE FILE
    node_file = text.index("*NODE FILE", at)
    destination.write_text(text[:node_file] + "\n".join(extra) + "\n" + text[node_file:], encoding="utf-8")
    return destination
```

If `xs.index` raises, that is a programmer error (stations drifted from housing ID).

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python3 -m pytest tests/test_damper_scenario.py::test_write_solid_map_inp_adds_inward_wall_cload tests/test_damper_scenario.py::test_write_solid_inp_contains_c3d8_and_cload -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/engineering_tools/damper_fea.py tests/test_damper_scenario.py
git commit -m "feat: write solid-map deck with inner-wall pressure CLOADs"
```

---

### Task 4: Orchestrator — CAD frame, Pa fields, pass 2

**Files:**
- Modify: `src/engineering_tools/damper_scenario.py`
- Modify: `tests/test_damper_scenario.py`
- Modify: `README.md` (fold: one sentence that pass 2 maps wall Pa)

**Interfaces:**
- Consumes: `require_density`, `kinematic_to_pa`, `write_solid_map_inp`, `mapped_deck_has_wall_cload`, `sample_frd_von_mises`, `evaluate_relations` new kwargs
- Produces: artifacts `solid-map.inp`, `solid-map.frd`; `product-state` with `coupling`, `fluid_density_kg_m3`, `fea_mapped`, `cfd.p` / `cfd.p_kinematic`; report `a_ok`, `b_ok`, `chamber_p` (Pa), `p_kinematic`

A bands: keep using **kinematic** `chamber_p` variable for `max_abs` **before** conversion (rename local `p_kin_center` / `p_kin_wall` if needed so Pa is not band-checked).

CAD: do **not** write `probes.json` before FreeCAD. After CAD files exist, if `probes.json` missing → `broken`. Load JSON; for each `REQUIRED_PROBES` compare `list(map(float, cad[name]))` to `probes_from_params`; mismatch → `broken` with `xyz mismatch`. Set `probes` from the CAD file (agreed list). Import `REQUIRED_PROBES`.

After icoFoam: `rho = require_density(params)` in try/except → `broken` with that message. `p_kin_center` / `p_kin_wall` from existing cell indices. Apply A `max_abs` to `p_kin_center` only. Then `p_center_pa = kinematic_to_pa(p_kin_center, rho)` and same for wall.

Pass 2: `write_solid_map_inp(params, out / "solid-map.inp", wall_p_pa=p_wall_pa)`; `ccx solid-map`; require `solid-map.frd`; `von_map_2 = sample_frd_von_mises(...)`. Finite mapped key stresses required for `weak-map` (relations), not A `> 0` bands on pass 2.

State rows: solids get `fea` from pass 1 and `fea_mapped` from pass 2, `cfd` null. Fluids get `fea`/`fea_mapped` null and `cfd: {p: pa, p_kinematic: kin}`.

`evaluate_relations(..., mapped_deck_has_wall_cload=mapped_deck_has_wall_cload(map_inp.read_text()), mapped_frd_exists=map_frd.is_file())`.

`product_state` adds `"coupling": "weak-map"` and `"fluid_density_kg_m3": rho`.

Report: `b_ok` = all relations ok; `chamber_p` = wall or center Pa (spec: `chamber_p` (Pa) — use **center** Pa for A narrative plus `wall_p_pa`; include `p_kinematic` as center kinematic); pass-2 keys `key_fillet_mapped`, `keyway_root_mapped`.

Fake FreeCADCmd must write `probes.json`. Helper:

```python
def _fake_cad_script(probes_path: Path) -> str:
    return f"cp '{probes_path}' probes.json\ntouch damper.FCStd solid.step fluid.step\nexit 0\n"
```

In each `run_damper_keyway` test, write `tmp_path / "probes.json"` from `json.dumps(probes_from_params(load_params()))` and point the fake at it.

Fake `ccx`: today `cp seed solid.frd`. Change to copy seed onto **both** `solid.frd` and `solid-map.frd` (same stresses is allowed; no Δσ floor):

```sh
cp 'SEED' solid.frd
cp 'SEED' solid-map.frd
printf 'Mises  15.5\n' > solid.dat
exit 0
```

Fake `icoFoam` uniform kinematic `p` of `2.0` keeps A band (`<= 50`) and `850 * 2 / 2e6` traction in band.

`test_run_damper_keyway_ok_with_fakes`: assert `result["report"]["b_ok"] is True` and `result["ok"] is True`.

`test_run_damper_keyway_fails_when_cad_probes_mismatch`: fake writes probes all `[0,0,0]`; assert `ok is False` and `"xyz"` in message.

`test_run_damper_keyway_fails_without_pass2_frd`: fake ccx writes only `solid.frd` (not `solid-map.frd`); assert `ok is False`.

Keep existing zero-stress / A-band / missing-`p` tests; update their FreeCADCmd to write valid probes so they still fail on the intended gate.

- [ ] **Step 1: Write the failing tests** (ok-with-fakes `b_ok`, CAD mismatch, missing pass-2 frd) using the helpers above.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_damper_scenario.py::test_run_damper_keyway_ok_with_fakes tests/test_damper_scenario.py::test_run_damper_keyway_fails_when_cad_probes_mismatch tests/test_damper_scenario.py::test_run_damper_keyway_fails_without_pass2_frd -v`

Expected: FAIL (`b_ok` missing or CAD still overwrites)

- [ ] **Step 3: Implement `run_damper_keyway` as specified in this task**

Wire imports; CAD probe check; kinematic A band; Pa conversion; `ccx solid-map`; state/relations/report. Comment at CAD: do not overwrite CAD probes.json if it matches params.

README: scenario line mentions CAD FEA CFD plus mapped wall Pa on a second ccx job.

- [ ] **Step 4: Run the tests and make sure they pass**

Run: `python3 -m pytest tests/test_damper_scenario.py -q && python3 -m pytest -q`

Expected: all PASS (120+ tests)

- [ ] **Step 5: Commit**

```bash
git add src/engineering_tools/damper_scenario.py tests/test_damper_scenario.py README.md
git commit -m "feat: map chamber wall Pa into a second CalculiX damper job"
```

---

### Task 5: Ubuntu reference (not GitHub Actions)

**Files:** none in git unless pass-2 explodes (then only then edit `a-bands.json` — do not add pass-2 bands unless runaway)

- [ ] **Step 1: Install and run on the Ubuntu host**

```bash
ssh -i "$HOME/.ssh/orchestration_vm_ed25519" agent@172.16.170.128 'export PATH="/home/agent/engineering-tools/.venv/bin:/home/agent/.local/etools-bin:$PATH"
cd ~/engineering-tools
git fetch origin feat/damper-keyway-scenario
git reset --hard origin/feat/damper-keyway-scenario
.venv/bin/pip install -e . -q
etools scenario damper-keyway --project /home/agent/damper-scenario-a --json'
```

Expected: `"ok": true`, `"a_ok": true`, `"b_ok": true`, four relations true, `cfd.p` ≈ `850 * p_kinematic`.

- [ ] **Step 2: If ok is false, fix in this branch with a new failing pytest then a commit. If ok is true, no extra commit.**

---

## Spec coverage

| Spec item | Task |
| --- | --- |
| Density 850, `p_Pa = rho * p_kin` | 1 |
| Traction in Pa, band `[1e-6, 1e6]` | 2 |
| named-coverage fea + fea_mapped + p + p_kinematic | 2 |
| weak-map deck marker, frd, finite mapped keys, no Δσ floor | 2, 3, 4 |
| Two ccx jobs, belt + inward wall CLOAD, MPa scaling | 3, 4 |
| shared-frame CAD vs params | 4 |
| A bands kinematic only | 4 |
| product-state coupling, density, schema | 4 |
| CI fakes / negatives | 2, 4 |
| Ubuntu | 5 |
| Out of scope FSI/MCP/GUI/tet/scale p | none (do not implement) |

## Placeholder scan

No TBD. `evaluate_relations` kwargs named in Task 2 and used in Task 4. `write_solid_map_inp(params, destination, wall_p_pa)` named in Task 3 and used in Task 4.
