# -*- coding: utf-8 -*-
"""Ghim mã băm các hàm / lớp / hằng máy chủ mà MSW của giao diện CHÉP luật (Codex lần 21, câu 1; lần 22 F286).

Giao diện có bản chép thứ hai của luật các lệnh ghi Văn bản Hội đồng: ``frontend/src/test/mocks/council-luat-may-chu.ts``
(máy chủ giả MSW từ chối theo luật thật — Codex lần 20, câu 2), theo bảng
``logs-P5/cong-bo-ket-qua/vong-giao-dien/HOP-DONG-THAN-YEU-CAU-LENH-GHI-GD1-2026-11-13.md`` (ngoài kho).

Test này KHÔNG chứng minh hai bản tương đương. Nó chỉ NHẮC: một nguồn đổi ⇒ test đỏ ⇒ người sửa phải rà bảng hợp đồng và mô-đun MSW
CÙNG LƯỢT, rồi mới cập nhật mã băm ở ``GHIM``. Không cập nhật mã băm "cho xanh" khi chưa rà (CLAUDE.md §7).

Ba loại nguồn (băm = sha256, 16 ký tự đầu):
- ``HAM``    — hàm / lớp: ``inspect.getsource`` (gồm decorator);
- ``HANG``   — hằng mô-đun: ``repr``;
- ``GIA_TRI`` — giá trị TÍNH RA mà luật dùng: mặc định của trường cấu hình (``default`` + ``metadata``), tập trạng thái hợp lệ.

Ca thứ hai canh BAO PHỦ (Codex lần 22 F286 — ghim ``tim_ho_so`` mà sót ``TU_KHOA_TOI_DA`` và tập trạng thái): mọi hằng và mọi hàm của
mô-đun Hội đồng mà một hàm trong ``HAM`` tham chiếu tới phải được ghim, hoặc nằm trong ``MIEN`` kèm lý do.
"""
import hashlib
import inspect
import re
import types

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

#: hàm / lớp — băm mã nguồn
HAM = {
    # mã hồ sơ / tìm / đổi mã (council_candidate_service)
    "ung_vien.loi_mot_ma": s_ung_vien.single_code_error,
    "ung_vien.chuan_hoa_ma": s_ung_vien.normalize_codes,
    "ung_vien._neu_dong": s_ung_vien._cite_rows,
    "ung_vien.doc_ho_so_theo_ma": s_ung_vien.read_profiles_by_code,
    "ung_vien.kiem_nam_hoc": s_ung_vien.check_academic_year,
    "ung_vien.tim_ho_so": s_ung_vien.search_profiles,
    "ung_vien.doi_ma_thanh_id": s_ung_vien.codes_to_ids,
    # dựng bộ / kiểm trước / xoá (council_document_set_service)
    "bo.tao_bo_van_ban": s_bo.create_document_set,
    "bo.tao_bo_van_ban_theo_id": s_bo.create_document_set_by_ids,
    "bo.kiem_danh_sach_id": s_bo.check_id_list,
    "bo.so_voi_kiem_truoc": s_bo.compare_with_preview,
    "bo.kiem_ly_do": s_bo.check_reason,
    "bo.kiem_ly_do_xoa": s_bo.check_delete_reason,
    "bo._dung_va_ghi_bo": s_bo._build_and_write_set,  # thứ tự ba pha của POST /sets dạng mã (cú pháp → trần → khớp)
    # ghi nhận / huỷ ghi nhận (council_decision_service)
    "qd.kiem_so_quyet_dinh": s_qd.check_decision_number,
    "qd.kiem_ngay": s_qd.check_date,
    "qd.kiem_scan": s_qd.check_scan,
    "qd.kiem_xac_nhan_trang_thai": s_qd.check_status_confirmation,
    "qd._so_tham_so": s_qd._compare_params,
    "qd._gia_tri_json": s_qd._json_value,  # chuẩn hoá giá trị trên giấy trước khi so với bản in
    "qd._bo_qd_hop_le": s_qd._set_decisions_valid,
    "qd._so_chua_dung": s_qd._number_not_in_use,
    "qd.ghi_nhan_quyet_dinh": s_qd.record_decision,
    "qd.huy_ghi_nhan": s_qd.revoke_record,
    "luot.kiem_ma_luot": s_luot.check_submission_code,
    # mẫu / tham số in
    "mau.tai_mau_len": s_mau.upload_template,
    "mau.kiem_goi_mau": s_mau.check_template_package,  # kiểm tệp .docx (MSW chép phần chữ ký ZIP + câu lỗi)
    "dung.DecisionParams": s_dung.DecisionParams,
    # khuôn thân yêu cầu (schema)
    "schema.CouncilSetCreate": s_vb.CouncilSetCreate,
    "schema.CouncilSetPreviewIn": s_vb.CouncilSetPreviewIn,
    "schema.CouncilCodesIn": s_vb.CouncilCodesIn,
    "schema.CouncilProfileSearchIn": s_vb.CouncilProfileSearchIn,
    "schema.CouncilSetDelete": s_vb.CouncilSetDelete,
    "schema.CouncilDecisionCancelIn": s_vb.CouncilDecisionCancelIn,
    # route (khuôn Form / thứ tự gọi service)
    "route.upload_council_template": r_vb.upload_council_template,
    "route.create_council_document_set": r_vb.create_council_document_set,
    "route.preview_council_document_set": r_vb.preview_council_document_set,
    "route.search_council_profiles": r_vb.search_council_profiles,
    "route.resolve_council_profile_codes": r_vb.resolve_council_profile_codes,
    "route.delete_council_document_set": r_vb.delete_council_document_set,
    "route.create_council_decision": r_vb.create_council_decision,
    "route._json_xac_nhan": r_vb._confirmation_json,  # đọc xac_nhan_trang_thai (JSON) của Form ghi nhận
    "route._doc_scan": r_vb._read_scan_upload,  # đọc tệp scan của Form ghi nhận
    "route.open_council_decision_submission": r_vb.open_council_decision_submission,
    "route.resolve_council_decision_submission": r_vb.resolve_council_decision_submission,
    "route.cancel_council_decision_record": r_vb.cancel_council_decision_record,
}

#: hằng mô-đun — băm repr. Khoá = "<nhãn>.<TÊN>"; (mô-đun, tên) để ca bao phủ tra.
HANG = {
    "ung_vien.DAI_MA_TOI_DA": (s_ung_vien, "DAI_MA_TOI_DA"),
    "ung_vien._RE_DINH_DANG_MA": (s_ung_vien, "_RE_DINH_DANG_MA"),
    "ung_vien._NEU_TOI_DA": (s_ung_vien, "_NEU_TOI_DA"),
    "ung_vien._CAU_LOI_MA": (s_ung_vien, "_CAU_LOI_MA"),
    "ung_vien.TU_KHOA_TOI_DA": (s_ung_vien, "TU_KHOA_TOI_DA"),
    "ung_vien.LOI_MA_KHONG_PHAI_CHUOI": (s_ung_vien, "LOI_MA_KHONG_PHAI_CHUOI"),
    "ung_vien.LOI_MA_RONG": (s_ung_vien, "LOI_MA_RONG"),
    "ung_vien.LOI_MA_KY_TU_LA": (s_ung_vien, "LOI_MA_KY_TU_LA"),
    "ung_vien.LOI_MA_SAI_DINH_DANG": (s_ung_vien, "LOI_MA_SAI_DINH_DANG"),
    "ung_vien.LOI_MA_TRUNG": (s_ung_vien, "LOI_MA_TRUNG"),
    "ung_vien.LOI_MA_KHONG_KHOP": (s_ung_vien, "LOI_MA_KHONG_KHOP"),
    "ung_vien.LOI_MA_NHIEU_HO_SO": (s_ung_vien, "LOI_MA_NHIEU_HO_SO"),
    "bo.MA_LOI_DOI_TU_LUC_KIEM": (s_bo, "MA_LOI_DOI_TU_LUC_KIEM"),
    "bo.CAU_DOI_TU_LUC_KIEM": (s_bo, "CAU_DOI_TU_LUC_KIEM"),
    "qd.TRUONG_THAM_SO_GIAY": (s_qd, "TRUONG_THAM_SO_GIAY"),
    "qd.SIGN_DATE_AFTER_TODAY_MESSAGE": (s_qd, "SIGN_DATE_AFTER_TODAY_MESSAGE"),  # review max PR #724 R7
    "qd.CONFIRMATION_JSON_MAX_CHARS": (s_qd, "CONFIRMATION_JSON_MAX_CHARS"),  # Codex 42 câu 4 — MSW TRAN_KY_TU_JSON_XAC_NHAN
    "mau.TEN_LOAI": (s_mau, "TEN_LOAI"),
    "model.LY_DO_XOA_TOI_DA": (m_vb, "LY_DO_XOA_TOI_DA"),
}


def _mac_dinh(ten: str) -> str:
    f = cau_hinh.Settings.model_fields[ten]
    return repr((f.default, [repr(m) for m in f.metadata]))


#: giá trị TÍNH RA — băm repr của giá trị (không băm mã: luật nằm ở GIÁ TRỊ)
GIA_TRI = {
    "cau_hinh.COUNCIL_SET_MAX_PROFILES": lambda: _mac_dinh("COUNCIL_SET_MAX_PROFILES"),
    "cau_hinh.COUNCIL_DECISION_SCAN_MAX_BYTES": lambda: _mac_dinh("COUNCIL_DECISION_SCAN_MAX_BYTES"),
    # tập trạng thái hợp lệ của bộ lọc tìm hồ sơ (MSW chép thành TRANG_THAI_HO_SO)
    "ung_vien._trang_thai_hop_le()": lambda: repr(sorted(s_ung_vien._valid_statuses())),
}
#: hàm mà luật nằm ở GIÁ TRỊ trả về (đã ghim ở GIA_TRI) — ca bao phủ coi như đã ghim
HAM_GHIM_THEO_GIA_TRI = {s_ung_vien._valid_statuses}

#: tham chiếu ca bao phủ bỏ qua — MỖI mục một lý do. Thêm mục mới phải ghi lý do, không thêm "cho xanh".
MIEN = {
    "logger": "ghi log, không phải luật",
    # cần CSDL — MSW cố ý KHÔNG mô phỏng (giới hạn đã ghi trong báo cáo MSW / gói Codex lần 21 mục 5)
    "_read_raw": "đọc hồ sơ thô từ CSDL",
    "_build_snapshot": "dựng ảnh chụp hồ sơ từ CSDL",
    "_block_by_state": "chặn theo Quyết định đang có của từng em — cần CSDL",
    "_count_status_changes": "đếm đổi trạng thái sau khi dựng — cần CSDL",
    "_check_count_confirmation": "khuôn 409 xác nhận số đếm — số đếm cần CSDL (MSW giữ các ca 409 có sẵn)",
    "_check_templates_by_signing_date": "kho mẫu theo ngày ký — cần CSDL",
    "_translate_db_error": "dịch lỗi ràng buộc CSDL",
    "_scan": "dựng bản ghi scan để lưu",
    "_decision_file_sha": "băm tệp Quyết định đã lưu — cần CSDL",
    "_event": "ghi sự kiện",
    "stored_warnings": "đọc cảnh báo vượt chỉ tiêu đã lưu — cần CSDL",
    "decision_state": "tình trạng Quyết định của từng em — cần CSDL",
    "NON_WARNING_STATUSES": "chỉ dùng khi đếm bật lại dòng của văn bản huỷ — cần CSDL",
    "_set_row_from_check": "dựng dòng bộ từ kết quả kiểm trước — cần CSDL",
    "_write_set_and_rows": "ghi bộ + dòng vào CSDL",
    "set_unit": "đơn vị của bộ theo hồ sơ — cần CSDL",
    "signing_date_for_template": "chọn ngày áp mẫu khi dựng — cần kho mẫu trong CSDL",
    "pick_templates": "chọn mẫu hiệu lực từ kho — cần CSDL",
    "CODE_VERSIONS": "nhãn phiên bản mã ghi vào thông tin dựng (kỹ thuật)",
    "_CHUNK": "kích thước khúc đọc gói zip của mẫu (kỹ thuật)",
    # MSW nhận sẵn từ dữ liệu giả, không chép thuật toán
    "normalize_rows": "thứ tự chuẩn của kiểm trước — MSW nhận thứ tự chuẩn của ảnh chụp giả",
    "preview_signature": "chữ ký HMAC của kiểm trước — MSW dùng dấu mờ của dữ liệu giả",
    # định dạng phản hồi, không phải luật thân yêu cầu
    "_recorded_decision_out": "dựng DTO phản hồi ghi nhận",
}


def _repr_hang(v) -> str:
    """``repr`` của hằng; biểu thức chính quy lấy (mẫu, cờ) — ``repr(re.Pattern)`` cắt mẫu dài quá 200 ký tự."""
    if isinstance(v, re.Pattern):
        return repr(("re.Pattern", v.pattern, int(v.flags)))
    return repr(v)


def _nguon() -> dict:
    out = {k: inspect.getsource(v) for k, v in HAM.items()}
    out.update({k: _repr_hang(getattr(m, n)) for k, (m, n) in HANG.items()})
    out.update({k: f() for k, f in GIA_TRI.items()})
    return out


#: Mã băm @ LXT1 ``2c83f91b`` (mã máy chủ Hội đồng không đổi kể từ ``16ce6312``), 13-11-2026. Đợt đầu (lần 21) đã rà cùng bảng hợp
#: đồng + MSW; đợt F286 (lần 22) thêm trần từ khoá, tập trạng thái, các hằng câu lỗi tách riêng và 5 hàm phụ. Đã biết: GIÁ TRỊ trần
#: từ khoá và tập trạng thái khớp MSW, nhưng hai CÂU lỗi của ``luatTimHoSo`` trong MSW lệch chữ với máy chủ — giao phiên giao diện sửa.
#: 15-11-2026 — đợt ĐỔI TÊN định danh mã ứng dụng sang tiếng Anh (refactor thuần, không đổi luật): băm HAM đổi vì tên định danh trong
#: mã nguồn; băm HANG / GIA_TRI GIỮ NGUYÊN (giá trị hằng không đổi một byte). Cấu trúc AST từng tệp đã so với bản trước đợt đổi tên:
#: giống hệt, chỉ khác định danh / docstring. MSW không phải sửa vì luật không đổi.
GHIM = {
    "bo.CAU_DOI_TU_LUC_KIEM": "236fff0ad0195cf0",
    "bo.MA_LOI_DOI_TU_LUC_KIEM": "111c5b69b272ed2c",
    "bo._dung_va_ghi_bo": "d9c3088d9a52984b",
    "bo.kiem_danh_sach_id": "858d08fb92cca75a",  # review max PR #724: cận trên int4 — MSW chép cùng lượt
    "bo.kiem_ly_do": "fc6a62b3da5c6187",
    "bo.kiem_ly_do_xoa": "82d807e7fcf70d19",
    "bo.so_voi_kiem_truoc": "ef089c77a7d56795",
    "bo.tao_bo_van_ban": "590f755b6bd25e9f",
    "bo.tao_bo_van_ban_theo_id": "5079197c8fe0bfeb",
    "cau_hinh.COUNCIL_DECISION_SCAN_MAX_BYTES": "cb01a688cfdfae4b",  # review max PR #724 R1: 9 MiB — MSW chép cùng lượt
    "cau_hinh.COUNCIL_SET_MAX_PROFILES": "b09d7b699cf5ffdf",
    "dung.DecisionParams": "fa964ed3e853a34f",  # review max PR #724 R7: số in sẵn không 0 đầu — MSW chép cùng lượt
    "luot.kiem_ma_luot": "308137227d71b47c",
    "mau.TEN_LOAI": "ff27ce4a7da9b1c2",
    "mau.kiem_goi_mau": "6c5b54edfd761661",
    "mau.tai_mau_len": "8b73bdb7e073f6e7",
    "model.LY_DO_XOA_TOI_DA": "40510175845988f1",
    "qd.TRUONG_THAM_SO_GIAY": "742204c74c586740",
    "qd.SIGN_DATE_AFTER_TODAY_MESSAGE": "01cfd96e18cc2e7e",  # MSW chép nguyên câu (luatGhiNhan, kiem_ngay)
    "qd._bo_qd_hop_le": "4bb5b9edd04eb5b6",
    "qd._gia_tri_json": "5f4fbf80c0147a7f",
    "qd._so_chua_dung": "a3830c24b477d7d0",
    "qd._so_tham_so": "203bc74e40ef9fc6",
    "qd.ghi_nhan_quyet_dinh": "9d8f98a70898d180",
    "qd.huy_ghi_nhan": "ca9f7185490424e1",
    "qd.kiem_ngay": "32acc69c19c328c2",  # review max PR #724 R7: ngày ký không sau hôm nay (giờ VN), câu = hằng nguyên văn — MSW chép cùng lượt
    "qd.kiem_scan": "ee7b2cb1bf446f2b",
    "qd.kiem_so_quyet_dinh": "6449b99d90d01950",  # R7 cấm 0 đầu; Codex 42 F337: "0" một chữ số nhận — MSW chép cùng lượt
    "qd.CONFIRMATION_JSON_MAX_CHARS": "e39eef82f61b21e2",  # Codex 42 câu 4 — MSW TRAN_KY_TU_JSON_XAC_NHAN = 1024
    "qd.kiem_xac_nhan_trang_thai": "c17156d4d7c11784",
    "route._doc_scan": "739d65dc50e09692",
    "route._json_xac_nhan": "1c036558d38fdfdf",  # + RecursionError; Codex 42: vượt trần ký tự ⇒ "không đọc được" — MSW chép cùng lượt (Codex 43: chỉ sửa chú thích)
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
    "schema.CouncilSetCreate": "1e68f824d4d373ec",
    "schema.CouncilSetDelete": "65ce52ad7d2280a9",
    "schema.CouncilSetPreviewIn": "9db8be743827b424",
    "ung_vien.DAI_MA_TOI_DA": "e29c9c180c6279b0",
    "ung_vien.LOI_MA_KHONG_KHOP": "205f3b8686d364cd",
    "ung_vien.LOI_MA_KHONG_PHAI_CHUOI": "c4a27bda582f1d17",
    "ung_vien.LOI_MA_KY_TU_LA": "fc3677f5cd36e7e8",
    "ung_vien.LOI_MA_NHIEU_HO_SO": "5e33d3bc3131904e",
    "ung_vien.LOI_MA_RONG": "c9bb9f8f258a1328",
    "ung_vien.LOI_MA_SAI_DINH_DANG": "bf5e67047221dc06",
    "ung_vien.LOI_MA_TRUNG": "492094c17b07e750",
    "ung_vien.TU_KHOA_TOI_DA": "ad57366865126e55",
    "ung_vien._CAU_LOI_MA": "aaf141faadda3181",
    "ung_vien._NEU_TOI_DA": "f5ca38f748a1d6ea",
    "ung_vien._RE_DINH_DANG_MA": "9f7ff644b8abad78",
    "ung_vien._neu_dong": "a8c0f83035fd75c8",
    "ung_vien._trang_thai_hop_le()": "0b3ef3f1a00a8bbd",
    "ung_vien.chuan_hoa_ma": "f20a365687bcbe74",
    "ung_vien.doc_ho_so_theo_ma": "51123e4e5708dbbb",
    "ung_vien.doi_ma_thanh_id": "289116fe5a318c05",
    "ung_vien.kiem_nam_hoc": "c5f3d0d4eac8c0a3",
    "ung_vien.loi_mot_ma": "519e68a62d3347c2",
    "ung_vien.tim_ho_so": "3ffb0aa1327e22fc",
}


def _bam(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def test_luat_may_chu_chep_sang_msw_chua_doi_ma_chua_ra():
    thuc = {k: _bam(v) for k, v in _nguon().items()}
    lech = sorted(k for k in thuc if GHIM.get(k) != thuc[k])
    thua = sorted(set(GHIM) - set(thuc))
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


_KIEU_HANG = (int, float, str, bytes, tuple, frozenset, dict, re.Pattern)
_MO_DUN_HOI_DONG = (
    "app.services.council_",
    "app.routers.council_documents",
    "app.schemas.council_document",
    "app.models.council_document",
)


def _ten_tham_chieu(fn) -> set:
    """Mọi tên toàn cục / thuộc tính mà mã của ``fn`` (kể cả hàm lồng, comprehension) nhắc tới."""
    ten, ngan = set(), [fn.__code__]
    while ngan:
        c = ngan.pop()
        ten.update(c.co_names)
        ngan.extend(k for k in c.co_consts if isinstance(k, types.CodeType))
    return ten


def _la_ham_hoi_dong(obj) -> bool:
    return inspect.isfunction(obj) and obj.__module__.startswith(_MO_DUN_HOI_DONG)


def test_moi_hang_va_ham_hoi_dong_ma_ham_ghim_tham_chieu_deu_duoc_ghim():
    ham_da_ghim = {v for v in HAM.values()} | HAM_GHIM_THEO_GIA_TRI
    hang_da_ghim = {(n, _repr_hang(getattr(m, n))) for m, n in HANG.values()}
    thieu = []
    for khoa, obj in HAM.items():
        fn = inspect.unwrap(obj) if inspect.isfunction(obj) else None
        if fn is None:  # lớp (schema / DecisionParams): luật nằm trong chính mã nguồn đã băm
            continue
        g = fn.__globals__
        for ten in sorted(_ten_tham_chieu(fn)):
            if ten in MIEN or ten not in g:
                continue
            v = g[ten]
            if isinstance(v, _KIEU_HANG) and not isinstance(v, bool):
                if (ten, _repr_hang(v)) not in hang_da_ghim:
                    thieu.append("%s → hằng %s" % (khoa, ten))
            elif _la_ham_hoi_dong(v) and v not in ham_da_ghim:
                thieu.append("%s → hàm %s.%s" % (khoa, v.__module__, v.__name__))
    assert not thieu, (
        "Hàm đã ghim tham chiếu nguồn luật CHƯA ghim (đổi nguồn ấy mà test ghim vẫn xanh — F286):\n  %s\n"
        "Thêm vào HANG / HAM / GIA_TRI (rồi rà %s), hoặc vào MIEN kèm LÝ DO nếu không phải luật."
        % ("\n  ".join(thieu), MSW)
    )
