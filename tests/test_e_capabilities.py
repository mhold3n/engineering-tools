"""Solver capability registry tests."""

from engineering_tools.e_capabilities import assign_participant, request_capability


def test_compatible_assignment_succeeds() -> None:
    got = assign_participant(
        "calculix",
        physical_region="deformable_solid",
        constitutive_model="linear_elastic",
        fields=["displacement"],
        require_checkpoint=True,
    )
    assert got["status"] == "ok"


def test_compressible_on_incompressible_only_adapter_fails() -> None:
    """CalculiX is not a compressible-fluid adapter."""
    got = assign_participant(
        "calculix",
        physical_region="compressible_fluid",
        require_compressible=True,
    )
    assert got["status"] == "missing"


def test_unsupported_constitutive_is_missing() -> None:
    got = request_capability("calculix", "constitutive_model", "damage_brittle")
    assert got["status"] == "missing"


def test_checkpoint_policy_rejects_adapter_without_restore() -> None:
    # Topology-change is unpublished; checkpoint is required for implicit graphs.
    got = assign_participant(
        "openfoam",
        physical_region="compressible_fluid",
        require_compressible=True,
        require_checkpoint=True,
    )
    assert got["status"] == "ok"
    missing = request_capability("calculix", "topology_change", True)
    assert missing["status"] == "missing"


def test_unknown_adapter_is_broken() -> None:
    got = request_capability("not-a-solver", "compressible", True)
    assert got["status"] == "broken"
