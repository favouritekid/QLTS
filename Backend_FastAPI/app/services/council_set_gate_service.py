# app/services/council_set_gate_service.py
"""Cổng dựng bộ văn bản Hội đồng (lượt G — quyết định owner 05-11: F228, F229, F231).

Thuần Python (không FastAPI, không CSDL): nhận dữ liệu kiểm ĐÃ ĐỌC trong CÙNG giao dịch chỉ đọc
của hàm đọc hồ sơ (:func:`app.services.council_candidate_service.doc_ho_so_theo_ma` —
``AnhChupHoSo.kiem``) và quyết từng dòng: CHẶN / CẢNH BÁO / qua. Không đổi giá trị nào của ảnh
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
mức theo năm học (F231); tắt hoặc không có luật ⇒ ``DIEM_KV_KHONG_CONG``; không xác định ⇒ CHẶN.
Chỉ điểm KV đổi — điểm đối tượng, trần ưu tiên vẫn theo luật v1 của bộ dựng.

**Lượt H2 (owner 06-11 — điểm đối tượng theo công tắc của đường xét, GIỮ cách tính):** cùng luật ấy,
công tắc ``apply_object_bonus`` qua ``priority_service.object_bonus_enabled`` (hàm T6 dùng). Bật ⇒ GIỮ
điểm đối tượng của luật v1 (dân tộc + xã thường trú) và trần 2,75 của bộ dựng; tắt / không có luật ⇒ in
``DIEM_UT_KHONG_CONG`` (:func:`diem_ut_in`); không xác định ⇒ CHẶN ``khong_xac_dinh_luat_cong_diem_ut``.
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
TRANG_THAI_CHAN = frozenset({"draft", "rejected", "withdrawal_pending", "withdrawn"})
TRANG_THAI_CANH_BAO = frozenset(
    {
        "submitted",
        "resubmitted",
        "reviewing",
        "revision_requested",
        "waitlisted",
        "result_published",
    }
)
TRANG_THAI_KHONG_CANH_BAO = frozenset(
    {"approved", "admitted", "confirmed", "enrolled", "overridden"}
)

MUC_CHAN = "chan"
MUC_CANH_BAO = "canh_bao"
MUC_KHONG = "khong"


def muc_trang_thai(status: object) -> str:
    """MỘT nguồn phân mức trạng thái. Chỉ hai tập "cho qua" được liệt kê dương; mọi giá trị
    khác — bốn trạng thái chặn, trạng thái thêm sau này, ``None``, không phải chuỗi — ⇒ CHẶN.
    """
    if isinstance(status, str):
        if status in TRANG_THAI_KHONG_CANH_BAO:
            return MUC_KHONG
        if status in TRANG_THAI_CANH_BAO:
            return MUC_CANH_BAO
    return MUC_CHAN


# ═══════════════════════════════ mã lý do chặn (không PII) ══════════════════════════════
LY_DO: Dict[str, str] = {
    # F228
    "trang_thai_chan": "trạng thái hồ sơ không được đưa vào Quyết định trúng tuyển",
    "trang_thai_la": "trạng thái hồ sơ không thuộc tập nào owner đã chốt — chặn",
    # F229 — chung
    "luong_khong_xac_dinh": "không xác định được hồ sơ một hay nhiều nguyện vọng",
    "thieu_hoc_phi_hk1": "chưa có khoản học phí học kỳ 1 — không có mã ngành để in",
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
}

# Câu 22 — luật cộng điểm KV của đường xét in (do hàm đọc điền bằng ĐÚNG hàm T6 dùng:
# ``resolve_effective_bonus_rule`` + ``priority_service.area_bonus_enabled``).
LUAT_KV_CONG = "cong"  # luật bật ``apply_area_bonus`` ⇒ in mức KV theo năm học
LUAT_KV_TAT = "tat"  # có luật, ``apply_area_bonus`` tắt ⇒ T6 tính 0 ⇒ in 0
# không override, phương thức không mặc định ⇒ T6 tính 0
LUAT_KV_KHONG_CO = "khong_co_luat"
LUAT_KV_HOP_LE = frozenset({LUAT_KV_CONG, LUAT_KV_TAT, LUAT_KV_KHONG_CO})
DIEM_KV_KHONG_CONG = "0.00"
# Owner 06-11 (lượt H2): công tắc ĐỐI TƯỢNG của cùng luật (``apply_object_bonus`` — hàm đọc điền bằng
# ``priority_service.object_bonus_enabled``), cùng ba giá trị ``LUAT_KV_*``. Cộng ⇒ GIỮ điểm đối tượng của
# luật v1 (suy từ dân tộc + xã thường trú; trần 2,75 của bộ dựng); tắt / không có luật ⇒ in "0" (như luật v1
# in cho người không thuộc diện). KHÔNG dùng ``max_total_bonus``, KHÔNG cắt tỉ lệ như T6.
DIEM_UT_KHONG_CONG = "0"


@dataclass(frozen=True)
class DuLieuKiem:
    """Dữ liệu kiểm của MỘT dòng — đọc trong cùng giao dịch chỉ đọc với ảnh chụp.

    ``nv_in_id`` / ``hp_*``: đúng nguyện vọng / khoản học phí mà truy vấn ảnh chụp
    (``SQL_SO_LIEU``) dùng để in (cột phụ của chính truy vấn ấy — không tính lại). ``nv1_id``:
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
    luat_kv: Optional[str]  # câu 22 — một trong LUAT_KV_HOP_LE; None = không xác định
    # lượt H2 — công tắc đối tượng, cùng ba giá trị; None = không xác định
    luat_ut: Optional[str]


def diem_ut_in(luat_ut: Optional[str], diem_ut_v1: str) -> Optional[str]:
    """Lượt H2 — điểm ĐỐI TƯỢNG in: luật cộng ⇒ GIỮ ``diem_ut_v1`` (luật v1 của bộ xuất); tắt / không có
    luật ⇒ ``DIEM_UT_KHONG_CONG``; không xác định ⇒ ``None`` (dòng ấy đã bị chặn)."""
    if luat_ut == LUAT_KV_CONG:
        return diem_ut_v1
    if luat_ut in (LUAT_KV_TAT, LUAT_KV_KHONG_CO):
        return DIEM_UT_KHONG_CONG
    return None


def diem_kv_in(k: DuLieuKiem) -> Optional[str]:
    """Câu 22 — điểm KV IN cho dòng: mức theo năm học (F231) khi luật của đường xét cộng KV;
    ``DIEM_KV_KHONG_CONG`` khi luật tắt / không có luật (đúng như T6 tính 0); ``None`` khi chưa có
    mức hoặc luật không xác định (dòng ấy đã bị chặn)."""
    if k.kv_muc is None:
        return None
    if k.luat_kv == LUAT_KV_CONG:
        return k.kv_muc
    if k.luat_kv in (LUAT_KV_TAT, LUAT_KV_KHONG_CO):
        return DIEM_KV_KHONG_CONG
    return None


def ly_do_cua_dong(k: DuLieuKiem) -> List[str]:
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
    if k.nv_in_path_id is not None and k.luat_kv not in LUAT_KV_HOP_LE:
        out.append("khong_xac_dinh_luat_cong_diem_kv")
    if k.nv_in_path_id is not None and k.luat_ut not in LUAT_KV_HOP_LE:
        out.append("khong_xac_dinh_luat_cong_diem_ut")
    return out


@dataclass(frozen=True)
class KetQuaCong:
    """Kết quả cổng cho cả danh sách (thứ tự dòng = thứ tự đầu vào, đếm từ 1)."""

    trang_thai: Tuple[Optional[str], ...]
    chan: Tuple[
        Tuple[str, Optional[str], Tuple[int, ...]], ...
    ]  # (mã, trạng thái?, dòng)
    canh_bao: Dict[str, Tuple[int, ...]]  # trạng thái cảnh báo -> dòng
    diem_kv: Tuple[Optional[str], ...]  # điểm KV IN (câu 22: theo luật của đường xét)
    luat_kv: Tuple[Optional[str], ...] = ()
    luat_ut: Tuple[Optional[str], ...] = ()  # lượt H2 — công tắc đối tượng từng dòng

    @staticmethod
    def _dem(gia_tri: Tuple[Optional[str], ...]) -> Dict[str, int]:
        dem: Dict[str, int] = {}
        for s in gia_tri:
            ten = s if isinstance(s, str) else "(không rõ)"
            dem[ten] = dem.get(ten, 0) + 1
        return dict(sorted(dem.items()))

    def so_theo_luat_kv(self) -> Dict[str, int]:
        return self._dem(self.luat_kv)

    def so_theo_luat_ut(self) -> Dict[str, int]:
        return self._dem(self.luat_ut)

    def so_canh_bao(self) -> Dict[str, int]:
        return {s: len(d) for s, d in sorted(self.canh_bao.items())}

    def so_theo_trang_thai(self) -> Dict[str, int]:
        dem: Dict[str, int] = {}
        for s in self.trang_thai:
            ten = s if isinstance(s, str) else "(không rõ)"
            dem[ten] = dem.get(ten, 0) + 1
        return dict(sorted(dem.items()))


def danh_gia(kiem: Sequence[DuLieuKiem]) -> KetQuaCong:
    """Áp ba cổng cho mọi dòng. Không ném lỗi — :func:`kiem_va_xac_nhan` quyết."""
    chan: Dict[Tuple[str, Optional[str]], List[int]] = {}
    canh_bao: Dict[str, List[int]] = {}
    for k in kiem:
        muc = muc_trang_thai(k.status)
        if muc == MUC_CHAN:
            ma = "trang_thai_chan" if k.status in TRANG_THAI_CHAN else "trang_thai_la"
            ten = k.status if isinstance(k.status, str) else None
            chan.setdefault((ma, ten), []).append(k.stt)
        elif muc == MUC_CANH_BAO:
            canh_bao.setdefault(k.status, []).append(k.stt)
        for ma in ly_do_cua_dong(k):
            chan.setdefault((ma, None), []).append(k.stt)
    thu_tu = list(LY_DO)
    return KetQuaCong(
        trang_thai=tuple(k.status for k in kiem),
        chan=tuple(
            (ma, tt, tuple(sorted(dong)))
            for (ma, tt), dong in sorted(
                chan.items(), key=lambda x: (thu_tu.index(x[0][0]), x[0][1] or "")
            )
        ),
        canh_bao={s: tuple(sorted(d)) for s, d in sorted(canh_bao.items())},
        diem_kv=tuple(diem_kv_in(k) for k in kiem),
        luat_kv=tuple(k.luat_kv for k in kiem),
        luat_ut=tuple(k.luat_ut for k in kiem),
    )


def _noi_dung_kiem(kq: KetQuaCong, muc: str, duoc_xac_nhan: bool) -> Dict[str, Any]:
    """Phần ``public_payload`` (JSON thuần — chỉ số dòng, mã lý do, trạng thái, số đếm)."""
    return {
        "kiem_tra_dung_bo": {
            "muc": muc,
            "so_dong": len(kq.trang_thai),
            "chan": [
                {
                    "ma": ma,
                    "mo_ta": LY_DO[ma],
                    "trang_thai": tt,
                    "so_ho_so": len(dong),
                    "dong": list(dong),
                }
                for ma, tt, dong in kq.chan
            ],
            "canh_bao": {
                "so_ho_so_theo_trang_thai": kq.so_canh_bao(),
                "dong_theo_trang_thai": {s: list(d) for s, d in kq.canh_bao.items()},
            },
            "can_admin_xac_nhan": bool(kq.canh_bao),
            "nguoi_goi_duoc_xac_nhan": bool(duoc_xac_nhan),
        }
    }


def kiem_dang_xac_nhan(xac_nhan: object) -> Optional[Dict[str, int]]:
    """``xac_nhan_trang_thai`` của yêu cầu: ``None`` (không xác nhận) hoặc dict KHÔNG rỗng
    {trạng thái thuộc tập CẢNH BÁO: số hồ sơ ≥ 1}. Sai dạng ⇒ ``DataValidationError``.
    """
    if xac_nhan is None:
        return None
    if not isinstance(xac_nhan, Mapping) or not xac_nhan:
        raise DataValidationError(
            "Xác nhận trạng thái phải là danh sách {trạng thái: số hồ sơ} không rỗng."
        )
    out: Dict[str, int] = {}
    for s, n in xac_nhan.items():
        if not isinstance(s, str) or s not in TRANG_THAI_CANH_BAO:
            raise DataValidationError(
                "Xác nhận chỉ áp cho trạng thái thuộc mức cảnh báo."
            )
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise DataValidationError("Số hồ sơ trong xác nhận phải là số nguyên ≥ 1.")
        out[s] = n
    return dict(sorted(out.items()))


def kiem_quyen_xac_nhan(
    xac_nhan: Optional[Dict[str, int]], duoc_xac_nhan: bool
) -> None:
    """CHỈ admin được gửi xác nhận (owner 05-11). Quyền ``duoc_xac_nhan`` do ``deps.py`` tính
    (tầng chủ sở hữu); kiểm TRƯỚC khi đọc hồ sơ."""
    if xac_nhan is not None and duoc_xac_nhan is not True:
        raise PermissionDeniedError(
            detail="Chỉ admin được xác nhận dựng bộ có hồ sơ ở trạng thái cần cảnh báo."
        )


def kiem_va_xac_nhan(
    kq: KetQuaCong,
    *,
    xac_nhan: Optional[Dict[str, int]],
    duoc_xac_nhan: bool,
) -> Optional[Dict[str, int]]:
    """Chặn ⇒ ``DataValidationError`` (400, liệt kê từng dòng — xác nhận KHÔNG gỡ được chặn).
    Có cảnh báo mà không xác nhận / xác nhận lệch số đếm hiện tại ⇒ ``ConflictError`` (409, số
    đếm theo trạng thái + số dòng). Trả số đếm ĐÃ xác nhận (để ghi vết) hoặc ``None``.
    """
    kiem_quyen_xac_nhan(xac_nhan, duoc_xac_nhan)
    if kq.chan:
        so_dong = len({d for _, _, dong in kq.chan for d in dong})
        raise DataValidationError(
            "Không dựng bộ văn bản: %d hồ sơ không đưa được vào văn bản (%d lý do) — xem "
            "danh sách từng dòng." % (so_dong, len(kq.chan)),
            public_payload=_noi_dung_kiem(kq, MUC_CHAN, duoc_xac_nhan),
        )
    dem = kq.so_canh_bao()
    if not dem:
        if xac_nhan is not None:
            raise ConflictError(
                "Không còn hồ sơ nào cần xác nhận trạng thái — gửi lại không kèm xác nhận.",
                public_payload=_noi_dung_kiem(kq, "xac_nhan_lech", duoc_xac_nhan),
            )
        return None
    if xac_nhan is None:
        cau = (
            "Có %d hồ sơ ở trạng thái cần cảnh báo — admin phải xác nhận số hồ sơ theo "
            "từng trạng thái rồi gửi lại." % sum(dem.values())
            if duoc_xac_nhan
            else "Có %d hồ sơ ở trạng thái cần cảnh báo — cần admin xác nhận."
            % sum(dem.values())
        )
        raise ConflictError(
            cau, public_payload=_noi_dung_kiem(kq, "can_xac_nhan", duoc_xac_nhan)
        )
    if xac_nhan != dem:
        raise ConflictError(
            "Số hồ sơ theo trạng thái đã khác lúc xác nhận — xem lại rồi xác nhận lại.",
            public_payload=_noi_dung_kiem(kq, "xac_nhan_lech", duoc_xac_nhan),
        )
    return dem
