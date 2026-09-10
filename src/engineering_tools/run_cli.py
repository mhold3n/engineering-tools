"""Run CLI dispatch helpers."""

from __future__ import annotations

from pathlib import Path

from .run import run_deck


def cmd_run_dispatch(
    *,
    tool: str,
    input_file: str,
    project: str | None,
    workdir: str | None = None,
    as_json: bool = False,
) -> int:
    """CLI dispatcher for ``etools run``. Returns exit code."""
    import json
    import sys

    from .project import is_project

    if project:
        root = Path(project).expanduser().resolve()
    else:
        cwd = Path.cwd().resolve()
        if is_project(cwd):
            root = cwd
        else:
            print(
                "No project path given and cwd is not an engineering-tools project. "
                "Pass a path: etools run --project ./my-part ...",
                file=sys.stderr,
            )
            return 2

    try:
        result = run_deck(
            project=root,
            tool=tool,
            input_file=input_file,
            workdir=workdir,
        )
    except (ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(result["message"])
    print(f"Project: {result['project']}")
    if as_json:
        print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1
