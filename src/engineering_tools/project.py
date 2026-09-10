"""Initialize a local engineering-tools project layout."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .registry import register_project

PROJECT_MARKER = ".engineering-tools.json"
PROJECT_DIR = ".engineering-tools"


def is_project(root: str | Path) -> bool:
    """True if path looks like an engineering-tools project."""
    path = Path(root).expanduser().resolve()
    return (path / PROJECT_MARKER).is_file() or (path / PROJECT_DIR).is_dir()


def init_project(root: str | Path, name: Optional[str] = None) -> Path:
    """Create jobs/, artifacts/, meta dir, README.md, ATTRIBUTION.md, and register.

    Returns the resolved project root. Idempotent for directories; overwrites
    marker metadata but will not clobber an existing README/ATTRIBUTION if
    they already exist (creates only when missing). Registers/updates the
    project in the user-level registry (dedupe by resolved path).
    """
    root_path = Path(root).expanduser().resolve()
    root_path.mkdir(parents=True, exist_ok=True)

    (root_path / "jobs").mkdir(exist_ok=True)
    (root_path / "artifacts").mkdir(exist_ok=True)
    (root_path / PROJECT_DIR).mkdir(exist_ok=True)

    project_name = name or root_path.name

    readme = root_path / "README.md"
    if not readme.exists():
        readme.write_text(
            f"# {project_name}\n\n"
            "Local project managed by engineering-tools (MIT glue).\n\n"
            "- `jobs/` -- solver job inputs / run directories\n"
            "- `artifacts/` -- meshes, results, exports\n"
            "- `.engineering-tools/` -- local job history and meta\n"
            "- See repository `THIRD_PARTY.md` / `ATTRIBUTION.md` for upstream licenses.\n",
            encoding="utf-8",
        )

    attribution = root_path / "ATTRIBUTION.md"
    if not attribution.exists():
        attribution.write_text(
            f"# Attribution -- {project_name}\n\n"
            "This project uses the engineering-tools MIT workflow layer. "
            "Do not vendor solvers here. Keep upstream licenses intact and "
            "record any third-party inputs you add below.\n\n"
            "## Upstream stack (typical)\n\n"
            "See the engineering-tools repository `THIRD_PARTY.md` and `SOURCE_MAP.md`.\n",
            encoding="utf-8",
        )

    marker = root_path / PROJECT_MARKER
    marker.write_text(
        json.dumps(
            {
                "name": project_name,
                "version": 1,
                "layout": ["jobs", "artifacts", PROJECT_DIR],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    register_project(root_path, name=project_name)
    return root_path
