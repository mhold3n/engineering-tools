"""Load and validate packaged open-source stack expectations."""

from __future__ import annotations

import hashlib
import json
import re
from importlib import resources
from pathlib import Path
from typing import Any

EXECUTION_TYPES = {"binary", "python", "container", "java", "service", "other"}
AUDIT_STATES = {"provisional", "audited"}
SOURCE_STATES = {"resolved", "source-unresolved"}
INSTALL_RECIPE_STATES = {"implemented", "recipe-unimplemented"}
PROBE_STATES = {"implemented", "probe-unimplemented"}
MAPPING_FIELDS = {
    "id",
    "inventory_id",
    "replacement",
    "fit",
    "components",
    "probe",
    "expected_signal",
}


class ManifestError(ValueError):
    def __init__(self, errors: tuple[str, ...]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _read_packaged_manifest() -> str:
    root = resources.files("engineering_tools")
    return (root / "data" / "stack.json").read_text(encoding="utf-8")


def load_manifest(path: str | Path | None = None) -> dict[str, Any]:
    try:
        text = (
            Path(path).expanduser().read_text(encoding="utf-8")
            if path is not None
            else _read_packaged_manifest()
        )
        data = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        raise ManifestError((f"manifest could not be loaded: {exc}",)) from exc
    errors = validate_manifest(data)
    if errors:
        raise ManifestError(errors)
    return data


def _ids(rows: object, section: str, errors: list[str]) -> set[str]:
    if not isinstance(rows, list):
        errors.append(f"{section} must be a list")
        return set()
    found: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
            errors.append(f"{section}[{index}] requires a nonempty id")
            continue
        if row["id"] in found:
            errors.append(f"{section} contains duplicate id {row['id']!r}")
        found.add(row["id"])
    return found


def validate_manifest(data: object) -> tuple[str, ...]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ("manifest root must be an object",)
    if data.get("schema_version") != 1:
        errors.append("schema_version must equal 1")
    if data.get("inventory_state") not in AUDIT_STATES:
        errors.append("inventory_state must be provisional or audited")
    inventory = data.get("inventory")
    components = data.get("components")
    mappings = data.get("mappings")
    inventory_ids = _ids(inventory, "inventory", errors)
    component_ids = _ids(components, "components", errors)
    _ids(mappings, "mappings", errors)

    if isinstance(inventory, list):
        for row in inventory:
            if isinstance(row, dict) and row.get("audit_state") not in AUDIT_STATES:
                errors.append(f"inventory {row.get('id')!r} has invalid audit state")

    mapped: list[str] = []
    if isinstance(mappings, list):
        for row in mappings:
            if not isinstance(row, dict):
                continue
            inventory_id = row.get("inventory_id")
            if inventory_id not in inventory_ids:
                errors.append(f"mapping {row.get('id')!r} references unknown inventory")
            elif inventory_id in mapped:
                errors.append(f"inventory {inventory_id!r} has multiple mappings")
            else:
                mapped.append(inventory_id)
            required = row.get("components")
            if not isinstance(required, list) or not required:
                errors.append(f"mapping {row.get('id')!r} components must not be empty")
            elif not all(isinstance(component, str) and component for component in required):
                errors.append(
                    f"mapping {row.get('id')!r} components must contain only nonempty strings"
                )
            elif unknown := sorted(set(required) - component_ids):
                errors.append(f"mapping {row.get('id')!r} references unknown component {unknown[0]!r}")

    for inventory_id in sorted(inventory_ids - set(mapped)):
        errors.append(f"inventory entry has no mapping: {inventory_id!r}")

    if isinstance(components, list):
        for row in components:
            if not isinstance(row, dict):
                continue
            execution = row.get("execution")
            execution_type = execution.get("type") if isinstance(execution, dict) else None
            locator = execution.get("locator") if isinstance(execution, dict) else None
            if execution_type not in EXECUTION_TYPES:
                errors.append(f"component {row.get('id')!r} has unsupported execution type")
            if not isinstance(locator, list) or not locator or not all(
                isinstance(item, str) and item for item in locator
            ):
                errors.append(f"component {row.get('id')!r} requires nonempty locator list")
            source = row.get("source")
            source_state = source.get("state") if isinstance(source, dict) else None
            if source_state not in SOURCE_STATES:
                errors.append(f"component {row.get('id')!r} has invalid source state")
            if source_state == "resolved":
                identity = source.get("identity")
                identity_type = identity.get("type") if isinstance(identity, dict) else None
                valid_identity = (
                    identity_type == "artifact"
                    and isinstance(identity.get("url"), str)
                    and isinstance(identity.get("sha256"), str)
                ) or (
                    identity_type == "container"
                    and isinstance(identity.get("digest"), str)
                    and identity["digest"].startswith("sha256:")
                ) or (
                    identity_type == "source"
                    and isinstance(identity.get("repository"), str)
                    and isinstance(identity.get("commit"), str)
                )
                if not valid_identity:
                    errors.append(f"component {row.get('id')!r} has malformed immutable identity")
            install_recipe = row.get("install_recipe")
            install_state = (
                install_recipe.get("state") if isinstance(install_recipe, dict) else None
            )
            if install_state not in INSTALL_RECIPE_STATES:
                errors.append(f"component {row.get('id')!r} has invalid install recipe state")
            probe = row.get("probe")
            probe_state = probe.get("state") if isinstance(probe, dict) else None
            if probe_state not in PROBE_STATES:
                errors.append(f"component {row.get('id')!r} has invalid probe state")

    if isinstance(mappings, list):
        for row in mappings:
            if not isinstance(row, dict):
                continue
            undeclared_fields = sorted(
                (key for key in row if not isinstance(key, str) or key not in MAPPING_FIELDS),
                key=repr,
            )
            for field in undeclared_fields:
                errors.append(f"mapping {row.get('id')!r} has undeclared field {field!r}")
            replacement = row.get("replacement")
            if not isinstance(replacement, str) or not replacement.strip():
                errors.append(f"mapping {row.get('id')!r} requires one replacement label")
            elif "/" in replacement or re.search(r"\bor\b", replacement, re.IGNORECASE):
                errors.append(f"mapping {row.get('id')!r} replacement must not encode alternatives")
            probe = row.get("probe")
            probe_state = probe.get("state") if isinstance(probe, dict) else None
            if probe_state not in PROBE_STATES:
                errors.append(f"mapping {row.get('id')!r} has invalid probe state")

    return tuple(sorted(set(errors)))


def manifest_digest(data: dict[str, Any]) -> str:
    payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
