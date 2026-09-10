"""BOM CLI dispatch helpers."""

from __future__ import annotations

from pathlib import Path

from .bom import add_item, list_items, remove_item


def cmd_bom_dispatch(rest: list[str], *, outer_json: bool = False) -> int:
    """CLI dispatcher for ``etools bom ...``. Returns exit code."""
    import argparse
    import json
    import sys

    from .project import is_project

    def resolve_project(explicit: str | None) -> Path:
        if explicit:
            return Path(explicit).expanduser().resolve()
        cwd = Path.cwd().resolve()
        if is_project(cwd):
            return cwd
        raise SystemExit(
            "No project path given and cwd is not an engineering-tools project. "
            "Pass a path: etools bom ./my-part"
        )

    parser = argparse.ArgumentParser(prog="etools bom", add_help=True)
    parser.add_argument("--json", action="store_true", help="Print JSON")

    if rest and rest[0] == "add":
        parser.add_argument("project", nargs="?", default=None)
        parser.add_argument("--part", required=True, help="Part name")
        parser.add_argument("--qty", required=True, type=float, help="Quantity")
        parser.add_argument("--unit", default="ea", help="Unit (default: ea)")
        parser.add_argument("--material", default="", help="Material")
        parser.add_argument("--source", default="", help="Source / vendor")
        parser.add_argument("--notes", default="", help="Notes")
        try:
            parsed = parser.parse_args(rest[1:])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 2
            return code or 0
        action = "add"
    elif rest and rest[0] == "remove":
        parser.add_argument("project", nargs="?", default=None)
        parser.add_argument("--id", default=None, help="Item id")
        parser.add_argument("--part", default=None, help="Exact part name match")
        try:
            parsed = parser.parse_args(rest[1:])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 2
            return code or 0
        action = "remove"
    else:
        if rest and rest[0] == "list":
            rest = rest[1:]
        parser.add_argument("project", nargs="?", default=None)
        try:
            parsed = parser.parse_args(rest)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 2
            return code or 0
        action = "list"

    if outer_json:
        parsed.json = True

    try:
        project = resolve_project(parsed.project)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if action == "list":
        items = list_items(project)
        if parsed.json:
            print(json.dumps({"version": 1, "items": items}, indent=2))
            return 0
        if not items:
            print(f"BOM empty for {project}")
            return 0
        print(f"BOM for {project} ({len(items)} item(s)):")
        print(f"{'ID':12}  {'QTY':>8}  {'UNIT':4}  {'PART':24}  MATERIAL")
        for item in items:
            print(
                f"{str(item.get('id', '')):12}  {item.get('qty', ''):>8}  "
                f"{str(item.get('unit', '')):4}  {str(item.get('part', '')):24}  "
                f"{item.get('material') or ''}"
            )
        return 0

    if action == "add":
        try:
            item = add_item(
                project,
                part=parsed.part,
                qty=parsed.qty,
                unit=parsed.unit,
                material=parsed.material or "",
                source=parsed.source or "",
                notes=parsed.notes or "",
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"Added BOM item {item['id']}: {item['qty']} {item['unit']} {item['part']}")
        if parsed.json:
            print(json.dumps(item, indent=2))
        return 0

    if action == "remove":
        try:
            removed = remove_item(project, item_id=parsed.id, part=parsed.part)
        except (ValueError, KeyError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        print(f"Removed BOM item {removed.get('id')}: {removed.get('part')}")
        if parsed.json:
            print(json.dumps(removed, indent=2))
        return 0

    print(f"Unknown bom action: {action}", file=sys.stderr)
    return 2
