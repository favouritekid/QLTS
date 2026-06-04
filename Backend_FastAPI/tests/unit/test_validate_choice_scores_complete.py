"""Unit tests — ``validate_choice_scores_complete`` (P0 hotfix multi-NV).

Pure SimpleNamespace stubs (no DB). Pins the per-NV *data-completeness*
submit-gate contract (plan "P0 Hotfix Multi-NV"):

  * gate = for every choice: ``|submitted ∩ allowed| ≥ required`` AND every
    counted score is valid numeric/range.
  * **NO** ``min_score`` / sàn check — that is the T6 publish per-NV cascade.
  * config-gap (``allowed == []``) → fail-closed.
  * best_n (``required_subject_count < len(allowed)``) → no over-block.

Non-tautological per memory ``pattern-change-impact-audit``: each test pins a
specific return shape / message substring, not merely "callable".
"""
from decimal import Decimal
from types import SimpleNamespace

from app.services.admission_choice_engine_service import (
    validate_choice_scores_complete,
)


def _choice(
    display_order,
    allowed_codes,
    scores,
    *,
    criteria_required=None,
    criteria_mode=None,
):
    """Build a stub AdmissionProfileChoice.

    Args:
        display_order: NV order (1-based).
        allowed_codes: subject codes in the combo (subject_group mappings).
        scores: list[(code, value, max_score_snapshot)].
        criteria_required / criteria_mode: when set, attach a per-choice
            ``admission_path.criteria`` (so the helper reads it instead of
            the profile snapshot). Left unset → no admission_path → helper
            falls back to applied_rules.
    """
    mappings = [
        SimpleNamespace(subject=SimpleNamespace(code=c)) for c in allowed_codes
    ]
    config = SimpleNamespace(
        subject_group=SimpleNamespace(subject_mappings=mappings)
    )
    score_rows = [
        SimpleNamespace(
            subject=SimpleNamespace(code=c),
            score=v,
            max_score_snapshot=m,
        )
        for (c, v, m) in scores
    ]
    admission_path = None
    if criteria_required is not None or criteria_mode is not None:
        admission_path = SimpleNamespace(
            criteria=SimpleNamespace(
                required_subject_count=criteria_required,
                subject_selection_mode=criteria_mode,
            )
        )
    return SimpleNamespace(
        display_order=display_order,
        path_subject_group_config=config,
        scores=score_rows,
        admission_path=admission_path,
    )


def test_complete_two_choices_below_floor_returns_no_error():
    """(1) NV1 đủ + NV2 đủ-nhưng-dưới-sàn → [] (helper KHÔNG xét min_score)."""
    nv1 = _choice(
        1,
        ["TOAN", "VAN"],
        [("TOAN", Decimal("8.0"), Decimal("10")),
         ("VAN", Decimal("7.0"), Decimal("10"))],
    )
    # NV2 data-complete nhưng điểm rất thấp (dưới mọi sàn). Helper chỉ check
    # data-complete → vẫn pass (contract: "nộp" ≠ "trúng tuyển").
    nv2 = _choice(
        2,
        ["TOAN", "VAN"],
        [("TOAN", Decimal("1.0"), Decimal("10")),
         ("VAN", Decimal("1.0"), Decimal("10"))],
    )
    assert validate_choice_scores_complete([nv1, nv2], {}) == []


def test_missing_subject_returns_one_error_naming_nv_and_subject():
    """(2) NV2 thiếu 1 môn tổ hợp → đúng 1 lỗi nêu NV2 + môn thiếu."""
    nv1 = _choice(
        1,
        ["TOAN", "VAN"],
        [("TOAN", Decimal("8"), Decimal("10")),
         ("VAN", Decimal("7"), Decimal("10"))],
    )
    nv2 = _choice(
        2,
        ["TOAN", "VAN"],
        [("TOAN", Decimal("8"), Decimal("10"))],  # VAN missing
    )
    errs = validate_choice_scores_complete([nv1, nv2], {})
    assert len(errs) == 1
    assert "NV2" in errs[0]
    assert "VAN" in errs[0]


def test_zero_choices_returns_empty():
    """(3) 0 choice → [] (≥1-choice gate enforced bởi caller, not helper)."""
    assert validate_choice_scores_complete([], {}) == []


def test_out_of_range_score_returns_error():
    """(4) Điểm > max_score_snapshot → lỗi 'không hợp lệ' nêu môn."""
    nv1 = _choice(1, ["TOAN"], [("TOAN", Decimal("11.0"), Decimal("10"))])
    errs = validate_choice_scores_complete([nv1], {})
    assert any("không hợp lệ" in e and "TOAN" in e for e in errs)


def test_negative_score_returns_error():
    """(4b) Điểm < 0 → lỗi 'không hợp lệ'."""
    nv1 = _choice(1, ["TOAN"], [("TOAN", Decimal("-1"), Decimal("10"))])
    errs = validate_choice_scores_complete([nv1], {})
    assert any("không hợp lệ" in e for e in errs)


def test_config_gap_empty_allowed_fail_closed():
    """(5) Config-gap allowed==[] → fail-closed 'tổ hợp chưa cấu hình môn'."""
    nv1 = _choice(1, [], [])  # subject_group has no mappings
    errs = validate_choice_scores_complete([nv1], {})
    assert len(errs) == 1
    assert "NV1" in errs[0]
    assert "chưa cấu hình môn" in errs[0]


def test_best_n_required_less_than_allowed_no_overblock():
    """(6) best_n: required_subject_count=2 < allowed=3, nhập đủ 2 → pass."""
    nv1 = _choice(
        1,
        ["TOAN", "VAN", "ANH"],
        [("TOAN", Decimal("8"), Decimal("10")),
         ("VAN", Decimal("7"), Decimal("10"))],  # 2 of 3 entered
    )
    applied = {"required_subject_count": 2, "subject_selection_mode": "best_n"}
    assert validate_choice_scores_complete([nv1], applied) == []


def test_best_n_below_required_still_blocks():
    """(6b) best_n: required=2 nhưng chỉ nhập 1 → vẫn báo thiếu (đúng gate)."""
    nv1 = _choice(
        1,
        ["TOAN", "VAN", "ANH"],
        [("TOAN", Decimal("8"), Decimal("10"))],  # only 1 of required 2
    )
    applied = {"required_subject_count": 2, "subject_selection_mode": "best_n"}
    errs = validate_choice_scores_complete([nv1], applied)
    assert len(errs) == 1
    assert "NV1" in errs[0] and "cần 2" in errs[0]


def test_per_choice_criteria_stricter_than_snapshot_blocks():
    """(7) Mixed criteria — NV2 path criteria stricter than the snapshot.

    applied_rules.required=2, NV2.criteria.required=3, chỉ nhập 2 môn → NV2
    PHẢI fail (gate đọc per-choice criteria, KHÔNG dùng snapshot=2)."""
    nv1 = _choice(
        1,
        ["TOAN", "VAN"],
        [("TOAN", Decimal("8"), Decimal("10")),
         ("VAN", Decimal("7"), Decimal("10"))],
        criteria_required=2,
    )
    nv2 = _choice(
        2,
        ["TOAN", "VAN", "ANH"],
        [("TOAN", Decimal("8"), Decimal("10")),
         ("VAN", Decimal("7"), Decimal("10"))],  # 2 entered, criteria needs 3
        criteria_required=3,
    )
    errs = validate_choice_scores_complete(
        [nv1, nv2], {"required_subject_count": 2}
    )
    assert len(errs) == 1  # NV1 ok (criteria 2), NV2 fails (criteria 3)
    assert "NV2" in errs[0] and "cần 3" in errs[0]


def test_per_choice_best_n_looser_than_snapshot_passes():
    """(8) Mixed criteria — NV2 path criteria best_n looser than snapshot.

    applied_rules.required=3, NV2.criteria best_n required=2, nhập 2 môn →
    PHẢI pass (gate đọc per-choice criteria, KHÔNG dùng snapshot=3)."""
    nv1 = _choice(
        1,
        ["TOAN", "VAN", "ANH"],
        [("TOAN", Decimal("8"), Decimal("10")),
         ("VAN", Decimal("7"), Decimal("10")),
         ("ANH", Decimal("6"), Decimal("10"))],
        criteria_required=3,
    )
    nv2 = _choice(
        2,
        ["TOAN", "VAN", "ANH"],
        [("TOAN", Decimal("8"), Decimal("10")),
         ("VAN", Decimal("7"), Decimal("10"))],  # 2 of 3, best_n needs 2
        criteria_required=2,
        criteria_mode="best_n",
    )
    errs = validate_choice_scores_complete(
        [nv1, nv2], {"required_subject_count": 3}
    )
    assert errs == []


def test_best_n_out_of_range_extra_blocks_data_integrity():
    """(9) best_n with a VALID best-N PLUS an out-of-range extra → BLOCKS.

    The gate hard-rejects any out-of-range in-combo score (data integrity):
    ``AdmissionScoringService.calculate_score`` does NOT range-check, so an
    out-of-range value must never reach the T6 cascade (best_n could select
    the inflated score). The candidate must fix/remove the bad entry — the
    UI input is range-clamped, so this only fires on API/stale-snapshot data.
    """
    nv1 = _choice(
        1,
        ["TOAN", "VAN", "ANH"],
        [("TOAN", Decimal("8"), Decimal("10")),
         ("VAN", Decimal("7"), Decimal("10")),
         ("ANH", Decimal("11"), Decimal("10"))],  # > max 10 → invalid
        criteria_required=2,
        criteria_mode="best_n",
    )
    errs = validate_choice_scores_complete([nv1], {})
    assert any("không hợp lệ" in e and "ANH" in e for e in errs)


def test_required_zero_falls_back_to_all_subjects():
    """(10) required_subject_count=0 is fail-CLOSED to 'need ALL allowed', NOT
    'zero required'. A choice with 1 of 2 combo subjects entered → blocks."""
    nv1 = _choice(
        1,
        ["TOAN", "VAN"],
        [("TOAN", Decimal("8"), Decimal("10"))],  # only 1 of 2
        criteria_required=0,
    )
    errs = validate_choice_scores_complete([nv1], {})
    assert len(errs) == 1
    assert "NV1" in errs[0] and "cần 2" in errs[0]
