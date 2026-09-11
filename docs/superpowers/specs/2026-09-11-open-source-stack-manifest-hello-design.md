# Open-Source Stack Manifest and `hello` Design

Created: 2026-09-11
Status: Approved for implementation

## Purpose

`engineering-tools` is an open-source response to the complete canonical Dassault product map. GitHub distributes first-party orchestration, installation knowledge, immutable upstream pointers, verification logic, and owned smoke fixtures. Third-party applications and engineering data remain outside the repository.

Alpha proves completeness, reproducible installability, and independent functional verification. Beta proves interoperability, workflow quality, and system-level integration.

## Product Contract

Alpha must prove that every canonical Dassault product has exactly one reproducibly installable, independently functioning open-source replacement solution.

- Every closed-source product in the canonical map has exactly one selected open-source response.
- A response may be a fixed composition when the capability inherently requires several components. It may not be a menu of competing alternatives.
- One open-source component may satisfy multiple product mappings.
- Every component has an official upstream source, immutable identity, license, installation recipe, execution locator, component probe, and expected signal.
- Every product mapping has a lightweight capability probe distinct from component verification.
- Missing or unfinished requirements remain visible failures. Package size never changes inclusion, priority, or pass/fail semantics.
- Third-party source trees, binaries, archives, images, dependency trees, and generated engineering data are not stored in this repository.
- Beta may improve or replace a mapping, but the one-response-per-product invariant is permanent.

“Functioning replacement coverage” is deliberately narrow in Alpha: the selected replacement is installed, executable, and demonstrates its assigned capability independently. Cross-component handoffs and polished integrated workflows belong to Beta.

## Canonical Product Map

This table is authoritative for manifest coverage. `+` denotes one fixed composite solution, not alternatives.

| Closed-source product or capability | Selected open-source response | Fit |
| --- | --- | --- |
| 3DEXPERIENCE | `engineering-tools` OpenCAE-style platform | C |
| CATIA | FreeCAD | B |
| SOLIDWORKS | FreeCAD | B |
| CATIA Magic | Eclipse Papyrus | B |
| Cameo | Eclipse Papyrus | B |
| Dymola | OpenModelica | A |
| DraftSight | LibreCAD | B |
| Spatial ACIS | Open CASCADE Technology | A/B |
| CGM | Open CASCADE Technology | A/B |
| Abaqus/CAE | SALOME-Meca + Code_Aster | A/B |
| Abaqus solver | Code_Aster | A/B |
| Abaqus-style simpler solver workflows | CalculiX | A/B |
| SOLIDWORKS Simulation | CalculiX | A/B |
| SIMULIA Fluid Dynamics Engineer | OpenFOAM | A |
| PowerFLOW | OpenLB | A/B |
| XFlow | OpenLB | A/B |
| CST Studio Suite | openEMS | B |
| Opera EM | Elmer FEM | A/B |
| Simpack | Project Chrono | A/B |
| Wave6 | openCFS | A/B |
| fe-safe | pyLife | A/B |
| Isight | OpenMDAO | A |
| Tosca | TopOpt.jl + Code_Aster | B |
| SOLIDWORKS CAM | FreeCAD CAM | B |
| SOLIDWORKS Electrical | QElectroTech | B |
| CATIA electrical/ECAD interaction | KiCad + KiCadStepUp + FreeCAD | B |
| SOLIDWORKS Visualize | Blender | A |
| CATIA Composer | Blender | B |
| SOLIDWORKS Composer | Blender | B |
| 3DEXCITE | Blender | A/B |
| ENOVIA | Git LFS + PostgreSQL + Nextcloud + ERPNext | C |
| SOLIDWORKS PDM | Git LFS + DVC | C |
| DELMIA Apriso | ERPNext Manufacturing | B/C |
| DELMIA Ortems | frePPLe | A/B |
| DELMIA Quintiq | frePPLe + Pyomo | B |
| DELMIA robotics | ROS 2 + MoveIt + Gazebo | A/B |
| GEOVIA Surpac | QGIS + GemPy | B |
| GEOVIA MineSched | Pyomo with a first-party mine-scheduling model | C |
| GEOVIA Whittle | Pyomo with a first-party pit-optimization model | C |
| NETVIBES | OpenSearch + Apache Superset | A/B |
| EXALEAD | OpenSearch + Apache Superset | A/B |
| BIOVIA Pipeline Pilot | KNIME Analytics Platform | A |
| BIOVIA Materials Studio | ASE + LAMMPS + Quantum ESPRESSO | A/B |
| BIOVIA Discovery Studio | RDKit + GROMACS + AutoDock Vina | B |
| BIOVIA ELN | eLabFTW | A/B |
| BIOVIA LIMS | SENAITE | A/B |
| TURBOMOLE | Psi4 | A/B |
| MEDIDATA Rave EDC | LibreClinica | A/B |
| 3DVIA HomeByMe | Sweet Home 3D | A |
| OUTSCALE | OpenStack | A |
| SIMULIA postprocessing | ParaView | A/B |

OpenCAE, DEXCS, and CAELinux are references rather than product replacements or install requirements. OpenCAE supplies ecosystem philosophy, DEXCS supplies contemporary OpenFOAM integration evidence, and CAELinux supplies engineering-workstation bundling evidence.

## System Boundary

```text
GitHub repository                         Local machine / CI runner
-------------------------------------     ---------------------------------
engineering-tools source                 installed third-party applications
canonical stack manifest                 containers and AppImages
immutable upstream pointers              download cache
installation recipes                     resolved machine-specific paths
owned smoke fixtures                     generated projects and artifacts
license and attribution metadata         verification logs and reports
CI workflow definitions                  large engineering data
```

GitHub is the distribution plane for first-party integration knowledge. It is not backup storage for the installed stack.

The first reference platform is Ubuntu 24.04 LTS on x86-64. Additional platforms may add immutable artifact variants later, without weakening requirements for the reference platform.

## Canonical Manifest

Add one versioned `src/engineering_tools/data/stack.json` as canonical source. Keeping it inside package data makes the same manifest available from a Git checkout and an installed wheel. JSON preserves the project’s standard-library-only runtime on Python 3.10; TOML would require a compatibility dependency and YAML would require a parser dependency.

The manifest contains two logical collections:

```text
src/engineering_tools/data/stack.json
  components
    source and immutable identity
    installation recipe
    execution locator
    component hello probe
    expected component signal
  products
    closed-source product identity
    exactly one replacement solution
    required component IDs
    fit grade
    mapping-specific capability probe
    expected capability signal
```

### Component fields

Each component declares:

- Stable component ID and display name.
- Official homepage and source repository.
- License identifier.
- Immutable source identity: release artifact plus digest, container digest, or source commit.
- Reference-platform installation recipe ID.
- Execution object with `type` and `locator`.
- Component probe ID and expected signal.
- Attribution reference.

Supported execution types are `binary`, `python`, `container`, `java`, `service`, and `other`. Locators are interpreted by their execution type instead of being assumed to be executable paths.

An entry whose immutable pointer or probe has not been completed uses an explicit lifecycle state such as `source-unresolved` or `probe-unimplemented`. These are reportable states, not placeholder text, and prevent Alpha from passing.

### Product fields

Each product declares:

- Stable product ID and closed-source display name.
- One replacement label.
- Fit grade.
- Nonempty ordered component ID list.
- Mapping-specific capability probe ID.
- Expected capability signal.

Manifest validation rejects missing product mappings, empty component lists, unknown component IDs, multiple replacement choices, duplicate IDs, unsupported execution types, and malformed immutable identities.

## Local State

Machine-specific state lives under `ETOOLS_HOME`, defaulting to `~/.engineering-tools/`:

```text
~/.engineering-tools/
  installations.json
  hello-report.json
  downloads/
  logs/
```

`installations.json` records resolved locators, installed immutable identities, verified digests, and installation timestamps. `hello-report.json` records manifest digest, Git commit when available, component results, product results, aggregate status, and verification time. These files are local evidence; they are not third-party payloads and are not committed by default.

## `hello` Contract

`etools doctor` remains discovery-focused: it reports what execution locators appear available.

`etools hello` becomes complete Alpha pulse verification:

1. Load and structurally validate the packaged `stack.json` resource.
2. Resolve every component’s installation receipt and execution locator.
3. Validate immutable identity and integrity evidence.
4. Execute every implemented component probe independently.
5. Execute every implemented product capability probe after its components pass.
6. Report every component and product; never return after the first success.
7. Write the complete local report atomically.
8. When `--project` is supplied, append one job record per component and one per product, including failures and unresolved states.
9. Exit zero only when every canonical product is covered.

The initial manifest/`hello` implementation is expected to exit nonzero. Current repository implements executable probes only for CalculiX and FreeCAD, has an unfinished OpenFOAM sample, and lacks most canonical components and product probes. This intentional red state is the actionable installation and implementation ledger.

### Acceptance hierarchy

```text
Component
  source valid
    -> immutable artifact/version resolved
    -> integrity verified
    -> license known
    -> installed outside repository
    -> execution locator resolved
    -> component hello probe passes
    -> component PASS

Mapped product
  every required component passes
    -> mapping-specific capability probe passes
    -> COVERED
```

A composite mapping such as DELMIA robotics requires independent PASS results from ROS 2, MoveIt, and Gazebo plus a lightweight mapping probe. Alpha does not require a polished ROS-to-MoveIt-to-Gazebo workflow.

### Result states

| State | Meaning |
| --- | --- |
| `ok` | Component probe passed. |
| `covered` | Product’s components and mapping-specific capability probe passed. |
| `missing` | Required component is not installed or its locator cannot be resolved. |
| `broken` | Installed component cannot execute its independent probe correctly. |
| `misconfigured` | Component executes, but environment or configuration blocks required behavior. |
| `unverified` | Installation exists, but integrity or verification has not completed. |
| `invalid-pointer` | Upstream source, artifact, commit, digest, or installation metadata cannot be resolved or validated. |
| `probe-unimplemented` | Required component or product probe has not been implemented. |
| `capability-failed` | Components work independently, but mapped capability probe fails. |
| `invalid-manifest` | Canonical manifest violates schema or coverage invariants. |

Every state except `ok` and `covered` prevents aggregate success. Expected incompleteness remains typed and actionable, but does not pass.

## Probe Boundaries

Component probes answer “does this installed component independently perform minimal work?” Product probes answer “does the selected solution demonstrate the specific mapped capability?”

Examples:

- FreeCAD component probe: launch headlessly, construct and save a valid solid document.
- CATIA product probe: verify resulting document contains a parametric solid shape.
- SOLIDWORKS product probe: independently verify the selected FreeCAD workflow can create and export a mechanical part.
- OpenFOAM component probe: stage owned cavity case, run `blockMesh`, and validate `constant/polyMesh/` output.
- SIMULIA Fluid Dynamics Engineer product probe: confirm the mesh represents a valid CFD case. Running a full CFD solver is outside the first OpenFOAM slice.

Probe code may be shared when product requirements genuinely match, but each product receives its own reported result.

## OpenFOAM Slice

Complete the already-started third adapter as first concrete manifest integration:

- Package the full owned `hello_cavity` case.
- Resolve direct `blockMesh`, falling back to `foamExec blockMesh`.
- Stage the case outside repository working files.
- Run mesh generation only.
- Validate `constant/polyMesh/` output.
- Add `openfoam` to custom `etools run`, accepting a case directory containing `system/`.
- Copy custom case into `artifacts/run-<id>/`, run `blockMesh`, and record outputs and attribution.
- Do not run a CFD solver, parse solver selection, use MPI, launch ParaView, or add container orchestration in this slice.

OpenFOAM becomes `ok` only after installation, locator, integrity, and component probe pass. Its SIMULIA CFD mapping becomes `covered` only after its separate mapping probe passes.

## Installation and CI

Installation recipes obtain third-party software from official immutable upstream sources and install outside the Git checkout. The repository stores pointers and recipes only.

CI uses the same manifest and commands as local verification:

- Manifest CI validates schema, one-response-per-product coverage, immutable pointer shape, attribution linkage, and adapter references.
- Reference-environment CI installs or reuses the declared stack outside the checkout, then runs `etools hello` against actual local locators.
- A persistent self-hosted reference runner may retain the large installation between runs; reuse never skips integrity or functional verification.
- Hosted CI that lacks the stack may validate repository logic with controlled fixtures, but it cannot certify Alpha coverage.
- No CI mode may convert required missing components into success.

## First Implementation Increment

The first increment establishes truthful red infrastructure rather than pretending Alpha is complete:

1. Add complete canonical product mapping and deduplicated component inventory to `src/engineering_tools/data/stack.json` and include it in built distributions.
2. Add manifest loader and structural validation.
3. Replace `hello` preference/early-return behavior with exhaustive component and product evaluation.
4. Port existing CalculiX and FreeCAD probes into manifest-driven reporting.
5. Finish OpenFOAM component and SIMULIA CFD capability probes.
6. Represent every remaining unresolved source, installation recipe, or probe explicitly so it fails with actionable state.
7. Add deterministic text and JSON reports plus atomic local report persistence.
8. Add project job logging for every evaluated component and product.
9. Add CI tests for manifest coverage and result aggregation using fake locators; do not claim full Alpha certification until reference-environment `hello` passes.

## Error Handling

- Malformed manifest produces `invalid-manifest`, prints all validation errors deterministically, writes report when possible, and exits nonzero without executing probes.
- One probe failure does not stop remaining probes.
- Probe timeouts and process exceptions become typed component failures.
- Product probes do not execute until all required components pass; they report the blocking component IDs.
- Report writes use temporary file plus atomic replacement to avoid corrupting previous evidence.
- Absolute local paths remain in local reports only; canonical manifest uses portable locators and installation-root tokens.
- Subprocess arguments are constructed by trusted first-party adapters, not arbitrary shell strings from manifest data.

## Testing Strategy

Tests use temporary `ETOOLS_HOME`, fake binaries/services, owned fixtures, and a reduced test manifest. They must cover:

- Full canonical product-map coverage and exactly-one-response invariant.
- Composite mapping resolution and component deduplication.
- Each manifest validation failure.
- Every result state and aggregate exit behavior.
- Exhaustive evaluation after an earlier component fails.
- Separate component and product results.
- CalculiX, FreeCAD, and OpenFOAM success, missing, execution failure, timeout, and expected-artifact failure.
- Direct `blockMesh` and `foamExec blockMesh` resolution.
- Custom OpenFOAM case validation, artifact staging, job logging, and attribution.
- Atomic local report creation with manifest digest and Git revision.
- Project logging of successful, missing, broken, unresolved, and capability-failed results.
- CLI text output ordering and stable JSON shape.

Real third-party applications are verified by reference-environment CI; unit tests prove orchestration and failure semantics without vendoring those applications.

## Non-Goals for This Increment

- Installing the entire stack in one change.
- Beta interoperability workflows.
- GUI implementation.
- Alternative OSS choices for any product mapping.
- Hosting third-party artifacts in GitHub.
- Treating fake-binary CI as Alpha certification.
- Generic plugin framework before third adapter demonstrates stable common behavior.

## Acceptance Criteria

The manifest/`hello` foundation is complete when:

- Packaged `src/engineering_tools/data/stack.json` represents every canonical product above with exactly one solution.
- Every referenced component exists once in component catalog.
- Manifest validation is deterministic and test-covered.
- `hello` evaluates all entries and produces component-level and product-level results.
- Existing CalculiX and FreeCAD checks work through new model.
- OpenFOAM `blockMesh` check and custom case run work through new model.
- Missing products and unfinished probes produce explicit nonzero results.
- Current incomplete local stack therefore fails honestly.
- No third-party payload is committed.
- Repository documentation describes GitHub/local boundary and Alpha/Beta contract consistently.
