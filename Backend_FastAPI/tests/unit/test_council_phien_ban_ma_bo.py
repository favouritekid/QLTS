# -*- coding: utf-8 -*-
"""PR-1 GĐ1 — U4 (ultra GĐ1, owner 21-11): ``BUILD_CODE_MODULES`` (F212 — "phiên bản mã" ghi vào mỗi bộ) phải phủ MỌI module
mà mã quyết NỘI DUNG bộ văn bản import — để danh sách không trôi nữa (F212 đóng với 5 tệp; về sau hàm đọc / cổng gọi thêm
``priority_service``, ``resolve_effective_bonus_rule``, tình trạng Quyết định… mà danh sách chỉ thêm cổng).

Cách khoá: đọc bằng ``ast`` (không chạy mã) MỌI câu ``import`` — kể cả trong thân hàm — của sáu module LÕI (hàm đọc + SQL,
cổng, bộ dựng, kho mẫu, tệp dựng bộ). Mỗi module ``app.*`` được import phải: có trong ``BUILD_CODE_MODULES``, hoặc nằm trong
``NGOAI_TRU`` kèm LÝ DO. Ngược lại: mỗi mục của ``NGOAI_TRU`` / ``BUILD_CODE_MODULES`` phải thật sự được lõi import (không mục
mồ côi). MỘT tầng — import của module đã thêm (vd ``priority_service``) không đi tiếp; giới hạn ấy là chủ ý (đi bắc cầu kéo
cả ứng dụng vào phiên bản).

Thêm mục vào ``NGOAI_TRU`` phải ghi lý do; không thêm "cho xanh". Đổi danh sách ⇒ mọi dấu kiểm trước cũ lệch sau lần deploy
đầu (409 "Kiểm tra lại") — đã biết, owner chấp nhận.
"""
import ast
import importlib.util
from pathlib import Path

import pytest

from app.services import council_document_set_service as bo_vb

pytestmark = pytest.mark.unit

#: Module LÕI — đi import của chính các tệp này.
LOI = (
    "app.services.council_candidate_service",  # hàm đọc hồ sơ (một giao dịch chỉ đọc) + KV / điểm in
    "app.repositories.council_candidate_repository",  # SQL đọc hồ sơ / kiểm trước
    "app.services.council_set_gate_service",  # cổng: em nào vào bộ, điểm KV / ĐT in
    "app.services.council_document_render_service",  # bộ dựng (luật in)
    "app.services.council_document_template_service",  # kho mẫu
    "app.services.council_document_set_service",  # tạo / tái dựng bộ
)

#: Module lõi import mà KHÔNG quyết nội dung bộ — MỖI mục một lý do.
NGOAI_TRU = {
    "app.config": "cấu hình — giá trị lấy từ môi trường (trần kỹ thuật), không phải mã quyết nội dung",
    "app.utils.exceptions": "lớp lỗi miền",
    "app.models": "gói định nghĩa bảng ORM dùng để truy vấn — câu truy vấn quyết nội dung nằm ở module đã băm",
    "app.models.admission_config.admission_path": "định nghĩa bảng ORM đường xét (nạp quan hệ khi tính luật cộng điểm)",
    "app.services.admission_state_machine": "tập trạng thái cho bộ lọc TÌM hồ sơ (trang chọn) — không vào bộ",
    "app.services.admission_service": "trang TÌM hồ sơ (get_profiles) — không vào bộ",
    "app.services.council_decision_submission_service": "lượt gửi ghi nhận chặn XOÁ bộ — không quyết nội dung",
    "app.services.council_decision_service": (
        "kiểm số / ngày / mẫu theo ngày ký của tái dựng — cho qua hay chặn, không đổi nội dung (vị từ chặn theo tình "
        "trạng Quyết định nằm ở set_gate + council_decision_status_service, đã băm)"
    ),
}

#: Ba module ultra nêu đích danh (U4) + nguồn SQL tình trạng Quyết định — phải có, kể cả khi cách import đổi.
ULTRA_NEU = (
    "app.services.priority_service",
    "app.services.admission_choice_engine_service",
    "app.services.council_decision_status_service",
    "app.models.council_document",
)


def _la_module(ten: str) -> bool:
    try:
        return importlib.util.find_spec(ten) is not None
    except (ModuleNotFoundError, ValueError, AttributeError):
        return False


def _import_cua(ten: str) -> set:
    """Mọi module ``app.*`` mà tệp nguồn của module ``ten`` import (ở bất kỳ đâu trong tệp)."""
    spec = importlib.util.find_spec(ten)
    cay = ast.parse(Path(spec.origin).read_text(encoding="utf-8"))
    goi = ten.rpartition(".")[0]
    ra = set()
    for n in ast.walk(cay):
        if isinstance(n, ast.Import):
            ra.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            if n.level:
                phan = goi.split(".")[: len(goi.split(".")) - (n.level - 1)]
                goc = ".".join(phan + ([n.module] if n.module else []))
            else:
                goc = n.module or ""
            for a in n.names:
                day_du = "%s.%s" % (goc, a.name)
                ra.add(day_du if _la_module(day_du) else goc)
    return {m for m in ra if m == "app" or m.startswith("app.")}


def _da_bam() -> set:
    return {m.__name__ for m in bo_vb.BUILD_CODE_MODULES}


def test_u4_moi_module_loi_import_deu_duoc_bam_hoac_loai_tru_co_ly_do():
    da_bam = _da_bam()
    assert set(LOI) <= da_bam, sorted(set(LOI) - da_bam)
    duoc_import = set().union(*(_import_cua(m) for m in LOI))
    thieu = sorted(duoc_import - da_bam - set(NGOAI_TRU))
    assert not thieu, "Module lõi import mà CHƯA vào BUILD_CODE_MODULES (thêm vào, hoặc NGOAI_TRU kèm lý do): %s" % thieu
    assert not set(NGOAI_TRU) & da_bam, sorted(set(NGOAI_TRU) & da_bam)
    mo_coi = sorted(set(NGOAI_TRU) - duoc_import)
    assert not mo_coi, "NGOAI_TRU có mục lõi không còn import: %s" % mo_coi
    thua = sorted(da_bam - duoc_import - set(LOI))
    assert not thua, "BUILD_CODE_MODULES có module lõi không import: %s" % thua


def test_u4_module_ultra_neu_co_trong_phien_ban_ma():
    assert set(ULTRA_NEU) <= _da_bam(), sorted(set(ULTRA_NEU) - _da_bam())


def test_u4_phien_ban_ma_dung_moi_module_da_bam():
    assert bo_vb.CODE_VERSIONS is not None
    assert set(bo_vb.CODE_VERSIONS) == _da_bam()
