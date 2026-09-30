# C-FSI — damper vertical (CalculiX + OpenFOAM + preCICE)

Created: 2026-09-25  
Status: Approved for implementation  
Depends on: `docs/superpowers/specs/2026-09-25-c-orchestration-design.md` (C contract); A and B damper specs  
CLI: `etools scenario damper-keyway --coupling c` (alias `--fsi`)

## Purpose

First **implemented** C vertical: true partitioned FSI as proof that the C façade can run off-the-shelf solid and fluid kernels with a replaceable coupler, keep a shared interface synchronized, and stay within **B-relative SI parity** bands.

This is not “an FSI pass beside C.” All C-FSI execution goes through the C façade. preCICE is `backend: precice`.

## Decisions

| Topic | Decision |
| --- | --- |
| Kernels | CalculiX solid participant + OpenFOAM **moving-mesh** fluid participant |
| Coupler | preCICE (generated config from C policy) |
| Geometry | Params-driven coarse hex/blockMesh **pair** sharing one named wall; **not** B’s 4-brick sandwich + lid-driven cavity; **not** Gmsh/SALOME tet of STEP |
| Time | Short transient: fixed small `endTime` / N steps (hello-cavity scale) |
| A/B | Unchanged; `--coupling c` runs A→B first, then C |
| C CFD | **Separate** artifact from A `icoFoam`; A bands stay on kinematic `icoFoam` `p` |
| C solid | **Separate** workdir/deck from `solid.inp` / `solid-map.inp` |
| Parity | Coupled residual **and** B-relative abs+rel bands on equivalent SI quantities |
| A bands on C | **Forbidden** (especially `p_kinematic`) |
| Motion | Fixture-specific interface displacement floor (noise < floor < expected min u for this pack) |
| Ubuntu bands | First green `--coupling c` is **calibration**; freeze values **with provenance**; a **later** clean run must pass frozen bands |

## CLI

```text
etools scenario damper-keyway                 # A → B; C not evaluated
etools scenario damper-keyway --coupling c    # A → B → C-FSI
etools scenario damper-keyway --fsi           # alias of --coupling c
```

- Default exit 0 iff A and B pass (today).
- `--coupling c` / `--fsi` exit 0 iff A/B pass **and** C-FSI passes.
- Requested C is never silently skipped.
- `--fsi` with a different `--coupling` → `broken`.
- Unknown `--coupling` token → `broken`.
- Known unimplemented **reserved** `--coupling` token → `missing` (none reserved yet; see C spec). Garbage token → `broken`.

## Sequence

1. Run existing A/B orchestrator. Do not mutate those solver paths for C.
2. If A or B not ok: **do not start C**. Report C not evaluated (`prerequisite_not_ok`). Exit 1.
3. Freeze immutable A/B snapshot (params digest, product-state, report, files needed for parity).
4. Via façade: register C-FSI session; construct independent C solid + C fluid meshes from `damper-params.json` with one canonical interface (housing inner wall).
5. Bind `backend: precice`. C declares Δt/windows, exchanged fields (solid displacement → fluid mesh motion; fluid wall traction/pressure → solid), residual, order. Backend **generates** preCICE XML and runs iterations.
6. Short transient. Each step must converge. Interface motion must exceed the C-FSI fixture floor.
7. Adapters resolve canonical probes onto their meshes; façade stores SI values.
8. Parity vs snapshot B (same physical quantities only).
9. Persist C session artifact; set `c_ok`; `scenario-report.json` includes C status. Exit 0 iff A/B and C all pass.

## Canonical probes (C-FSI)

Probe identity is C’s, not a solver node number. Required IDs:

| Canonical ID | SI quantity | B snapshot counterpart (same kind) |
| --- | --- | --- |
| `housing.wall.pressure` | Pa | B `chamber_wall` `cfd.p` (Pa) |
| `key.root.von_mises` | Pa | B `keyway_root` `fea_mapped.von_mises` converted to Pa (CalculiX MPa × 1e6) |
| `housing.wall.displacement` | m | No B displacement field; still required **finite** and used for motion floor. Parity vs B is **not** required for this ID until B records u. |
| `housing.wall.traction` | Pa | B wall load equivalent: `|chamber_wall cfd.p|` as pressure traction magnitude (Pa) |

Additional optional ID `key.fillet.von_mises` (Pa) vs B `key_fillet` `fea_mapped` if the C solid mesh has a resolvable fillet probe; if the coarse C mesh cannot resolve it, omit from the packaged parity list rather than invent a location.

Each adapter documents how it maps the ID (nearest node/face on the shared wall or key root). Canonical XYZ comes from `probes_from_params` (mm) converted to m in the CAD frame. Resolved location must lie within the **packaged geometric tolerance** (metres) in that fixture; exceed → `broken`.

## Parity bands

Packaged fixture (not A `a-bands.json`):

- Per-probe **absolute** and **relative** components: pass if `|C − B| ≤ abs + rel * |B|` (or equivalent stated formula).
- Units SI only.
- First Ubuntu success **calibrates** numbers; commit file must state git SHA / date / command of the calibration run. A **subsequent** Ubuntu run is the acceptance evidence against those frozen bands.

## C-FSI proof criteria (not universal C)

- preCICE (backend) reports convergence **every** coupling step.
- Shared interface **moves** (max |u| on interface ≥ fixture floor).
- Coupled fields at required probes finite and valid.
- Every declared B-relative parity row in band.

## Error handling (this vertical)

| Condition | C status |
| --- | --- |
| No `--coupling` / no `--fsi` | not evaluated |
| A/B fail with C requested | not evaluated (`prerequisite_not_ok`) |
| preCICE or FSI OpenFOAM / ccx binary absent | `missing` |
| First-party C adapter missing/corrupt | `broken` |
| Snapshot freeze fail | `broken` |
| No shared wall / probe unresolved | `broken` |
| Generated config/launch fail; residual fail; motion below floor; non-finite field; parity fail | `broken` |

## Artifacts

Under the scenario workdir, distinct from A/B foam/`solid.inp`:

- C solid workdir + CalculiX outputs
- C fluid moving-mesh case + OpenFOAM outputs
- generated preCICE config (derived)
- A/B snapshot dir + digest
- C session JSON with: status, `backend` = `precice`, N time indices, per-step convergence, canonical probe IDs + SI values, parity rows, snapshot digest, `c_ok`

## Tests

**CI — CLI**

- `--fsi` and `--coupling c` equivalent
- conflicting flags → `broken`
- unknown coupling → `broken`
- known-unimplemented capability → `missing`

**CI — fakes**

Fake ccx, moving-mesh OpenFOAM, and preCICE. Assert **persisted** session artifact, not only return codes:

- session status
- N time indices
- per-step convergence
- canonical probe IDs + SI values
- parity rows
- A/B snapshot digest
- `backend` = `precice`
- `c_ok`

Negatives: absent preCICE binary → C `missing`; residual fail; zero motion; unresolved probe; parity out of band; A fail → C not evaluated.

Scenario module must not launch preCICE; adapters/backend only.

**Ubuntu**

- Default command: A/B still green.
- `--coupling c`: real stack. Calibration run then frozen bands then **second** clean run for acceptance.

GitHub Actions is not required to be green for live preCICE (same class as A/B Ubuntu reference).

## Out of scope

solids4Foam / replacing CalculiX; first-party file stagger without preCICE; tet of STEP; making FSI mandatory on default CLI; implementing other C capabilities; applying A `p_kinematic` bands to C pressure; treating preCICE XML as source of truth.
