"""Normalize scenario --coupling / --fsi. Comments for other agents: unknown tokens are broken, not missing."""

from __future__ import annotations

from dataclasses import dataclass


IMPLEMENTED = frozenset({"c"})


@dataclass(frozen=True)
class CouplingRequest:
    token: str | None
    status: str | None
    detail: str


def parse_coupling_flags(*, coupling: str | None, fsi: bool) -> CouplingRequest:
    if fsi and coupling is not None and coupling != "c":
        return CouplingRequest(None, "broken", "conflicting --fsi and --coupling")
    token = "c" if fsi or coupling == "c" else coupling
    if token is None:
        return CouplingRequest(None, None, "c not requested")
    if token not in IMPLEMENTED:
        return CouplingRequest(None, "broken", f"unknown coupling: {token}")
    return CouplingRequest("c", "ok", "coupling c")
