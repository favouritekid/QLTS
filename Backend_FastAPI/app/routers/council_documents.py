# app/routers/council_documents.py
"""API văn bản Hội đồng tuyển sinh (Lần xét tuyển GĐ1, PR 1.4) — router MỎNG.

Dưới tiền tố ``/api/admission-config/council-documents`` — tiền tố ĐÃ nằm trong
``FROZEN_PREFIXES`` (``app/middleware/admission_freeze.py``) và trong khối đóng băng của
nginx ⇒ cần gạt đóng băng tuyển sinh chặn ba route GHI (503: tải mẫu, dựng bộ, xoá bộ), route
ĐỌC vẫn đi như mọi route đọc khác của tiền tố. Module khai trong ``ADMISSION_ROUTER_MODULES``
+ ba route ghi trong ``ADMISSION_WRITE_ROUTES``.

Quyền — hai tầng (``AUTHORIZATION_GUIDELINES.md``):
  1. ``CasbinAuth`` là tham số phụ thuộc ĐẦU TIÊN ⇒ vai bị từ chối nhận 403 trước khi body
     được kiểm. Admin: mọi route (wildcard). Manager: ba route ĐỌC bộ văn bản (template +
     migration ``hdts20261103b``) — KHÔNG có dòng cho xoá bộ, danh sách mã đầu vào, nhật ký.
     Officer / accountant / user: không có dòng nào.
  2. Phạm vi / IDOR ở ``deps.get_council_document_scope`` /
     ``deps.get_council_document_set_for_user``: manager chỉ bộ của đơn vị mình, bộ
     ``unit_id`` NULL chỉ admin, ngoài phạm vi ⇒ 404. Route CHỈ ADMIN (owner 04-11, J1 dòng
     29–31) thêm lớp phụ ``deps.require_council_document_admin`` /
     ``deps.get_council_document_set_for_admin`` (không phải admin ⇒ 403).

Xoá bộ: lý do bắt buộc + vết xoá độc lập, cùng giao dịch với lệnh xoá (xoá trên phần mềm KHÔNG
xoá khỏi bản sao lưu đã có). Tải tệp: nhật ký ghi BỀN (commit) TRƯỚC khi trả bytes; ghi lỗi ⇒
không trả. Không log dữ liệu cá nhân (danh sách mã, DTO, bytes, lý do xoá) ở bất kỳ nhánh nào
— chỉ id + số đếm. Lỗi 422 của các route này chỉ vào log ở dạng đã chuẩn hoá
(``exception_handlers._khong_log_input_422`` / ``_loi_422_an_toan_de_log``).
"""
from datetime import date
from typing import List, Optional
from urllib.parse import quote

import structlog
from fastapi import APIRouter, Depends, File, Form, Path, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from .. import database, models
from ..config import settings
from ..core import deps
from ..core.rate_limits import RateLimits, limiter
from ..schemas.council_document import (
    CouncilDownloadLogOut,
    CouncilSetCreate,
    CouncilSetDelete,
    CouncilSetDeletionOut,
    CouncilSetDetailOut,
    CouncilSetInputCodesOut,
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
    # Nhật ký tải (J1 dòng 31) ghi BỀN TRƯỚC khi trả bytes — như giấy báo nhập học
    # (``enrollment_letters.py``): ghi / commit lỗi ⇒ ngoại lệ ⇒ KHÔNG trả bytes.
    await bo_vb.ghi_nhat_ky_tai(
        db, set_id=bo.id, thu_tu=thu_tu, tep=tep, nguoi_tai_id=current_user.id
    )
    await db.commit()
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


# ═══════════════════ CHỈ ADMIN — xoá bộ · danh sách mã đầu vào · nhật ký (J1 dòng 29–31) ═══
@router.delete(
    "/sets/{set_id}",
    response_model=CouncilSetDeletionOut,
    summary="Xoá một bộ văn bản (chỉ admin, bắt buộc lý do, ghi vết độc lập)",
)
@limiter.limit(RateLimits.ADMIN_DELETE)
async def delete_council_document_set(
    request: Request,
    payload: CouncilSetDelete,
    current_user: models.User = deps.CasbinAuth,
    bo: models.CouncilDocumentSet = Depends(deps.get_council_document_set_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    vet, _ = await bo_vb.xoa_bo_van_ban(
        db, bo, ly_do=payload.ly_do, nguoi_xoa_id=current_user.id
    )
    await db.commit()
    log.info(
        "council_document_set_deleted",
        set_id=vet.set_id,
        so_ho_so=vet.so_ho_so,
        so_tep=vet.so_tep,
        deletion_id=vet.id,
        actor=current_user.id,
    )
    return CouncilSetDeletionOut.model_validate(vet)


@router.get(
    "/sets/{set_id}/ma-ho-so",
    response_model=CouncilSetInputCodesOut,
    summary="Danh sách mã hồ sơ (CCCD) đầu vào của một bộ — chỉ admin",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def get_council_document_set_input_codes(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    bo: models.CouncilDocumentSet = Depends(deps.get_council_document_set_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    ma = await bo_vb.ma_ho_so_dau_vao(db, bo.id)
    log.info(  # KHÔNG log mã — chỉ id bộ + số đếm
        "council_document_input_codes_viewed",
        set_id=bo.id,
        so_ho_so=len(ma),
        actor=current_user.id,
    )
    return JSONResponse(
        content=CouncilSetInputCodesOut(
            set_id=bo.id, so_ho_so=len(ma), ma_ho_so=ma
        ).model_dump(),
        headers=dict(_TIEU_DE_TAI),
    )


@router.get(
    "/nhat-ky-tai",
    response_model=List[CouncilDownloadLogOut],
    summary="Nhật ký tải tệp bộ văn bản (chỉ admin; bộ đã xoá vẫn xem được)",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def list_council_document_download_log(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    _scope: deps.CouncilDocumentScope = Depends(deps.require_council_document_admin),
    set_id: Optional[int] = Query(None, ge=1),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(database.get_db),
):
    ds = await bo_vb.liet_ke_nhat_ky_tai(db, set_id=set_id, limit=limit, offset=offset)
    return [CouncilDownloadLogOut.model_validate(d) for d in ds]


@router.get(
    "/nhat-ky-xoa",
    response_model=List[CouncilSetDeletionOut],
    summary="Vết xoá bộ văn bản (chỉ admin)",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def list_council_document_set_deletions(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    _scope: deps.CouncilDocumentScope = Depends(deps.require_council_document_admin),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(database.get_db),
):
    ds = await bo_vb.liet_ke_vet_xoa(db, limit=limit, offset=offset)
    return [CouncilSetDeletionOut.model_validate(d) for d in ds]
