# Product capability probes — slice 2

Created: 2026-09-24
Status: Implemented
Depends on: slice 1 reuse-result probes

## Purpose

Extend the reuse-result product probe to every remaining single-component mapping except the two gates that were explicitly deferred.

## In this slice

Every single-component mapping whose probe id is registered in `PRODUCT_PROBES` returns `covered` when that component is `ok` in the same `hello` run.

## Still deferred

- `3dexperience-capability` — platform composition
- `simulia-fluid-dynamics-engineer-capability` — microscopic CFD, not `blockMesh` presence
- All mappings that require two or more components
