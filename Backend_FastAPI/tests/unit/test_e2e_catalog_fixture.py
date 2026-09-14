# -*- coding: utf-8 -*-
"""Hợp đồng của fixture danh mục E2E — ``scripts/seeds/seed_e2e_catalog_fixture.py``.

Ba nhóm khẳng định, ba mục đích khác nhau:

1. **GUARD hai tầng** — canh đúng điều khiến script này an toàn khi nó nằm sẵn
   trong ảnh production. Kiểm trên HÀM THUẦN (``assert_app_env_allowed`` /
   ``assert_db_name_allowed``) chứ không qua ``apply()``: ở môi trường
   production, ``app/config.py`` ném ``LoiCauHinh`` TRƯỚC khi guard của script
   kịp chạy (đã đo), nên một phép kiểm end-to-end sẽ xanh vì LÝ DO KHÁC và che
   mất chính thứ nó định canh.

2. **QUAN HỆ VỚI NGUỒN PA-A** — hằng số trong script phải TÁI LẬP được từ
   ``Documents/reports/dak_lak_kv_table.csv`` bằng đúng quy tắc đã công bố.

3. **TOÀN VẸN NỘI BỘ** — trường trỏ tới xã có thật, mã KV khớp CHECK của CSDL,
   không mã nào trùng, và ``moet_province_code`` đúng 3 ký tự (hợp đồng của
   ``GET /api/v2/vn-school/search``, ``Query(min_length=3, max_length=3)``).

⚠️ VỀ ``_goc_repo()``: ``Documents/`` nằm NGOÀI ``Backend_FastAPI`` nên khi
pytest chạy trong container backend (``docker-compose.override.yml`` mount
``./Backend_FastAPI:/app``) cây repo KHÔNG có mặt. Đây là cùng hoàn cảnh mà
``tests/unit/test_ci_test_visibility.py:64`` và
``tests/unit/test_nginx_template_packaging.py:104`` đã xử lý: trên runner CI
(``backend-test.yml`` chạy pytest với ``working-directory: Backend_FastAPI``
sau ``actions/checkout``) cây repo LUÔN có mặt nên nhóm (2) chạy thật; trong
container thì mount cây repo và đặt ``QLTS_REPO_ROOT``. Chỉ ĐÚNG MỘT phép kiểm
phụ thuộc điều này — hai nhóm còn lại chạy ở mọi nơi.
"""

from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
DUONG_SCRIPT = BACKEND / "scripts" / "seeds" / "seed_e2e_catalog_fixture.py"


def _nap_script():
    """Nạp script seed THEO ĐƯỜNG DẪN — không phụ thuộc sys.path/cwd.

    ``Backend_FastAPI/`` luôn là ``parents[2]`` của tệp test này ở MỌI cách
    chạy (runner CI lẫn container), nên đường này không bao giờ hụt.
    """
    assert DUONG_SCRIPT.is_file(), f"không thấy {DUONG_SCRIPT}"
    spec = importlib.util.spec_from_file_location("_p3_seed_fixture", DUONG_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SEED = _nap_script()

# Mirror CHECK ``ck_vn_commune_area_map_area_code_format`` và
# ``ck_vn_school_kv_assignment_kv_code_format`` (đã đọc bằng \d trên qlts_test).
RE_KV = re.compile(r"^KV[1-9](-NT)?$")


def _goc_repo() -> Path | None:
    ung_vien = [Path(os.environ["QLTS_REPO_ROOT"])] if os.environ.get(
        "QLTS_REPO_ROOT"
    ) else []
    ung_vien += list(Path(__file__).resolve().parents)
    for thu_muc in ung_vien:
        if (thu_muc / SEED.PA_A_CSV_REPO_PATH).is_file():
            return thu_muc
    return None


# ===========================================================================
# (1) GUARD HAI TẦNG
# ===========================================================================

class TestGuardTang1AppEnv:
    @pytest.mark.parametrize("gia_tri", ["production", "PRODUCTION", "prod", "staging"])
    @pytest.mark.parametrize("allow_dev", [False, True])
    def test_chan_cung_khong_co_co_nao_noi_duoc(self, gia_tri, allow_dev):
        with pytest.raises(SEED.GuardError, match="TẦNG 1 TỪ CHỐI"):
            SEED.assert_app_env_allowed(gia_tri, allow_dev=allow_dev)

    @pytest.mark.parametrize("gia_tri", [None, "", "   "])
    def test_rong_thi_tu_choi_khong_mac_dinh_cho_qua(self, gia_tri):
        with pytest.raises(SEED.GuardError, match="TẦNG 1 TỪ CHỐI"):
            SEED.assert_app_env_allowed(gia_tri)

    def test_test_duoc_phep(self):
        assert SEED.assert_app_env_allowed("test") == "test"

    def test_development_chi_qua_khi_co_allow_dev(self):
        with pytest.raises(SEED.GuardError, match="TẦNG 1 TỪ CHỐI"):
            SEED.assert_app_env_allowed("development")
        assert (
            SEED.assert_app_env_allowed("development", allow_dev=True)
            == "development"
        )

    def test_gia_tri_la_khong_nam_trong_allowlist_thi_tu_choi(self):
        # Một tên môi trường MỚI (chưa ai nghĩ tới) phải bị TỪ CHỐI, không
        # phải được cho qua vì "không nằm trong danh sách cấm".
        with pytest.raises(SEED.GuardError, match="TẦNG 1 TỪ CHỐI"):
            SEED.assert_app_env_allowed("preprod", allow_dev=True)


class TestGuardTang2TenCsdl:
    @pytest.mark.parametrize(
        "gia_tri", ["qlts_production", "qlts_prod", "qlts", "QLTS_PRODUCTION"]
    )
    @pytest.mark.parametrize("allow_dev", [False, True])
    def test_chan_cung_khong_co_co_nao_noi_duoc(self, gia_tri, allow_dev):
        with pytest.raises(SEED.GuardError, match="TẦNG 2 TỪ CHỐI"):
            SEED.assert_db_name_allowed(gia_tri, allow_dev=allow_dev)

    @pytest.mark.parametrize("gia_tri", [None, "", "   "])
    def test_rong_thi_tu_choi(self, gia_tri):
        with pytest.raises(SEED.GuardError, match="TẦNG 2 TỪ CHỐI"):
            SEED.assert_db_name_allowed(gia_tri)

    def test_qlts_test_duoc_phep(self):
        assert SEED.assert_db_name_allowed("qlts_test") == "qlts_test"

    def test_qlts_dev_chi_qua_khi_co_allow_dev(self):
        with pytest.raises(SEED.GuardError, match="TẦNG 2 TỪ CHỐI"):
            SEED.assert_db_name_allowed("qlts_dev")
        assert SEED.assert_db_name_allowed("qlts_dev", allow_dev=True) == "qlts_dev"

    def test_ten_la_bi_tu_choi(self):
        with pytest.raises(SEED.GuardError, match="TẦNG 2 TỪ CHỐI"):
            SEED.assert_db_name_allowed("qlts_staging", allow_dev=True)

    def test_thong_diep_neu_ro_nguon_do(self):
        # Hai lượt kiểm (URL trước khi kết nối / current_database() sau khi kết
        # nối) phải phân biệt được trong log, nếu không người đọc không biết
        # tầng nào đã bắt.
        with pytest.raises(SEED.GuardError, match=r"current_database\(\)"):
            SEED.assert_db_name_allowed("qlts_production", nguon="current_database()")


# --- Hằng số của guard: canh TRỰC TIẾP, vì hành vi không cô lập được chúng ---
#
# Hai lớp (allowlist + chặn cứng) DƯ THỪA CÓ CHỦ Ý, nên không đột biến
# một-dòng nào cô lập được lớp chặn cứng: gỡ ``qlts_production`` khỏi
# ``_ALWAYS_FORBIDDEN_DB`` thì allowlist VẪN từ chối (đã đo: đột biến vẫn
# XANH ở nhóm kiểm hành vi). Vì vậy nội dung hai tập hợp phải được ghim
# thẳng — nếu không, một lớp có thể bị gỡ mà không gì đỏ.

def test_danh_sach_chan_cung_khong_duoc_thu_hep():
    """⊇ cho phép THÊM, chặn BỚT."""
    assert {"production", "prod", "staging"} <= SEED._ALWAYS_FORBIDDEN_APP_ENV
    assert {"qlts_production", "qlts_prod", "qlts"} <= SEED._ALWAYS_FORBIDDEN_DB


def test_allowlist_la_quyet_dinh_da_duoc_xem_khong_duoc_noi_am_tham():
    """Nới allowlist = mở thêm một môi trường được phép GHI. Ghim CHÍNH XÁC để
    việc nới buộc phải sửa test — tức buộc phải có người xem."""
    assert set(SEED._DEFAULT_ALLOWED_APP_ENV) == {"test"}
    assert set(SEED._DEV_ALLOWED_APP_ENV) == {"test", "development"}
    assert set(SEED._DEFAULT_ALLOWED_DB) == {"qlts_test"}
    assert set(SEED._DEV_ALLOWED_DB) == {"qlts_test", "qlts_dev"}


# ===========================================================================
# (2) QUAN HỆ VỚI NGUỒN PA-A
# ===========================================================================

CSV_MAU = (
    "\ufeffward_code,ward_name,kind,area_code,source_summary\r\n"
    "10001,Xã A,XA,KV1,ghi chú\r\n"
    "10002,Phường B,PHUONG,KV2,ghi chú\r\n"
    "10003,Xã C,XA,KV1,trùng KV1 — phải BỎ\r\n"
    "10004,Xã D,XA,KV2-NT,ghi chú\r\n"
    "10005,Phường E,PHUONG,KV2,trùng KV2 — phải BỎ\r\n"
)


def test_doc_duoc_bom_va_crlf():
    rows = SEED.read_pa_a_rows(CSV_MAU)
    assert [r["ward_code"] for r in rows] == [
        "10001", "10002", "10003", "10004", "10005",
    ]
    assert rows[0]["ward_name"] == "Xã A"


def test_thieu_cot_thi_no_chu_khong_im_lang():
    with pytest.raises(ValueError, match="thiếu cột"):
        SEED.read_pa_a_rows("ward_code,ward_name\r\n1,x\r\n")


def test_quy_tac_chon_lay_hang_dau_cua_moi_area_code_theo_thu_tu_tep():
    picked = SEED.select_minimal_wards(SEED.read_pa_a_rows(CSV_MAU))
    assert [p["ward_code"] for p in picked] == ["10001", "10002", "10004"]
    assert [p["area_code"] for p in picked] == ["KV1", "KV2", "KV2-NT"]


def test_hang_so_tai_lap_duoc_tu_pa_a():
    """Hằng số trong script == kết quả áp quy tắc lên CSV THẬT trong git."""
    goc = _goc_repo()
    if goc is None:
        pytest.skip(
            f"không thấy {SEED.PA_A_CSV_REPO_PATH} (cây repo không được mount). "
            "Chạy trong container backend thì mount cây repo + đặt QLTS_REPO_ROOT; "
            "trên runner CI đường này LUÔN có.",
        )
    rows = SEED.read_pa_a_rows(
        (goc / SEED.PA_A_CSV_REPO_PATH).read_text(encoding="utf-8-sig")
    )

    assert len(rows) == SEED.PA_A_ROW_COUNT

    ma = [r["ward_code"] for r in rows]
    assert len(set(ma)) == len(ma), "PA-A có ward_code trùng lặp"

    phan_bo: dict[str, int] = {}
    for r in rows:
        phan_bo[r["area_code"]] = phan_bo.get(r["area_code"], 0) + 1
    assert phan_bo == SEED.PA_A_AREA_CODE_DISTRIBUTION

    chon = SEED.select_minimal_wards(rows)
    assert list(SEED.FIXTURE_WARDS) == chon, (
        "FIXTURE_WARDS đã lệch khỏi PA-A. Chạy lại quy tắc "
        f"{SEED.PA_A_SELECTION_RULE!r} rồi chép nguyên văn."
    )


# ===========================================================================
# (3) TOÀN VẸN NỘI BỘ
# ===========================================================================

def test_moi_truong_tro_toi_mot_xa_co_that():
    ma_xa = {w["ward_code"] for w in SEED.FIXTURE_WARDS}
    for s in SEED.FIXTURE_SCHOOLS:
        assert s["commune_code"] in ma_xa, s


def test_ma_kv_khop_check_cua_csdl():
    for w in SEED.FIXTURE_WARDS:
        assert RE_KV.match(w["area_code"]), w
    for s in SEED.FIXTURE_SCHOOLS:
        assert RE_KV.match(s["kv_code"]), s


def test_khong_ma_nao_trung():
    ma_xa = [w["ward_code"] for w in SEED.FIXTURE_WARDS]
    assert len(set(ma_xa)) == len(ma_xa)
    ma_truong = [s["moet_school_code"] for s in SEED.FIXTURE_SCHOOLS]
    assert len(set(ma_truong)) == len(ma_truong)


def test_phu_du_moi_lop_kv_co_trong_pa_a():
    assert {w["area_code"] for w in SEED.FIXTURE_WARDS} == set(
        SEED.PA_A_AREA_CODE_DISTRIBUTION
    )


def test_co_dung_mot_truong_kv3_lech_kv_xa():
    """KV-trường và KV-thường-trú là HAI NGUỒN TÁCH RỜI.

    Fixture cố ý giữ một trường mà KV của nó KHÁC KV của xã nơi nó đóng: đó là
    thứ duy nhất cho phép một khẳng định E2E trên ``kv_resolved`` phân biệt
    được engine đã đi ngã LICH_SU_THPT (trường) hay THUONG_TRU (xã). Mất tính
    chất này thì hai ngã cho cùng một KV và phép kiểm hết phân biệt được.
    """
    kv_xa = {w["ward_code"]: w["area_code"] for w in SEED.FIXTURE_WARDS}
    lech = [s for s in SEED.FIXTURE_SCHOOLS if s["kv_code"] != kv_xa[s["commune_code"]]]
    assert len(lech) == 1, lech
    assert lech[0]["kv_code"] == "KV3"


def test_moet_province_code_dung_3_ky_tu():
    """Hợp đồng của ``GET /api/v2/vn-school/search``: ``province`` là
    ``Query(min_length=3, max_length=3)``. Mã 2 ký tự không bao giờ khớp."""
    assert len(SEED.MOET_PROVINCE_CODE) == 3
    assert SEED.MOET_PROVINCE_CODE.isdigit()
    assert len(SEED.MOET_CODE_PROVINCE_PREFIX) == 2


def test_dai_nam_kv_truong_thoa_check_va_du_rong():
    assert SEED.SCHOOL_KV_TO_YEAR is None or (
        SEED.SCHOOL_KV_TO_YEAR >= SEED.SCHOOL_KV_FROM_YEAR
    )
    # academic_history của E2E dùng năm 2019-2023; dải phải phủ chúng, nếu
    # không lookup miss → catalog_gap_school, đúng lỗi fixture sinh ra để đóng.
    assert SEED.SCHOOL_KV_FROM_YEAR <= 2019


def test_dry_run_khong_cham_csdl():
    """``main([])`` (không ``--apply``) phải KHÔNG import app/kết nối CSDL."""
    assert SEED.main([]) == 0
