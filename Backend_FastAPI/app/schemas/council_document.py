# app/schemas/council_document.py
"""Schema API văn bản Hội đồng tuyển sinh (Lần xét tuyển GĐ1 — kho mẫu + bộ văn bản).

KHÔNG trả ra API: bytes mẫu / tệp (chỉ qua route tải tệp có kiểm quyền), danh sách mã hồ sơ
đầu vào và ảnh chụp DTO (``ma_ho_so_dau_vao`` / ``snapshot_dto`` — DỮ LIỆU CÁ NHÂN; cột
deferred, không đọc ở đây). ``thong_tin_dung`` chỉ có luật, thư viện, sha mẫu / tệp / mã
nguồn, ngành + số thí sinh, năm học, mốc giao dịch — không dữ liệu cá nhân.
"""
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictInt

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
