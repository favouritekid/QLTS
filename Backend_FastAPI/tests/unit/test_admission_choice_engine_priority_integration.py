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

    # HAI phạm vi, HAI ranh giới. Gộp làm một là sai — bản trước đã sai đúng
    # chỗ này. Hai câu hỏi khác nhau về BẢN CHẤT:
    #
    #   (a) "có chạy lúc NẠP MODULE không?"  -> thân `class` CÓ chạy lúc nạp,
    #       nên phải ĐI VÀO ClassDef; chỉ dừng ở function/lambda.
    #
    #   (b) "có bind vào LOCAL của evaluate_cascade không?" -> thân `class`
    #       KHÔNG bind vào local của hàm bao. Đây là ngữ nghĩa Python, không
    #       phải chi tiết cú pháp:
    #
    #           def f():
    #               class C:
    #                   from math import sqrt
    #               sqrt(4)          # NameError
    #
    #       Nên câu (b) phải dừng THÊM ở ClassDef. Nếu không, chuyển import vào
    #       một class lồng trong `evaluate_cascade` sẽ làm test XANH trong khi
    #       production ném NameError.
    DUNG_KHI_NAP = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
    DUNG_KHI_LOCAL = DUNG_KHI_NAP + (ast.ClassDef,)

    def _nut(nut, dung):
        for con in ast.iter_child_nodes(nut):
            if isinstance(con, dung):
                continue
            yield con
            yield from _nut(con, dung)

    def _import_tu(nut, dung) -> set:
        ra = set()
        for c in _nut(nut, dung):
            if isinstance(c, ast.ImportFrom) and c.module == MODULE:
                ra |= {a.name for a in c.names}
        return ra

    o_module = _import_tu(cay, DUNG_KHI_NAP)
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

    o_ham = _import_tu(ham[0], DUNG_KHI_LOCAL)
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


def test_nap_engine_khong_keo_theo_priority_service() -> None:
    """Nạp engine trong TIẾN TRÌNH SẠCH không được kéo `priority_service` vào.

    Đây là vế RUNTIME, bổ sung cho phép kiểm AST ở trên chứ không thay thế nó.
    Hai vế bắt hai thứ khác nhau, và cần cả hai:

      * AST (dương tính): import PHẢI tồn tại trong local scope của
        `evaluate_cascade`. Runtime không nói được điều này — gỡ hẳn import đi
        thì `sys.modules` càng sạch, phép kiểm runtime càng xanh.
      * Runtime (âm tính): nạp module KHÔNG được kéo theo `priority_service`.
        Vế này ĐỘC LẬP CÚ PHÁP — mọi biến thể `if True:` / `try:` / `class` ở
        tầng module đều bị bắt như nhau, không cần liệt kê từng dạng.

    Phải là SUBPROCESS sạch, không phải `importlib` trong tiến trình pytest
    đang chạy: conftest và các ca khác đã nạp sẵn nửa cây phụ thuộc, nên
    `sys.modules` ở đây không nói lên điều gì về thứ tự nạp thật.
    """
    import subprocess
    import sys

    MOC = "KETQUA:"
    ma = (
        "import sys\n"
        "import app.services.admission_choice_engine_service\n"
        "print('" + MOC + "' + ('CO' if 'app.services.priority_service' in sys.modules"
        " else 'KHONG'))\n"
    )
    r = subprocess.run(
        [sys.executable, "-c", ma],
        capture_output=True,
        text=True,
        cwd=str(_ENGINE_SRC.parents[2]),
    )
    assert r.returncode == 0, f"nạp engine hỏng:\n{r.stderr[-1500:]}"

    dong = [x for x in r.stdout.splitlines() if x.startswith(MOC)]
    assert len(dong) == 1, f"không đọc được kết quả; stdout:\n{r.stdout[-800:]}"
    assert dong[0] == MOC + "KHONG", (
        "nạp engine đã kéo `app.services.priority_service` vào sys.modules — "
        "vòng phụ thuộc lúc nạp đã quay lại"
    )
