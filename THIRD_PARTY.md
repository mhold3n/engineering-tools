# Third-party sources and credits

Engineering tools builds on existing open-source work wherever possible.
This file is the running credit ledger: every upstream project, asset, or
snippet we incorporate gets a short entry here with license and attribution.

Our own glue, PLM/workflow layer, and docs stay under the project [MIT License](LICENSE).
We do **not** re-license upstream code — copyleft components keep their terms.

## How we credit

- Prefer calling / embedding upstreams over rewriting them.
- Keep original copyright and license notices intact in vendored trees.
- Add or update a row below when something lands in the tree (or becomes a hard dependency).
- Re-check SPDX identifiers at first incorporation; notes below are planning guidance.

## Planned upstream map

See [`SOURCE_MAP.md`](SOURCE_MAP.md) for the Dassault → OSS layering.

| Source | Layer | Upstream license (planning) | Notes |
| --- | --- | --- | --- |
| [FreeCAD](https://github.com/FreeCAD/FreeCAD) | CAD geometry | LGPL-2.0-or-later | App shell / workbenches |
| [OpenCASCADE Technology (OCCT)](https://dev.opencascade.org/) | CAD geometry | LGPL-2.1 WITH Open CASCADE Exception | B-rep kernel |
| [CalculiX](http://www.calculix.de/) | FEA | GPL-2.0 | Structural FEA |
| [Code_Aster](https://code-aster.org/) | FEA | GPL-3.0 | Industrial FEA (EDF); related tools vary |
| [OpenFOAM](https://www.openfoam.com/) | CFD | GPL-3.0-or-later | Continuum CFD |
| [OpenLB](https://www.openlb.net/) | CFD | GPL-2.0-or-later | Lattice Boltzmann |
| [openEMS](https://openems.de/) | EM | GPL-3.0-or-later | FDTD EM; CSXCAD is LGPL-3.0-or-later |
| [Elmer](https://www.elmerfem.org/) | EM / multiphysics | Mixed GPL / LGPL | Solver lib often LGPL; many modules GPL |
| [Project Chrono](https://projectchrono.org/) | MBD | BSD-3-Clause | Multibody dynamics |
| [OpenModelica](https://openmodelica.org/) | System simulation | OSMC-PL / AGPL-3.0 (choice) | Modelica toolchain |
| [OpenMDAO](https://openmdao.org/) | Optimization | Apache-2.0 | MDAO framework |
| [Pyomo](https://www.pyomo.org/) | Optimization | BSD-3-Clause | Algebraic optimization modeling |
| [RDKit](https://www.rdkit.org/) | Scientific R&D | BSD-3-Clause | Cheminformatics |
| [LAMMPS](https://www.lammps.org/) | Scientific R&D | GPL-2.0 | Classical MD |
| [Quantum ESPRESSO](https://www.quantum-espresso.org/) | Scientific R&D | GPL-2.0-or-later | Electronic structure |
| [GROMACS](https://www.gromacs.org/) | Scientific R&D | LGPL-2.1-or-later | Molecular dynamics |
| _PLM / workflow stack_ | PLM / workflow | MIT (ours) | Weakest OSS layer — first-party integration |

## Incorporated so far

| Source | What we use | Upstream license | Notes |
| --- | --- | --- | --- |
| [CalculiX](http://www.calculix.de/) | Called by `etools hello` via packaged MIT sample deck `hello_beam.inp` | GPL-2.0 | CalculiX source is not vendored (GPL-2.0); only the MIT sample is packaged |
| [FreeCAD](https://www.freecad.org/) | Called by `etools hello` via packaged MIT `hello_box.py` | LGPL-2.0-or-later | FreeCAD source not vendored (LGPL) |

## Integration note

Most CAD/CAE solvers above are **copyleft** (GPL/LGPL). Ship them as separate
processes or clearly bounded modules, keep our orchestration MIT, and never
strip their notices. Permissive pieces (Chrono, OpenMDAO, Pyomo, RDKit) are
easier to embed deeply.
