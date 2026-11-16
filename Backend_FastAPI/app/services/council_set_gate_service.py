# app/services/council_set_gate_service.py
"""Cổng dựng bộ văn bản Hội đồng (lượt G — quyết định owner 05-11: F228, F229, F231).

Thuần Python (không FastAPI, không CSDL): nhận dữ liệu kiểm ĐÃ ĐỌC trong CÙNG giao dịch chỉ đọc
của hàm đọc hồ sơ (:func:`app.services.council_candidate_service.doc_ho_so_theo_ma` —
``ProfileSnapshot.kiem``) và quyết từng dòng: CHẶN / CẢNH BÁO / qua. Không đổi giá trị nào của ảnh
chụp ngoài ``diem_kv`` (F231 — mức theo năm học, do hàm đọc tra bằng helper của
``priority_service``).

**F228 — trạng thái hồ sơ, ba mức (owner 05-11, nguyên văn):**

* CHẶN: ``draft``, ``rejected``, ``withdrawal_pending``, ``withdrawn``;
* CẢNH BÁO + ADMIN xác nhận, ghi vết: ``submitted``, ``resubmitted``, ``reviewing``,
  ``revision_requested``, ``waitlisted``, ``result_published``;
* KHÔNG cảnh báo: ``approved``, ``admitted``, ``confirmed``, ``enrolled``, ``overridden``.

Trạng thái không thuộc tập nào (thêm sau này) ⇒ CHẶN (fail-closed). Ba tập phủ ĐỦ 15 trạng thái
của CHECK ``ck_admission_profile_status`` (``app/models/admission.py``) và của
``ALLOWED_TRANSITIONS`` — test ``tests/unit/test_council_set_gate.py`` khoá.

**F229 — mỗi luồng một nguồn (owner 05-11).** "Một / nhiều nguyện vọng" theo ĐÚNG cờ app dùng:
``admission_profile.uses_choice_engine`` (``app/models/admission.py`` — cờ TƯỜNG MINH, không suy
từ số dòng nguyện vọng): ``False`` = hồ sơ một nguyện vọng kiểu cũ (điểm ở
``profile_subject_score``, ngành theo cấu hình hồ sơ như ``resolve_fee_academic_info`` nhánh
legacy); ``True`` = bộ máy nguyện vọng (lấy NV1 theo ``display_order``). Không phải bool ⇒ CHẶN.
Văn bản in theo truy vấn bộ xuất (bảng nguyện vọng) — mọi chỗ nguồn in KHÁC nguồn của luồng ⇒
CHẶN, liệt kê từng dòng (không tự chọn bên nào).

**F231 — khu vực ưu tiên:** KV đã phân giải theo ĐÚNG vị từ của app (``kv_snapshot_resolved``);
ấn định thủ công phải còn hiệu lực theo ĐÚNG ``verify_manual_override_provenance``; mức theo năm
học của hồ sơ qua ``select_open_priority_rates`` (hàm đọc gọi — không chép luật ở đây). Thiếu ⇒
CHẶN, không in rỗng / 0.

**Câu 21 (owner 06-11 — chặn và liệt kê):** KV in lấy từ ảnh chụp; "Nộp lại" không chụp lại ⇒
hàm đọc TÍNH LẠI KV chỉ đọc bằng ĐÚNG resolver của app (``resolve_kv_for_profile`` — năm học hồ sơ
qua ``priority_academic_year`` bên trong nó; cùng ngữ cảnh trình độ / loại hình đã ghi trong ảnh
chụp) và so mã KV. Khác ⇒ CHẶN ``khu_vuc_doi_sau_anh_chup``; resolver ném lỗi ⇒ CHẶN
``khu_vuc_khong_tinh_lai_duoc``. Ấn định thủ công không tính lại (resolver CỐ Ý không phân giải
nhánh ấy) — đã qua ``verify_manual_override_provenance``, hàm này tự so dấu vân tay dữ liệu KV.

**Câu 22 (owner 06-11 — theo cấu hình đường xét):** điểm KV IN theo luật cộng điểm của ĐƯỜNG XÉT
của nguyện vọng in, đúng như T6 của app: hàm đọc lấy luật bằng ``resolve_effective_bonus_rule``
(override của đường xét, không thì mặc định của phương thức — JSON ``null`` của cột override đọc
qua ORM thành ``None`` ⇒ rơi về phương thức, như T6) và quyết bằng
``priority_service.area_bonus_enabled`` (cùng hàm ``calculate_priority_bonus`` dùng). Luật bật ⇒
mức theo năm học (F231); tắt hoặc không có luật ⇒ ``AREA_SCORE_NOT_ADDED``; không xác định ⇒ CHẶN.
Chỉ điểm KV đổi — điểm đối tượng, trần ưu tiên vẫn theo luật v1 của bộ dựng.

**Lượt H2 (owner 06-11 — điểm đối tượng theo công tắc của đường xét, GIỮ cách tính):** cùng luật ấy,
công tắc ``apply_object_bonus`` qua ``priority_service.object_bonus_enabled`` (hàm T6 dùng). Bật ⇒ GIỮ
điểm đối tượng của luật v1 (dân tộc + xã thường trú) và trần 2,75 của bộ dựng; tắt / không có luật ⇒ in
``PRIORITY_SCORE_NOT_ADDED`` (:func:`printed_priority_score`); không xác định ⇒ CHẶN ``khong_xac_dinh_luat_cong_diem_ut``.
KHÔNG dùng ``max_total_bonus`` của đường xét, KHÔNG cắt tỉ lệ như T6. Mã đối tượng in (``ut_ma``) giữ nguyên.

Lỗi chỉ nêu SỐ DÒNG + mã lý do + trạng thái — không mã hồ sơ, không giá trị dữ liệu.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.utils.exceptions import (
    ConflictError,
    DataValidationError,
    PermissionDeniedError,
)

# ═══════════════════════════════ F228 — ba mức trạng thái ═══════════════════════════════
BLOCKING_STATUSES = frozenset({"draft", "rejected", "withdrawal_pending", "withdrawn"})
WARNING_STATUSES = frozenset(
    {
        "submitted",
        "resubmitted",
        "reviewing",
        "revision_requested",
        "waitlisted",
        "result_published",
    }
)
NON_WARNING_STATUSES = frozenset(
    {"approved", "admitted", "confirmed", "enrolled", "overridden"}
)

LEVEL_BLOCK = "chan"
LEVEL_WARNING = "canh_bao"
LEVEL_NONE = "khong"


def status_level(status: object) -> str:
    """MỘT nguồn phân mức trạng thái. Chỉ hai tập "cho qua" được liệt kê dương; mọi giá trị
    khác — bốn trạng thái chặn, trạng thái thêm sau này, ``None``, không phải chuỗi — ⇒ CHẶN.
    """
    if isinstance(status, str):
        if status in NON_WARNING_STATUSES:
            return LEVEL_NONE
        if status in WARNING_STATUSES:
            return LEVEL_WARNING
    return LEVEL_BLOCK


# ═══════════════════════════════ mã lý do chặn (không PII) ══════════════════════════════
BLOCK_REASONS: Dict[str, str] = {
    # F228
    "trang_thai_chan": "trạng thái hồ sơ không được đưa vào Quyết định trúng tuyển",
    "trang_thai_la": "trạng thái hồ sơ không thuộc tập nào owner đã chốt — chặn",
    # F229 — chung
    "luong_khong_xac_dinh": "không xác định được hồ sơ một hay nhiều nguyện vọng",
    "thieu_hoc_phi_hk1": "chưa có khoản học phí học kỳ 1 — không có mã ngành để in",
    # Review max PR #724 (R5): CCCD = mã hồ sơ in trên văn bản; thiếu thì CHẶN DÒNG ẤY (trước đây làm hỏng cả lô).
    "thieu_ma_ho_so": "hồ sơ chưa có số CCCD — mã hồ sơ in trên văn bản sẽ trống; bổ sung CCCD rồi kiểm lại",
    # Codex 42 F334 (nhánh anh em của R5): trước đây làm hỏng CẢ LÔ, kèm số dòng đếm SAU khi lọc (sai dòng).
    "tham_chieu_trung": (
        "dữ liệu tham chiếu (địa giới / khu vực / dân tộc) của hồ sơ khớp nhiều hàng hiện hành — phần mềm không tự "
        "chọn một hàng; sửa danh mục rồi kiểm lại"
    ),
    "hoc_phi_chua_gan_nganh": "khoản học phí học kỳ 1 chưa gắn ngành — không có mã ngành để in",
    "hoc_phi_khac_nganh_nv": (
        "ngành của khoản học phí học kỳ 1 khác ngành của nguyện vọng dùng để in"
    ),
    "diem_hai_nguon_khac": (
        "hai bảng điểm (nguyện vọng / hồ sơ) cùng có môn của tổ hợp in mà khác nhau"
    ),
    # F229 — hồ sơ nhiều nguyện vọng (bộ máy nguyện vọng)
    "nhieu_nv_khong_co_nv": "hồ sơ nhiều nguyện vọng không có nguyện vọng nào",
    "nv1_thieu_cau_hinh": (
        "không nguyện vọng nào đủ đường xét / tổ hợp / ngành — văn bản không in được "
        "nguyện vọng 1"
    ),
    "nv_in_khac_nv1": (
        "văn bản sẽ in một nguyện vọng không phải nguyện vọng 1 (nguyện vọng 1 thiếu "
        "đường xét / tổ hợp / ngành)"
    ),
    "trung_nv_khac": (
        "hồ sơ trúng một nguyện vọng khác nguyện vọng dùng để in (nguyện vọng 2 trở đi)"
    ),
    "nhieu_nv_trung": "hồ sơ có hơn một nguyện vọng trúng tuyển (dữ liệu lỗi)",
    # F229 — hồ sơ một nguyện vọng (kiểu cũ)
    "mot_nv_khong_co_dong_nguyen_vong": (
        "hồ sơ một nguyện vọng (kiểu cũ) không có dòng ở bảng nguyện vọng — văn bản chưa in "
        "được điểm từ bảng điểm hồ sơ (chưa hỗ trợ)"
    ),
    "mot_nv_nhieu_dong_nguyen_vong": (
        "hồ sơ một nguyện vọng (kiểu cũ) có nhiều dòng ở bảng nguyện vọng — không xác định "
        "được nguyện vọng in"
    ),
    "mot_nv_khong_xac_dinh_nganh": (
        "hồ sơ một nguyện vọng: không xác định được ngành từ cấu hình của hồ sơ"
    ),
    "mot_nv_khong_xac_dinh_duong_xet": (
        "hồ sơ một nguyện vọng: không xác định được đường xét (phương thức) của hồ sơ"
    ),
    "mot_nv_khong_xac_dinh_to_hop": (
        "hồ sơ một nguyện vọng: hồ sơ chưa ghi tổ hợp đã chọn"
    ),
    "mot_nv_khac_nganh": (
        "hồ sơ một nguyện vọng: ngành trên dòng nguyện vọng khác ngành của hồ sơ"
    ),
    "mot_nv_khac_duong_xet": (
        "hồ sơ một nguyện vọng: đường xét (phương thức) trên dòng nguyện vọng khác của hồ sơ"
    ),
    "mot_nv_khac_to_hop": (
        "hồ sơ một nguyện vọng: tổ hợp trên dòng nguyện vọng khác tổ hợp hồ sơ đã chọn"
    ),
    "mot_nv_diem_lech": (
        "hồ sơ một nguyện vọng: điểm sẽ in (bảng nguyện vọng) khác bảng điểm hồ sơ"
    ),
    # F231
    "thieu_khu_vuc": "hồ sơ chưa có khu vực ưu tiên đã phân giải",
    "khu_vuc_thu_cong_khong_hieu_luc": "khu vực ấn định thủ công không còn hiệu lực",
    "chua_co_muc_khu_vuc": (
        "chưa có mức điểm khu vực đang áp dụng cho năm học của hồ sơ"
    ),
    "muc_khu_vuc_khong_nhat_quan": (
        "hơn một mức điểm khu vực đang mở cho cùng năm học (dữ liệu mức lỗi)"
    ),
    # Câu 21 (owner 06-11 — chặn và liệt kê)
    "khu_vuc_doi_sau_anh_chup": (
        "khu vực tính lại từ dữ liệu hiện tại của hồ sơ khác khu vực sẽ in (ảnh chụp lúc "
        "nộp / chấm) — dữ liệu khu vực đã đổi sau lần chụp"
    ),
    "khu_vuc_khong_tinh_lai_duoc": (
        "không tính lại được khu vực từ dữ liệu hiện tại của hồ sơ để đối chiếu"
    ),
    # Câu 22 (owner 06-11 — theo cấu hình đường xét)
    "khong_xac_dinh_luat_cong_diem_kv": (
        "không xác định được luật cộng điểm khu vực của đường xét dùng để in"
    ),
    # Owner 06-11 (lượt H2) — điểm đối tượng theo công tắc của đường xét
    "khong_xac_dinh_luat_cong_diem_ut": (
        "không xác định được luật cộng điểm đối tượng của đường xét dùng để in"
    ),
    # Lượt I (F230) — tình trạng Quyết định đã ký của hồ sơ (đọc trong CÙNG giao dịch chỉ đọc bằng
    # biểu thức một nguồn ``SQL_COT_TINH_TRANG_QD``). N10 / C7 / N13 + E1.
    "da_co_quyet_dinh": (
        "hồ sơ đã có tên trong một Quyết định đã ký đang hiệu lực — không đưa vào bộ văn bản mới"
    ),
    "cho_admin_quyet": (
        "hồ sơ thuộc Quyết định đã bị huỷ hiệu lực — chờ Admin cho phép xét lại"
    ),
    "dau_trung_tuyen_appsheet": (
        "hồ sơ mang dấu 'Đã trúng tuyển theo QĐ số …' (nhập từ AppSheet) — chưa có sổ Quyết "
        "định cũ trong phần mềm"
    ),
}

#: Mã chặn theo TÌNH TRẠNG Quyết định (lượt I) — tách khỏi cổng dữ liệu để đường tái dựng bản ký dùng
#: riêng (đặc tả mục 3.1 bước 7).
DECISION_STATE_CODES = ("da_co_quyet_dinh", "cho_admin_quyet", "dau_trung_tuyen_appsheet")

# Câu 22 — luật cộng điểm KV của đường xét in (do hàm đọc điền bằng ĐÚNG hàm T6 dùng:
# ``resolve_effective_bonus_rule`` + ``priority_service.area_bonus_enabled``).
AREA_RULE_ADD = "cong"  # luật bật ``apply_area_bonus`` ⇒ in mức KV theo năm học
AREA_RULE_OFF = "tat"  # có luật, ``apply_area_bonus`` tắt ⇒ T6 tính 0 ⇒ in 0
# không override, phương thức không mặc định ⇒ T6 tính 0
AREA_RULE_NONE = "khong_co_luat"
VALID_AREA_RULES = frozenset({AREA_RULE_ADD, AREA_RULE_OFF, AREA_RULE_NONE})
AREA_SCORE_NOT_ADDED = "0.00"
# Owner 06-11 (lượt H2): công tắc ĐỐI TƯỢNG của cùng luật (``apply_object_bonus`` — hàm đọc điền bằng
# ``priority_service.object_bonus_enabled``), cùng ba giá trị ``LUAT_KV_*``. Cộng ⇒ GIỮ điểm đối tượng của
# luật v1 (suy từ dân tộc + xã thường trú; trần 2,75 của bộ dựng); tắt / không có luật ⇒ in "0" (như luật v1
# in cho người không thuộc diện). KHÔNG dùng ``max_total_bonus``, KHÔNG cắt tỉ lệ như T6.
PRIORITY_SCORE_NOT_ADDED = "0"


@dataclass(frozen=True)
class CheckData:
    """Dữ liệu kiểm của MỘT dòng — đọc trong cùng giao dịch chỉ đọc với ảnh chụp.

    ``nv_in_id`` / ``hp_*``: đúng nguyện vọng / khoản học phí mà truy vấn ảnh chụp
    (``SQL_PRINT_FIGURES``) dùng để in (cột phụ của chính truy vấn ấy — không tính lại). ``nv1_id``:
    nguyện vọng 1 theo app (``display_order`` rồi ``id``, KHÔNG đòi chuỗi cấu hình đủ).
    ``lg_*``: nguồn của hồ sơ một nguyện vọng kiểu cũ. ``diem_*``: số môn của tổ hợp in lệch
    giữa hai bảng điểm. ``kv_*``: kết quả tra khu vực (F231) do hàm đọc điền."""

    stt: int
    status: Optional[str]
    uses_choice_engine: Any
    so_nv: int
    nv1_id: Optional[int]
    nv_in_id: Optional[int]
    so_nv_trung: int
    nv_trung_id: Optional[int]
    hp_co: bool
    hp_nganh_id: Optional[int]
    nv_in_nganh_id: Optional[int]
    nv_in_path_id: Optional[int]
    nv_in_sg_id: Optional[int]
    lg_nganh_id: Optional[int]
    lg_path_id: Optional[int]
    lg_sg_id: Optional[int]
    diem_ca_hai_khac: int
    diem_chi_nv: int
    diem_chi_hs: int
    kv_ly_do: Optional[str]
    kv_muc: Optional[str]
    luat_kv: Optional[str]  # câu 22 — một trong VALID_AREA_RULES; None = không xác định
    # lượt H2 — công tắc đối tượng, cùng ba giá trị; None = không xác định
    luat_ut: Optional[str]
    # Lượt I (F230) — khoá đếm của NV in (ghi vào dòng bộ) + tình trạng Quyết định (hàm đọc điền
    # bằng ``council_decision_status_service.from_row`` trên cột ``SQL_COT_TINH_TRANG_QD``).
    nv_in_ai_id: Optional[int] = None
    nv_in_offering_id: Optional[int] = None
    qd_hieu_luc_id: Optional[int] = None
    qd_chuoi_id: Optional[int] = None
    cho_quyet_id: Optional[int] = None
    dau_appsheet: bool = False
    # Review max PR #724 (R5): CCCD (``ma_ho_so``) trống / chỉ khoảng trắng ⇒ dòng bị chặn ``thieu_ma_ho_so``.
    thieu_ma_ho_so: bool = False
    # Codex 42 F334: số liệu in của hồ sơ khớp NHIỀU hàng tham chiếu hiện hành ⇒ dòng bị chặn ``tham_chieu_trung``.
    duplicate_reference: bool = False


def printed_priority_score(priority_rule: Optional[str], priority_score_v1: str) -> Optional[str]:
    """Lượt H2 — điểm ĐỐI TƯỢNG in: luật cộng ⇒ GIỮ ``priority_score_v1`` (luật v1 của bộ xuất); tắt / không có
    luật ⇒ ``PRIORITY_SCORE_NOT_ADDED``; không xác định ⇒ ``None`` (dòng ấy đã bị chặn)."""
    if priority_rule == AREA_RULE_ADD:
        return priority_score_v1
    if priority_rule in (AREA_RULE_OFF, AREA_RULE_NONE):
        return PRIORITY_SCORE_NOT_ADDED
    return None


def printed_area_score(k: CheckData) -> Optional[str]:
    """Câu 22 — điểm KV IN cho dòng: mức theo năm học (F231) khi luật của đường xét cộng KV;
    ``AREA_SCORE_NOT_ADDED`` khi luật tắt / không có luật (đúng như T6 tính 0); ``None`` khi chưa có
    mức hoặc luật không xác định (dòng ấy đã bị chặn)."""
    if k.kv_muc is None:
        return None
    if k.luat_kv == AREA_RULE_ADD:
        return k.kv_muc
    if k.luat_kv in (AREA_RULE_OFF, AREA_RULE_NONE):
        return AREA_SCORE_NOT_ADDED
    return None


def row_block_reason(k: CheckData) -> List[str]:
    """Mã lý do CHẶN của một dòng (F229 + F231; F228 tính riêng theo trạng thái). Rỗng ⇒ dòng
    qua được phần nguồn dữ liệu."""
    out: List[str] = []
    ce = k.uses_choice_engine
    if not isinstance(ce, bool):
        out.append("luong_khong_xac_dinh")
    elif ce:
        # Bộ máy nguyện vọng: in NV1 (owner 05-11).
        if k.so_nv == 0:
            out.append("nhieu_nv_khong_co_nv")
        else:
            if k.nv_in_id is None:
                out.append("nv1_thieu_cau_hinh")
            elif k.nv_in_id != k.nv1_id:
                out.append("nv_in_khac_nv1")
            if k.so_nv_trung > 1:
                out.append("nhieu_nv_trung")
            elif k.so_nv_trung == 1 and k.nv_trung_id != k.nv_in_id:
                out.append("trung_nv_khac")
    else:
        # Một nguyện vọng kiểu cũ: nguồn = cấu hình + bảng điểm của HỒ SƠ.
        if k.so_nv == 0:
            out.append("mot_nv_khong_co_dong_nguyen_vong")
        elif k.so_nv > 1:
            out.append("mot_nv_nhieu_dong_nguyen_vong")
        if k.lg_nganh_id is None:
            out.append("mot_nv_khong_xac_dinh_nganh")
        if k.lg_path_id is None:
            out.append("mot_nv_khong_xac_dinh_duong_xet")
        if k.lg_sg_id is None:
            out.append("mot_nv_khong_xac_dinh_to_hop")
        if k.so_nv == 1:
            if k.lg_nganh_id is not None and k.nv_in_nganh_id != k.lg_nganh_id:
                out.append("mot_nv_khac_nganh")
            if k.lg_path_id is not None and k.nv_in_path_id != k.lg_path_id:
                out.append("mot_nv_khac_duong_xet")
            if k.lg_sg_id is not None and k.nv_in_sg_id != k.lg_sg_id:
                out.append("mot_nv_khac_to_hop")
            if k.diem_ca_hai_khac or k.diem_chi_nv or k.diem_chi_hs:
                out.append("mot_nv_diem_lech")
    if isinstance(ce, bool) and ce and k.diem_ca_hai_khac:
        out.append("diem_hai_nguon_khac")
    # Học phí (cả hai luồng): mã ngành in CHỈ lấy từ khoản học phí ⇒ thiếu = không in được.
    if not k.hp_co:
        out.append("thieu_hoc_phi_hk1")
    elif k.hp_nganh_id is None:
        out.append("hoc_phi_chua_gan_nganh")
    elif k.nv_in_nganh_id is not None and k.hp_nganh_id != k.nv_in_nganh_id:
        out.append("hoc_phi_khac_nganh_nv")
    # F231
    if k.kv_ly_do is not None:
        out.append(k.kv_ly_do)
    # Câu 22: đường xét in đã biết (không thì dòng đã bị chặn ở trên) mà luật không xác định.
    if k.nv_in_path_id is not None and k.luat_kv not in VALID_AREA_RULES:
        out.append("khong_xac_dinh_luat_cong_diem_kv")
    if k.nv_in_path_id is not None and k.luat_ut not in VALID_AREA_RULES:
        out.append("khong_xac_dinh_luat_cong_diem_ut")
    if k.thieu_ma_ho_so:
        out.append("thieu_ma_ho_so")
    if k.duplicate_reference:
        out.append("tham_chieu_trung")
    return out


def decision_state_block_reason(
    k: CheckData, allowed_decision_chain: Optional[int] = None
) -> List[str]:
    """Mã chặn theo tình trạng Quyết định của MỘT dòng (lượt I). ``allowed_decision_chain`` = id Quyết
    định gốc của chuỗi mà bộ ĐIỀU CHỈNH được dựng cho — CHỈ nới đúng một phép: hồ sơ có dòng hiệu lực
    TRONG CHÍNH chuỗi ấy (ca "sửa thông tin em C" — BS §1.3). Dựng bộ xét mới gọi KHÔNG kèm chuỗi."""
    out: List[str] = []
    if k.qd_hieu_luc_id is not None and not (
        allowed_decision_chain is not None and k.qd_chuoi_id == allowed_decision_chain
    ):
        out.append("da_co_quyet_dinh")
    if k.cho_quyet_id is not None:
        out.append("cho_admin_quyet")
    if k.dau_appsheet:
        out.append("dau_trung_tuyen_appsheet")
    return out


@dataclass(frozen=True)
class GateResult:
    """Kết quả cổng cho cả danh sách (thứ tự dòng = thứ tự đầu vào, đếm từ 1)."""

    statuses: Tuple[Optional[str], ...]
    blocks: Tuple[
        Tuple[str, Optional[str], Tuple[int, ...]], ...
    ]  # (mã, trạng thái?, dòng)
    warnings: Dict[str, Tuple[int, ...]]  # trạng thái cảnh báo -> dòng
    area_scores: Tuple[Optional[str], ...]  # điểm KV IN (câu 22: theo luật của đường xét)
    area_rules: Tuple[Optional[str], ...] = ()
    priority_rules: Tuple[Optional[str], ...] = ()  # lượt H2 — công tắc đối tượng từng dòng

    @staticmethod
    def _count(value: Tuple[Optional[str], ...]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for s in value:
            name = s if isinstance(s, str) else "(không rõ)"
            counts[name] = counts.get(name, 0) + 1
        return dict(sorted(counts.items()))

    def count_by_area_rule(self) -> Dict[str, int]:
        return self._count(self.area_rules)

    def count_by_priority_rule(self) -> Dict[str, int]:
        return self._count(self.priority_rules)

    def warning_count(self) -> Dict[str, int]:
        return {s: len(d) for s, d in sorted(self.warnings.items())}

    def count_by_status(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for s in self.statuses:
            name = s if isinstance(s, str) else "(không rõ)"
            counts[name] = counts.get(name, 0) + 1
        return dict(sorted(counts.items()))


def evaluate(
    check: Sequence[CheckData], *, allowed_decision_chain: Optional[int] = None
) -> GateResult:
    """Áp các cổng cho mọi dòng. Không ném lỗi — :func:`check_and_confirm` quyết. Dựng bộ XÉT MỚI
    (``POST /sets``) gọi KHÔNG kèm ``allowed_decision_chain``; chỉ bộ điều chỉnh truyền chuỗi gốc."""
    blocked: Dict[Tuple[str, Optional[str]], List[int]] = {}
    warnings: Dict[str, List[int]] = {}
    for k in check:
        item = status_level(k.status)
        if item == LEVEL_BLOCK:
            code = "trang_thai_chan" if k.status in BLOCKING_STATUSES else "trang_thai_la"
            name = k.status if isinstance(k.status, str) else None
            blocked.setdefault((code, name), []).append(k.stt)
        elif item == LEVEL_WARNING:
            warnings.setdefault(k.status, []).append(k.stt)
        for code in row_block_reason(k) + decision_state_block_reason(k, allowed_decision_chain):
            blocked.setdefault((code, None), []).append(k.stt)
    return _result(check, blocked, warnings)


def evaluate_rebuild(check: Sequence[CheckData]) -> GateResult:
    """Cổng của đường TÁI DỰNG BẢN KÝ (lượt I, đặc tả mục 3.1 bước 6 — F245, owner C2 / C3) cho
    các dòng SỬA TAY: cổng DỮ LIỆU đủ (``row_block_reason`` — F229, F231, câu 21, câu 22) nhưng KHÔNG
    cổng trạng thái F228 (trạng thái chỉ được liệt kê — bản ký thắng), trừ trạng thái LẠ (dữ liệu
    hỏng ⇒ chặn). Tình trạng Quyết định kiểm riêng cho MỌI dòng (hàm hỏi). KHÔNG BAO GIỜ dùng cho bộ
    xét mới — ``tao_bo_van_ban`` gọi :func:`evaluate`."""
    blocked: Dict[Tuple[str, Optional[str]], List[int]] = {}
    for k in check:
        if not (
            isinstance(k.status, str)
            and (
                k.status in BLOCKING_STATUSES
                or k.status in WARNING_STATUSES
                or k.status in NON_WARNING_STATUSES
            )
        ):
            name = k.status if isinstance(k.status, str) else None
            blocked.setdefault(("trang_thai_la", name), []).append(k.stt)
        for code in row_block_reason(k):
            blocked.setdefault((code, None), []).append(k.stt)
    return _result(check, blocked, {})


def _result(check, blocked, warnings) -> GateResult:
    order_no = list(BLOCK_REASONS)
    return GateResult(
        statuses=tuple(k.status for k in check),
        blocks=tuple(
            (code, status, tuple(sorted(row)))
            for (code, status), row in sorted(
                blocked.items(), key=lambda x: (order_no.index(x[0][0]), x[0][1] or "")
            )
        ),
        warnings={s: tuple(sorted(d)) for s, d in sorted(warnings.items())},
        area_scores=tuple(printed_area_score(k) for k in check),
        area_rules=tuple(k.luat_kv for k in check),
        priority_rules=tuple(k.luat_ut for k in check),
    )


def _check_content(result: GateResult, item: str, can_confirm: bool) -> Dict[str, Any]:
    """Phần ``public_payload`` (JSON thuần — chỉ số dòng, mã lý do, trạng thái, số đếm)."""
    return {
        "kiem_tra_dung_bo": {
            "muc": item,
            "so_dong": len(result.statuses),
            "chan": [
                {
                    "ma": code,
                    "mo_ta": BLOCK_REASONS[code],
                    "trang_thai": status,
                    "so_ho_so": len(row),
                    "dong": list(row),
                }
                for code, status, row in result.blocks
            ],
            "canh_bao": {
                "so_ho_so_theo_trang_thai": result.warning_count(),
                "dong_theo_trang_thai": {s: list(d) for s, d in result.warnings.items()},
            },
            "can_admin_xac_nhan": bool(result.warnings),
            "nguoi_goi_duoc_xac_nhan": bool(can_confirm),
        }
    }


def check_confirmation_shape(confirmation: object) -> Optional[Dict[str, int]]:
    """``xac_nhan_trang_thai`` của yêu cầu: ``None`` (không xác nhận) hoặc dict KHÔNG rỗng
    {trạng thái thuộc tập CẢNH BÁO: số hồ sơ ≥ 1}. Sai dạng ⇒ ``DataValidationError``.
    """
    if confirmation is None:
        return None
    if not isinstance(confirmation, Mapping) or not confirmation:
        raise DataValidationError(
            "Xác nhận trạng thái phải là danh sách {trạng thái: số hồ sơ} không rỗng."
        )
    out: Dict[str, int] = {}
    for s, n in confirmation.items():
        if not isinstance(s, str) or s not in WARNING_STATUSES:
            raise DataValidationError(
                "Xác nhận chỉ áp cho trạng thái thuộc mức cảnh báo."
            )
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise DataValidationError("Số hồ sơ trong xác nhận phải là số nguyên ≥ 1.")
        out[s] = n
    return dict(sorted(out.items()))


def check_confirm_permission(
    confirmation: Optional[Dict[str, int]], can_confirm: bool
) -> None:
    """CHỈ admin được gửi xác nhận (owner 05-11). Quyền ``can_confirm`` do ``deps.py`` tính
    (tầng chủ sở hữu); kiểm TRƯỚC khi đọc hồ sơ."""
    if confirmation is not None and can_confirm is not True:
        raise PermissionDeniedError(
            detail="Chỉ admin được xác nhận dựng bộ có hồ sơ ở trạng thái cần cảnh báo."
        )


def check_and_confirm(
    result: GateResult,
    *,
    confirmation: Optional[Dict[str, int]],
    can_confirm: bool,
) -> Optional[Dict[str, int]]:
    """Chặn ⇒ ``DataValidationError`` (400, liệt kê từng dòng — xác nhận KHÔNG gỡ được chặn).
    Có cảnh báo mà không xác nhận / xác nhận lệch số đếm hiện tại ⇒ ``ConflictError`` (409, số
    đếm theo trạng thái + số dòng). Trả số đếm ĐÃ xác nhận (để ghi vết) hoặc ``None``.
    """
    check_confirm_permission(confirmation, can_confirm)
    if result.blocks:
        row_count = len({d for _, _, row in result.blocks for d in row})
        raise DataValidationError(
            "Không dựng bộ văn bản: %d hồ sơ không đưa được vào văn bản (%d lý do) — xem "
            "danh sách từng dòng." % (row_count, len(result.blocks)),
            public_payload=_check_content(result, LEVEL_BLOCK, can_confirm),
        )
    counts = result.warning_count()
    if not counts:
        if confirmation is not None:
            raise ConflictError(
                "Không còn hồ sơ nào cần xác nhận trạng thái — gửi lại không kèm xác nhận.",
                public_payload=_check_content(result, "xac_nhan_lech", can_confirm),
            )
        return None
    if confirmation is None:
        message = (
            "Có %d hồ sơ ở trạng thái cần cảnh báo — admin phải xác nhận số hồ sơ theo "
            "từng trạng thái rồi gửi lại." % sum(counts.values())
            if can_confirm
            else "Có %d hồ sơ ở trạng thái cần cảnh báo — cần admin xác nhận."
            % sum(counts.values())
        )
        raise ConflictError(
            message, public_payload=_check_content(result, "can_xac_nhan", can_confirm)
        )
    if confirmation != counts:
        raise ConflictError(
            "Số hồ sơ theo trạng thái đã khác lúc xác nhận — xem lại rồi xác nhận lại.",
            public_payload=_check_content(result, "xac_nhan_lech", can_confirm),
        )
    return counts
