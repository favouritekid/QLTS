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

    # Ca này CHỈ còn vế DƯƠNG TÍNH: import phải tồn tại trong local scope của
    # `evaluate_cascade`. Vế âm ("không được chạy lúc nạp module") ĐÃ BỎ khỏi
    # đây và giao hẳn cho `test_nap_engine_khong_keo_theo_priority_service`.
    #
    # Vì sao bỏ: mọi bản AST của vế âm đều đỏ oan với `if TYPE_CHECKING:` —
    # khối ấy KHÔNG chạy lúc runtime, nhưng AST tĩnh không phân biệt được nó
    # với một `if` thường. Đã đo: TYPE_CHECKING=False mà AST vẫn đánh dấu eager.
    # Đuổi theo bằng cách liệt kê `TYPE_CHECKING` như một ngoại lệ chỉ đẻ ra
    # biến thể kế tiếp (`typing.TYPE_CHECKING`, alias, `if not TYPE_CHECKING`).
    # Phép kiểm runtime trả lời đúng câu hỏi ấy mà không cần biết cú pháp.
    #
    # Vế dương tính thì KHÔNG thay bằng runtime được: gỡ hẳn import đi thì
    # `sys.modules` càng sạch, phép kiểm runtime càng xanh. Nên cần cả hai.
    #
    # Ranh giới dừng ở đây là ranh giới của LOCAL SCOPE, không phải của thứ tự
    # nạp: thân `class` KHÔNG bind vào local của hàm bao — ngữ nghĩa Python,
    # không phải chi tiết cú pháp:
    #
    #     def f():
    #         class C:
    #             from math import sqrt
    #         sqrt(4)          # NameError
    #
    # nên phải dừng ở CẢ class lẫn function/lambda.
    DUNG_KHI_LOCAL = (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.Lambda,
        ast.ClassDef,
    )

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


def test_engine_lay_nam_tu_ho_so_khong_bo_cham() -> None:
    """Owner Q10(a): T6 tra mức theo NĂM TUYỂN SINH của hồ sơ; không còn nhánh "đợt chưa nạp ⇒ bỏ chấm 0đ"."""
    src = _ENGINE_SRC.read_text(encoding="utf-8")
    assert "academic_year = priority_academic_year(profile)" in src
    assert "priority_bonus_skipped_missing_academic_year" not in src
    assert "if academic_year is not None:" not in src


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
    """Router publish-result nạp chuỗi T6 qua MỘT nguồn ``t6_profile_load_options()``, và chuỗi ấy có
    ``AdmissionPath.admission_round`` — T6 so năm đợt với năm hồ sơ (lệch ⇒ ``PriorityYearMismatch``)."""
    router_src = (
        _ENGINE_SRC.parent.parent
        / "routers"
        / "admissions_v2.py"
    ).read_text(encoding="utf-8")
    assert "choice_engine.t6_profile_load_options()" in router_src
    src = _ENGINE_SRC.read_text(encoding="utf-8")
    ham = src[src.index("def t6_profile_load_options()"):src.index("# PR-1 (2026-05-28) — Capacity check helper")]
    assert "AdmissionPath.admission_round" in ham


def test_engine_nam_dot_lech_thi_dung() -> None:
    """Đợt đã nạp mà khác năm hồ sơ ⇒ DỪNG có nhãn (``PriorityYearMismatch``), không chấm theo năm đợt."""
    src = _ENGINE_SRC.read_text(encoding="utf-8")
    assert "raise PriorityYearMismatch(" in src


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
