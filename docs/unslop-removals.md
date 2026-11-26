# Unslop removals

Date: 2026-11-16. Checkout: `.worktrees/phase-e-cad-analysis`.

Comments, docstrings, and `README.md` lost dash and arrow glue. Behavior did not change. Stored product labels still contain `→` because tests and hello output use those exact strings.

## Removed from comments and the README

- `e_interaction.py`. `Solid→Fluid` and `Fluid→Solid` in comments. "Freeze one fluid-first step." "No tolerance is invented."
- `e_policy.py`. Opening arrow. `first→second`. The em dash before "status broken". "acceleration knob". The quantity-map arrow in a comment. `Solid→Fluid` in a comment.
- `e_facade.py`. Em dash in the ESI binary docstring. `Missing tool → None`.
- `e_field.py`. Quantity-map arrow in a comment.
- `e_backend_precice.py`. Opening arrow. `second→first`. Scheme arrows. "source of truth". Parenthetical "not from/to". `<solver:…/>`.
- `e_adapters.py`. Opening arrow.
- `e_interface_map.py`. Opening arrow.
- `e_mesh.py`. `entity→mesh-set`.
- `e_mesh_fluid.py`. `mm→m`. Em dash before "the same CAD entity".
- `e_mesh_geo.py`. `mm→m`.
- `e_cad.py`. Em dash before "never damper hex writers". Three path arrows in the import docstring.
- `e_mapping.py`. Em dash before "never alias". En dash in `Sutherland–Hodgman`. Constant-field arrow.
- `e_adapter_calculix.py`. En dash in `S1–S4`. `Gmsh tets → e-solid.inp`.
- `e_verify.py`. `Overflow → undefined`.
- `e_time.py`. Subcycle arrow.
- `c_snapshot.py`. Em dash before "not a JSON merge".
- `c_contract.py`. `unknown → broken, unavailable → missing`.
- `product_probes.py`. Module-doc arrow only. The label table was not edited.
- `install.py`. Em dash in the `noqa: S310` note.
- `data/e-demo/extract_identity.py`. Em dash and arrow in the file header.
- `data/e-demo/build_vessel.py`. Em dash in the file header.
- `data/freecad/hello_box.py` and `examples/freecad/hello_box.py`. Em dash in the file header.
- `data/damper/build_damper.py`. Em dash in the file header.
- `tests/test_freecad_hello.py`. Em dash in the no-ccx comment.
- `tests/test_e_policy.py`. `First→second` in a comment.
- `tests/test_e_mapping.py`. Face-normal arrow in a comment.
- `tests/test_install_waves.py`. Unimplemented-recipe arrow in a comment.
- `tests/test_c_fsi.py`. Kinematic-pressure arrow in a comment.
- `tests/test_c_adapter_calculix.py`. Absent-binary arrow in a docstring.
- `README.md`. Hello-sample arrows. License em dashes. "we practice what we preach for upstreams."

## Left in place

- `product_probes.py` and `workflow_probes.py` mapping labels such as `CATIA→FreeCAD`.
- `tests/test_hello.py` label `Closed→Open`.
- Archived files under `docs/plans/` and `docs/superpowers/`. They still use em dashes as list punctuation. This pass did not rewrite them.
