# Phase E independent-mesh live couple

This note records **what the live adapters contribute** and **operator-proven
Ubuntu outcomes**. Solver dumps (FRD, OpenFOAM time directories, participant
logs, `e-session.json` from `/tmp`) are **not** in git.

## Function (stack contribution)

Phase E sits above C/D damper FSI. It does not replace `--coupling c` / `d`.

| Layer | Contribution |
| --- | --- |
| CAD identity | Heated-vessel STEP entities (`face.inner_wall`) are the coupling support, not coincident node IDs. |
| Independent meshes | Gmsh **C3D4** solid (volume union of shell+lid) vs blockMesh **hex envelope** fluid. Unequal counts are required. |
| Participants | Concurrent `ccx_preCICE` (Solid, `mpirun -n 1`) and ESI `rhoPimpleFoam` (Fluid). No process named `precice`. |
| Mapping | preCICE 3 serial-implicit Force/Displacement; Fluid write **conservative**; Displacement **consistent**. |
| Hosted CI | Schema, fakes, and PATH stubs. Live kernels are not the GitHub Actions gate. |

## Completion

**Closed on this slice:** live partitioned couple using the independent mesh pair; session `live: true`; fail-closed if node counts match.

**Not this slice:** thermal Heat-Flux in live XML; CAD viewer results; spatial refinement of two live discretizations; any-CAD/any-load.

## Validation

- **pytest:** PATH fakes (including a 6-node CI msh2). Does not prove Ubuntu physics.
- **Ubuntu hhpe-forge (operator, 2026-09-30):** `etools`/PYTHONPATH tree under `/tmp/phase-e-src`. First green `/tmp/e-ref-pair/proj`; acceptance `/tmp/e-ref-pair-2/proj`.

Recorded session fields (not stored as artifacts here):

- `live` true, `e_ok` true, **2/2** coupling windows
- **solid_nodes 319**, **fluid_nodes 729**, `conformal` false
- CAD probes: wall p **101325 Pa**, T **350 K**, max interface \|U\| **4.272420720645381e-09 m**

## Stability

- Solid `*DYNAMIC` dt matches the preCICE window (0.01 s, end 0.02 s) so CalculiX does not `advance(0)`.
- ESI v2512 bashrc wrap is required for `rhoPimpleFoam` (`libthermoTools.so`).
- Second clean project matched the first measured \|U\| and window count (repeatability of this short implicit pair).
