"""Command-line entry point for engineering-tools / etools."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import __version__
from .hello import run_hello
from .jobs import append_job, read_jobs
from .profile import detect_profile, summarize_profile
from .project import init_project, is_project
from .registry import list_projects, touch_project


def _cmd_doctor(_args: argparse.Namespace) -> int:
    detected = detect_profile()
    summary = summarize_profile(detected)
    print(f"engineering-tools {__version__} -- doctor")
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


def _record_hello_job(project: str, result: dict) -> None:
    status = "ok" if result.get("ok") else "fail"
    append_job(
        project,
        tool=result.get("backend"),
        command="hello",
        status=status,
        workdir=result.get("workdir"),
        outputs=list(result.get("outputs") or []),
        message=str(result.get("message") or ""),
        credit=result.get("credit"),
    )
    touch_project(project)


def _cmd_hello(args: argparse.Namespace) -> int:
    result = run_hello(project=args.project)
    print(result["message"])
    if args.project:
        print(f"Project: {result['project']}")
        _record_hello_job(args.project, result)
    if args.json:
        print(json.dumps({k: v for k, v in result.items() if k != "summary"}, indent=2))
    return 0 if result["ok"] else 1


def _cmd_projects(args: argparse.Namespace) -> int:
    projects = list_projects()
    if args.json:
        print(json.dumps(projects, indent=2))
        return 0
    if not projects:
        print("No registered projects. Run `etools init` first.")
        return 0
    print(f"{'NAME':24}  {'UPDATED':20}  PATH")
    for entry in projects:
        name = str(entry.get("name") or "")[:24]
        updated = str(entry.get("updated") or "")[:20]
        path = entry.get("path") or ""
        print(f"{name:24}  {updated:20}  {path}")
    return 0


def _resolve_jobs_project(explicit: Optional[str]) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    cwd = Path.cwd().resolve()
    if is_project(cwd):
        return cwd
    raise SystemExit(
        "No project path given and cwd is not an engineering-tools project. "
        "Pass a path: etools jobs ./my-part"
    )


def _cmd_jobs(args: argparse.Namespace) -> int:
    try:
        project = _resolve_jobs_project(args.project)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 2
    jobs = read_jobs(project, limit=args.limit)
    if args.json:
        print(json.dumps(jobs, indent=2))
        return 0
    if not jobs:
        print(f"No jobs recorded under {project}")
        return 0
    print(f"Jobs for {project} (newest first, limit {args.limit}):")
    for job in jobs:
        created = job.get("created") or ""
        status = job.get("status") or "?"
        tool = job.get("tool") or "-"
        command = job.get("command") or "-"
        print(f"  {created}  [{status:4}]  {tool}/{command}  id={job.get('id', '')[:8]}")
    return 0


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

    projects = sub.add_parser("projects", help="List registered projects")
    projects.add_argument("--json", action="store_true", help="Print JSON")
    projects.set_defaults(func=_cmd_projects)

    jobs = sub.add_parser("jobs", help="List recent job history for a project")
    jobs.add_argument(
        "project",
        nargs="?",
        default=None,
        help="Project path (default: cwd if it is a project)",
    )
    jobs.add_argument("--json", action="store_true", help="Print JSON")
    jobs.add_argument("--limit", type=int, default=20, help="Max jobs to show (default: 20)")
    jobs.set_defaults(func=_cmd_jobs)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
