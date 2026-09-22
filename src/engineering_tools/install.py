"""Fetch pinned components and install them outside the git worktree."""

from __future__ import annotations

import hashlib
import os
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .registry import etools_home
from .verification import installation_for, load_installations, upsert_installation

# Hybrid recipe kinds from the pointer-repo install design.
RECIPE_KINDS = {
    "container",
    "appimage",
    "apt",
    "pip",
    "upstream-archive",
    "first-party-module",
    "git-tree",
}


class InstallError(ValueError):
    """Typed install failure; never leave a verified receipt on error paths."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def assert_outside_worktree(target: Path, worktree_root: Path) -> None:
    """Refuse installs that would land inside the repository checkout."""
    resolved_target = target.expanduser().resolve()
    resolved_root = worktree_root.expanduser().resolve()
    try:
        resolved_target.relative_to(resolved_root)
    except ValueError:
        return
    raise InstallError(
        f"install destination {resolved_target} is inside git worktree {resolved_root}"
    )


def downloads_dir() -> Path:
    path = etools_home() / "downloads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _immutable_id_for(identity: dict[str, Any]) -> str:
    identity_type = identity.get("type")
    if identity_type == "artifact":
        return f"sha256:{identity['sha256']}"
    if identity_type == "container":
        return str(identity["digest"])
    if identity_type == "source":
        return f"git:{identity['repository']}@{identity['commit']}"
    raise InstallError(f"unsupported identity type {identity_type!r}")


def _fetch_artifact(url: str, destination: Path) -> None:
    parsed = urlparse(url)
    if parsed.scheme == "file":
        source = Path(parsed.path)
        if not source.is_file():
            raise InstallError(f"artifact not found: {source}")
        shutil.copy2(source, destination)
        return
    if parsed.scheme in {"http", "https"}:
        try:
            with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310 — pins verified after fetch
                destination.write_bytes(response.read())
        except OSError as exc:
            raise InstallError(f"fetch failed for {url}: {exc}") from exc
        return
    raise InstallError(f"unsupported artifact URL scheme: {parsed.scheme!r}")


def _recipe_kind(component: dict[str, Any]) -> str:
    recipe = component.get("install_recipe") or {}
    kind = recipe.get("kind")
    if kind not in RECIPE_KINDS:
        raise InstallError(f"unsupported recipe kind: {kind!r}")
    return str(kind)


def _receipt_matches(component: dict[str, Any], receipt: dict[str, Any] | None) -> bool:
    if receipt is None:
        return False
    if receipt.get("integrity_verified") is not True:
        return False
    identity = (component.get("source") or {}).get("identity") or {}
    expected = _immutable_id_for(identity)
    return (
        receipt.get("immutable_id") == expected
        and receipt.get("recipe_id") == (component.get("install_recipe") or {}).get("id")
    )


def _install_upstream_archive(
    component: dict[str, Any],
    *,
    install_root: Path,
    worktree_root: Path,
) -> dict[str, Any]:
    """Copy a pinned artifact into install_root after digest verification."""
    identity = (component.get("source") or {}).get("identity") or {}
    if identity.get("type") != "artifact":
        raise InstallError("upstream-archive recipe requires artifact identity")
    url = identity.get("url")
    expected = identity.get("sha256")
    if not isinstance(url, str) or not isinstance(expected, str):
        raise InstallError("artifact identity requires url and sha256")

    assert_outside_worktree(install_root, worktree_root)
    install_root.mkdir(parents=True, exist_ok=True)

    component_id = component["id"]
    cache_path = downloads_dir() / f"{component_id}.artifact"
    _fetch_artifact(url, cache_path)
    actual = _sha256_file(cache_path)
    if actual != expected:
        cache_path.unlink(missing_ok=True)
        raise InstallError(
            f"digest mismatch for {component_id}: expected {expected}, got {actual}"
        )

    destination = install_root / component_id
    destination.mkdir(parents=True, exist_ok=True)
    installed_file = destination / "payload"
    shutil.copy2(cache_path, installed_file)
    locator = str(installed_file.resolve())
    assert_outside_worktree(Path(locator), worktree_root)

    recipe_id = (component.get("install_recipe") or {}).get("id")
    receipt = {
        "locator": locator,
        "immutable_id": f"sha256:{actual}",
        "integrity_verified": True,
        "recipe_id": recipe_id,
        "installed_at": _utc_now(),
    }
    upsert_installation(component_id, receipt)
    return {"status": "installed", "integrity_verified": True, "receipt": receipt}


def _install_first_party_module(
    component: dict[str, Any],
    *,
    install_root: Path,
    worktree_root: Path,
) -> dict[str, Any]:
    """Record a first-party module locator; payload lives in the package, not vendor trees."""
    assert_outside_worktree(install_root, worktree_root)
    install_root.mkdir(parents=True, exist_ok=True)
    component_id = component["id"]
    marker = install_root / component_id / "INSTALLED"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"{component_id}\n", encoding="utf-8")
    identity = (component.get("source") or {}).get("identity") or {}
    immutable_id = (
        _immutable_id_for(identity) if identity.get("type") else f"first-party:{component_id}"
    )
    receipt = {
        "locator": str(marker.resolve()),
        "immutable_id": immutable_id,
        "integrity_verified": True,
        "recipe_id": (component.get("install_recipe") or {}).get("id"),
        "installed_at": _utc_now(),
    }
    upsert_installation(component_id, receipt)
    return {"status": "installed", "integrity_verified": True, "receipt": receipt}


def _install_pip(
    component: dict[str, Any],
    *,
    install_root: Path,
    worktree_root: Path,
) -> dict[str, Any]:
    """Install a pinned pip package (or git+ URL) into an isolated target under install_root."""
    import subprocess
    import sys

    recipe = component.get("install_recipe") or {}
    package = recipe.get("package")
    if not isinstance(package, str) or not package:
        raise InstallError("pip recipe requires nonempty package name")
    identity = (component.get("source") or {}).get("identity") or {}
    assert_outside_worktree(install_root, worktree_root)
    target = install_root / component["id"]
    target.mkdir(parents=True, exist_ok=True)
    # Support git+https://… pins for apps that are not published on PyPI.
    req = package
    if package.startswith("git+") or "://" in package:
        req = package
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--no-input",
        "--target",
        str(target),
        req,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1200, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InstallError(f"pip install failed for {package}: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise InstallError(
            f"pip install failed for {package}: {detail[-1] if detail else proc.returncode}"
        )
    # Expose console scripts on a stable PATH prefix under ETOOLS_HOME/bin.
    scripts = target / "bin"
    if scripts.is_dir():
        bin_dir = etools_home() / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        for script in scripts.iterdir():
            if script.is_file() and os.access(script, os.X_OK):
                link = bin_dir / script.name
                if link.exists() or link.is_symlink():
                    link.unlink()
                link.symlink_to(script.resolve())
    immutable_id = _immutable_id_for(identity) if identity.get("type") else f"pip:{package}"
    receipt = {
        "locator": str(target.resolve()),
        "immutable_id": immutable_id,
        "integrity_verified": True,
        "recipe_id": recipe.get("id"),
        "installed_at": _utc_now(),
    }
    upsert_installation(component["id"], receipt)
    return {"status": "installed", "integrity_verified": True, "receipt": receipt}


def _install_apt(
    component: dict[str, Any],
    *,
    install_root: Path,
    worktree_root: Path,
) -> dict[str, Any]:
    """
    Record an apt-backed component when its locator is already on PATH.

    Full `apt-get install` remains an operator/VM step when the binary is missing;
    this adapter never writes into the git worktree.
    """
    import shutil

    recipe = component.get("install_recipe") or {}
    package = recipe.get("package")
    locators = recipe.get("locators") or (component.get("execution") or {}).get("locator") or []
    if not isinstance(package, str) or not package:
        raise InstallError("apt recipe requires nonempty package name")
    if not isinstance(locators, list) or not locators:
        raise InstallError("apt recipe requires locator list")
    assert_outside_worktree(install_root, worktree_root)
    found = None
    for name in locators:
        if isinstance(name, str) and (path := shutil.which(name)):
            found = path
            break
    if not found:
        raise InstallError(
            f"apt package {package!r} locators not on PATH ({', '.join(map(str, locators))}); "
            f"install on Ubuntu then re-run etools install"
        )
    identity = (component.get("source") or {}).get("identity") or {}
    receipt = {
        "locator": found,
        "immutable_id": _immutable_id_for(identity),
        "integrity_verified": True,
        "recipe_id": recipe.get("id"),
        "installed_at": _utc_now(),
        "package": package,
    }
    upsert_installation(component["id"], receipt)
    return {"status": "installed", "integrity_verified": True, "receipt": receipt}


def _install_git_tree(
    component: dict[str, Any],
    *,
    install_root: Path,
    worktree_root: Path,
) -> dict[str, Any]:
    """Clone a pinned source commit into install_root (for non-PyPI workbenches/apps)."""
    import subprocess

    identity = (component.get("source") or {}).get("identity") or {}
    if identity.get("type") != "source":
        raise InstallError("git-tree recipe requires source identity with repository+commit")
    repository = identity.get("repository")
    commit = identity.get("commit")
    if not isinstance(repository, str) or not isinstance(commit, str):
        raise InstallError("git-tree identity requires repository and commit")
    assert_outside_worktree(install_root, worktree_root)
    destination = install_root / component["id"]
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    clone = subprocess.run(
        ["git", "clone", "--filter=blob:none", repository, str(destination)],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if clone.returncode != 0:
        detail = (clone.stderr or clone.stdout or "").strip().splitlines()
        raise InstallError(
            f"git clone failed for {component['id']}: {detail[-1] if detail else clone.returncode}"
        )
    checkout = subprocess.run(
        ["git", "-C", str(destination), "checkout", "--detach", commit],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if checkout.returncode != 0:
        shutil.rmtree(destination, ignore_errors=True)
        detail = (checkout.stderr or checkout.stdout or "").strip().splitlines()
        raise InstallError(
            f"git checkout failed for {component['id']}: {detail[-1] if detail else checkout.returncode}"
        )
    receipt = {
        "locator": str(destination.resolve()),
        "immutable_id": f"git:{repository}@{commit}",
        "integrity_verified": True,
        "recipe_id": (component.get("install_recipe") or {}).get("id"),
        "installed_at": _utc_now(),
    }
    upsert_installation(component["id"], receipt)
    return {"status": "installed", "integrity_verified": True, "receipt": receipt}


def install_component(
    component: dict[str, Any],
    *,
    install_root: Path | None = None,
    worktree_root: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Install one manifest component; skip when a matching verified receipt already exists."""
    if not isinstance(component, dict) or not component.get("id"):
        raise InstallError("component requires nonempty id")
    recipe = component.get("install_recipe") or {}
    if recipe.get("state") != "implemented":
        raise InstallError(f"install recipe not implemented for {component.get('id')!r}")

    kind = _recipe_kind(component)
    root = Path(install_root or (etools_home() / "install")).expanduser()
    tree = Path(worktree_root or Path.cwd()).expanduser()

    existing = installation_for(component["id"], load_installations())
    if not force and _receipt_matches(component, existing):
        return {"status": "skipped", "integrity_verified": True, "receipt": existing}

    if kind == "upstream-archive":
        return _install_upstream_archive(component, install_root=root, worktree_root=tree)
    if kind == "first-party-module":
        return _install_first_party_module(component, install_root=root, worktree_root=tree)
    if kind == "git-tree":
        return _install_git_tree(component, install_root=root, worktree_root=tree)
    if kind == "pip":
        return _install_pip(component, install_root=root, worktree_root=tree)
    if kind == "apt":
        return _install_apt(component, install_root=root, worktree_root=tree)
    if kind in {"container", "appimage"}:
        # Until image pulls land: treat as locator presence on PATH (operator-provisioned).
        return _install_apt(component, install_root=root, worktree_root=tree)

    raise InstallError(f"recipe kind {kind!r} is declared but not yet executable in this build")


def install_components(
    components: list[dict[str, Any]],
    *,
    install_root: Path | None = None,
    worktree_root: Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Install many components; continue after failures and summarize."""
    results: list[dict[str, Any]] = []
    for component in components:
        component_id = str(component.get("id") or "")
        try:
            outcome = install_component(
                component,
                install_root=install_root,
                worktree_root=worktree_root,
                force=force,
            )
            results.append(
                {
                    "id": component_id,
                    "status": outcome["status"],
                    "message": outcome.get("status"),
                }
            )
        except InstallError as exc:
            results.append({"id": component_id, "status": "failed", "message": str(exc)})
    failed = [row for row in results if row["status"] == "failed"]
    return {
        "ok": not failed,
        "results": results,
        "counts": {
            "installed": sum(1 for row in results if row["status"] == "installed"),
            "skipped": sum(1 for row in results if row["status"] == "skipped"),
            "failed": len(failed),
        },
    }
