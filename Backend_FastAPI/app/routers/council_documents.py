# app/routers/council_documents.py
"""API văn bản Hội đồng tuyển sinh (Lần xét tuyển GĐ1, PR 1.4) — router MỎNG.

Dưới tiền tố ``/api/admission-config/council-documents`` — tiền tố ĐÃ nằm trong
``FROZEN_PREFIXES`` (``app/middleware/admission_freeze.py``) và trong khối đóng băng của
nginx ⇒ cần gạt đóng băng tuyển sinh chặn hai route GHI (503), route ĐỌC vẫn đi như mọi route
đọc khác của tiền tố. Module khai trong ``ADMISSION_ROUTER_MODULES`` + hai route ghi trong
``ADMISSION_WRITE_ROUTES``.

Quyền — hai tầng (``AUTHORIZATION_GUIDELINES.md``):
  1. ``CasbinAuth`` là tham số phụ thuộc ĐẦU TIÊN ⇒ vai bị từ chối nhận 403 trước khi body
     được kiểm. Admin: mọi route (wildcard). Manager: ba route ĐỌC bộ văn bản (template +
     migration ``hdts20261103b``). Officer / accountant / user: không có dòng nào.
  2. Phạm vi / IDOR ở ``deps.get_council_document_scope`` /
     ``deps.get_council_document_set_for_user``: manager chỉ bộ của đơn vị mình, bộ
     ``unit_id`` NULL chỉ admin, ngoài phạm vi ⇒ 404.

Không có route XOÁ: hạn lưu + quyền xoá bộ văn bản là câu nghiệp vụ chưa chốt. Không log dữ
liệu cá nhân (danh sách mã, DTO, bytes) ở bất kỳ nhánh nào — chỉ id + số đếm. Lỗi 422 của
các route này KHÔNG ghi ``input`` vào log (``exception_handlers._khong_log_input_422``).
"""
from datetime import date
from typing import List, Optional
from urllib.parse import quote

import structlog
from fastapi import APIRouter, Depends, File, Form, Path, Query, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models
from ..config import settings
from ..core import deps
from ..core.rate_limits import RateLimits, limiter
from ..schemas.council_document import (
    CouncilSetCreate,
    CouncilSetDetailOut,
    CouncilSetOut,
    CouncilTemplateOut,
)
from ..services import council_document_render_service as bo_dung
from ..services import council_document_set_service as bo_vb
from ..services import council_document_template_service as kho_mau

log = structlog.get_logger(__name__)

#: Tiền tố của router (dưới ``/api``) — MỘT nguồn cho router; ``exception_handlers`` khoá
#: tiền tố đầy đủ ``/api`` + đây bằng test (mọi route của module phải khớp vị từ log 422).
TIEN_TO = "/admission-config/council-documents"

router = APIRouter(prefix=TIEN_TO, tags=["Văn bản Hội đồng tuyển sinh"])

# Tệp sinh có dữ liệu cá nhân: không lưu đệm, không gửi referrer, không đoán kiểu.
_TIEU_DE_TAI = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
_KIEU_TEP = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def content_disposition_tai_ve(path: str) -> str:
    """``attachment`` cho tên = đoạn cuối của ``path``: ``filename=`` ASCII (bỏ dấu, ký tự
    lạ thành ``_``) + ``filename*=UTF-8''…`` (RFC 6266 / 5987) cho tên có dấu. Không có
    CR / LF / nháy kép nào lọt vào tiêu đề."""
    ten = path.rsplit("/", 1)[-1] or "tep"
    ascii_ = "".join(
        c if (c.isascii() and (c.isalnum() or c in "._-")) else "_"
        for c in bo_dung.khong_dau(ten)
    )
    return "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (
        ascii_ or "tep",
        quote(ten, safe=""),
    )


# ═══════════════════════════════ kho mẫu (admin) ═══════════════════════════════════════
@router.post(
    "/templates",
    response_model=CouncilTemplateOut,
    status_code=201,
    summary="Tải lên một mẫu Word (Biên bản / Quyết định / Danh sách)",
)
@limiter.limit(RateLimits.FILE_UPLOAD)
async def upload_council_template(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    loai: str = Form(..., description="bien_ban | quyet_dinh | danh_sach"),
    hieu_luc_tu: date = Form(..., description="Áp cho văn bản ký từ ngày này"),
    ghi_chu: Optional[str] = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(database.get_db),
):
    # Đọc tối đa trần + 1 byte: tệp lớn hơn bị service từ chối mà không nạp hết vào RAM.
    noi_dung = await file.read(settings.COUNCIL_TEMPLATE_MAX_BYTES + 1)
    mau, _ = await kho_mau.tai_mau_len(
        db,
        loai=loai,
        hieu_luc_tu=hieu_luc_tu,
        noi_dung=noi_dung,
        nguoi_tai_id=current_user.id,
        ghi_chu=ghi_chu,
    )
    await db.commit()
    log.info(
        "council_template_uploaded",
        template_id=mau.id,
        loai=mau.loai,
        kich_thuoc=mau.kich_thuoc,
        actor=current_user.id,
    )
    return CouncilTemplateOut.model_validate(mau)


@router.get(
    "/templates",
    response_model=List[CouncilTemplateOut],
    summary="Danh sách mẫu trong kho (không có nội dung tệp)",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def list_council_templates(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    db: AsyncSession = Depends(database.get_db),
):
    return [CouncilTemplateOut.model_validate(m) for m in await kho_mau.liet_ke_mau(db)]


# ═══════════════════════════════ bộ văn bản ═════════════════════════════════════════════
@router.post(
    "/sets",
    response_model=CouncilSetDetailOut,
    status_code=201,
    summary="Dựng + lưu một bộ văn bản Hội đồng từ danh sách mã hồ sơ",
)
@limiter.limit(RateLimits.REPORT_GENERATE)
async def create_council_document_set(
    request: Request,
    payload: CouncilSetCreate,
    current_user: models.User = deps.CasbinAuth,
    db: AsyncSession = Depends(database.get_db),
):
    bo, _ = await bo_vb.tao_bo_van_ban(
        db,
        database.engine,
        ma_ho_so=payload.ma_ho_so,
        academic_year=payload.academic_year,
        tham_so=payload.tham_so_quyet_dinh,
        nguoi_tao_id=current_user.id,
    )
    await db.commit()
    log.info(
        "council_document_set_created",
        set_id=bo.id,
        so_ho_so=bo.so_ho_so,
        so_tep=bo.so_tep,
        actor=current_user.id,
    )
    return CouncilSetDetailOut.tu_bo_va_tep(bo, await bo_vb.tep_cua_bo(db, bo.id))


@router.get(
    "/sets",
    response_model=List[CouncilSetOut],
    summary="Danh sách bộ văn bản (admin: mọi bộ; quản lý: bộ của đơn vị mình)",
)
@limiter.limit(RateLimits.DATA_READ)
async def list_council_document_sets(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    scope: deps.CouncilDocumentScope = Depends(deps.get_council_document_scope),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(database.get_db),
):
    ds = await bo_vb.liet_ke_bo(
        db, tat_ca=scope.tat_ca, chi_don_vi=scope.unit_id, limit=limit, offset=offset
    )
    return [CouncilSetOut.tu_bo(b) for b in ds]


@router.get(
    "/sets/{set_id}",
    response_model=CouncilSetDetailOut,
    summary="Metadata một bộ văn bản + danh sách tệp",
)
@limiter.limit(RateLimits.DATA_READ)
async def get_council_document_set(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    bo: models.CouncilDocumentSet = Depends(deps.get_council_document_set_for_user),
    db: AsyncSession = Depends(database.get_db),
):
    return CouncilSetDetailOut.tu_bo_va_tep(bo, await bo_vb.tep_cua_bo(db, bo.id))


@router.get(
    "/sets/{set_id}/files/{thu_tu}",
    summary="Tải MỘT tệp đã lưu của bộ văn bản (bytes đã lưu, không dựng lại)",
)
@limiter.limit(RateLimits.DATA_READ)
async def download_council_document_file(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    bo: models.CouncilDocumentSet = Depends(deps.get_council_document_set_for_user),
    thu_tu: int = Path(..., ge=1),
    db: AsyncSession = Depends(database.get_db),
):
    tep = await bo_vb.doc_tep_da_luu(db, bo.id, thu_tu)
    log.info(
        "council_document_file_downloaded",
        set_id=bo.id,
        thu_tu=thu_tu,
        actor=current_user.id,
    )
    return Response(
        content=tep.noi_dung,
        media_type=_KIEU_TEP.get(
            tep.path.rsplit(".", 1)[-1].lower(), "application/octet-stream"
        ),
        headers={
            "Content-Disposition": content_disposition_tai_ve(tep.path),
            **_TIEU_DE_TAI,
        },
    )
