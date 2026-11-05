# app/schemas/council_document.py
"""Schema API văn bản Hội đồng tuyển sinh (Lần xét tuyển GĐ1 — kho mẫu + bộ văn bản).

KHÔNG trả ra API: bytes mẫu / tệp (chỉ qua route tải tệp có kiểm quyền), ảnh chụp DTO
(``snapshot_dto``); danh sách mã hồ sơ đầu vào (``ma_ho_so_dau_vao`` — DỮ LIỆU CÁ NHÂN) chỉ
qua route riêng CHỈ ADMIN (``CouncilSetInputCodesOut``, J1 dòng 30). Hai cột ấy deferred,
không đọc ở các schema còn lại. ``thong_tin_dung`` chỉ có luật, thư viện, sha mẫu / tệp / mã
nguồn, ngành + số thí sinh, năm học, mốc giao dịch — không dữ liệu cá nhân.
"""
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from app.services.council_document_render_service import DecisionParams


class CouncilTemplateOut(BaseModel):
    """Một mẫu trong kho — metadata, không có bytes."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    loai: str
    hieu_luc_tu: date
    sha256: str
    kich_thuoc: int
    nguoi_tai_id: Optional[int] = None
    tai_luc: datetime
    ghi_chu: Optional[str] = None


class CouncilSetCreate(BaseModel):
    """Tạo bộ văn bản từ một danh sách mã hồ sơ (số CCCD) ĐÚNG THỨ TỰ — tương đương
    ``--chi-ma`` của bộ xuất. ``academic_year`` bắt buộc (CCCD chỉ duy nhất trong một năm
    học). Kiểm từng mã (rỗng / trùng / ký tự lạ / không khớp đúng một hồ sơ) và trần số hồ
    sơ do service làm — lỗi nêu SỐ DÒNG, không nêu giá trị."""

    model_config = ConfigDict(extra="forbid")

    ma_ho_so: List[str] = Field(..., min_length=1)
    academic_year: StrictInt
    tham_so_quyet_dinh: Optional[DecisionParams] = None
    # Lượt G (owner 05-11, F228): admin XÁC NHẬN dựng bộ có hồ sơ ở mức cảnh báo — ĐÚNG số hồ
    # sơ theo từng trạng thái máy chủ vừa báo (409). Khoá / số đếm do service kiểm
    # (``council_set_gate_service``); chỉ admin được gửi (``deps.py`` tính quyền).
    xac_nhan_trang_thai: Optional[Dict[str, StrictInt]] = None


class CouncilSetFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    thu_tu: int
    path: str
    sha256: str
    kich_thuoc: int


class CouncilSetOut(BaseModel):
    """Metadata một bộ văn bản (dùng cho danh sách)."""

    id: int
    nguoi_tao_id: Optional[int] = None
    tao_luc: datetime
    moc_chup: datetime
    unit_id: Optional[int] = None
    trinh_do: str
    so_ho_so: int
    so_tep: int
    kich_thuoc_tong: int
    nam_hoc: Optional[int] = None
    tham_so_quyet_dinh: Optional[Dict[str, Any]] = None

    @classmethod
    def tu_bo(cls, bo) -> "CouncilSetOut":
        return cls(
            id=bo.id,
            nguoi_tao_id=bo.nguoi_tao_id,
            tao_luc=bo.tao_luc,
            moc_chup=bo.moc_chup,
            unit_id=bo.unit_id,
            trinh_do=bo.trinh_do,
            so_ho_so=bo.so_ho_so,
            so_tep=bo.so_tep,
            kich_thuoc_tong=bo.kich_thuoc_tong,
            nam_hoc=(bo.thong_tin_dung or {}).get("nam_hoc"),
            tham_so_quyet_dinh=bo.tham_so_quyet_dinh,
        )


class CouncilSetDetailOut(CouncilSetOut):
    """Metadata đầy đủ + danh sách tệp (không bytes)."""

    thong_tin_dung: Dict[str, Any]
    tep: List[CouncilSetFileOut]

    @classmethod
    def tu_bo_va_tep(cls, bo, tep) -> "CouncilSetDetailOut":
        return cls(
            **CouncilSetOut.tu_bo(bo).model_dump(),
            thong_tin_dung=bo.thong_tin_dung,
            tep=[CouncilSetFileOut.model_validate(t) for t in tep],
        )


# ═══════════════════ lượt E3 — xoá bộ · danh sách mã đầu vào · nhật ký (CHỈ admin) ═════════
class CouncilSetDelete(BaseModel):
    """Thân ``DELETE /sets/{set_id}``: lý do BẮT BUỘC (J1 dòng 29). Kiểm rỗng / trần kỹ thuật
    / ký tự lạ ở service (``kiem_ly_do_xoa`` — một nguồn)."""

    model_config = ConfigDict(extra="forbid")

    ly_do: StrictStr


class CouncilSetDeletionOut(BaseModel):
    """Vết xoá một bộ — không danh sách CCCD, không DTO."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    set_id: int
    so_ho_so: int
    so_tep: int
    danh_sach_tep: List[Dict[str, Any]]
    nguoi_xoa_id: int
    xoa_luc: datetime
    ly_do: str


class CouncilSetInputCodesOut(BaseModel):
    """Danh sách mã hồ sơ đầu vào ĐÚNG THỨ TỰ (DỮ LIỆU CÁ NHÂN — chỉ admin, J1 dòng 30)."""

    set_id: int
    so_ho_so: int
    ma_ho_so: List[str]


class CouncilDocumentPermissions(BaseModel):
    """Cờ quyền GIAO DIỆN (lượt F) — mỗi cờ ứng với ĐÚNG MỘT route của module, do máy chủ đánh
    giá chính các cổng của route ấy cho người gọi (``deps.quyen_van_ban_hoi_dong``). Giao diện
    ẩn / hiện theo cờ, không theo vai. Tên trường = khoá của ``ENDPOINT_THEO_CO`` ở router
    (test khoá bằng nhau)."""

    model_config = ConfigDict(extra="forbid")

    xem_mau: bool
    tai_mau_len: bool
    xem_danh_sach_bo: bool
    tao_bo: bool
    xem_chi_tiet_bo: bool
    tai_tep: bool
    xoa_bo: bool
    xem_ma_ho_so: bool
    xem_nhat_ky_tai: bool
    xem_nhat_ky_xoa: bool


class CouncilDocumentPermissionsOut(BaseModel):
    """``GET /quyen`` — khuôn ``permissions`` của giao diện (``src/lib/permissions.ts``)."""

    permissions: CouncilDocumentPermissions


class CouncilDownloadLogOut(BaseModel):
    """Một dòng nhật ký: máy chủ đã CẤP tệp ``thu_tu`` của bộ ``set_id`` cho người
    ``nguoi_tai_id`` lúc ``tai_luc`` (không tuyên bố người dùng đã nhận xong)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    set_id: int
    thu_tu: int
    path: str
    sha256: str
    nguoi_tai_id: int
    tai_luc: datetime
