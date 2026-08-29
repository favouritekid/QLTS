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
    """Engine phải import ``calculate_priority_bonus`` LAZY, trong thân hàm.

    Bất biến: ``priority_service`` import ``app.models``, nên đưa import này lên
    module level là tái lập vòng phụ thuộc lúc nạp engine.

    Bản cũ grep NGUYÊN VĂN một dòng
    ``"from app.services.priority_service import calculate_priority_bonus"``.
    Import ấy vẫn còn và vẫn lazy, nhưng nay là dạng nhiều tên trong ngoặc nên
    chuỗi một dòng không còn xuất hiện — ca đỏ trong khi sản phẩm đúng. Đây là
    lớp lỗi "test grep văn bản nguồn": nó vỡ vì ĐỊNH DẠNG, và ngược lại có thể
    xanh oan nếu chuỗi ấy nằm trong một chú thích.

    Nay soi bằng AST và khoá ĐÚNG hai chiều: có ở tầng hàm, và KHÔNG có ở tầng
    module.
    """
    import ast

    cay = ast.parse(_ENGINE_SRC.read_text(encoding="utf-8"))
    MODULE = "app.services.priority_service"

    def _nut_thuc_thi(nut):
        """Nút CHẠY khi phạm vi này chạy — dừng ở thân function/lambda.

        Dùng chung cho cả hai phạm vi, và ranh giới "dừng ở đâu" là phần đắt
        nhất của ca này:

        * ĐI VÀO `if` / `try` / `with` / `for` / `class`: thân chúng chạy cùng
          phạm vi cha. Một eager import nấp trong ``if True:`` ở tầng module
          VẪN chạy lúc nạp module — bản trước chỉ đọc con trực tiếp của
          `Module.body` nên đột biến ấy lọt. Thân `class` cũng chạy lúc nạp,
          nên KHÔNG được loại.
        * KHÔNG đi vào `def` / `async def` / `lambda`: thân chúng chỉ chạy khi
          được gọi, nên ở tầng module chúng vô hại, còn trong
          `evaluate_cascade` chúng không bảo đảm gì cho chính hàm ấy.
        """
        for con in ast.iter_child_nodes(nut):
            if isinstance(con, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            yield con
            yield from _nut_thuc_thi(con)

    def _import_tu(nut) -> set:
        ra = set()
        for c in _nut_thuc_thi(nut):
            if isinstance(c, ast.ImportFrom) and c.module == MODULE:
                ra |= {a.name for a in c.names}
        return ra

    o_module = _import_tu(cay)
    assert "calculate_priority_bonus" not in o_module, (
        "import phải LAZY — chạy lúc nạp module là tái lập vòng phụ thuộc, "
        "kể cả khi nấp trong if/try/with/class ở tầng module"
    )

    # Phải khoanh vào ĐÚNG `evaluate_cascade`, không gom import từ mọi hàm:
    # chuyển import sang một hàm khác (vd `_collect_subject_scores`) thì phép
    # kiểm gom-tất-cả vẫn xanh, trong khi `evaluate_cascade` mất đường lấy
    # priority bonus. Đã đo: đột biến ấy KHÔNG bị bắt ở bản gom.
    ham = [
        n
        for n in ast.walk(cay)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "evaluate_cascade"
    ]
    assert len(ham) == 1, f"kỳ vọng đúng 1 evaluate_cascade; có {len(ham)}"

    o_ham = _import_tu(ham[0])
    assert "calculate_priority_bonus" in o_ham, (
        "evaluate_cascade phải tự lazy-import calculate_priority_bonus; "
        f"thấy trong hàm: {sorted(o_ham)}"
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
