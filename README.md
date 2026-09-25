# engineering-tools

Open-source, Linux-based alternative to SolidWorks and the Dassault Systèmes software suite.

Built for hobbyists. We reuse existing open-source work wherever we can and give full credit to every source.

**Approach:** stand on a CAELinux-style mature solver stack; our MIT package is the PLM/workflow layer on top. See [`STRATEGY.md`](STRATEGY.md), [`SOURCE_MAP.md`](SOURCE_MAP.md), and [`THIRD_PARTY.md`](THIRD_PARTY.md).

## Install

```bash
pip install -e ".[dev]"
```

This installs the `engineering-tools` and `etools` console scripts.

## Quickstart

```bash
etools doctor          # discover execution locators
etools init ./my-part  # jobs/, artifacts/, bom.json, attribution + registry
etools hello           # verify every declared component and product mapping; currently expected red
etools hello --json    # machine-readable completion ledger
etools hello --project ./my-part
etools projects        # list registered projects
etools jobs ./my-part  # recent job history (jsonl under .engineering-tools/)

# BOM-lite (hobbyist bill of materials)
etools bom ./my-part
etools bom add ./my-part --part Bracket --qty 2 --material AL6061
etools bom remove ./my-part --part Bracket

# Run a custom solver deck (logs to jobs.jsonl; outputs under artifacts/run-<id>/)
etools run --tool calculix --input deck.inp --project ./my-part
etools run calculix deck.inp --project ./my-part          # shorthand
etools run --tool freecad --input script.py --project ./my-part
etools run openfoam ./case --project ./my-part
etools scenario damper-keyway --project ./my-part
```

`etools profile` is an alias for `doctor`.

Project registry lives under `~/.engineering-tools/registry.json` (override with `ETOOLS_HOME`). Per-project job history is append-only JSONL at `<project>/.engineering-tools/jobs.jsonl`. BOM-lite lives at `<project>/.engineering-tools/bom.json`. Complete latest pulse lives at `~/.engineering-tools/hello-report.json`.

## Install waves (pointer repo)

`etools install` fetches pinned components **outside** the git tree and writes
receipts under `ETOOLS_HOME/installations.json`:

```bash
etools install --wave 1-cad-viz
etools install --wave 7-first-party
etools install --all
etools hello --json   # components may be ok; products need capability probes for Alpha
```

Waves: `1-cad-viz`, `2-cae-core`, `3-electrical`, `4-science`, `5-mbse-plm-light`,
`6-mega-ops`, `7-first-party` (53 components). Pointer-repo DoD is met when those
53 report `status: ok` with verified receipts on Ubuntu 24.04 x86-64. Inventory is
audited (`docs/superpowers/specs/2026-09-22-inventory-audit-freeze.md`). Product
capability probes and 3DEXPERIENCE GUI composition are the next phases. Hosted CI
does not certify VM installs.

### Alpha pulse

`hello` evaluates every manifest component and proprietary-product mapping. It never selects a preferred backend or stops after one success. Success states are `ok` for components and `covered` for products. Non-success states are `missing`, `broken`, `misconfigured`, `unverified`, `invalid-pointer`, `probe-unimplemented`, `capability-failed`, `inventory-unfrozen`, and `invalid-manifest`.

Packaged inventory is audited, so `inventory-unfrozen` is cleared. Single-component product mappings reuse component hello results when those components are `ok`. The OpenFOAM component probe meshes the cavity and runs a short `icoFoam` solve; that result covers SIMULIA Fluid Dynamics Engineer. GEOVIA Surpac, MineSched, and Whittle run in-process numeric checks. Pyomo hello solves a one-variable LP when `glpk`, `cbc`, or HiGHS is installed. SOLIDWORKS PDM, DELMIA Quintiq, DELMIA Robotics, the two BIOVIA studio mappings, CATIA electrical, Tosca, ENOVIA, Netvibes, and Exalead run joint local checks. Container tools use a tag already on the host and `docker run --pull=never` so hello never starts a session or pulls an image. Abaqus CAE stays red until a local image whose name contains `salome` is present (`ghcr.io/codeaster/salome-meca:latest` is not pulled: it requires GHCR auth). 3DEXPERIENCE is covered by the engineering-tools CLI kernel, not a 3DEXPERIENCE GUI.

### Hello samples

- **CalculiX** (`ccx`): MIT deck `examples/calculix/hello_beam.inp` → `artifacts/calculix-hello/`
- **FreeCAD** (`FreeCADCmd`): MIT script `examples/freecad/hello_box.py` → `artifacts/freecad-hello/hello_box.FCStd`
- **OpenFOAM** (`blockMesh` or `foamExec blockMesh`): MIT cavity case → `artifacts/openfoam-hello/constant/polyMesh/`
- **Scenario** (`etools scenario damper-keyway`): parametric damper CAD + CalculiX + OpenFOAM + named probe relations → `artifacts/scenario-damper-keyway/`

Upstream solvers stay GPL/LGPL; we only call them.

## License

[MIT](LICENSE) — use it, fork it, ship it. Attribution required (and we practice what we preach for upstreams).

We never vendor solvers and never strip upstream licenses — see `THIRD_PARTY.md`.
