# Product capability probes — slice 1 (reuse component results)

Created: 2026-09-23  
Status: Approved for implementation (operator chose reuse-result mode)  
Depends on: inventory audit freeze; pointer-repo 53-component DoD

## Purpose

Start Alpha product coverage: mark selected proprietary→OSS mappings `covered` when their required components already report `ok` in the same `etools hello` run. Do not re-execute solver/CAD jobs inside the product probe for this slice.

## Decisions

| Topic | Decision |
| --- | --- |
| Probe mode | Reuse component probe outcomes from the current hello report |
| First slice | Single-component CAD/FEA/system mappings with strong existing component hellos |
| Deferred | CFD microscopic (OpenFOAM Fluid Dynamics), multi-component composites, 3DEXPERIENCE platform |
| Component≠product | Still enforced: product stays `probe-unimplemented` until a registered product probe exists; auto-covered-without-probe is forbidden |

## First-slice mappings

| Probe id | Required component |
| --- | --- |
| `catia-capability` | `freecad` |
| `solidworks-capability` | `freecad` |
| `draftsight-capability` | `librecad` |
| `solidworks-simulation-capability` | `calculix` |
| `abaqus-style-simpler-solver-workflows-capability` | `calculix` |
| `dymola-capability` | `openmodelica` |

## Behavior

For each registered product probe:

1. Caller already verified required components are `ok` (else product is blocked earlier).
2. Probe inspects `results[component_id]["status"]` for its declared primary component(s).
3. Return `covered` with a message naming the reused component row, or `capability-failed` if unexpected.

## Out of scope (later slices)

- Independent re-execution of FreeCAD/CalculiX/OMC inside product probes.
- `simulia-fluid-dynamics-engineer-capability` microscopic CFD.
- Composite mappings (2+ components).
- `3dexperience-capability`.
