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
etools init ./my-part  # jobs/, artifacts/, attribution scaffold + registry
etools hello           # CalculiX hello_beam if ccx on PATH, else FreeCAD hello_box
etools hello --project ./my-part
etools projects        # list registered projects
etools jobs ./my-part  # recent job history (jsonl under .engineering-tools/)
```

`etools profile` is an alias for `doctor`.

Project registry lives under `~/.engineering-tools/registry.json` (override with `ETOOLS_HOME`). Per-project job history is append-only JSONL at `<project>/.engineering-tools/jobs.jsonl`.

### Hello samples

- **CalculiX** (`ccx`): MIT deck `examples/calculix/hello_beam.inp` → `artifacts/calculix-hello/`
- **FreeCAD** (`FreeCADCmd`): MIT script `examples/freecad/hello_box.py` → `artifacts/freecad-hello/hello_box.FCStd`

Upstream solvers stay GPL/LGPL; we only call them.

## License

[MIT](LICENSE) — use it, fork it, ship it. Attribution required (and we practice what we preach for upstreams).

We never vendor solvers and never strip upstream licenses — see `THIRD_PARTY.md`.
