"""Break campaign and coupled-point campaign.

Agents: run_break_campaign is the fixed refusal table. Do not add a row
while a current row's observed field differs from required.
run_coupled_campaign is a list of session points. Each point has its own
directory and calls run_e_session. The record keeps probes, mapping_error,
completed_windows, and e_ok. An edge is a change in one of those fields
between neighbors. engineering is true only when the session is live and
e_ok. A PATH mock walks the loop and stays engineering false.
"""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any, Callable

from engineering_tools.e_interaction import interaction_step
from engineering_tools.e_mesh_solid import write_solid_geo

DEBUG_KEYS = (
    "id",
    "axis",
    "call",
    "inputs",
    "required",
    "observed",
    "returned",
    "exception_type",
    "exception_message",
    "site",
    "traceback",
    "evidence",
)

Invoke = Callable[[Path], Any]
Evidence = Callable[[Path], dict[str, Any]]


def _observe_bool(result: Any) -> str:
    """False is a refusal. True is acceptance. Anything else is other."""
    if result is False:
        return "refused"
    if result is True:
        return "accepted"
    return "other"


def _observe_step(result: Any) -> str:
    """Callers branch on status. broken is a refusal. ok is acceptance."""
    if not isinstance(result, dict):
        return "other"
    status = result.get("status")
    if status == "broken":
        return "refused"
    if status == "ok":
        return "accepted"
    return "other"


def _returned(result: Any) -> Any:
    """JSON-safe view of a normal return. Exceptions stay out of this field."""
    if isinstance(result, dict):
        summary: dict[str, Any] = {"status": result.get("status")}
        if "detail" in result:
            summary["detail"] = result["detail"]
        return summary
    if isinstance(result, bool):
        return result
    return repr(result)


def _declared_site(fn: Invoke) -> str:
    code = fn.__code__
    return f"{Path(code.co_filename).name}:{code.co_firstlineno}"


def _raised_site(tb: Any) -> str:
    """Deepest project frame. That line is the first place the call blew up."""
    frames = traceback.extract_tb(tb)
    chosen = frames[-1]
    for frame in frames:
        if "engineering_tools" in frame.filename:
            chosen = frame
    return f"{Path(chosen.filename).name}:{chosen.lineno}"


def _negative_element_size(work: Path) -> bool:
    return write_solid_geo(work / "solid.geo", h_max=-1.0)


def _geo_evidence(work: Path) -> dict[str, bool]:
    return {"geo_exists": (work / "solid.geo").is_file()}


def _scalar_force(_work: Path) -> dict[str, Any]:
    return interaction_step(wall_items=[{"name": "force", "value": 10, "unit": "N"}])


def _infinite_window(_work: Path) -> dict[str, Any]:
    return interaction_step(stop_rule="dynamic", window_dt_s=float("inf"), fluid_dt_s=1.0)


def _legal_force(_work: Path) -> dict[str, Any]:
    return interaction_step(wall_items=[{"name": "force", "value": [0.0, 0.0, 1.0], "unit": "N"}])


# The first three rows are the current breaks. The last row is the legal
# control. Append a new break only after every current row matches required.
BREAK_PROBES: tuple[dict[str, Any], ...] = (
    {
        "id": "negative-element-size",
        "axis": "dimension",
        "call": "engineering_tools.e_mesh_solid.write_solid_geo",
        "inputs": {"h_max": -1.0},
        "required": "refused",
        "invoke": _negative_element_size,
        "observe": _observe_bool,
        "evidence": _geo_evidence,
        "target": write_solid_geo,
    },
    {
        "id": "scalar-force",
        "axis": "magnitude",
        "call": "engineering_tools.e_interaction.interaction_step",
        "inputs": {"name": "force", "value": 10, "unit": "N"},
        "required": "refused",
        "invoke": _scalar_force,
        "observe": _observe_step,
        "evidence": lambda _work: {},
        "target": interaction_step,
    },
    {
        "id": "infinite-dynamic-window",
        "axis": "transient",
        "call": "engineering_tools.e_interaction.interaction_step",
        "inputs": {"stop_rule": "dynamic", "window_dt_s": "inf", "fluid_dt_s": 1.0},
        "required": "refused",
        "invoke": _infinite_window,
        "observe": _observe_step,
        "evidence": lambda _work: {},
        "target": interaction_step,
    },
    {
        "id": "legal-force",
        "axis": "magnitude",
        "call": "engineering_tools.e_interaction.interaction_step",
        "inputs": {"name": "force", "value": [0.0, 0.0, 1.0], "unit": "N"},
        "required": "accepted",
        "invoke": _legal_force,
        "observe": _observe_step,
        "evidence": lambda _work: {},
        "target": interaction_step,
    },
)


def run_break_campaign(destination: Path) -> list[dict[str, Any]]:
    """Run every probe. Write the record even when a probe misses required."""
    records: list[dict[str, Any]] = []
    root = destination.parent / f"{destination.stem}-work"
    for probe in BREAK_PROBES:
        work = root / str(probe["id"])
        work.mkdir(parents=True, exist_ok=True)
        returned: Any = None
        exception_type = None
        exception_message = None
        trace = None
        site = _declared_site(probe["target"])
        try:
            returned = probe["invoke"](work)
            observed = probe["observe"](returned)
        except Exception as exc:
            observed = "raised"
            exception_type = type(exc).__name__
            exception_message = str(exc)
            trace = traceback.format_exc()
            site = _raised_site(exc.__traceback__)
        records.append(
            {
                "id": probe["id"],
                "axis": probe["axis"],
                "call": probe["call"],
                "inputs": probe["inputs"],
                "required": probe["required"],
                "observed": observed,
                "returned": None if observed == "raised" else _returned(returned),
                "exception_type": exception_type,
                "exception_message": exception_message,
                "site": site,
                "traceback": trace,
                "evidence": probe["evidence"](work),
            }
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    return records


# Fields a neighbor compare can see. Status text is not one of them.
COUPLED_FIELDS = ("probes", "mapping_error", "completed_windows", "e_ok")


def _completed_windows(session: dict[str, Any]) -> Any:
    """Window count from the session discretization. Missing stays None."""
    discretization = session.get("discretization")
    if isinstance(discretization, dict) and "completed_windows" in discretization:
        return discretization["completed_windows"]
    return session.get("completed_windows")


def _same_json(left: Any, right: Any) -> bool:
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def _point_record(point: dict[str, Any], session: dict[str, Any], directory: Path) -> dict[str, Any]:
    """One coupled point. engineering requires a live session with e_ok."""
    engineering = bool(session.get("e_ok") and session.get("live") and session.get("status") == "ok")
    return {
        "id": str(point["id"]),
        "inputs": {
            "h_max": point.get("h_max", 0.012),
            "physical_time_s": point.get("physical_time_s", 0.02),
            "time_window_s": point.get("time_window_s", 0.01),
        },
        "directory": str(directory),
        "status": session.get("status"),
        "live": bool(session.get("live")),
        "e_ok": bool(session.get("e_ok")),
        "probes": session.get("probes"),
        "mapping_error": session.get("mapping_error"),
        "completed_windows": _completed_windows(session),
        "engineering": engineering,
    }


def _neighbor_edge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any] | None:
    """A change in a coupled field. Mock sessions cannot make it engineering."""
    changed = [field for field in COUPLED_FIELDS if not _same_json(left[field], right[field])]
    if not changed:
        return None
    return {
        "left": left["id"],
        "right": right["id"],
        "changed": changed,
        "engineering": bool(left["engineering"] and right["engineering"]),
    }


def run_coupled_campaign(destination: Path, points: list[dict[str, Any]]) -> dict[str, Any]:
    """Run each point through run_e_session. Write the point list and edges.

    run_e_session is the path into run_coupled_participants. A point that
    fails before that call is still a record, with the missing fields null.
    """
    from engineering_tools.e_facade import run_e_session
    from engineering_tools.e_scenario import reference_model

    model = reference_model()
    root = destination.parent / f"{destination.stem}-points"
    records: list[dict[str, Any]] = []
    for point in points:
        directory = root / str(point["id"])
        session = run_e_session(
            directory,
            model,
            h_max=float(point.get("h_max", 0.012)),
            physical_time_s=float(point.get("physical_time_s", 0.02)),
            time_window_s=float(point.get("time_window_s", 0.01)),
        )
        records.append(_point_record(point, session, directory))
    edges = []
    for left, right in zip(records, records[1:]):
        edge = _neighbor_edge(left, right)
        if edge is not None:
            edges.append(edge)
    report = {"points": records, "edges": edges}
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report
