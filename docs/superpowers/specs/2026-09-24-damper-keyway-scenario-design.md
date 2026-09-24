# Damper keyway scenario — sequential CAD + FEA + CFD

Created: 2026-09-24  
Status: Approved for implementation  
Depends on: pointer-repo hello green; OpenFOAM icoFoam component probe; CalculiX hello_beam; FreeCADCmd hello_box

## Purpose

Replace “each tool exists” with one **headless product scenario**: build a hydraulic fluid damper from parameters, apply belt torque on the housing, and analyze **key/keyway stress** and **internal fluid** without a human in CAD and without a 3DEXPERIENCE GUI.

This sprint delivers **approach A** (two independent solves after one CAD product representation) plus a **B baseline**: compare named point values in one product-state file as a short-term stand-in for live coupling.

## Decisions

| Topic | Decision |
| --- | --- |
| Pass bar this sprint | A: sequential CAD → CalculiX solid + OpenFOAM fluid |
| B in this sprint | Baseline only: relation of solutions/state at named probes, not FSI |
| C | Out of scope (two-way mesh motion / dynamic continuity) |
| CAD | Headless FreeCADCmd from a first-party script; no GUI |
| MCP | Out of scope; later project wrapping this CLI |
| Geometry fidelity | Toy parametric damper, not a production viscous-damper drawing |
| Mesh this sprint | Shared parameters drive CAD solids **and** solver decks; do not require Gmsh/SALOME tet meshing of STEP |
| CLI | `etools scenario damper-keyway` |
| 3DEXPERIENCE GUI | Out of scope |

## Product representation

Source of truth is packaged `damper-params.json` (mm, N, MPa, kg, s as declared in-file).

The scenario writes, under `<project>/artifacts/scenario-damper-keyway/`:

| File | Role |
| --- | --- |
| `damper-params.json` | Copy of the pin used for this run |
| `damper.FCStd` | FreeCAD document |
| `solid.step` | Housing + shaft + key (product solid) |
| `fluid.step` | Internal chamber solid (boolean void) |
| `probes.json` | Named points in the same frame as the CAD model |
| `solid.inp` / CalculiX outputs | Structural job |
| OpenFOAM case + `p`/`U` | Fluid job |
| `product-state.json` | A results + B point-value relations |
| `scenario-report.json` | Pass/fail ledger for pytest and `etools` |

Required probe names (coordinates computed from params, not picked in a GUI):

- `key_fillet` — solid, key/shaft interface
- `keyway_root` — solid, housing keyway
- `belt_land` — solid, outer belt contact
- `chamber_center` — fluid
- `chamber_wall` — fluid, inner housing wall adjacent to the chamber

Geometry (minimum): cylindrical housing, coaxial shaft, rectangular key in a matching keyway, belt land on the housing OD, internal cylindrical chamber. Units mm.

## Approach A — independent solves

### CAD

Run FreeCADCmd on the packaged script with params path and output directory. Fail if any of `damper.FCStd`, `solid.step`, `fluid.step`, `probes.json` is missing or a required probe name is absent.

### CalculiX (key / keyway / belt torque)

Generate a small `.inp` from the **same** params (C3D8 or equivalent coarse brick model is enough). Represent belt torque as a tangential surface traction on the belt land. Boundary: shaft axis held. Require `*.frd` (or equivalent written field). Extract von Mises (or equivalent stress) at `key_fillet` and `keyway_root`.

A fails if: ccx missing; nonzero exit; no field file; NaN/Inf stress; stress at both key probes is exactly zero.

Declared band (A): both key stresses finite and `> 0`. After the first Ubuntu reference run, freeze numeric upper bounds in the fixture so regressions cannot silently explode.

### OpenFOAM (chamber fluid)

Stage a short laminar/viscous case whose block dimensions match the chamber params (same spirit as hello cavity: short `endTime`, written `p` and `U`). Fail if no written `p` with `internalField`, or `chamber_center` pressure is NaN/Inf.

Declared band (A): `p` at `chamber_center` finite. Freeze a numeric band after the first Ubuntu reference run.

Solves do not exchange fields during A.

## Approach B baseline — point-value relations

`product-state.json` schema (all present or B fails):

```json
{
  "schema_version": 1,
  "scenario": "damper-keyway",
  "params_digest": "<sha256 of damper-params.json>",
  "probes": {
    "key_fillet": {"xyz_mm": [0, 0, 0], "fea": {"von_mises": 0.0}, "cfd": null},
    "chamber_center": {"xyz_mm": [0, 0, 0], "fea": null, "cfd": {"p": 0.0}}
  },
  "relations": [
    {"id": "shared-frame", "ok": true, "detail": "..."}
  ]
}
```

Relations required this sprint:

1. **shared-frame** — every probe `xyz_mm` in `product-state.json` equals `probes.json` (exact float match from the same writer).
2. **named-coverage** — solid probes have `fea` scalars; fluid probes have `cfd` scalars; no required name missing.
3. **order-of-magnitude traction** — `|p|` at `chamber_wall` vs belt-land traction magnitude from params: ratio in `[1e-6, 1e6]` (finite, same unit system declared). This is **not** equilibrium; it only proves both states were recorded in one product representation.

B does not move the mesh, does not iterate in time between solvers, and does not claim FSI.

## CLI and jobs

```text
etools scenario damper-keyway [--project DIR] [--json]
```

- Requires a project (`etools init` or `--project`).
- Prepends `ETOOLS_HOME/bin` like other commands.
- Appends `jobs.jsonl` (`command: scenario`, tool `damper-keyway`).
- Exit 0 only if A CAD, A FEA, A CFD, and B relations all pass.
- `--json` prints `scenario-report.json`.

Missing FreeCADCmd / ccx / blockMesh|icoFoam: scenario status `missing` (exit 1), same vocabulary as hello where it fits.

## Tests

1. **Unit (CI, fakes):** fake FreeCADCmd writes the four CAD artifacts; fake ccx writes `.frd` with a parseable stress; fake OpenFOAM writes `0.1/p` with `internalField`; pytest asserts report `ok` and B relations.
2. **Negative:** omit a probe name → fail; zero stress → fail; missing `p` field → fail; mismatched xyz → B fail.
3. **Ubuntu reference (not required to be green in GitHub Actions):** one real `etools scenario damper-keyway` after A lands; freeze numeric bands from that run in a follow-up commit if needed.

## Out of scope

- MCP servers for CAD
- 3DEXPERIENCE composition/GUI
- Tosca / TopOpt on the keyway
- Gmsh, SALOME meshing, tet mesh of STEP
- Two-way FSI, mesh motion, live/dynamic continuity (approach C)
- `etools run` for every stack component

## Later (not this spec)

- MCP wrapping `etools scenario`
- Approach B weak coupling: map CFD `p` at `chamber_wall` into the next CalculiX pressure load
- Approach C: FSI
- Richer annular damper physics
