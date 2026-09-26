# C — suite orchestration and co-simulation contract

Created: 2026-09-25  
Status: Approved for implementation (contract only; first vertical is C-FSI)  
Depends on: `docs/superpowers/specs/2026-09-24-damper-keyway-scenario-design.md` (A); `docs/superpowers/specs/2026-09-24-damper-keyway-b-weak-map-design.md` (B)  
First vertical: `docs/superpowers/specs/2026-09-25-c-fsi-damper-design.md`

## Purpose

C is the **solver-agnostic orchestration and state contract** for the engineering-tools suite: one first-party layer that can later coordinate CAD, meshing, solids, fluids, assemblies, thermal, and other off-the-shelf tools while keeping identity, units, frames, time, ownership, coupling, mapping, convergence, execution order, and result reconciliation consistent.

C is **not** FSI, **not** preCICE, and **not** a co-simulation operating system. FSI is the first demanding proof that independent kernels can run behind this contract. preCICE is one **replaceable coupling backend**.

This spec defines the model. Shipment of unused backends (thermal, CAD-in-loop, assemblies, multirate, checkpoint/rollback) waits for a real consumer. Calling a specified-but-unavailable capability **fails closed**.

## Decisions

| Topic | Decision |
| --- | --- |
| Shape | Contract + thin executable façade; expand runtime only when a later vertical needs it |
| Authority | C policy (time window, exchange, residual, order) is source of truth; backend config is generated |
| Solvers | No kernel is the system model; adapters translate C ↔ native decks/cases |
| A/B | Unchanged paths; C consumes **immutable versioned snapshots**, never mutates A/B in place |
| Bypass | Scenario/product code must not spawn C solvers or write coupler config; adapters/backends under the façade may call binaries |
| Parity | Equivalent physics within declared abs+rel tolerances; **not** bit-identical across schemes |
| Status | `ok` = requested capability ran and passed; `missing` = known capability/dependency unavailable; `broken` = invalid request, inconsistent state, or attempted execution failed |
| MCP / 3DX GUI | Out of scope |
| Tet of STEP | Out of scope (meshing adapter is specified/unavailable until a vertical owns it) |

## Status vocabulary

- **`ok`** — requested C capability executed and passed its gates.
- **`missing`** — the requested capability or an **external** dependency is **known** but unavailable (unimplemented C capability; absent `precice` / `ccx` / OpenFOAM FSI solver binary).
- **`broken`** — unknown coupling id; conflicting flags; inconsistent session; **first-party** adapter module absent/corrupt; snapshot freeze failed; execution started and failed (residual, probes, parity, generated-config/launch).
- **Not evaluated** — C was requested but a **prerequisite** (A/B) did not pass. Report C as not started (`prerequisite_not_ok`). Do **not** label C `missing` or `broken`; nothing in C ran. Process exit is still 1.

Unknown `--coupling` values are **`broken`**. A capability named in the capability table but not implemented is **`missing`**.

## Façade (mandatory C I/O)

The façade is the only **C-facing API** for scenario/product code. It must actually own, not merely wrap after the fact:

- canonical entity and interface identity
- SI units and **separate** frame identity
- time/state indexing
- field ownership
- participant registration
- mapping declarations
- convergence criteria
- execution ordering
- result reconciliation
- B-relative (or other declared) parity checks when a vertical requires them
- artifact and status reporting

Adapters under the façade invoke native solvers. Generated coupler files (e.g. preCICE XML) are **artifacts**, never the authoritative definition of policy.

## Identity, frames, units

- **Entity / interface / probe IDs** are canonical strings owned by C (example vertical: `housing.wall.pressure`). Solvers do not define probe identity; each adapter **resolves** a canonical probe onto its mesh.
- **Frame** is CAD-defined origin and orientation (same product frame as A/B `xyz_mm`). C preserves frame identity.
- **Canonical C quantities** are SI (m, s, kg, Pa, K, …).
- **Unit conversion** is an adapter duty (CAD mm → m at the adapter boundary; CalculiX mm/N/MPa internally). Frame and units are **not** one field.

## Participants, ownership, mapping

A **participant** is a registered solver role (solid, fluid, later mesh, CAD, …) with owned fields. An **interface** binds two participants and the fields they exchange. A **mapping declaration** states what is transferred (e.g. displacement vs traction) and which side owns the geometry of the interface. A **coupling backend** realizes mapping and iteration; it does not invent field names.

Execution **order** and **convergence criterion** live in C. The backend iterates until C’s residual is met or reports failure.

## Time and state

C indexes coupling windows / time steps. A vertical chooses steady, one window, or short transient. C records, for each index: whether the backend reported convergence, and reconciled SI probe values used for reporting/parity.

Checkpoint, rollback, and multirate/subcycling are **specified / unavailable** until a vertical requires them. Invoking them is `missing`.

## Capability table (C spec)

| Capability | Status this shipment |
| --- | --- |
| Session, participants, interfaces, SI+frame, time index, mapping, convergence, order, reconciliation, status artifacts | **Implemented** (used by C-FSI) |
| Coupling backend `precice` | **Implemented** (C-FSI) |
| CalculiX adapter, OpenFOAM moving-mesh adapter | **Implemented** (C-FSI) |
| Other coupling backends | specified / unavailable |
| CAD-in-loop, assembly participant, meshing adapter, thermal, extra physics | specified / unavailable |
| Parallel launch of arbitrary participant graphs | specified / unavailable |
| Multirate / subcycling | specified / unavailable |
| Checkpoint / rollback | specified / unavailable |

## A/B snapshots

When a vertical compares to A/B, C receives a **frozen copy**: params digest, `product-state.json`, `scenario-report.json`, and any field files required for parity. Byte content and digest of the snapshot must not change because C ran. C may **read and compare**; it must not rewrite A/B workdirs or reinterpret A/B files in place.

## CLI (suite)

C is requested as analysis depth on an existing scenario, not a second product:

```text
etools scenario <name> --coupling c
etools scenario <name> --fsi
```

`--fsi` is an alias of `--coupling c`. Conflicting values together → `broken`. Default (no flag) does not evaluate C.

Implemented `--coupling` token: `c` (alias `--fsi`). Reserved unimplemented tokens (façade would accept the name but vertical not shipped): **none in this spec**. Any other token is **unknown** → `broken`. When a future spec reserves a token (`thermal`, …) before shipping it, that token becomes **`missing`**. Do not treat capability-table rows as CLI tokens unless listed here.

## Artifacts (session)

A C run persists (names may be scenario-prefixed) at least:

- session status (`ok` / `missing` / `broken` / not evaluated)
- backend id (e.g. `precice`)
- time indices and per-step convergence
- canonical probe IDs and SI values
- parity rows when required
- A/B snapshot digest when a snapshot was taken
- `c_ok` (boolean; false if not evaluated or not passed)

## Tests (contract, CI)

No live FSI required:

- façade registration, SI vs frame, canonical probe ids
- policy in C → generated backend config is output, not input
- unknown coupling → `broken`; unimplemented known capability → `missing`
- snapshot immutability (digest/bytes)
- CLI: `--fsi` ≡ `--coupling c`; conflicting flags → `broken`

## Out of scope

Implementing the full capability table; treating preCICE XML as architecture; bit-identical solver agreement; MCP; 3DEXPERIENCE GUI; making C mandatory on the default scenario command.
