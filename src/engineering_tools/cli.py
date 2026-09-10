"""Command-line entry point for engineering-tools / etools."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

from . import __version__
from .hello import run_hello
from .profile import detect_profile, summarize_profile
from .project import init_project


def _cmd_doctor(_args: argparse.Namespace) -> int:
    detected = detect_profile()
    summary = summarize_profile(detected)
    print(f"engineering-tools {__version__} \u2014 doctor")
    print(f"Found {summary['found_count']} / {summary['total']} tools")
    for detail in summary["details"]:
        if detail["found"]:
            print(f"  [OK]  {detail['name']:16} {detail['binary']} -> {detail['path']}")
        else:
            print(f"  [--]  {detail['name']:16} missing  ({detail['license_hint']})")
    if summary["by_layer"]:
        print("By layer:")
        for layer, names in sorted(summary["by_layer"].items()):
            print(f"  {layer}: {', '.join(names)}")
    return 0 if summary["found_count"] else 1


def _cmd_init(args: argparse.Namespace) -> int:
    root = args.path or "."
    path = init_project(root, name=args.name)
    print(f"Initialized project at {path}")
    return 0


def _cmd_hello(args: argparse.Namespace) -> int:
    result = run_hello(project=args.project)
    print(result["message"])
    if args.project:
        print(f"Project: {result['project']}")
    if args.json:
        print(json.dumps({k: v for k, v in result.items() if k != "summary"}, indent=2))
    return 0 if result["ok"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="etools",
        description="MIT PLM/workflow glue for a CAELinux-style open-source stack.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", aliases=["profile"], help="Detect installed tools")
    doctor.set_defaults(func=_cmd_doctor)

    init = sub.add_parser("init", help="Create a local project layout")
    init.add_argument("path", nargs="?", default=".", help="Project directory (default: .)")
    init.add_argument("--name", default=None, help="Project display name")
    init.set_defaults(func=_cmd_init)

    hello = sub.add_parser("hello", help="Smoke-check FreeCAD / CalculiX / PATH tools")
    hello.add_argument("--project", default=None, help="Optional project path to note")
    hello.add_argument("--json", action="store_true", help="Also print JSON result")
    hello.set_defaults(func=_cmd_hello)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
