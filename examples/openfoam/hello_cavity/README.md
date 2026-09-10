# hello_cavity

MIT sample OpenFOAM case for **engineering-tools** (tiny lid-driven cavity,
`icoFoam`-ready layout).

OpenFOAM itself is **GPL** upstream and is **not** vendored - we only call
`blockMesh` (and optionally a solver) when installed on your system.

```bash
# After sourcing OpenFOAM's etc/bashrc (or with foamExec on PATH):
blockMesh
# optional: icoFoam
```

`etools hello` stages this case and runs `blockMesh` when neither CalculiX nor
FreeCAD is available. `etools run --tool openfoam --input DIR` runs `blockMesh`
on any case directory that contains `system/`.
