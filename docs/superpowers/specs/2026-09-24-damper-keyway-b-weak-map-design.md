# Damper keyway B — weak map (Pa state + second CalculiX job)

Created: 2026-09-24  
Status: Approved for implementation  
Depends on: `docs/superpowers/specs/2026-09-24-damper-keyway-scenario-design.md` (approach A complete on Ubuntu); `etools scenario damper-keyway`

## Purpose

Finish approach **B** as a product-state contract: named probes share one frame, coverage includes both solid passes and converted fluid pressure, traction is compared in **Pa**, and CFD `chamber_wall` pressure is applied as the **next** CalculiX load (belt traction kept). This is not FSI.

## Decisions

| Topic | Decision |
| --- | --- |
| Scope | Baseline B relations (honest) plus one weak-coupling solid job |
| Pass 2 loads | Same belt `*CLOAD` as pass 1, **plus** inner-wall loads from converted wall pressure |
| CFD storage | `cfd.p` is Pa; `cfd.p_kinematic` kept for traceability |
| Density | Pin `fluid_density_kg_m3` in `damper-params.json`, default **850** |
| Conversion | `p_Pa = fluid_density_kg_m3 * p_kinematic` |
| CalculiX units | Deck remains mm / N / MPa; mapped pressure in deck is `p_Pa / 1e6` MPa |
| Inner-wall load | `*CLOAD` direction 1, negative (inward −X) on the four nodes at `x = housing_id_mm / 2` |
| Increment | Do **not** require `|σ_mapped − σ_pass1|` above a floor |
| Jobs | Two ccx invocations: `solid` then `solid-map` (two `.inp`, two `.frd`) |
| A bands | Unchanged; apply to pass-1 key von Mises and **kinematic** chamber-center `p`. Do not apply `chamber_center_p.max_abs` to Pa |
| FSI / C | Out of scope |
| MCP / GUI | Out of scope |
| Tet of STEP | Out of scope |
| Scale cavity `p` for a visible Δσ | Out of scope |

## Sequence

Unchanged through A: CAD (cwd params) → `ccx solid` → blockMesh / icoFoam → A bands on **pass 1** key stresses and chamber-center `p_kinematic` (bands file stays as today; they are not Pa).

Then:

1. Convert center and wall cell kinematic `p` to Pa with the pinned density.
2. Write `solid-map.inp` from the same radial C3D8 sandwich as `solid.inp`, copying belt loads and adding inner-wall `*CLOAD`s. Force per inner node = `(p_Pa / 1e6) * inner_face_area_mm2 / 4` where `inner_face_area_mm2` is `key_width_mm * key_length_mm` (the ID-plane face of the sandwich).
3. Run `ccx solid-map`. Require `solid-map.frd`. Sample von Mises at solid probes the same way as pass 1.
4. Write `product-state.json` and evaluate B relations. Exit 0 only if A bands and all B relations pass.

## `shared-frame`

After FreeCAD, read CAD `probes.json`. Fail if any required name is missing or XYZ differs from `probes_from_params` (exact float match). Copy that agreed list into `product-state` `xyz_mm`. The orchestrator must not silently overwrite a drifting CAD file.

## `product-state.json`

```json
{
  "schema_version": 1,
  "scenario": "damper-keyway",
  "params_digest": "<sha256 of damper-params.json>",
  "coupling": "weak-map",
  "fluid_density_kg_m3": 850.0,
  "probes": {
    "key_fillet": {
      "xyz_mm": [10.0, 3.0, 0.0],
      "fea": {"von_mises": 0.0},
      "fea_mapped": {"von_mises": 0.0},
      "cfd": null
    },
    "chamber_wall": {
      "xyz_mm": [-25.0, 0.0, 0.0],
      "fea": null,
      "fea_mapped": null,
      "cfd": {"p": 0.0, "p_kinematic": 0.0}
    }
  },
  "relations": [
    {"id": "shared-frame", "ok": true, "detail": "..."},
    {"id": "named-coverage", "ok": true, "detail": "..."},
    {"id": "order-of-magnitude-traction", "ok": true, "detail": "..."},
    {"id": "weak-map", "ok": true, "detail": "..."}
  ]
}
```

Solid probes (`key_fillet`, `keyway_root`, `belt_land`): `fea` and `fea_mapped`, `cfd` null.  
Fluid probes (`chamber_center`, `chamber_wall`): `cfd.p` (Pa) and `cfd.p_kinematic`, both `fea` fields null.

## Relations

1. **shared-frame** — CAD `probes.json` equals `probes_from_params`.
2. **named-coverage** — solid probes: finite `fea.von_mises` and `fea_mapped.von_mises`. Fluid probes: finite `cfd.p` and `cfd.p_kinematic`.
3. **order-of-magnitude-traction** — `|chamber_wall cfd.p|` (Pa) / `(|belt_land_traction_mpa| * 1e6)` in `[1e-6, 1e6]`.
4. **weak-map** — `solid-map.inp` contains the extra inner-wall `CLOAD`s; `solid-map.frd` exists; mapped key stresses are finite. No increment floor.

## CLI and report

Same command. `scenario-report.json` includes `a_ok`, `b_ok`, pass-1 and pass-2 key stresses, `chamber_p` (Pa), `p_kinematic`. `--json` prints that report. `jobs.jsonl` still `command: scenario`, `tool: damper-keyway`. Exit 0 iff A and B both pass.

Missing density, pass-2 `ccx` / `frd`, or CAD xyz mismatch: `broken` or `missing` as appropriate (density missing is `broken`; `ccx` gone after pass 1 is `missing`).

## Tests

- Fakes: two FRDs at probe nodes; uniform kinematic `p` such that `rho * p_kin` sits in the traction band; assert `b_ok`, four relations, `fea` vs `fea_mapped`, extra `CLOAD` in `solid-map.inp`.
- Negatives: omit density; CAD xyz mismatch; no pass-2 `frd`; traction still computed from kinematic `p` (ratio out of band).
- Ubuntu: one real scenario; expect `a_ok` and `b_ok`. Do not freeze pass-2 stress bands unless a runaway appears.

## Out of scope

Two-way FSI, mesh motion, load iteration to convergence, Gmsh/SALOME tet of STEP, MCP, 3DEXPERIENCE GUI, inflating cavity `p` so Δσ is visible.
