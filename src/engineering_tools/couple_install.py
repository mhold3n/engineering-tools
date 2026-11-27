"""Ubuntu 24.04 live-couple install, beside the hello apt recipes.

Agents: hello `calculix` stays `calculix-ccx` and hello `openfoam` stays the
distro package. This module installs the ESI couple the live session already
checks. It is not an install wave. The Python package stays a separate pip
command. The ESI repo bootstrap is recorded and is not executed here.
"""

from __future__ import annotations

import json
import platform
import shlex
import shutil
import subprocess
import tarfile
from importlib import resources
from pathlib import Path
from typing import Any, Callable

from .c_adapter_calculix import find_calculix_participant
from .c_backend_precice import find_precice
from .e_adapter_openfoam import _ESI_FOAM
from .install import InstallError, _fetch_artifact, _utc_now
from .verification import installations_path, upsert_installation

# Stable id. Install waves must not gain this name.
COUPLE_ID = "ubuntu-24.04-couple"
# Fields taken from https://dl.openfoam.com/add-debian-repo.sh on 2026-11-23.
# The script writes this key and this noble amd64 source. The installer records
# them and does not execute the script.
DOCUMENTED_BOOTSTRAP_URL = "https://dl.openfoam.com/add-debian-repo.sh"
DOCUMENTED_PUBKEY_URL = "https://dl.openfoam.com/pubkey.gpg"
DOCUMENTED_PUBKEY_PATH = "/etc/apt/trusted.gpg.d/openfoam.gpg"
DOCUMENTED_SOURCE_PATH = "/etc/apt/sources.list.d/openfoam.list"
DOCUMENTED_SOURCE_LINE = "deb [arch=amd64] https://dl.openfoam.com/repos/deb noble main"
# Hello recipe packages. Selecting either one here would retarget the couple.
_HELLO_PACKAGES = frozenset({"openfoam", "calculix-ccx"})
# VM smoke stays unrun until this tree is what an Ubuntu 24.04 host clones.
VM_SMOKE = "not_run"
# Official v1.4.0 archive for OpenFOAM v1812 through v2606. ESI 2512 is in that
# range. The release is source; Allwmake produces the function-object library.
# The site lib is on the ESI bashrc LD_LIBRARY_PATH for every user. A build
# into FOAM_USER_LIBBIN would be visible only to the account that compiled it.
ADAPTER_ARCHIVE_NAME = "openfoam-adapter-1.4.0-OpenFOAMv1812-v2606-newer.tar.gz"
ADAPTER_LIBRARY = Path(
    "/usr/lib/openfoam/openfoam2512/site/2512/platforms/"
    "linux64GccDPInt32Opt/lib/libpreciceAdapterFunctionObject.so"
)

Host = dict[str, str]
Runner = Callable[[list[str]], int]
Fetcher = Callable[[str, Path], None]
Probe = Callable[[], dict[str, bool]]


def load_couple_requirements() -> dict[str, Any]:
    """Load and validate the packaged Ubuntu 24.04 couple list."""
    root = resources.files("engineering_tools")
    text = (root / "data" / "couple-ubuntu-24.04.json").read_text(encoding="utf-8")
    data = json.loads(text)
    validate_couple_requirements(data)
    return data


def validate_couple_requirements(data: dict[str, Any]) -> None:
    """Reject an empty package or URL, a hello package, or the 2.20.1 adapter pin.

    The 2.20.1 noble adapter deb depends on libprecice2. The couple pin is 2.20.2.
    """
    if not isinstance(data, dict) or data.get("id") != COUPLE_ID:
        raise InstallError(f"couple list id must be {COUPLE_ID!r}")
    _require_text(data.get("os"), "os")
    _require_text(data.get("version_id"), "version_id")
    python_package = data.get("python_package") or {}
    argv = python_package.get("argv")
    if python_package.get("installer") != "pip" or argv != ["pip", "install", "-e", ".[dev]"]:
        raise InstallError("python package install must stay pip install -e \".[dev]\"")
    for entry in _entries(data.get("archive"), "archive"):
        _reject_package(entry.get("package"), "archive package")
    foam = data.get("openfoam") or {}
    _reject_package(foam.get("package"), "openfoam package")
    if foam.get("package") != "openfoam2512-default":
        raise InstallError("couple OpenFOAM package must be openfoam2512-default")
    bootstrap = foam.get("bootstrap") or {}
    if bootstrap.get("url") != DOCUMENTED_BOOTSTRAP_URL:
        raise InstallError("OpenFOAM bootstrap URL is not the documented ESI script")
    if bootstrap.get("pubkey_url") != DOCUMENTED_PUBKEY_URL:
        raise InstallError("OpenFOAM bootstrap key is not the documented pubkey.gpg")
    if bootstrap.get("pubkey_path") != DOCUMENTED_PUBKEY_PATH:
        raise InstallError("OpenFOAM bootstrap key path is not the documented trusted.gpg path")
    if bootstrap.get("source_path") != DOCUMENTED_SOURCE_PATH:
        raise InstallError("OpenFOAM apt source path is not the documented openfoam.list path")
    if bootstrap.get("source_line") != DOCUMENTED_SOURCE_LINE:
        raise InstallError("OpenFOAM apt source line is not the documented noble amd64 entry")
    if bootstrap.get("executed_by_installer") is not False:
        raise InstallError("OpenFOAM bootstrap must stay unexecuted by the installer")
    debs = _entries(data.get("debs"), "debs")
    for entry in debs:
        _reject_package(entry.get("package"), "deb package")
        _require_text(entry.get("url"), "deb url")
    adapter = _deb(debs, "calculix-adapter")
    if adapter.get("version") != "2.20.2" or "2.20.1" in str(adapter.get("url")):
        raise InstallError("CalculiX adapter pin must be 2.20.2, not 2.20.1")
    precice = _deb(debs, "precice")
    if precice.get("package") != "libprecice3" or not str(precice.get("url")).endswith(
        "libprecice3_3.5.0_noble.deb"
    ):
        raise InstallError("preCICE deb must be the noble libprecice3 3.5.0 package")
    archive_packages = {entry.get("package") for entry in _entries(data.get("archive"), "archive")}
    if "pkgconf" not in archive_packages:
        raise InstallError("couple archive must include pkgconf so Allwmake can see libprecice")
    foam_adapter = data.get("openfoam_adapter") or {}
    if foam_adapter.get("version") != "1.4.0":
        raise InstallError("OpenFOAM adapter pin must be 1.4.0")
    if not str(foam_adapter.get("url") or "").endswith(ADAPTER_ARCHIVE_NAME):
        raise InstallError("OpenFOAM adapter URL is not the v1.4.0 OpenFOAM v1812-v2606 archive")
    if foam_adapter.get("library") != ADAPTER_LIBRARY.name:
        raise InstallError("OpenFOAM adapter library must be libpreciceAdapterFunctionObject.so")


def apt_commands(data: dict[str, Any], deb_paths: list[Path]) -> list[list[str]]:
    """Explicit apt argv for the couple. No shell, no curl, no bootstrap script."""
    archive = [str(entry["package"]) for entry in data["archive"]]
    debs = [str(path) for path in deb_paths]
    return [
        ["apt-get", "install", "-y", *archive],
        ["apt-get", "install", "-y", *debs],
        ["apt-get", "install", "-y", str(data["openfoam"]["package"])],
    ]


def current_host() -> Host:
    """Read the running OS. Missing os-release leaves id and version empty."""
    identity: Host = {"system": platform.system(), "id": "", "version_id": ""}
    release = Path("/etc/os-release")
    if not release.is_file():
        return identity
    for line in release.read_text(encoding="utf-8").splitlines():
        if line.startswith("ID="):
            identity["id"] = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("VERSION_ID="):
            identity["version_id"] = line.split("=", 1)[1].strip().strip('"')
    return identity


def default_couple_probe() -> dict[str, bool]:
    """Presence of the locators the live session already requires.

    OpenFOAM counts only as the ESI prefix files. A PATH copy is absent here.
    preCICE uses find_precice (precice-tools, then binprecice, then precice).
    The CalculiX hit must be the ccx_preCICE name, not plain ccx.
    This function does not set ETOOLS_E_MOCK_SOLVERS.
    """
    participant = find_calculix_participant()
    return {
        "rhoPimpleFoam": (_ESI_FOAM / "rhoPimpleFoam").is_file(),
        "gmshToFoam": (_ESI_FOAM / "gmshToFoam").is_file(),
        "ccx_preCICE": participant is not None and participant.name == "ccx_preCICE",
        "precice": find_precice() is not None,
        "gmsh": shutil.which("gmsh") is not None,
        "mpirun": shutil.which("mpirun") is not None,
        "pkg-config": shutil.which("pkg-config") is not None,
        "openfoam_adapter": ADAPTER_LIBRARY.is_file(),
    }


def install_couple(
    *,
    destination: Path,
    worktree_root: Path,
    host: Host | None = None,
    runner: Runner | None = None,
    fetch: Fetcher | None = None,
    probe: Probe | None = None,
) -> dict[str, Any]:
    """Apply the couple list on Ubuntu 24.04. Other hosts get an unavailable result.

    `destination` holds downloaded debs and must sit outside the git worktree.
    A non-Ubuntu host returns before any apt command. A missing locator after
    the Ubuntu commands is a failed install.
    """
    data = load_couple_requirements()
    target = Path(destination).expanduser()
    tree = Path(worktree_root).expanduser()
    assert_destination_outside_worktree(target, tree)
    identity = host if host is not None else current_host()
    if not _ubuntu_2404(identity):
        return {
            "status": "unavailable",
            "apt_attempted": False,
            "message": (
                "The live couple installs on Ubuntu 24.04. "
                "This host keeps the Python package install and leaves the couple uninstalled."
            ),
            "python_package": list(data["python_package"]["argv"]),
            "vm_smoke": VM_SMOKE,
        }
    receipt_path = installations_path()
    assert_destination_outside_worktree(receipt_path, tree)
    target.mkdir(parents=True, exist_ok=True)
    fetch_deb = fetch or _fetch_artifact
    deb_paths: list[Path] = []
    for entry in data["debs"]:
        deb_path = target / Path(str(entry["url"])).name
        fetch_deb(str(entry["url"]), deb_path)
        deb_paths.append(deb_path)
    commands = apt_commands(data, deb_paths)
    _reject_shell_bootstrap(commands)
    run = runner or _apt_runner
    for argv in commands:
        if run(list(argv)) != 0:
            return {
                "status": "failed",
                "apt_attempted": True,
                "message": f"couple command failed: {' '.join(argv)}",
                "vm_smoke": VM_SMOKE,
            }
    built = _install_openfoam_adapter(data, target, fetch_deb, run)
    if built is not None:
        return built
    present = (probe or default_couple_probe)()
    missing = [name for name, found in present.items() if not found]
    if missing:
        return {
            "status": "failed",
            "apt_attempted": True,
            "missing": missing,
            "message": "couple locators missing: " + ", ".join(missing),
            "vm_smoke": VM_SMOKE,
        }
    receipt = {
        "locator": str(_ESI_FOAM / "rhoPimpleFoam"),
        "immutable_id": f"couple:{COUPLE_ID}",
        "integrity_verified": True,
        "recipe_id": COUPLE_ID,
        "installed_at": _utc_now(),
        "package": data["openfoam"]["package"],
        "vm_smoke": VM_SMOKE,
    }
    written = upsert_installation(COUPLE_ID, receipt)
    return {
        "status": "installed",
        "apt_attempted": True,
        "missing": [],
        "message": "couple locators present",
        "receipt_path": str(written),
        "vm_smoke": VM_SMOKE,
    }


def assert_destination_outside_worktree(target: Path, worktree_root: Path) -> None:
    """Same refusal as the component installer: no debs inside the checkout."""
    from .install import assert_outside_worktree

    assert_outside_worktree(target, worktree_root)


def _ubuntu_2404(host: Host) -> bool:
    """True only for Ubuntu 24.04. Other Linux releases stay unavailable."""
    return host.get("system") == "Linux" and host.get("id") == "ubuntu" and host.get("version_id") == "24.04"


def _entries(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise InstallError(f"{label} must be a nonempty list")
    return value


def _require_text(value: Any, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise InstallError(f"{label} is empty")


def _reject_package(value: Any, label: str) -> None:
    _require_text(value, label)
    if value in _HELLO_PACKAGES:
        raise InstallError(f"{label} selected hello package {value!r}")


def _deb(entries: list[dict[str, Any]], entry_id: str) -> dict[str, Any]:
    for entry in entries:
        if entry.get("id") == entry_id:
            return entry
    raise InstallError(f"couple list is missing deb {entry_id}")


def adapter_build_argv(source_dir: Path, target_dir: Path) -> list[str]:
    """Allwmake under the ESI bashrc, installing into the shared site lib.

    Agents: this is not an apt command and it is not the ESI bootstrap script.
    FOAM_USER_LIBBIN is per account. The site directory is already on the
    bashrc library path, so the etools user can load what root compiled.
    """
    bashrc = "/usr/lib/openfoam/openfoam2512/etc/bashrc"
    # `set -u` or `pipefail` before this source aborts inside the ESI bashrc
    # (`pop_var_context`). Allwmake has its own `set -e -u` after the environment exists.
    script = " ".join(
        [
            "set +u;",
            f". {shlex.quote(bashrc)};",
            f"cd {shlex.quote(str(source_dir))};",
            f"export PRECICE_OPENFOAM_TARGET_DIR={shlex.quote(str(target_dir))};",
            "./Allwmake",
        ]
    )
    return ["bash", "--noprofile", "--norc", "-c", script]


def _extract_adapter(archive: Path, destination: Path) -> Path:
    """Extract the pinned adapter archive and return the directory with Allwmake.

    Agents: members that resolve outside `destination` are refused. The
    official tarball has one top directory; the Allwmake search does not
    assume that directory's name.
    """
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            target = (root / member.name).resolve()
            if target != root and root not in target.parents:
                raise InstallError("OpenFOAM adapter archive path escapes the destination")
        extract_kwargs = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        tar.extractall(destination, **extract_kwargs)
    found = [path for path in destination.rglob("Allwmake") if path.is_file()]
    if len(found) != 1:
        raise InstallError("OpenFOAM adapter archive did not contain one Allwmake")
    return found[0].parent


def _install_openfoam_adapter(
    data: dict[str, Any],
    target: Path,
    fetch: Callable[[str, Path], None],
    run: Callable[[list[str]], int],
) -> dict[str, Any] | None:
    """Build libpreciceAdapterFunctionObject.so when the site lib lacks it.

    Agents: a present library skips the build. Tests inject `run` and cannot
    create `/usr/lib/openfoam`; that mkdir failure is a failed install only
    for the real apt runner. None means the caller should continue to the
    locator probe.
    """
    if ADAPTER_LIBRARY.is_file():
        return None
    entry = data["openfoam_adapter"]
    archive = target / ADAPTER_ARCHIVE_NAME
    fetch(str(entry["url"]), archive)
    try:
        source = _extract_adapter(archive, target / "openfoam-adapter-src")
    except (InstallError, tarfile.TarError, OSError) as exc:
        return {
            "status": "failed",
            "apt_attempted": True,
            "message": f"OpenFOAM adapter archive: {exc}",
            "vm_smoke": VM_SMOKE,
        }
    try:
        ADAPTER_LIBRARY.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        if run is _apt_runner:
            return {
                "status": "failed",
                "apt_attempted": True,
                "message": f"OpenFOAM adapter library directory: {exc}",
                "vm_smoke": VM_SMOKE,
            }
    if run(adapter_build_argv(source, ADAPTER_LIBRARY.parent)) != 0:
        return {
            "status": "failed",
            "apt_attempted": True,
            "message": "OpenFOAM adapter Allwmake failed",
            "vm_smoke": VM_SMOKE,
        }
    return None


def _reject_shell_bootstrap(commands: list[list[str]]) -> None:
    """The documented ESI script is not an apt argument and is not piped."""
    banned = {"curl", "wget", "bash", "sh", "sudo"}
    for argv in commands:
        names = {Path(arg).name for arg in argv}
        if names & banned or any("|" in arg for arg in argv):
            raise InstallError("couple commands must be apt-get installs, not a bootstrap shell")
        if DOCUMENTED_BOOTSTRAP_URL in argv:
            raise InstallError("couple commands must not execute the OpenFOAM bootstrap URL")


def _apt_runner(argv: list[str]) -> int:
    """Run one apt-get argv. Tests inject a runner and never reach this."""
    completed = subprocess.run(argv, check=False)
    return completed.returncode
