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
etools doctor          # detect FreeCAD, CalculiX, OpenFOAM, ...
etools init ./my-part  # jobs/, artifacts/, attribution scaffold
etools hello           # run packaged CalculiX hello_beam if ccx is on PATH
etools hello --project ./my-part   # write outputs under artifacts/calculix-hello/
```

`etools profile` is an alias for `doctor`.

When `ccx` (CalculiX) is installed, `hello` runs the MIT sample deck in
`examples/calculix/hello_beam.inp` (also packaged under
`engineering_tools/data/calculix/`). CalculiX itself stays upstream GPL — we only
call it. If CalculiX is missing, `hello` falls back to a FreeCAD headless box, then
to detect-only.

## License

[MIT](LICENSE) — use it, fork it, ship it. Attribution required (and we practice what we preach for upstreams).

We never vendor solvers and never strip upstream licenses — see `THIRD_PARTY.md`.
