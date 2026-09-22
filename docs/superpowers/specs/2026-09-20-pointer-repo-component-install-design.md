# Pointer-Repo Component Install and Hello Design

Created: 2026-09-20  
Status: Approved for planning  
Depends on: `docs/superpowers/specs/2026-09-11-open-source-stack-manifest-hello-design.md`

## Purpose

Make `engineering-tools` a repeatable **pointer repository**: it pins every off-the-shelf open-source replacement component, installs them onto a Linux machine outside the git tree, and proves each component with an independent `hello` probe. This phase does not interconnect tools and does not build the future GUI “we are 3DEXPERIENCE” composition layer.

The long-term product intent remains: this repo becomes the composition/GUI layer over collected upstreams. That work is explicitly later. This design only covers collect → install → component-green.

## Decisions Locked In Brainstorming

| Topic | Decision |
| --- | --- |
| Repo shape | Pointer + recipe + ledger; do not vendor ~50 large install trees into Git |
| Install delivery | Hybrid per recipe: containers/AppImages for heavy stacks; apt/pip/upstream archives for smaller tools; small first-party MIT modules in-repo where required |
| Success bar | Manifest pins + recipes in-repo; VM installs with verified receipts; every in-scope component probe `ok` |
| Aggregate `hello` | Keep current contract; aggregate may stay non-success (`inventory-unfrozen`, products `probe-unimplemented`) |
| Interconnect / product probes | Out of scope |
| GUI / 3DEXPERIENCE composition | Out of scope for this phase; deferred mapping only |
| Electrical | In scope (QElectroTech; KiCad + KiCadStepUp + FreeCAD) |
| Mega-stacks and first-party GEOVIA models | Full bar (OpenStack, ROS 2 + MoveIt + Gazebo, mine-scheduling and pit-optimization models) |
| Approach | Manifest-driven installer with domain wave rollout |

## Scope

### In scope

- Complete packaged `stack.json` entries for every component required by all proprietary mappings **except** the deferred 3DEXPERIENCE → OpenCAE-style platform mapping.
- That set is **53 components** (all non-3DEXPERIENCE mapping dependencies), including electrical and first-party GEOVIA models.
- For each in-scope component:
  - Resolve immutable upstream pointer (`source.state: resolved` + `identity`).
  - Land hybrid install recipe (`install_recipe.state: implemented`).
  - Install on the reference Linux VM **outside** the git checkout.
  - Write integrity-verified receipts under `ETOOLS_HOME/installations.json`.
  - Pass an independent component `hello` probe (`probe.state: implemented`).
- Add `etools install` with single-component, wave, and all-in-scope modes.

### Out of scope

- Product/capability probes and multi-component workflows.
- GUI / 3DEXPERIENCE composition layer.
- Aggregate Alpha certification (`ok: true` for full `hello`).
- Implementing the deferred 3DEXPERIENCE platform component as a phase gate.
- Hosted CI claiming reference-VM certification.

### Done when

- On the reference Ubuntu 24.04 LTS x86-64 VM, every in-scope component reports `status: ok` in `hello-report.json`.
- Receipts match manifest immutable identities with `integrity_verified: true`.
- A clean machine can repeat collect → install → component-green from this repository alone, without copying third-party trees into Git.

## Architecture

```text
GitHub: engineering-tools (pointer repo)
  stack.json          inventory + components + mappings
  install recipes     hybrid recipe modules keyed by recipe id
  hello probes        independent component adapters
  first-party/        minimal mine-sched + pit-opt models (GEOVIA)
  CLI                 etools install | doctor | hello

Linux VM (outside git)
  download cache      fetched artifacts
  install roots       /opt, containers, venvs, services as recipe dictates
  installations.json  locator + immutable_id + integrity_verified
  hello-report.json   exhaustive pulse (components must go green)
```

### Roles

- **Manifest** — single source of truth for pins, recipe id, execution locator, and probe id.
- **Recipe runner** — trusted first-party code only; fetches by pin, verifies digest or commit, installs outside the checkout, updates receipts.
- **Hybrid rule** — recorded per recipe kind: `container`, `appimage`, `apt`, `pip`, `upstream-archive`, or `first-party-module`.
- **Probes** — independent component smoke only.
- **3DEXPERIENCE mapping** — remains in the manifest as deferred/uncovered; not a gate for component-green.

### Invariant

`git clone` → `etools install` → `etools hello` on a fresh Ubuntu 24.04 x86-64 VM yields the same in-scope component-green set without third-party trees in Git.

## Install and Probe Contract

### Pointers

Each in-scope component moves to `source.state: resolved` with immutable `identity`:

- `artifact` — url + sha256, or
- `container` — digest beginning `sha256:`, or
- `source` — repository + commit.

Homepage and repository URLs remain informational. Install verifies **identity**.

### Recipes and CLI

`install_recipe.state` becomes `implemented` with a stable recipe id.

```text
etools install <component-id>
etools install --wave <wave-name>
etools install --all
```

Behavior:

1. Load and validate packaged (or override) manifest.
2. Skip components whose receipt already matches the pin unless `--force`.
3. Fetch into cache outside the git worktree.
4. Verify digest/commit; refuse to continue on mismatch.
5. Install to recipe-defined root outside the checkout.
6. Write/update `installations.json` only after successful verify+install.
7. Never download or extract into the repository tree; refuse paths that resolve inside the worktree.

`--all` means all **in-scope** components (non-3DEXPERIENCE mapping dependencies), not the deferred platform row.

### Receipts

Each successful install records at least:

- `locator`
- `immutable_id`
- `integrity_verified: true`
- timestamp
- recipe id

`hello` keeps existing rules: missing or unverified receipt → component non-`ok`.

### Component probes

Every in-scope component gets `probe.state: implemented` and a registered probe function returning the existing component result shape.

Probe = minimal independent smoke (CLI exit, tiny owned fixture, or service health check). No multi-tool workflows.

Existing CalculiX, FreeCAD, and OpenFOAM probes remain. First-party GEOVIA models are small MIT modules in-repo; their probes run a toy schedule/optimize and check expected output.

### Phase success signal

Operators judge success by in-scope component rows all showing `status: ok`. Aggregate `ok` may remain `false`. Product mappings stay `probe-unimplemented` until a later phase.

## Delivery Waves

Each wave completes pin → recipe → install → component probe green before relying on later waves. Failures are typed; one failure does not skip remaining installs in the wave.

| Wave | Name | Focus | Count |
| --- | --- | --- | --- |
| 1 | `1-cad-viz` | FreeCAD, FreeCAD CAM, LibreCAD, OCCT, Blender, Sweet Home 3D | 6 |
| 2 | `2-cae-core` | CalculiX, OpenFOAM, ParaView, OpenModelica, OpenMDAO, Code_Aster, SALOME-Meca, Elmer, Chrono, OpenLB, openCFS, openEMS, pyLife, TopOpt.jl | 14 |
| 3 | `3-electrical` | QElectroTech, KiCad, KiCadStepUp | 3 |
| 4 | `4-science` | KNIME, ASE, LAMMPS, Quantum ESPRESSO, RDKit, GROMACS, AutoDock Vina, Psi4, eLabFTW, SENAITE | 10 |
| 5 | `5-mbse-plm-light` | Papyrus, Git LFS, DVC, Pyomo, frePPLe, PostgreSQL, Nextcloud, ERPNext, ERPNext Manufacturing, OpenSearch, Superset, LibreClinica, QGIS, GemPy | 14 |
| 6 | `6-mega-ops` | ROS 2, MoveIt, Gazebo, OpenStack | 4 |
| 7 | `7-first-party` | First-party mine-scheduling model, first-party pit-optimization model | 2 |

**Total in-scope:** 53 components.  
**Deferred:** 3DEXPERIENCE platform mapping only.

Wave membership is a testable invariant: every non-3DEXPERIENCE mapping component appears in exactly one wave.

## Error Handling

### Install

- Fetch failure, digest/commit mismatch, unsupported recipe kind, privilege or disk failure → typed non-zero result.
- Do not write a verified receipt on failure.
- One component failure does not abort the rest of a wave; summarize failures at the end.
- Refuse install targets inside the git worktree.

### Hello

- Existing typed states unchanged (`missing`, `broken`, `unverified`, `invalid-pointer`, `probe-unimplemented`, `invalid-manifest`, etc.).
- Products remain non-blocking for this phase’s operator gate.
- Aggregate exit may stay nonzero; that is expected.

## Testing Strategy

- Unit tests: pointer/recipe validation; receipt skip/`--force`; digest mismatch; worktree path-escape refusal.
- Probe tests with fake binaries/fixtures (existing CalculiX/FreeCAD/OpenFOAM pattern).
- Wave membership coverage for all 53 in-scope components.
- Hosted CI: schema, fake install/probe paths only — does not certify the reference VM.
- Reference Linux VM: real `etools install --wave …` and `etools hello`; evidence is the growing component-green set to 53.

No product-capability or multi-tool workflow tests in this phase.

## Operator Workflow

```text
# On Ubuntu 24.04 x86-64 VM, with engineering-tools installed editable from clone
etools install --wave 1-cad-viz
etools hello --json   # confirm wave components ok; aggregate may still be false
# … waves 2–7 …
etools install --all  # idempotent catch-up
etools hello --json   # all 53 in-scope components status=ok
```

`etools doctor` remains discovery-only and does not replace install verification.

## Relationship to Existing Specs

This design extends the 2026-09-11 stack-manifest/`hello` contract. It does not weaken:

- one replacement mapping per inventory row
- exhaustive hello evaluation
- third-party trees outside Git
- component success ≠ product coverage

It narrows the next implementation plan to **pointers, hybrid install, receipts, and component probes** for the 53 in-scope components, with explicit deferral of product probes and the 3DEXPERIENCE composition/GUI layer.

## Non-Goals

- Rebasing or forking upstream solvers into this organization.
- Shipping a full Linux ISO.
- Declaring Alpha complete while inventory remains provisional or products lack capability probes.
- Building the GUI composition layer in this phase.
