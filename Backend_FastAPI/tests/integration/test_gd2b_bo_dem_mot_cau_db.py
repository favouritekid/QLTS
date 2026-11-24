# tests/integration/test_gd2b_bo_dem_mot_cau_db.py
"""GĐ2-B đợt 2 — bộ đếm MỌI học vụ trong MỘT câu (``quota_occupancy_service.count_by_academic_infos``) sau Codex 22-11 lượt 2
B-P5: phần hồ sơ kiểu cũ (``pub_a2``) từng đặt điều kiện học vụ ở câu con lồng THÊM một cấp ⇒ không tương quan ⇒ tích Descartes
``FROM admission_path, offering_academic_info`` ⇒ một hồ sơ kiểu cũ ở X làm tăng cả Y.

* Mức SQL: biên dịch câu (không CSDL) — tên bảng ``offering_academic_info`` chỉ được đứng ở FROM của câu NGOÀI.
* Mức dữ liệu (số VIẾT TAY): hai học vụ X / Y; hồ sơ kiểu cũ chiếm chỗ CHỈ ở X; hồ sơ bộ máy NV có Quyết định hiệu lực ở X (phần B
  khác 0 — bộ gieo bổ sung a của Codex); hồ sơ "Đã nộp" có Quyết định hiệu lực ở Y. Đối chiếu từng học vụ với
  ``count_by_academic_info`` / ``count_by_offering_year``.
"""
import re

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import quota_occupancy_service as qos
from tests.integration.test_quota_occupancy_db import _ghi_nhan, _hs, c  # noqa: F401

pytestmark = pytest.mark.integration


def test_cau_dem_moi_hoc_vu_khong_co_tich_descartes_voi_hoc_vu_ngoai():
    sql = str(qos.academic_infos_count_statement([1, 2]).compile(dialect=postgresql.dialect()))
    # Tên bảng đứng trơn (không phải ``offering_academic_info.<cột>``) chỉ ở FROM của câu ngoài — câu con nào có nó trong FROM là
    # KHÔNG tương quan (tích Descartes).
    tron = re.findall(r"\boffering_academic_info\b(?!\.)", sql)
    assert len(tron) == 1, sql
    assert ", offering_academic_info" not in sql, sql


async def test_bo_dem_mot_cau_x_y_so_viet_tay_va_bang_ham_goc(c):
    await _hs(c, "approved", o="X", kieu_cu="X")  # H1: kiểu cũ, chiếm chỗ, đường xét X — CHỈ thuộc X
    h2 = await _hs(c, "approved", o="X", nv="X")  # H2: bộ máy NV, NV trúng X …
    await _ghi_nhan(c, [h2], "X")  # … có Quyết định hiệu lực ở X ⇒ chỉ ở phần B
    h3 = await _hs(c, "submitted", o="Y")  # H3: "Đã nộp" có Quyết định hiệu lực ở Y ⇒ phần B của Y
    await _ghi_nhan(c, [h3], "Y")
    x, y = c.info["X"], c.info["Y"]
    async with AsyncSession(bind=c) as db:
        mot_cau = await qos.count_by_academic_infos(db, academic_info_ids=[x["ai"], y["ai"]])
        for o in (x, y):
            cong_bo = await qos.count_by_academic_info(db, academic_info_id=o["ai"])
            phe_duyet = await qos.count_by_offering_year(db, offering_id=o["off"], academic_year=2026)
            assert mot_cau[o["ai"]] == {"publish_count": cong_bo, "approved_count": phe_duyet, "used": max(cong_bo, phe_duyet)}
    # X: công bố = A2 (H1) + B (H2) = 2; Phê duyệt cũ = A theo lead (H1) + B theo ngành (H2) = 2.
    assert mot_cau[x["ai"]] == {"publish_count": 2, "approved_count": 2, "used": 2}, mot_cau
    # Y: chỉ phần B của H3 — H1 KHÔNG được đếm vào Y.
    assert mot_cau[y["ai"]] == {"publish_count": 1, "approved_count": 1, "used": 1}, mot_cau
