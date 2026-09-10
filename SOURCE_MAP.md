# Source map — Dassault monolith → open stack

Engineering tools replaces a closed CAD/CAE/PLM suite by composing existing
open-source projects. Our own code stays MIT; upstreams keep their own licenses
(see [`THIRD_PARTY.md`](THIRD_PARTY.md)).

```
Dassault monolith
      │
      ├── CAD geometry ──────► FreeCAD / OpenCASCADE
      ├── FEA ───────────────► CalculiX / Code_Aster
      ├── CFD ───────────────► OpenFOAM / OpenLB
      ├── EM ────────────────► openEMS / Elmer
      ├── MBD ───────────────► Project Chrono
      ├── system simulation ─► OpenModelica
      ├── optimization ──────► OpenMDAO / Pyomo
      ├── scientific R&D ────► RDKit / LAMMPS / Quantum ESPRESSO / GROMACS
      └── PLM/workflow ──────► weakest OSS layer; requires a custom stack
```

## Layer notes

| Layer | Upstream candidates | Role |
| --- | --- | --- |
| CAD geometry | FreeCAD, OpenCASCADE (OCCT) | Parametric modeling, B-rep kernel, CAD exchange |
| FEA | CalculiX, Code_Aster | Structural / multiphysics finite-element solve |
| CFD | OpenFOAM, OpenLB | Continuum and lattice-Boltzmann flow |
| EM | openEMS, Elmer | Electromagnetic and coupled field solve |
| MBD | Project Chrono | Multibody dynamics |
| System simulation | OpenModelica | Modelica-based system / mechatronic simulation |
| Optimization | OpenMDAO, Pyomo | Multidisciplinary and mathematical optimization |
| Scientific R&D | RDKit, LAMMPS, Quantum ESPRESSO, GROMACS | Chemistry, MD, electronic structure |
| PLM / workflow | _(custom stack)_ | Product data, process, and orchestration — build/integrate |

## Integration stance

1. Prefer calling or embedding upstreams over rewriting them.
2. Keep attribution current in `THIRD_PARTY.md` the moment a source lands.
3. Treat PLM/workflow as first-party glue: APIs, job runners, data model, and UI that stitch the solvers together for hobbyists.
