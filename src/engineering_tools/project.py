"""Initialize a local engineering-tools project layout."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


PROJECT_MARKER = ".engineering-tools.json"


def init_project(root: str | Path, name: Optional[str] = None) -> Path:
    """Create jobs/, artifacts/, README.md, ATTRIBUTION.md, and project marker.

    Returns the resolved project root. Idempotent for directories; overwrites
    marker metadata but will not clobber an existing README/ATTRIBUTION if
    they already exist (creates only when missing).
    """
    root_path = Path(root).expanduser().resolve()
    root_path.mkdir(parents=True, exist_ok=True)

    (root_path / "jobs").mkdir(exist_ok=True)
    (root_path / "artifacts").mkdir(exist_ok=True)

    project_name = name or root_path.name

    readme = root_path / "README.md"
    if not readme.exists():
        readme.write_text(
            f"# {project_name}\n\n"
            "Local project managed by engineering-tools (MIT glue).\n\n"
            "- `jobs/` \u2014 solver job inputs / run directories\n"
            "- `artifacts/` \u2014 meshes, results, exports\n"
            "- See repository `THIRD_PARTY.md` / `ATTRIBUTION.md` for upstream licenses.\n",
            encoding="utf-8",
        )

    attribution = root_path / "ATTRIBUTION.md"
    if not attribution.exists():
        attribution.write_text(
            f"# Attribution \u2014 {project_name}\n\n"
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
                "layout": ["jobs", "artifacts"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    return root_path
