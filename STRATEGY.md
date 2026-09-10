# Strategy — stand on mature CAE, own the MIT layer

## Decision

Start from the **most mature hobbyist CAE workstation pattern** (what
[CAELinux](https://www.caelinux.com/) proved), not from rewriting solvers.

**Engineering tools** is the MIT package *on top*: workflow / PLM glue,
launcher, credits, docs, and opinionated defaults for hobbyists.
Solvers stay upstream (GPL/LGPL/etc.) and keep their licenses.

## Why CAELinux (and why not freeze on it)

CAELinux already assembled the mature stack we mapped in
[`SOURCE_MAP.md`](SOURCE_MAP.md):

| Our layer | Already in CAELinux 2020 (approx.) |
| --- | --- |
| CAD | FreeCAD 0.18.x, LibreCAD, Salome |
| FEA | Code_Aster 14.4 (Salome_Meca), CalculiX, Elmer |
| CFD | OpenFOAM v7 (+ Helyx-OS), Code_Saturne |
| System sim | OpenModelica |
| Pre/post | Salome, ParaView, Gmsh, CalculiX Launcher |
| Maker extras | KiCad, Cura, PyCAM, Arduino, … |

Gaps vs our fuller map: Project Chrono, OpenMDAO/Pyomo, RDKit/LAMMPS/QE/GROMACS,
and especially **PLM/workflow** (the first-party MIT work).

Caveats on the distro itself:

- Last full ISO is **CAELinux 2020** on **Xubuntu 18.04 LTS** (base OS is EOL).
- Maintainer notes (2022 forum): remastering got hard; Salome_Meca alone is multi-GB;
  direction discussed was a **CAE App Center** + **Singularity/containers** (and/or
  a thin base ISO), not endless giant ISOs.
- So: treat CAELinux as the **reference maturity blueprint**, not as the forever
  runtime we ship frozen.

## How we build on that maturity

1. **Reference target** — Document a “known-good” toolchain matching CAELinux’s
   package set (current upstream versions preferred).
2. **MIT package (`engineering-tools`)** — Hobbyist PLM/workflow:
   project/data model, job runner, solver adapters, attribution ledger, UI.
3. **Runtime** — Prefer **containers / AppImages / distro packages** of current
   FreeCAD, Salome_Meca/Aster, OpenFOAM, CalculiX, Elmer, OpenModelica, etc.
   Optional: support CAELinux 2020 as an early “smoke” environment, not the default.
4. **Credits** — Every called binary stays listed in [`THIRD_PARTY.md`](THIRD_PARTY.md).

```
┌─────────────────────────────────────────┐
│  engineering-tools (MIT)                │  ← we own this
│  PLM · workflow · launcher · credits    │
└─────────────────┬───────────────────────┘
                  │ adapters / jobs / files
┌─────────────────▼───────────────────────┐
│  Mature CAE apps (upstream licenses)    │  ← CAELinux-proven set
│  FreeCAD · Aster · CalculiX · OpenFOAM  │
│  Elmer · OpenModelica · Salome · …      │
└─────────────────────────────────────────┘
```

## First build slice

1. Declare the **base profile** (which apps + how we detect them).
2. Ship a tiny MIT CLI/GUI that can: create a project, find installed solvers,
   launch a “hello” FEA or CAD path with attribution.
3. Grow PLM (revisions, BOM-lite, job history) once the adapter pattern is real.

## Non-goals (for now)

- Forking Salome_Meca / OpenFOAM / Code_Aster.
- Shipping a full Linux ISO as v0.
- Replacing GPL solvers with MIT rewrites.
