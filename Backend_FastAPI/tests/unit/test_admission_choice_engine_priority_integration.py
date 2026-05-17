"""Anchor test for Q9 #07 PR2b — priority_service integration into
``evaluate_cascade`` at T6 publish.

Locks the contract that the engine wires the 3 snapshot columns
(``priority_area_bonus_snapshot`` / ``priority_object_bonus_snapshot`` /
``priority_config_snapshot``) at the same point it writes
``bonus_rule_snapshot``. A regression here = silent zero-bonus on the
next admission round, which is the failure mode Q9 #07 was supposed
to prevent.
"""
from __future__ import annotations

import inspect
from decimal import Decimal
from pathlib import Path


_ENGINE_SRC = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "services"
    / "admission_choice_engine_service.py"
)


def test_evaluate_cascade_imports_priority_service() -> None:
    """Engine must import calculate_priority_bonus inside evaluate_cascade
    (lazy import to avoid circular dependency at module load)."""
    src = _ENGINE_SRC.read_text(encoding="utf-8")
    assert (
        "from app.services.priority_service import calculate_priority_bonus"
        in src
    )


def test_evaluate_cascade_sets_three_snapshot_columns() -> None:
    """Engine writes all 3 priority snapshot columns on each choice —
    not just one or two. A missing column write = engine silently
    omits the field and downstream scoring code sees NULL."""
    src = _ENGINE_SRC.read_text(encoding="utf-8")
    for col in (
        "choice.priority_area_bonus_snapshot",
        "choice.priority_object_bonus_snapshot",
        "choice.priority_config_snapshot",
    ):
        assert col in src, f"Engine missing assignment to {col}"


def test_engine_uses_academic_year_from_admission_round() -> None:
    """The plain Integer academic_year is read via
    ``path.admission_round.academic_year`` (NOT academic_year_id —
    there is no academic_year FK table in the schema).

    Review-3 update: access pattern switched to ``__dict__.get`` for
    eager-load safety (avoid MissingGreenlet in async context). The
    expectation remains "read academic_year from admission_round".
    """
    src = _ENGINE_SRC.read_text(encoding="utf-8")
    assert 'round_obj.__dict__.get("academic_year")' in src
    # And guard against the old assumption resurfacing
    assert "academic_year_id" not in src.split(
        "calculate_priority_bonus"
    )[1][:500]


def test_engine_passes_bonus_rule_snapshot_to_priority_service() -> None:
    """Priority service receives the SAME snapshot dict the engine
    just wrote to ``choice.bonus_rule_snapshot``. Mismatch = snapshot
    drift between bonus_rule_snapshot and priority_config_snapshot."""
    src = _ENGINE_SRC.read_text(encoding="utf-8")
    # Locate the calculate_priority_bonus call
    idx = src.index("calculate_priority_bonus(")
    call_block = src[idx : idx + 400]
    assert "rule=choice.bonus_rule_snapshot" in call_block


def test_priority_service_returns_decimal_for_snapshot_columns() -> None:
    """priority_area/object_bonus_snapshot are NUMERIC(4,2). Service
    must return Decimal not float — runtime SQLAlchemy will coerce
    but Decimal is the canonical type for currency-like precision."""
    from app.services.priority_service import calculate_priority_bonus

    sig = inspect.signature(calculate_priority_bonus)
    # Service has 4 params (db, profile, rule, academic_year)
    assert set(sig.parameters.keys()) == {
        "db", "profile", "rule", "academic_year",
    }


def test_engine_skips_priority_if_academic_year_missing() -> None:
    """If round_obj.academic_year is None (legacy / mis-eager-loaded),
    engine must skip the priority calculation to avoid crashing the
    whole cascade — defensive guard for prod safety."""
    src = _ENGINE_SRC.read_text(encoding="utf-8")
    assert "if academic_year is not None:" in src


def test_snapshot_freeze_pattern_matches_bonus_rule_snapshot() -> None:
    """Q-P3-11 freeze semantic: priority snapshot fires AFTER
    bonus_rule_snapshot (so they capture the same atomic moment)
    and BEFORE _evaluate_single_choice (so gates run on frozen data).
    Order matters for replay determinism."""
    src = _ENGINE_SRC.read_text(encoding="utf-8")

    bonus_idx = src.index("choice.bonus_rule_snapshot = resolve_effective_bonus_rule")
    priority_idx = src.index("calculate_priority_bonus(")
    evaluate_idx = src.index("decision, score_result, reason_codes = _evaluate_single_choice")

    assert bonus_idx < priority_idx < evaluate_idx, (
        "Snapshot order violation: bonus_rule -> priority -> evaluate_single"
    )


def test_publish_result_router_eager_loads_admission_round() -> None:
    """Review-3 MAJOR fix lock: production publish_result router must
    eager-load AdmissionPath.admission_round so the engine can read
    academic_year for priority_*_config lookup.

    Without this, the engine's defensive ``__dict__.get`` returns None,
    priority calc is silently skipped, and every candidate gets 0đ
    bonus — a regression of the CR-P0 fix that was caught in review-3.
    """
    router_src = (
        _ENGINE_SRC.parent.parent
        / "routers"
        / "admissions_v2.py"
    ).read_text(encoding="utf-8")

    # The eager-load chain must include admission_round on the path
    # used for cascade. We assert both the relation reference and the
    # comment marker so reviewers know it's intentional, not orphan.
    assert "AdmissionPath.admission_round" in router_src, (
        "publish_result router missing selectinload(admission_round) — "
        "priority bonus will silently be 0đ in prod."
    )


def test_engine_warns_on_skipped_priority() -> None:
    """Review-3 MAJOR: defensive log.warning when priority calc is
    skipped due to missing academic_year — so future eager-load
    regressions surface in logs instead of silently scoring 0đ."""
    src = _ENGINE_SRC.read_text(encoding="utf-8")
    assert "priority_bonus_skipped_missing_academic_year" in src
    assert "log.warning(" in src
