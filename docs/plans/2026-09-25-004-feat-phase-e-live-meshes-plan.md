---
title: "feat: Phase E live meshes from CAD face identity"
date: 2026-09-25
type: feat
artifact_contract: ce-unified-plan/v1
artifact_readiness: implementation-ready
product_contract_source: ce-plan-bootstrap
execution: code
origin: docs/plans/2026-09-25-003-feat-phase-e-cad-coupled-analysis-plan.md
depends_on: feat/phase-e-cad-analysis c9b5227 (FreeCAD STEP identity)
---

# feat: Phase E live meshes from CAD face identity

## Goal Capsule

Turn the heated-vessel **canonical entity IDs** into **independent physics discretizations** bound to those IDs. Structural and fluid meshes must share `face.inner_wall` / `iface.fluid_solid` without equal node counts.

This is the second Ubuntu-owned E gate item (live physics meshing). It does **not** launch preCICE, pimpleFoam, or CalculiX as coupled participants. Residual-only coupling is out of scope.

Authority: E DoD after CAD identity. D damper hex writers stay unused.

Stop when Ubuntu can write a solid mesh and a compressible-fluid volume mesh from `vessel.step` identity, both naming the same canonical interface; CI tests the binding contract with fakes or fixture mesh stats; C/D tests stay green.

---

## Product Contract

### Summary

Common geometry identity; independent discretization. Meshes reference CAD entities. Mapping/conservation of fields stays in `e_mapping.py` and is not re-solved here beyond storing entity→patch/nset bindings.

### Requirements

- R1. Input is `import_identity(vessel.step)` (or the packaged STEP when FreeCAD is present). Do not mint entity IDs from mesh node numbers.
- R2. Produce at least two mesh records: structural (tet or hex) and fluid (volume, boundary-layer capable settings recorded even if first Ubuntu mesh is coarse).
- R3. Both meshes bind `face.inner_wall` (and `iface.fluid_solid`) to a named patch or nset. Node counts may differ.
- R4. Mesh records store `mesh_id`, `participant`, `source topology_version`, entity→mesh-set binding, quality metrics, refinement settings (`e_mesh.py` already has the schema).
- R5. Stale `topology_version` vs current identity is `broken`. Missing interface binding is `broken`.
- R6. Missing Gmsh/blockMesh/snappy is `missing`, not a silent `d_fsi_meshes` / sandwich hex fallback.
- R7. pytest does not require a live couple. Ubuntu meshing is the live gate for this chunk.

### Actors

- A1. Operator on Ubuntu with FreeCAD plus the chosen mesher(s).
- A2. Implementer extending `e_mesh.py` / new `e_mesh_solid.py` / `e_mesh_fluid.py` without rewriting E field schema.

### Key Flows

- F1. STEP → identity → solid mesh bound to bodies/faces.
- F2. Same identity → fluid mesh bound to gas region + wall patch.
- F3. Validate both records against current topology_version.

### Acceptance Examples

- AE1. Solid nset and fluid patch both cite `face.inner_wall`; `n_nodes` differ.
- AE2. Identity topology_version 2 rejects meshes tagged version 1.
- AE3. No FreeCAD: STEP identity still `missing`; mesh job does not invent hex sandwich IDs.
- AE4. `etools scenario damper-keyway --coupling d` tests still pass.

### Scope Boundaries

**In scope:** writers + bindings + Ubuntu generate-once artifacts or live mesh commands; quality/refinement fields; pytest.

**Deferred:** preCICE launch, compressible solver run, CalculiX run, checkpoint on solvers, `e-bands.json`, refinement *solution* comparison (that is the later verify chunk).

**Outside:** conformal-only meshes; D/C surrogate geometry as E meshes.

---

## Planning Contract

### Key Technical Decisions

- KTD1. Reuse `e_mesh.validate_mesh`. Add writers; do not replace the schema.
- KTD2. Solid: Gmsh (preferred) or FreeCAD FEM netgen from the same STEP/labels. First mesh may be coarse tet.
- KTD3. Fluid: OpenFOAM `blockMesh`/`snappyHexMesh` from CAD-derived STL of the gas solid + wall patch named from `face.inner_wall`. First run may skip a full BL stack if settings are recorded and the wall patch exists.
- KTD4. Bindings JSON is the product of this chunk; native `.msh` / `polyMesh` are artifacts under `artifacts/scenario-e-reference/meshes/`.
- KTD5. Classification of solids follows `extract_identity.py` (labels `body.gas` / `body.shell` / `body.lid`), not OCCT face indices.

### Assumptions

- Identity chunk (`vessel.step`, FreeCAD extract) remains the geometry source.
- ESI OpenFOAM locators from C/D apply when the fluid mesher is OpenFOAM.

### High-Level Technical Design

```text
vessel.step
    → import_identity (canonical IDs)
    → solid writer  → mesh_id=solid  bindings[face.inner_wall]=NSET/patch
    → fluid writer  → mesh_id=fluid  bindings[face.inner_wall]=patch
    → validate_mesh(..., current_topology_version=identity)
```

---

## Implementation Units

### U1. Solid mesh writer bound to CAD bodies

**Goal:** Tet/hex volume for `body.shell` (and lid if included) with inner-wall nset/patch.
**Requirements:** R1–R6
**Files:**
- Create: `src/engineering_tools/e_mesh_solid.py`
- Modify: `src/engineering_tools/e_mesh.py` if a `write_mesh_record` helper is needed
- Test: `tests/test_e_mesh_solid.py`
**Approach:** Export wall surface from identity/STEP via FreeCAD or Gmsh geo from classified solids. Missing mesher → `missing`.
**Test scenarios:** fake Gmsh/FreeCAD writes a record with unequal-ready binding; missing tool is missing; stale topology broken (if writer stamps version).

### U2. Fluid mesh writer bound to `body.gas` and inner wall

**Goal:** Volume mesh for compressible-gas region with `face.inner_wall` patch.
**Requirements:** R2, R3, R6
**Dependencies:** U1 only for shared binding helper, not for solid nodes
**Files:**
- Create: `src/engineering_tools/e_mesh_fluid.py`
- Test: `tests/test_e_mesh_fluid.py`
**Approach:** STL or tri surface of gas + wall; OpenFOAM mesh; patch name in bindings. Do not require conformal nodes vs U1.
**Test scenarios:** fake blockMesh/snappy produces polyMesh metadata; wall patch listed; missing OpenFOAM is missing.

### U3. Pair validation and e-reference mesh session

**Goal:** One call writes both records, asserts same interface entity, different `n_nodes`.
**Requirements:** R3, R5, R7, AE1, AE2
**Dependencies:** U1, U2
**Files:**
- Create: `src/engineering_tools/e_mesh_pair.py`
- Modify: `src/engineering_tools/e_scenario.py` to optionally emit mesh artifacts without coupling
- Test: `tests/test_e_mesh_pair.py`
**Approach:** `mesh_e_reference(project)` after identity. Fail-closed if either binding missing.
**Test scenarios:** Covers AE1/AE2 with fakes; D regression untouched.

---

## Verification Contract

- Pytest: new mesh tests + `tests/test_e_cad.py` + C/D suites.
- Ubuntu: FreeCAD identity + both meshers produce artifacts; bindings share `face.inner_wall`; node counts differ.
- No claim that coupled residuals converged.

---

## Definition of Done

- Independent solid and fluid meshes exist for the heated vessel.
- Both reference the same canonical interface IDs.
- Bindings and topology_version are fail-closed.
- Live couple, bands, and refinement-of-results remain the following chunks.

---

## Open Questions

- Q1 (deferred): snappy vs cfMesh vs cartesian for first fluid mesh. Default: OpenFOAM snappy or blockMesh-from-bounds if snappy is too heavy for the first Ubuntu green — record the choice in mesh `refinement` settings.
- Q2 (deferred): whether lid is meshed with the shell or as a separate solid mesh. Default: shell + lid in one structural mesh, gas-only fluid mesh.
