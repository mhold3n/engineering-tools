"""Exhaustive component and product verification."""

from __future__ import annotations

import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .hello_probes import COMPONENT_PROBES
from .manifest import ManifestError, load_manifest, manifest_digest
from .product_probes import PRODUCT_PROBES
from .verification import installation_for, load_installations, write_hello_report


def _created() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_revision() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.strip() if proc.returncode == 0 else None


def _unavailable_component(component: dict[str, Any], status: str, message: str) -> dict[str, Any]:
    return {
        "kind": "component", "id": component["id"], "name": component["name"],
        "status": status, "message": message, "locator": None, "workdir": None,
        "outputs": [], "credit": None, "returncode": None,
    }


def _evaluate_component(component: dict[str, Any], installations: dict[str, Any], project: str | Path | None) -> dict[str, Any]:
    if component["source"]["state"] != "resolved":
        return _unavailable_component(component, "invalid-pointer", "immutable upstream source is unresolved")
    if component["install_recipe"]["state"] != "implemented":
        return _unavailable_component(component, "unverified", "installation recipe is not implemented")
    receipt = installation_for(component["id"], installations)
    if receipt is None:
        return _unavailable_component(component, "missing", "installation receipt is missing")
    if not receipt.get("immutable_id") or receipt.get("integrity_verified") is not True:
        return _unavailable_component(component, "unverified", "installation integrity is unverified")
    probe = component["probe"]
    if probe["state"] != "implemented":
        return _unavailable_component(component, "probe-unimplemented", "component probe is not implemented")
    # Guard override/edited manifests that skip validation or omit probe.id.
    probe_id = probe.get("id")
    if not isinstance(probe_id, str) or not probe_id:
        return _unavailable_component(component, "invalid-manifest", "implemented component probe requires nonempty id")
    implementation = COMPONENT_PROBES.get(probe_id)
    if implementation is None:
        return _unavailable_component(component, "invalid-manifest", f"unknown implemented probe {probe_id!r}")
    try:
        result = implementation(project=project)
    except Exception as exc:
        return _unavailable_component(component, "broken", f"component probe raised {type(exc).__name__}: {exc}")
    normalized = dict(result)
    normalized.update(kind="component", id=component["id"], name=component["name"])
    return normalized


def _evaluate_product(mapping: dict[str, Any], inventory: dict[str, Any], results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    required = mapping["components"]
    blocked = [component_id for component_id in required if results[component_id]["status"] != "ok"]
    base = {
        "kind": "product", "id": inventory["id"], "name": inventory["name"],
        "replacement": mapping["replacement"], "components": list(required),
        "blocked_by": blocked,
    }
    if blocked:
        status = results[blocked[0]]["status"]
        return {**base, "status": status, "message": f"blocked by components: {', '.join(blocked)}"}
    probe = mapping["probe"]
    if probe["state"] != "implemented":
        return {**base, "status": "probe-unimplemented", "message": "product capability probe is not implemented"}
    # Same defensive contract for product probes as for components.
    probe_id = probe.get("id")
    if not isinstance(probe_id, str) or not probe_id:
        return {**base, "status": "invalid-manifest", "message": "implemented product probe requires nonempty id"}
    implementation = PRODUCT_PROBES.get(probe_id)
    if implementation is None:
        return {**base, "status": "invalid-manifest", "message": f"unknown implemented product probe {probe_id!r}"}
    try:
        outcome = implementation(results)
    except Exception as exc:
        return {**base, "status": "capability-failed", "message": f"capability probe raised {type(exc).__name__}: {exc}"}
    status = outcome.get("status")
    if status not in {"covered", "capability-failed"}:
        return {**base, "status": "invalid-manifest", "message": "product probe returned invalid status"}
    return {**base, "status": status, "message": str(outcome.get("message") or status)}


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(row["status"] for row in rows).items()))


def run_hello(project: str | Path | None = None, manifest_path: str | Path | None = None) -> dict[str, Any]:
    """Evaluate every declared component and proprietary product mapping."""
    resolved_project = str(Path(project).expanduser().resolve()) if project else None
    common = {"schema_version": 1, "created": _created(), "git_revision": _git_revision(), "project": resolved_project}
    try:
        manifest = load_manifest(manifest_path)
    except ManifestError as exc:
        report = {**common, "ok": False, "status": "invalid-manifest", "manifest_digest": None,
                  "inventory_state": None, "components": [], "products": [],
                  "counts": {"components": {}, "products": {}}, "errors": list(exc.errors)}
        write_hello_report(report)
        return report

    installations = load_installations()
    components = [_evaluate_component(item, installations, project) for item in manifest["components"]]
    by_component = {item["id"]: item for item in components}
    inventory = {item["id"]: item for item in manifest["inventory"]}
    products = [_evaluate_product(mapping, inventory[mapping["inventory_id"]], by_component) for mapping in manifest["mappings"]]
    inventory_frozen = manifest["inventory_state"] == "audited" and all(item["audit_state"] == "audited" for item in manifest["inventory"])
    all_covered = bool(products) and all(item["status"] == "covered" for item in products)
    invalid = any(item["status"] == "invalid-manifest" for item in components + products)
    ok = inventory_frozen and all_covered and not invalid
    status = "covered" if ok else "invalid-manifest" if invalid else "inventory-unfrozen" if not inventory_frozen else "incomplete"
    report = {**common, "ok": ok, "status": status, "manifest_digest": manifest_digest(manifest),
              "inventory_state": manifest["inventory_state"], "components": components, "products": products,
              "counts": {"components": _counts(components), "products": _counts(products)}}
    write_hello_report(report)
    return report
