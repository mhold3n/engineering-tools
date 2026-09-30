# hello_cavity

MIT sample OpenFOAM case for **engineering-tools** (tiny lid-driven cavity,
`icoFoam`-ready layout).

OpenFOAM itself is **GPL** upstream and is **not** vendored. `etools hello`
copies this case, runs `blockMesh`, then a short `icoFoam` solve (`endTime`
0.1) and requires a written velocity field.

```bash
# After sourcing OpenFOAM's etc/bashrc (or with foamExec on PATH):
blockMesh
icoFoam
```

`etools run --tool openfoam --input DIR` still runs `blockMesh` only on a
case directory that contains `system/`.
