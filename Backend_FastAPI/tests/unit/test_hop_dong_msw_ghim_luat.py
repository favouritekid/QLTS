# -*- coding: utf-8 -*-
"""Ghim mã băm các hàm / lớp / hằng máy chủ mà MSW của giao diện CHÉP luật (Codex lần 21, câu 1).

Giao diện có bản chép thứ hai của luật các lệnh ghi Văn bản Hội đồng: ``frontend/src/test/mocks/council-luat-may-chu.ts``
(máy chủ giả MSW từ chối theo luật thật — Codex lần 20, câu 2), theo bảng
``logs-P5/cong-bo-ket-qua/vong-giao-dien/HOP-DONG-THAN-YEU-CAU-LENH-GHI-GD1-2026-11-13.md`` (ngoài kho).

Test này KHÔNG chứng minh hai bản tương đương. Nó chỉ NHẮC: một hàm / hằng nguồn đổi ⇒ test đỏ ⇒ người sửa phải rà bảng hợp đồng
và mô-đun MSW CÙNG LƯỢT, rồi mới cập nhật mã băm ở ``GHIM``. Không cập nhật mã băm "cho xanh" khi chưa rà (CLAUDE.md §7).

Băm = sha256 (16 ký tự đầu) của:
- ``inspect.getsource`` cho hàm / lớp (gồm decorator);
- ``repr`` cho hằng;
- ``repr((default, metadata))`` cho giá trị mặc định của trường cấu hình.
"""
import hashlib
import inspect

import pytest

from app import config as cau_hinh
from app.models import council_document as m_vb
from app.routers import council_documents as r_vb
from app.schemas import council_document as s_vb
from app.services import council_candidate_service as s_ung_vien
from app.services import council_decision_service as s_qd
from app.services import council_decision_submission_service as s_luot
from app.services import council_document_render_service as s_dung
from app.services import council_document_set_service as s_bo
from app.services import council_document_template_service as s_mau

pytestmark = pytest.mark.unit

MSW = "frontend/src/test/mocks/council-luat-may-chu.ts"


def _ma(obj) -> str:
    return inspect.getsource(obj)


def _mac_dinh(ten: str) -> str:
    f = cau_hinh.Settings.model_fields[ten]
    return repr((f.default, [repr(m) for m in f.metadata]))


#: nhãn → hàm trả văn bản nguồn. Thêm luật chép mới vào MSW ⇒ thêm nguồn ở đây.
NGUON = {
    # ── mã hồ sơ / tìm / đổi mã (council_candidate_service) ──
    "ung_vien.loi_mot_ma": lambda: _ma(s_ung_vien.loi_mot_ma),
    "ung_vien.chuan_hoa_ma": lambda: _ma(s_ung_vien.chuan_hoa_ma),
    "ung_vien._neu_dong": lambda: _ma(s_ung_vien._neu_dong),
    "ung_vien.doc_ho_so_theo_ma": lambda: _ma(s_ung_vien.doc_ho_so_theo_ma),
    "ung_vien.kiem_nam_hoc": lambda: _ma(s_ung_vien.kiem_nam_hoc),
    "ung_vien.tim_ho_so": lambda: _ma(s_ung_vien.tim_ho_so),
    "ung_vien.doi_ma_thanh_id": lambda: _ma(s_ung_vien.doi_ma_thanh_id),
    "ung_vien.DAI_MA_TOI_DA": lambda: repr(s_ung_vien.DAI_MA_TOI_DA),
    "ung_vien._RE_DINH_DANG_MA": lambda: repr(s_ung_vien._RE_DINH_DANG_MA.pattern),
    "ung_vien._NEU_TOI_DA": lambda: repr(s_ung_vien._NEU_TOI_DA),
    "ung_vien._CAU_LOI_MA": lambda: repr(s_ung_vien._CAU_LOI_MA),
    "ung_vien.LOI_MA": lambda: repr(
        [
            s_ung_vien.LOI_MA_KHONG_PHAI_CHUOI,
            s_ung_vien.LOI_MA_RONG,
            s_ung_vien.LOI_MA_KY_TU_LA,
            s_ung_vien.LOI_MA_SAI_DINH_DANG,
            s_ung_vien.LOI_MA_TRUNG,
            s_ung_vien.LOI_MA_KHONG_KHOP,
            s_ung_vien.LOI_MA_NHIEU_HO_SO,
        ]
    ),
    # ── dựng bộ / kiểm trước / xoá (council_document_set_service) ──
    "bo.tao_bo_van_ban": lambda: _ma(s_bo.tao_bo_van_ban),
    "bo.tao_bo_van_ban_theo_id": lambda: _ma(s_bo.tao_bo_van_ban_theo_id),
    "bo.kiem_danh_sach_id": lambda: _ma(s_bo.kiem_danh_sach_id),
    "bo.so_voi_kiem_truoc": lambda: _ma(s_bo.so_voi_kiem_truoc),
    "bo.kiem_ly_do": lambda: _ma(s_bo.kiem_ly_do),
    "bo.kiem_ly_do_xoa": lambda: _ma(s_bo.kiem_ly_do_xoa),
    "bo.DOI_TU_LUC_KIEM": lambda: repr([s_bo.MA_LOI_DOI_TU_LUC_KIEM, s_bo.CAU_DOI_TU_LUC_KIEM]),
    # ── ghi nhận / huỷ ghi nhận (council_decision_service) ──
    "qd.kiem_so_quyet_dinh": lambda: _ma(s_qd.kiem_so_quyet_dinh),
    "qd.kiem_ngay": lambda: _ma(s_qd.kiem_ngay),
    "qd.kiem_scan": lambda: _ma(s_qd.kiem_scan),
    "qd.kiem_xac_nhan_trang_thai": lambda: _ma(s_qd.kiem_xac_nhan_trang_thai),
    "qd._so_tham_so": lambda: _ma(s_qd._so_tham_so),
    "qd._bo_qd_hop_le": lambda: _ma(s_qd._bo_qd_hop_le),
    "qd._so_chua_dung": lambda: _ma(s_qd._so_chua_dung),
    "qd.ghi_nhan_quyet_dinh": lambda: _ma(s_qd.ghi_nhan_quyet_dinh),
    "qd.huy_ghi_nhan": lambda: _ma(s_qd.huy_ghi_nhan),
    "qd.TRUONG_THAM_SO_GIAY": lambda: repr(s_qd.TRUONG_THAM_SO_GIAY),
    "luot.kiem_ma_luot": lambda: _ma(s_luot.kiem_ma_luot),
    # ── mẫu / tham số in ──
    "mau.tai_mau_len": lambda: _ma(s_mau.tai_mau_len),
    "mau.TEN_LOAI": lambda: repr(s_mau.TEN_LOAI),
    "dung.DecisionParams": lambda: _ma(s_dung.DecisionParams),
    # ── khuôn thân yêu cầu (schema) ──
    "schema.CouncilSetCreate": lambda: _ma(s_vb.CouncilSetCreate),
    "schema.CouncilSetPreviewIn": lambda: _ma(s_vb.CouncilSetPreviewIn),
    "schema.CouncilCodesIn": lambda: _ma(s_vb.CouncilCodesIn),
    "schema.CouncilProfileSearchIn": lambda: _ma(s_vb.CouncilProfileSearchIn),
    "schema.CouncilSetDelete": lambda: _ma(s_vb.CouncilSetDelete),
    "schema.CouncilDecisionCancelIn": lambda: _ma(s_vb.CouncilDecisionCancelIn),
    # ── route (khuôn Form / thứ tự gọi service) ──
    "route.upload_council_template": lambda: _ma(r_vb.upload_council_template),
    "route.create_council_document_set": lambda: _ma(r_vb.create_council_document_set),
    "route.preview_council_document_set": lambda: _ma(r_vb.preview_council_document_set),
    "route.search_council_profiles": lambda: _ma(r_vb.search_council_profiles),
    "route.resolve_council_profile_codes": lambda: _ma(r_vb.resolve_council_profile_codes),
    "route.delete_council_document_set": lambda: _ma(r_vb.delete_council_document_set),
    "route.create_council_decision": lambda: _ma(r_vb.create_council_decision),
    "route.open_council_decision_submission": lambda: _ma(r_vb.open_council_decision_submission),
    "route.resolve_council_decision_submission": lambda: _ma(r_vb.resolve_council_decision_submission),
    "route.cancel_council_decision_record": lambda: _ma(r_vb.cancel_council_decision_record),
    # ── trần / hằng kỹ thuật ──
    "model.LY_DO_XOA_TOI_DA": lambda: repr(m_vb.LY_DO_XOA_TOI_DA),
    "cau_hinh.COUNCIL_SET_MAX_PROFILES": lambda: _mac_dinh("COUNCIL_SET_MAX_PROFILES"),
    "cau_hinh.COUNCIL_DECISION_SCAN_MAX_BYTES": lambda: _mac_dinh("COUNCIL_DECISION_SCAN_MAX_BYTES"),
}

#: Mã băm đã rà cùng bảng hợp đồng + MSW @ LXT1 ``16ce6312`` (máy chủ = ``19424587``), 13-11-2026.
GHIM: dict = {
    "bo.DOI_TU_LUC_KIEM": "2fa97413ec1c36fa",
    "bo.kiem_danh_sach_id": "08b6b1f445b2bb01",
    "bo.kiem_ly_do": "a3a6177fdef55e9f",
    "bo.kiem_ly_do_xoa": "130741794b06a57c",
    "bo.so_voi_kiem_truoc": "f1b793b23f4e2d81",
    "bo.tao_bo_van_ban": "bbd2856bd47942da",
    "bo.tao_bo_van_ban_theo_id": "db846adea3478a18",
    "cau_hinh.COUNCIL_DECISION_SCAN_MAX_BYTES": "46e7fca293474ecc",
    "cau_hinh.COUNCIL_SET_MAX_PROFILES": "b09d7b699cf5ffdf",
    "dung.DecisionParams": "2c96e62f6f91e9db",
    "luot.kiem_ma_luot": "308137227d71b47c",
    "mau.TEN_LOAI": "ff27ce4a7da9b1c2",
    "mau.tai_mau_len": "c84f9839f764bd0d",
    "model.LY_DO_XOA_TOI_DA": "40510175845988f1",
    "qd.TRUONG_THAM_SO_GIAY": "742204c74c586740",
    "qd._bo_qd_hop_le": "4bb5b9edd04eb5b6",
    "qd._so_chua_dung": "a3830c24b477d7d0",
    "qd._so_tham_so": "203bc74e40ef9fc6",
    "qd.ghi_nhan_quyet_dinh": "9d8f98a70898d180",
    "qd.huy_ghi_nhan": "ca9f7185490424e1",
    "qd.kiem_ngay": "c003052f130402c7",
    "qd.kiem_scan": "ee7b2cb1bf446f2b",
    "qd.kiem_so_quyet_dinh": "6e43fb7cbecabcce",
    "qd.kiem_xac_nhan_trang_thai": "c17156d4d7c11784",
    "route.cancel_council_decision_record": "8652360e55420ed5",
    "route.create_council_decision": "b6a564e00dfe18e9",
    "route.create_council_document_set": "f14d7ca19acadabe",
    "route.delete_council_document_set": "43d1c2e1e9a830f9",
    "route.open_council_decision_submission": "60e4dd887b8d3f92",
    "route.preview_council_document_set": "8e3538427a620866",
    "route.resolve_council_decision_submission": "e05bcb1dd1001486",
    "route.resolve_council_profile_codes": "395206373f6e37e6",
    "route.search_council_profiles": "48917db783154124",
    "route.upload_council_template": "c225df49a7b87cb0",
    "schema.CouncilCodesIn": "b565161d8df6fba8",
    "schema.CouncilDecisionCancelIn": "fa53cae74ae5567c",
    "schema.CouncilProfileSearchIn": "5edfaebdfdaccde2",
    "schema.CouncilSetCreate": "9505dc4c9b241ab3",
    "schema.CouncilSetDelete": "65ce52ad7d2280a9",
    "schema.CouncilSetPreviewIn": "9db8be743827b424",
    "ung_vien.DAI_MA_TOI_DA": "e29c9c180c6279b0",
    "ung_vien.LOI_MA": "a89efbef70cd03fd",
    "ung_vien._CAU_LOI_MA": "aaf141faadda3181",
    "ung_vien._NEU_TOI_DA": "f5ca38f748a1d6ea",
    "ung_vien._RE_DINH_DANG_MA": "7f59434ed3b55e05",
    "ung_vien._neu_dong": "593f548219b1223e",
    "ung_vien.chuan_hoa_ma": "209ee954e8e34a23",
    "ung_vien.doc_ho_so_theo_ma": "1152bb4bef3510b7",
    "ung_vien.doi_ma_thanh_id": "821fa31cffb1ed75",
    "ung_vien.kiem_nam_hoc": "6c2368803370c343",
    "ung_vien.loi_mot_ma": "616dcb2349645900",
    "ung_vien.tim_ho_so": "cbd9ffc77774d53a",
}


def _bam(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def test_luat_may_chu_chep_sang_msw_chua_doi_ma_chua_ra():
    thuc = {k: _bam(f()) for k, f in NGUON.items()}
    lech = sorted(k for k in NGUON if GHIM.get(k) != thuc[k])
    thua = sorted(set(GHIM) - set(NGUON))
    assert not lech and not thua, (
        "Luật máy chủ mà MSW giao diện CHÉP đã đổi (hoặc danh sách ghim lệch): %s%s.\n"
        "Việc phải làm CÙNG LƯỢT: rà bảng hợp đồng thân yêu cầu + %s theo mã mới; xong mới cập nhật GHIM.\n"
        "Giá trị thật hiện tại (dán vào GHIM SAU KHI đã rà):\n%s"
        % (
            ", ".join(lech),
            (" · thừa trong GHIM: " + ", ".join(thua)) if thua else "",
            MSW,
            "\n".join('    "%s": "%s",' % (k, thuc[k]) for k in sorted(thuc)),
        )
    )
