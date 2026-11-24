# tests/unit/test_gd2b_lan_xet_hop_dong.py
"""GĐ2-B đợt 2 (L3a + L4) — phần hợp đồng API kiểm được KHÔNG cần CSDL (hợp đồng API GĐ2-B bản 4 ``b877fba1…``):

* HĐ1 — 9 route (method + đường dẫn) có trên bảng route THẬT của ``app.main`` với đúng mã thành công (E1 201, E6 202, còn lại 200);
  tên trường request / phản hồi GHIM theo hợp đồng §2, §3 (bảng kỳ vọng gõ TAY — đổi tên một trường ⇒ đỏ).
* HĐ9 — MỌI route trong 9 có CẢ Casbin (``deps.check_permission``) LẪN lớp phụ ``deps.require_review_admin`` trong cây dependency
  (bỏ lớp phụ khỏi một route ⇒ đỏ); giới hạn tần suất đúng thứ tự decorator (``__wrapped__``).
* HĐ10 — không trường / tham số nào kiểu "vượt" (``bypass*`` / ``override*``) ở thân request lẫn tham số truy vấn của 9 route.
* §1.4 — điểm sàn nhận số / chuỗi, ≤ 2 chữ số thập phân, 0–999,99; ``bool`` / mũ / dấu âm ⇒ lỗi.
* §3.1 / §4.2 — ``available_actions`` và cổng ghi E4 / E5 / E6 đi qua MỘT hàm (``session_actions``); AST: dịch vụ chạy kiểm và bộ nạp
  không còn so trạng thái riêng.
* §6.8 — thứ tự khoá của E4 / E5 (đọc năm → khoá năm CHIA SẺ → dòng lần xét; E1 ĐỘC QUYỀN — quyết định owner 23-11) và phép đọc
  sàn ở ``check_academic_info_move_allowed`` (AST — lớp thứ hai; hành vi + chế độ khoá đo bằng hai phiên ở
  ``tests/api/test_gd2b_lan_xet_hai_phien_api.py``).
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from decimal import Decimal

import pytest
from fastapi.routing import APIRoute

pytestmark = pytest.mark.unit

P = "/api/admission-config/review-sessions"
#: Hợp đồng §0 — (method, đường dẫn, mã thành công). Gõ TAY.
CHIN_ROUTE = {
    ("POST", P): 201,
    ("GET", P): 200,
    ("GET", P + "/{session_id}"): 200,
    ("PUT", P + "/{session_id}/floors"): 200,
    ("POST", P + "/{session_id}/cancel"): 200,
    ("POST", P + "/{session_id}/runs"): 202,
    ("GET", P + "/{session_id}/runs"): 200,
    ("GET", P + "/{session_id}/runs/{run_id}"): 200,
    ("GET", P + "/{session_id}/runs/{run_id}/rows"): 200,
}
#: Phụ lục HĐ4 E10 (S1, 24-11) — route thứ mười, chỉ đọc. Gõ TAY. Ca riêng của E10: ``tests/api/test_gd2b_s1_hoc_vu_nhap_san_api.py``.
E10_ROUTE = {("GET", P + "/{session_id}/floor-candidates"): 200}
ROUTE_HOP_DONG = {**CHIN_ROUTE, **E10_ROUTE}


def _route_lan_xet():
    from app.main import fastapi_app

    out = {}
    for r in fastapi_app.routes:
        if isinstance(r, APIRoute) and r.path.startswith(P):
            for m in r.methods:
                out[(m, r.path)] = r
    return out


def test_hd1_dung_9_route_cong_e10_dung_ma_thanh_cong():
    routes = _route_lan_xet()
    assert set(routes) == set(ROUTE_HOP_DONG)
    for k, ma in ROUTE_HOP_DONG.items():
        assert (routes[k].status_code or 200) == ma, k


def _goi_trong_cay(dependant) -> set:
    out = set()
    for dep in dependant.dependencies:
        out.add(dep.call)
        out |= _goi_trong_cay(dep)
    return out


def test_hd9_moi_route_co_casbin_va_lop_phu_chi_admin_va_gioi_han_tan_suat():
    from app.core import deps

    for k, r in _route_lan_xet().items():
        goi = _goi_trong_cay(r.dependant)
        assert deps.check_permission in goi, k
        assert deps.require_review_admin in goi, k
        assert hasattr(r.endpoint, "__wrapped__"), k  # @router.* ĐỨNG TRÊN @limiter.limit (tests/security/test_ratelimit_order_guard.py)


def _truong(model) -> set:
    return set(model.model_fields)


def test_hd1_ghim_ten_truong_request_va_khoa_la_bi_cam():
    from app.schemas import admission_review as s

    ky_vong = {
        s.ReviewSessionCreateIn: {"academic_year", "admission_round_id"},
        s.ReviewFloorsPutIn: {"version", "floors"},
        s.ReviewFloorIn: {"offering_academic_info_id", "floor_score"},
        s.ReviewSessionCancelIn: {"version", "reason"},
        s.ReviewRunCreateIn: {"kind", "session_version"},
    }
    for model, ten in ky_vong.items():
        assert _truong(model) == ten, model.__name__
        assert model.model_config.get("extra") == "forbid", model.__name__


def test_hd1_ghim_ten_truong_phan_hoi():
    from app.schemas import admission_review as s

    ky_vong = {
        s.SessionOut: {
            "id", "academic_year", "admission_round", "seq_no", "status", "version", "created_by_user_id", "created_at",
            "updated_at", "cancelled_by_user_id", "cancelled_at", "cancel_reason", "quota_table", "floors", "latest_run",
            "latest_done_run_id", "available_actions",
        },
        s.AdmissionRoundRefOut: {"id", "round_code", "round_name"},
        s.QuotaTableStateOut: {"status", "version", "quota_fingerprint"},
        s.FloorOut: {
            "offering_academic_info_id", "floor_score", "major_code", "major_name", "offering_type", "annual_admission_quota",
            "group_code", "is_deleted", "updated_by_user_id", "updated_at",
        },
        s.SessionListItemOut: {
            "id", "academic_year", "admission_round", "seq_no", "status", "version", "created_by_user_id", "created_at",
            "floor_count", "latest_run",
        },
        s.RunSummaryOut: {
            "id", "kind", "status", "rule_version", "requested_by_user_id", "requested_at", "finished_at", "duration_ms",
            "tab_counts", "config_changed_since_run",
        },
        s.RunOut: {
            "id", "session_id", "kind", "status", "rule_version", "requested_by_user_id", "requested_at", "started_at",
            "finished_at", "duration_ms", "error_code", "inputs", "summary", "quota_view", "config_changed_since_run",
        },
        s.RunInputsOut: {"academic_year", "session_version", "floors", "quota_table", "fee_gate_mode", "snapshot_at"},
        s.RunSummaryCountsOut: {"rows_total", "pool_total", "tab_counts", "reason_counts", "flag_counts", "warnings"},
        s.QuotaViewOut: {"majors", "groups"},
        s.QuotaViewMajorOut: {
            "offering_academic_info_id", "offering_id", "major_code", "major_name", "offering_type", "group_id", "group_code",
            "annual_admission_quota", "floor_score", "used_publish", "used_approved", "used", "remaining", "state",
            "candidates", "auto", "needs_decision", "offering_inactive", "major_inactive",
        },
        s.QuotaViewGroupOut: {
            "group_id", "code", "name", "ceiling", "used_publish", "used_approved", "used", "auto_in_run",
            "remaining_after_auto", "would_exceed",
        },
        s.RowOut: {
            "profile_id", "full_name", "unit_id", "profile_status", "tab", "reason_codes", "flags", "decision_hints",
            "document_gaps", "considered_choice", "review_total", "score_parts", "floor_score", "rank_in_major", "within_seats",
            "ethnic_priority_state", "per_choice", "prior_year_findings", "row_hash",
        },
        s.ConsideredChoiceOut: {
            "choice_id", "display_order", "offering_academic_info_id", "offering_id", "admission_path_id", "major_code",
            "major_name", "offering_type",
        },
        s.ScorePartsOut: {"subject_total", "area", "object", "priority_total"},
        s.PerChoiceOut: {"choice_id", "display_order", "offering_academic_info_id", "status", "reason_codes", "review_total",
                         "floor_score"},
        s.DocumentGapsOut: {"missing", "not_verified"},
        s.PriorYearFindingOut: {"year", "basis", "status"},
        s.SessionPageOut: {"items", "total", "page", "page_size", "total_pages"},
        s.RunPageOut: {"items", "total", "page", "page_size", "total_pages"},
        s.RowPageOut: {"items", "total", "page", "page_size", "total_pages", "tab_counts"},
    }
    for model, ten in ky_vong.items():
        assert _truong(model) == ten, (model.__name__, sorted(_truong(model) ^ ten))


def test_hd1_ghim_tham_so_truy_van_e2_e7_e9():
    routes = _route_lan_xet()

    def ten(k):
        return {p.name for p in routes[k].dependant.query_params}

    assert ten(("GET", P)) == {"academic_year", "status", "page", "page_size"}
    assert ten(("GET", P + "/{session_id}/runs")) == {"page", "page_size"}
    assert ten(("GET", P + "/{session_id}/runs/{run_id}/rows")) == {
        "tab", "offering_academic_info_id", "reason_code", "flag", "page", "page_size",
    }


def test_hd10_khong_truong_hay_tham_so_vuot_chi_tieu():
    from app.main import fastapi_app

    tai_lieu = fastapi_app.openapi()
    cam = ("bypass", "override", "force", "vuot")
    for (m, duong) in ROUTE_HOP_DONG:
        op = tai_lieu["paths"][duong][m.lower()]
        for p in op.get("parameters", []):
            assert not any(c in p["name"].lower() for c in cam), (m, duong, p["name"])
    from app.schemas import admission_review as s

    for model in (s.ReviewSessionCreateIn, s.ReviewFloorsPutIn, s.ReviewFloorIn, s.ReviewSessionCancelIn, s.ReviewRunCreateIn):
        assert not any(c in f.lower() for f in model.model_fields for c in cam), model.__name__


# ── điểm sàn (hợp đồng §1.4) ─────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "vao, ra",
    [(0, "0.00"), (15, "15.00"), (18.25, "18.25"), (12.5, "12.50"), ("7", "7.00"), ("18.5", "18.50"), (" 18.25 ", "18.25"),
     ("999.99", "999.99"), (999.99, "999.99"), (Decimal("3.10"), "3.10"), (-0.0, "0.00")],
)
def test_diem_san_hop_le(vao, ra):
    from app.schemas.admission_review import parse_floor_score

    assert format(parse_floor_score(vao), "f") == ra


@pytest.mark.parametrize(
    "vao",
    [True, False, None, -1, -0.01, "-1", 1000, 999.995, "1000", "18.255", 18.255, 0.1 + 0.2, "1e1", "abc", "", " ", "0x10",
     float("nan"), float("inf"), Decimal("NaN"), Decimal("1E+3"), [1], {"a": 1}, "١٢"],
)
def test_diem_san_sai(vao):
    from app.schemas.admission_review import parse_floor_score

    with pytest.raises(ValueError):
        parse_floor_score(vao)


# ── available_actions = cổng ghi (một nguồn) ─────────────────────────────────────────────────────────────────────────
def test_thao_tac_theo_trang_thai():
    from app.services.admission_review_service import session_actions

    assert session_actions("draft") == ["edit_floors", "run_evaluate", "cancel"]
    assert session_actions("cancelled") == []
    assert session_actions("locked") == [] and session_actions("") == []  # trạng thái lạ ⇒ rỗng (fail-closed)


@pytest.mark.parametrize("trang_thai", ["cancelled", "locked", "signed", ""])
@pytest.mark.parametrize("thao_tac", ["edit_floors", "run_evaluate", "cancel"])
def test_cong_ghi_tu_choi_khi_khong_con_thao_tac(trang_thai, thao_tac):
    from app.services import admission_review_errors as e
    from app.services.admission_review_service import require_session_action

    with pytest.raises(e.ReviewConflict) as loi:
        require_session_action(trang_thai, thao_tac)
    assert loi.value.reason_code == "review_session_not_draft"
    assert loi.value.public_payload == {"reason_code": "review_session_not_draft", "status": trang_thai}


def test_cong_ghi_cho_qua_khi_nhap():
    from app.services.admission_review_service import require_session_action

    for thao_tac in ("edit_floors", "run_evaluate", "cancel"):
        require_session_action("draft", thao_tac)


def _ast_ham(mod, ten):
    goc = textwrap.dedent(inspect.getsource(mod))
    for nut in ast.walk(ast.parse(goc)):
        if isinstance(nut, (ast.FunctionDef, ast.AsyncFunctionDef)) and nut.name == ten:
            return nut
    raise AssertionError("không thấy hàm %s" % ten)


def _ten_goi(nut) -> list:
    """Tên các lời gọi trong thân hàm theo THỨ TỰ xuất hiện trong mã (``a.b(...)`` ⇒ ``b``)."""
    out = []
    for n in ast.walk(nut):
        if isinstance(n, ast.Call):
            f = n.func
            out.append((n.lineno, n.col_offset, f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)))
    return [t for _, _, t in sorted(out)]


def test_ast_chay_kiem_va_bo_nap_dung_chung_cong_require_session_action():
    """CLAUDE.md §7: cổng "lần xét còn chạy được" của E6 (bước 1, bước ghi, và ảnh chụp của bộ nạp) đi qua ĐÚNG
    ``require_session_action`` — không còn so ``REVIEW_SESSION_DRAFT`` riêng."""
    from app.services import admission_review_loader as loader
    from app.services import admission_review_run_service as run_service

    for mod, ten, so in ((run_service, "run_evaluate", 2), (loader, "load_run_facts", 1)):
        nut = _ast_ham(mod, ten)
        assert _ten_goi(nut).count("require_session_action") == so, (mod.__name__, ten)
        assert "REVIEW_SESSION_DRAFT" not in ast.unparse(nut), (mod.__name__, ten)


def test_ast_thu_tu_khoa_e4_e5_doc_nam_khoa_nam_roi_dong_lan_xet():
    """§6.8 + quyết định owner 23-11 (E4 / E5 khoá năm CHIA SẺ, E1 ĐỘC QUYỀN) — lớp AST; chế độ khoá đo ở CSDL (``pg_locks.mode``) bằng
    ca hai phiên (e), (f) của ``tests/api/test_gd2b_lan_xet_hai_phien_api.py``."""
    from app.services import admission_review_service as svc

    khoa = ("read_session_year", "lock_review_year", "lock_review_years", "lock_review_years_shared", "lock_session")
    goi = _ten_goi(_ast_ham(svc, "_locked_session"))
    assert [g for g in goi if g in khoa] == ["read_session_year", "lock_review_years_shared", "lock_session"]
    for ham in ("replace_floors", "cancel_session"):
        goi = _ten_goi(_ast_ham(svc, ham))
        assert goi.index("_locked_session") < goi.index("delete_floors"), ham
        assert not [g for g in goi if g in khoa], ham  # chỉ qua MỘT chỗ khoá — không tự lấy thêm / nâng khoá năm
    goi = _ten_goi(_ast_ham(svc, "create_session"))
    assert [g for g in goi if g in khoa] == ["lock_review_year"]  # E1 ĐỘC QUYỀN (cấp seq_no)
    assert goi.index("lock_review_year") < goi.index("max_seq_no") < goi.index("insert_session")


def test_i1_route_ghi_kiem_phan_hoi_dung_response_model_truoc_commit():
    """Rà hợp nhất 23-11 I1 (lớp AST; hành vi đo bằng request thật ở ``test_i1_*`` của hai tệp API): route nào trong 9 có
    ``db.commit()`` thì gọi ``response_checked_before_commit(<response_model CỦA CHÍNH route>, …)`` ĐÚNG một lần và TRƯỚC commit.
    Tập route ghi gõ TAY (E1, E4, E5, E6) — route mới có commit mà quên kiểm ⇒ đỏ."""
    import app.routers.admission_review as mod

    cay = ast.parse(inspect.getsource(mod))
    ham = {n.name: n for n in ast.walk(cay) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    co_commit = set()
    for k, r in _route_lan_xet().items():
        nut = ham[r.endpoint.__name__]
        commit = [n for n in ast.walk(nut) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "commit"]
        kiem = [n for n in ast.walk(nut) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "response_checked_before_commit"]
        if not commit:
            assert not kiem, k
            continue
        co_commit.add(k)
        assert len(commit) == 1 and len(kiem) == 1, k
        assert (kiem[0].lineno, kiem[0].col_offset) < (commit[0].lineno, commit[0].col_offset), k
        assert isinstance(kiem[0].args[0], ast.Name) and kiem[0].args[0].id == r.response_model.__name__, k
    assert co_commit == {
        ("POST", P), ("PUT", P + "/{session_id}/floors"), ("POST", P + "/{session_id}/cancel"), ("POST", P + "/{session_id}/runs"),
    }


def test_ast_doi_nam_hoc_vu_doc_san_lan_xet_nhap():
    from app.services import admission_quota_table_service as q

    goi = _ten_goi(_ast_ham(q, "check_academic_info_move_allowed"))
    assert "sessions_with_floor_for_academic_info" in goi and "AcademicInfoInReviewFloor" in goi


def test_ket_qua_doi_cau_hinh_sau_run():
    from app.services.admission_review_service import config_changed_since_run

    qt = {"status": "draft", "version": 3, "quota_fingerprint": "a" * 64}
    vao = {"session_version": 2, "quota_table": dict(qt)}
    assert config_changed_since_run(vao, session_version=2, quota_table=qt) is False
    assert config_changed_since_run(vao, session_version=3, quota_table=qt) is True
    for k, v in (("status", "locked"), ("version", 4), ("quota_fingerprint", "b" * 64)):
        assert config_changed_since_run(vao, session_version=2, quota_table={**qt, k: v}) is True, k


# ── BT25 / BT42 cho mã MỚI của L3a / L4 (khuôn ``test_gd2b_vi_tu_mot_nguon.py`` — module máy xét đã có ca riêng) ──────────────
MODULE_L4 = ("routers/admission_review.py", "services/admission_review_service.py", "schemas/admission_review.py")
CAM_GOI = {"evaluate_cascade", "publish_result", "freeze_priority_snapshot", "transition", "state_transition",
           "_assert_quota_or_bypass"}


def _cay_app(rel: str) -> ast.Module:
    from pathlib import Path

    return ast.parse((Path(__file__).resolve().parents[2] / "app" / rel).read_text(encoding="utf-8"))


@pytest.mark.parametrize("rel", MODULE_L4)
def test_bt25_bt42_ma_l4_khong_goi_ham_ghi_ho_so_hay_vuot_chi_tieu_khong_dinh_danh_bypass(rel):
    cay = _cay_app(rel)
    assert not (set(_ten_goi(cay)) & CAM_GOI), rel
    ten = set()
    for n in ast.walk(cay):
        if isinstance(n, ast.Name):
            ten.add(n.id)
        elif isinstance(n, ast.Attribute):
            ten.add(n.attr)
        elif isinstance(n, ast.arg):
            ten.add(n.arg)
        elif isinstance(n, ast.keyword) and n.arg:
            ten.add(n.arg)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            ten.add(n.name)
        elif isinstance(n, ast.alias):
            ten.add(n.asname or n.name)
    assert not [t for t in ten if "bypass" in t.lower()], rel


async def test_hd4_e9_order_by_ket_thuc_bang_profile_id_tang():
    """HĐ4 — câu SQL thật của E9 (``admission_review_repository.list_rows``, biên dịch theo PostgreSQL): ORDER BY = tab → ngành →
    học vụ → tổng điểm GIẢM → ``profile_id`` TĂNG ở CUỐI (khoá phụ chỉ để phân trang ổn định). Bắt câu bằng một đối tượng ghi lại
    lời gọi ``execute`` (không CSDL) — hành vi trên dữ liệu đo ở ``tests/api/test_gd2b_chay_kiem_api.py``."""
    from sqlalchemy.dialects import postgresql

    from app.repositories import admission_review_repository as repo

    cau = []

    class _KetQua:
        def scalar_one(self):
            return 0

        def scalars(self):
            return []

    class _GhiLai:
        async def execute(self, stmt, *a, **k):
            cau.append(stmt)
            return _KetQua()

    await repo.list_rows(_GhiLai(), 1, offset=0, limit=50)
    sql = str(cau[-1].compile(dialect=postgresql.dialect()))
    thu_tu = [x.strip() for x in sql.split("ORDER BY", 1)[1].split("LIMIT", 1)[0].split(",")]
    assert thu_tu[-1] == "admission_review_row.profile_id ASC", thu_tu
    assert thu_tu[-2] == "admission_review_row.review_total DESC NULLS LAST", thu_tu
    assert thu_tu[1:3] == [
        "admission_review_row.considered_major_code ASC NULLS LAST",
        "admission_review_row.considered_offering_academic_info_id ASC NULLS LAST",
    ], thu_tu
