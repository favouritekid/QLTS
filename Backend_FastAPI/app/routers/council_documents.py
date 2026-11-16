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
  Cờ quyền giao diện (lượt F): ``GET /quyen`` — máy chủ đánh giá CHÍNH hai tầng trên cho từng
  route (``deps.council_document_permissions`` + ``ENDPOINT_BY_FLAG`` cuối tệp), không bảng vai thứ hai.

Xoá bộ: lý do bắt buộc + vết xoá độc lập, cùng giao dịch với lệnh xoá (xoá trên phần mềm KHÔNG
xoá khỏi bản sao lưu đã có). Tải tệp: nhật ký ghi BỀN (commit) TRƯỚC khi trả bytes; ghi lỗi ⇒
không trả. Không log dữ liệu cá nhân (danh sách mã, DTO, bytes, lý do xoá) ở bất kỳ nhánh nào
— chỉ id + số đếm. Lỗi 422 của các route này chỉ vào log ở dạng đã chuẩn hoá
(``exception_handlers._no_log_input_422`` / ``_safe_422_error_for_log``).
"""
import asyncio
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
    CouncilDecisionCancelIn,
    CouncilDecisionDetailOut,
    CouncilDecisionOut,
    CouncilDecisionRowOut,
    CouncilDecisionWriteOut,
    CouncilDocumentPermissions,
    CouncilDocumentPermissionsOut,
    CouncilDownloadLogOut,
    CouncilEventOut,
    CouncilCodesIn,
    CouncilCodesOut,
    CouncilHoldOut,
    CouncilHoldReleaseIn,
    CouncilProfileSearchIn,
    CouncilProfileSearchOut,
    CouncilResignIn,
    CouncilSetCreate,
    CouncilSetCreatorOut,
    CouncilSetDelete,
    CouncilSetDeletionOut,
    CouncilSetDetailOut,
    CouncilSetInputCodesOut,
    CouncilSetOut,
    CouncilSetPreviewIn,
    CouncilSetPreviewOut,
    CouncilSubmissionOpenOut,
    CouncilSubmissionOut,
    CouncilSubmissionResolveOut,
    CouncilTemplateOut,
)
from ..services import council_candidate_service as candidate_service
from ..services import council_decision_service as decision_service
from ..services import council_decision_submission_service as submission_service
from ..services import council_document_render_service as render_service
from ..services import council_document_set_service as set_service
from ..services import council_document_template_service as template_service

log = structlog.get_logger(__name__)

#: Tiền tố của router (dưới ``/api``) — MỘT nguồn cho router; ``exception_handlers`` khoá
#: tiền tố đầy đủ ``/api`` + đây bằng test (mọi route của module phải khớp vị từ log 422).
ROUTER_PREFIX = "/admission-config/council-documents"

router = APIRouter(prefix=ROUTER_PREFIX, tags=["Văn bản Hội đồng tuyển sinh"])

# Tệp sinh có dữ liệu cá nhân: không lưu đệm, không gửi referrer, không đoán kiểu.
_DOWNLOAD_HEADERS = {
    "Cache-Control": "no-store",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}
_FILE_MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def download_content_disposition(path: str) -> str:
    """``attachment`` cho tên = đoạn cuối của ``path``: ``filename=`` ASCII (bỏ dấu, ký tự
    lạ thành ``_``) + ``filename*=UTF-8''…`` (RFC 6266 / 5987) cho tên có dấu. Không có
    CR / LF / nháy kép nào lọt vào tiêu đề."""
    name = path.rsplit("/", 1)[-1] or "tep"
    ascii_ = "".join(
        c if (c.isascii() and (c.isalnum() or c in "._-")) else "_"
        for c in render_service.strip_accents(name)
    )
    return "attachment; filename=\"%s\"; filename*=UTF-8''%s" % (
        ascii_ or "tep",
        quote(name, safe=""),
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
    content = await file.read(settings.COUNCIL_TEMPLATE_MAX_BYTES + 1)
    template, _ = await template_service.upload_template(
        db,
        kind=loai,
        effective_from=hieu_luc_tu,
        content=content,
        downloader_id=current_user.id,
        note=ghi_chu,
    )
    await db.commit()
    log.info(
        "council_template_uploaded",
        template_id=template.id,
        loai=template.loai,
        kich_thuoc=template.kich_thuoc,
        actor=current_user.id,
    )
    return CouncilTemplateOut.model_validate(template)


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
    return [CouncilTemplateOut.model_validate(m) for m in await template_service.list_templates(db)]


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
    can_confirm: bool = Depends(deps.get_council_document_confirm_right),
    db: AsyncSession = Depends(database.get_db),
):
    if payload.profile_ids is not None:
        # Vòng giao diện (đặc tả 3.3): dạng id + dấu kiểm trước.
        doc_set, _ = await set_service.create_document_set_by_ids(
            db,
            database.engine,
            profile_ids=payload.profile_ids,
            check_signature=payload.phien_ban_kiem,
            academic_year=payload.academic_year,
            params=payload.tham_so_quyet_dinh,
            creator_id=current_user.id,
            confirm_status=payload.xac_nhan_trang_thai,
            can_confirm=can_confirm,
        )
    else:
        doc_set, _ = await set_service.create_document_set(
            db,
            database.engine,
            profile_codes=payload.ma_ho_so,
            academic_year=payload.academic_year,
            params=payload.tham_so_quyet_dinh,
            creator_id=current_user.id,
            confirm_status=payload.xac_nhan_trang_thai,
            can_confirm=can_confirm,
        )
    await db.commit()
    confirmation = (doc_set.thong_tin_dung or {}).get("xac_nhan_canh_bao_trang_thai")
    log.info(
        "council_document_set_created",
        set_id=doc_set.id,
        so_ho_so=doc_set.so_ho_so,
        so_tep=doc_set.so_tep,
        actor=current_user.id,
        # lượt G — chỉ số đếm theo trạng thái (không mã, không số dòng)
        xac_nhan_canh_bao=(confirmation or {}).get("so_ho_so_theo_trang_thai"),
    )
    return CouncilSetDetailOut.from_set_and_files(doc_set, await set_service.set_file(db, doc_set.id))


@router.post(
    "/sets/kiem-truoc",
    response_model=CouncilSetPreviewOut,
    summary="Kiểm trước danh sách hồ sơ (mức từng dòng + thứ tự chuẩn + dấu) — không ghi gì",
)
@limiter.limit(RateLimits.DATA_READ)
async def preview_council_document_set(
    request: Request,
    payload: CouncilSetPreviewIn,
    current_user: models.User = deps.CasbinAuth,
    scope: deps.CouncilDocumentScope = Depends(deps.get_council_document_scope),
    can_confirm: bool = Depends(deps.get_council_document_confirm_right),
):
    result = await set_service.preview(
        database.engine,
        profile_ids=payload.profile_ids,
        academic_year=payload.academic_year,
        all_units=scope.all_units,
        only_unit_id=scope.unit_id,
        can_confirm=can_confirm,
    )
    # Chỉ số đếm — không id, không họ tên, không dấu.
    log.info(
        "council_document_set_previewed",
        so_dong=len(result["dong"]),
        so_khong_tim_thay=len(result["khong_tim_thay"]),
        actor=current_user.id,
    )
    return JSONResponse(
        content=CouncilSetPreviewOut(**result).model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


@router.post(
    "/sets/tim-ho-so",
    response_model=CouncilProfileSearchOut,
    summary="Tìm hồ sơ cho trang chọn (cùng service + phạm vi của danh sách hồ sơ) — tham số ở thân",
)
@limiter.limit(RateLimits.DATA_READ)
async def search_council_profiles(
    request: Request,
    payload: CouncilProfileSearchIn,
    current_user: models.User = deps.CasbinAuth,
    _scope: deps.CouncilDocumentScope = Depends(deps.get_council_document_scope),
    db: AsyncSession = Depends(database.get_db),
):
    result = await candidate_service.search_profiles(
        db,
        current_user=current_user,
        academic_year=payload.academic_year,
        keyword=payload.tu_khoa,
        major_ids=payload.major_ids,
        status=payload.trang_thai,
        page=payload.page,
        page_size=payload.page_size,
    )
    # KHÔNG log từ khoá (có thể là CCCD / tên) — chỉ số đếm.
    log.info(
        "council_profiles_searched",
        so_dong=len(result["dong"]),
        tong=result["tong"],
        co_tu_khoa=bool(payload.tu_khoa),
        actor=current_user.id,
    )
    return JSONResponse(
        content=CouncilProfileSearchOut(**result).model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


@router.post(
    "/sets/doi-ma",
    response_model=CouncilCodesOut,
    summary="Đổi danh sách mã hồ sơ (dán) thành id hồ sơ — lỗi chỉ nêu số dòng; không ghi gì",
)
@limiter.limit(RateLimits.DATA_READ)
async def resolve_council_profile_codes(
    request: Request,
    payload: CouncilCodesIn,
    current_user: models.User = deps.CasbinAuth,
    scope: deps.CouncilDocumentScope = Depends(deps.get_council_document_scope),
):
    pids, error_rows = await candidate_service.codes_to_ids(
        database.engine,
        payload.ma_ho_so,
        academic_year=payload.academic_year,
        all_units=scope.all_units,
        only_unit_id=scope.unit_id,
    )
    log.info(
        "council_profile_codes_resolved",
        so_khop=len(pids),
        so_dong_loi=len(error_rows),
        actor=current_user.id,
    )
    return JSONResponse(
        content=CouncilCodesOut(profile_ids=pids, dong_loi=error_rows).model_dump(
            mode="json"
        ),
        headers={"Cache-Control": "no-store"},
    )


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
    # Vòng giao diện (đặc tả 3.4) — bộ lọc KHÔNG phải dữ liệu cá nhân; phân trang GIỮ limit / offset.
    so_quyet_dinh: Optional[str] = Query(None, pattern=r"^[0-9]{1,6}$"),
    nam_hoc: Optional[int] = Query(None, ge=2000, le=2100),
    tinh_trang: Optional[str] = Query(
        None,
        pattern=r"^(chua_ghi_nhan|con_hieu_luc|het_hieu_luc|da_huy_ghi_nhan|chua_xac_dinh)$",
    ),
    nguoi_tao_id: Optional[int] = Query(None, ge=1),
    db: AsyncSession = Depends(database.get_db),
):
    rows = await set_service.list_sets_extended(
        db,
        all_units=scope.all_units,
        only_unit_id=scope.unit_id,
        show_submission=await _can_record(request, current_user),
        academic_year=nam_hoc,
        creator_id=nguoi_tao_id,
        decision_number=so_quyet_dinh,
        state=tinh_trang,
        limit=limit,
        offset=offset,
    )
    return [CouncilSetOut(**d) for d in rows]


@router.get(
    "/nguoi-tao-bo",
    response_model=List[CouncilSetCreatorOut],
    summary="Người tạo phân biệt của các bộ trong phạm vi người gọi (bộ lọc danh sách bộ)",
)
@limiter.limit(RateLimits.DATA_READ)
async def list_council_document_set_creators(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    scope: deps.CouncilDocumentScope = Depends(deps.get_council_document_scope),
    db: AsyncSession = Depends(database.get_db),
):
    return [
        CouncilSetCreatorOut(**d)
        for d in await set_service.set_creators(
            db, all_units=scope.all_units, only_unit_id=scope.unit_id
        )
    ]


@router.get(
    "/sets/{set_id}",
    response_model=CouncilSetDetailOut,
    summary="Metadata một bộ văn bản + danh sách tệp",
)
@limiter.limit(RateLimits.DATA_READ)
async def get_council_document_set(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    scope: deps.CouncilDocumentScope = Depends(deps.get_council_document_scope),
    doc_set: models.CouncilDocumentSet = Depends(deps.get_council_document_set_for_user),
    db: AsyncSession = Depends(database.get_db),
):
    return CouncilSetDetailOut.from_set_and_files(
        doc_set,
        await set_service.set_file(db, doc_set.id),
        await set_service.extended_set_detail(
            db, doc_set.id, show_submission=await _can_record(request, current_user)
        ),
    )


@router.get(
    "/sets/{set_id}/files/{thu_tu}",
    summary="Tải MỘT tệp đã lưu của bộ văn bản (bytes đã lưu, không dựng lại)",
)
@limiter.limit(RateLimits.DATA_READ)
async def download_council_document_file(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    doc_set: models.CouncilDocumentSet = Depends(deps.get_council_document_set_for_user),
    thu_tu: int = Path(..., ge=1),
    db: AsyncSession = Depends(database.get_db),
):
    file = await set_service.read_stored_file(db, doc_set.id, thu_tu)
    # Nhật ký tải (J1 dòng 31) ghi BỀN TRƯỚC khi trả bytes — như giấy báo nhập học
    # (``enrollment_letters.py``): ghi / commit lỗi ⇒ ngoại lệ ⇒ KHÔNG trả bytes.
    await set_service.log_download(
        db, set_id=doc_set.id, order_no=thu_tu, file=file, downloader_id=current_user.id
    )
    await db.commit()
    log.info(
        "council_document_file_downloaded",
        set_id=doc_set.id,
        thu_tu=thu_tu,
        actor=current_user.id,
    )
    return Response(
        content=file.content,
        media_type=_FILE_MEDIA_TYPES.get(
            file.path.rsplit(".", 1)[-1].lower(), "application/octet-stream"
        ),
        headers={
            "Content-Disposition": download_content_disposition(file.path),
            **_DOWNLOAD_HEADERS,
        },
    )


@router.get(
    "/sets/{set_id}/tai-ca-bo",
    summary="Tải CẢ BỘ (zip đúng các bytes đã lưu — không dựng lại; nhật ký tải mỗi tệp ghi bền trước khi trả)",
)
@limiter.limit(RateLimits.DATA_READ)
async def download_council_document_set_zip(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    doc_set: models.CouncilDocumentSet = Depends(deps.get_council_document_set_for_user),
    db: AsyncSession = Depends(database.get_db),
):
    # Đặc tả 3.6 — quyền + phạm vi Y HỆT tải lẻ. Trước khi trả byte nào: đọc mọi tệp + so sha từng tệp (lệch ⇒ lỗi, không
    # trả) → nén (NGOÀI event loop; nén hỏng ⇒ chưa ghi nhật ký nào) → MỘT dòng nhật ký tải cho MỖI tệp → COMMIT → trả.
    file = await set_service.read_whole_set(db, doc_set.id)
    zip_ = await asyncio.to_thread(set_service.zip_whole_set, [t for _, t in file], doc_set.tao_luc)
    for order_no, t in file:
        await set_service.log_download(
            db, set_id=doc_set.id, order_no=order_no, file=t, downloader_id=current_user.id
        )
    await db.commit()
    log.info(
        "council_document_set_zip_downloaded",
        set_id=doc_set.id,
        so_tep=len(file),
        actor=current_user.id,
    )
    return Response(
        content=zip_,
        media_type="application/zip",
        headers={
            # Tên tệp KHÔNG chứa tên người — chỉ id bộ.
            "Content-Disposition": 'attachment; filename="bo-%d.zip"' % doc_set.id,
            **_DOWNLOAD_HEADERS,
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
    doc_set: models.CouncilDocumentSet = Depends(deps.get_council_document_set_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    trace, _ = await set_service.delete_document_set(
        db, doc_set, reason=payload.ly_do, deleter_id=current_user.id
    )
    await db.commit()
    log.info(
        "council_document_set_deleted",
        set_id=trace.set_id,
        so_ho_so=trace.so_ho_so,
        so_tep=trace.so_tep,
        deletion_id=trace.id,
        actor=current_user.id,
    )
    return CouncilSetDeletionOut.model_validate(trace)


@router.get(
    "/sets/{set_id}/ma-ho-so",
    response_model=CouncilSetInputCodesOut,
    summary="Danh sách mã hồ sơ (CCCD) đầu vào của một bộ — chỉ admin",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def get_council_document_set_input_codes(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    doc_set: models.CouncilDocumentSet = Depends(deps.get_council_document_set_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    code = await set_service.input_profile_codes(db, doc_set.id)
    log.info(  # KHÔNG log mã — chỉ id bộ + số đếm
        "council_document_input_codes_viewed",
        set_id=doc_set.id,
        so_ho_so=len(code),
        actor=current_user.id,
    )
    return JSONResponse(
        content=CouncilSetInputCodesOut(
            set_id=doc_set.id, so_ho_so=len(code), ma_ho_so=code
        ).model_dump(),
        headers=dict(_DOWNLOAD_HEADERS),
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
    rows = await set_service.list_download_log(db, set_id=set_id, limit=limit, offset=offset)
    name = await set_service.user_names(db, [d.nguoi_tai_id for d in rows])
    return [
        CouncilDownloadLogOut.model_validate(d).model_copy(
            update={"nguoi_tai_ten": name.get(d.nguoi_tai_id)}
        )
        for d in rows
    ]


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
    rows = await set_service.list_deletion_traces(db, limit=limit, offset=offset)
    name = await set_service.user_names(db, [d.nguoi_xoa_id for d in rows])
    return [
        CouncilSetDeletionOut.model_validate(d).model_copy(
            update={"nguoi_xoa_ten": name.get(d.nguoi_xoa_id)}
        )
        for d in rows
    ]


# ═══════════════════ Lượt I (F230) — ghi nhận Quyết định ĐÃ KÝ (CHỈ admin) ═══════════════════
# Quyền: Casbin (admin wildcard; KHÔNG vai nào khác có dòng) + lớp phụ ``require_council_document_admin``
# (trực tiếp hoặc qua ``get_council_document_set_for_admin`` / ``get_council_decision_for_admin`` /
# ``get_council_decision_hold_for_admin``). Route ghi khai trong ``ADMISSION_WRITE_ROUTES`` (đóng băng ⇒
# 503). Log chỉ id + số đếm — không CCCD, không lý do. Bản scan đọc tối đa trần + 1 byte.
def _recorded_decision_out(decision, figures=None, warnings=None, *, root=None, submission_code=None, repeated=False) -> CouncilDecisionWriteOut:
    return CouncilDecisionWriteOut(
        **CouncilDecisionOut.model_validate(decision).model_dump(),
        so_lieu=figures,
        canh_bao_vuot_chi_tieu=warnings or [],
        goc=root,
        ma_luot_gui=submission_code,
        lap_lai=repeated,
    )


async def _read_scan_upload(scan: UploadFile) -> bytes:
    return await scan.read(settings.COUNCIL_DECISION_SCAN_MAX_BYTES + 1)


def _confirmation_json(value: Optional[str]):
    """Trường form ``xac_nhan_trang_thai`` (JSON ``{loại: số}``) — sai dạng ⇒ 400 qua service."""
    import json

    if value is None or value == "":
        return None
    # Codex 42 (câu 4): vượt trần độ dài ⇒ "không đọc được" — giữ JSON hợp lệ dưới trần xa ngưỡng đệ quy (ngưỡng phụ thuộc
    # bản dựng / ngăn xếp ⇒ MSW không chép được; xem CONFIRMATION_JSON_MAX_CHARS). ``len`` = số ký tự (code point) như MSW.
    if len(value) > decision_service.CONFIRMATION_JSON_MAX_CHARS:
        return "<khong-doc-duoc>"
    try:
        return json.loads(value)
    # Review max PR #724 (dưới ngưỡng): JSON lồng quá sâu ⇒ ``RecursionError`` (trước đây 500) — cùng đường "không đọc
    # được" ⇒ 400 qua service.
    except (ValueError, RecursionError):
        return "<khong-doc-duoc>"


@router.post(
    "/decisions",
    response_model=CouncilDecisionWriteOut,
    status_code=201,
    summary="Ghi nhận MỘT Quyết định trúng tuyển / bổ sung ĐÃ KÝ từ một bộ (chỉ admin, kèm scan)",
)
@limiter.limit(RateLimits.ADMIN_WRITE)
async def create_council_decision(
    request: Request,
    response: Response,
    current_user: models.User = deps.CasbinAuth,
    _scope: deps.CouncilDocumentScope = Depends(deps.require_council_document_admin),
    set_id: int = Form(..., ge=1),
    loai: str = Form(..., pattern=r"^(trung_tuyen|bo_sung)$"),
    goc_id: Optional[int] = Form(None, ge=1),
    so_quyet_dinh: str = Form(..., pattern=r"^[0-9]{1,6}$"),
    ngay_ky: date = Form(...),
    so_bien_ban: Optional[str] = Form(None, pattern=r"^[0-9]{1,6}$"),
    ngay_bien_ban: Optional[date] = Form(None),
    dot_so: Optional[str] = Form(None, pattern=r"^[0-9]{1,2}$"),
    dot_thang: Optional[int] = Form(None, ge=1, le=12),
    xac_nhan_so_ho_so: int = Form(..., ge=1),
    xac_nhan_khop_ban_in: bool = Form(...),
    xac_nhan_trang_thai: Optional[str] = Form(None),
    ghi_chu_mau: Optional[str] = Form(None),
    scan: UploadFile = File(...),
    # Vòng giao diện (đặc tả bản 2 mục 3.7.3): mã lượt gửi do POST /sets/{id}/luot-ghi-nhan cấp — BẮT BUỘC.
    ma_luot_gui: str = Form(..., pattern=r"^[0-9a-fA-F-]{36}$"),
    db: AsyncSession = Depends(database.get_db),
):
    decision, warnings, repeated = await decision_service.record_decision(
        db,
        set_id=set_id,
        kind=loai,
        root_id=goc_id,
        decision_number=so_quyet_dinh,
        signing_date=ngay_ky,
        paper_params={
            "so_bien_ban": so_bien_ban,
            "ngay_bien_ban": ngay_bien_ban,
            "dot_so": dot_so,
            "dot_thang": dot_thang,
        },
        confirm_profile_count=xac_nhan_so_ho_so,
        confirm_printed_copy_match=xac_nhan_khop_ban_in,
        confirm_status=_confirmation_json(xac_nhan_trang_thai),
        template_note=ghi_chu_mau,
        scan=await _read_scan_upload(scan),
        actor_id=current_user.id,
        submission_code=ma_luot_gui,
    )
    root = await decision_service.root_summary(db, decision.goc_id)
    out = _recorded_decision_out(decision, warnings=warnings, root=root, submission_code=ma_luot_gui, repeated=repeated)
    await db.commit()  # gửi lặp: không có gì để ghi — kết thúc giao dịch NGAY (F272)
    if repeated:
        response.status_code = 200
    log.info(
        "council_decision_recorded",
        decision_id=decision.id,
        set_id=decision.set_id,
        so_ho_so=decision.so_ho_so,
        actor=current_user.id,
        so_o_vuot_chi_tieu=len(warnings),
        lap_lai=repeated,
    )
    return out


# ═══════════════════════════════ lượt gửi ghi nhận (vòng giao diện — đặc tả bản 2 mục 3.7) ═══════════
def _submission_out(x) -> CouncilSubmissionOut:
    return CouncilSubmissionOut(
        ma=str(x.ma),
        trang_thai=x.trang_thai,
        tao_luc=x.tao_luc,
        ket_thuc_luc=x.ket_thuc_luc,
        decision_id=x.decision_id,
    )


@router.post(
    "/sets/{set_id}/luot-ghi-nhan",
    response_model=CouncilSubmissionOpenOut,
    status_code=201,
    summary="Mở MỘT lượt gửi ghi nhận cho bộ (chỉ admin) — gọi NGAY trước POST /decisions",
)
@limiter.limit(RateLimits.ADMIN_WRITE)
async def open_council_decision_submission(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    doc_set: models.CouncilDocumentSet = Depends(deps.get_council_document_set_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    submission = await submission_service.open_submission(db, set_id=doc_set.id, actor_id=current_user.id)
    code = str(submission.ma)
    await db.commit()  # commit RỒI mới trả mã (3.7.2)
    log.info("council_submission_opened", set_id=doc_set.id, actor=current_user.id)
    return CouncilSubmissionOpenOut(ma=code)


@router.get(
    "/sets/{set_id}/luot-ghi-nhan",
    response_model=List[CouncilSubmissionOut],
    summary="Các lượt gửi ghi nhận của bộ (chỉ admin) — khôi phục sau tải lại trang, không lưu mã ở trình duyệt",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def list_council_decision_submissions(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    doc_set: models.CouncilDocumentSet = Depends(deps.get_council_document_set_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    return [_submission_out(x) for x in await submission_service.set_submission(db, doc_set.id)]


@router.post(
    "/luot-ghi-nhan/{ma}/chan",
    response_model=CouncilSubmissionResolveOut,
    summary="Phân xử lượt gửi chưa rõ kết quả: đã ghi / chưa ghi (chặn lượt) / đang xử lý (chỉ admin)",
)
@limiter.limit(RateLimits.ADMIN_WRITE)
async def resolve_council_decision_submission(
    request: Request,
    ma: str = Path(..., pattern=r"^[0-9a-fA-F-]{36}$"),
    current_user: models.User = deps.CasbinAuth,
    _scope: deps.CouncilDocumentScope = Depends(deps.require_council_document_admin),
    db: AsyncSession = Depends(database.get_db),
):
    code_uuid = submission_service.check_submission_code(ma)
    try:
        result, decision_id = await submission_service.adjudicate(db, code_uuid)
    except submission_service.SubmissionProcessingError:
        await db.rollback()  # giao dịch đã hỏng (55P03) — ROLLBACK trước khi trả (3.7.4)
        return CouncilSubmissionResolveOut(ket_qua=submission_service.PROCESSING)
    resolved_decision = None
    if result == submission_service.RECORDED:
        decision = await decision_service.recorded_decision_detail(db, decision_id)
        resolved_decision = _recorded_decision_out(
            decision,
            warnings=await decision_service.stored_warnings(db, decision_id, "ghi_nhan"),
            root=await decision_service.root_summary(db, decision.goc_id),
            submission_code=str(code_uuid),
        )
    await db.commit()  # chỉ kết luận SAU commit
    log.info("council_submission_resolved", ket_qua=result, actor=current_user.id)
    return CouncilSubmissionResolveOut(ket_qua=result, quyet_dinh=resolved_decision)


@router.get(
    "/decisions",
    response_model=List[CouncilDecisionOut],
    summary="Danh sách văn bản đã ký (chỉ admin)",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def list_council_decisions(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    _scope: deps.CouncilDocumentScope = Depends(deps.require_council_document_admin),
    set_id: Optional[int] = Query(None, ge=1),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    # Vòng giao diện: lọc ở máy chủ, đúng tập CHECK của bảng (CHECK_DECISION_KIND / CHECK_DECISION_STATUS).
    loai: Optional[str] = Query(
        None, pattern=r"^(trung_tuyen|bo_sung|dieu_chinh|van_ban_huy)$"
    ),
    trang_thai: Optional[str] = Query(
        None, pattern=r"^(hieu_luc|het_hieu_luc|huy_ghi_nhan)$"
    ),
    db: AsyncSession = Depends(database.get_db),
):
    from ..repositories.council_decision_repository import CouncilDecisionRepository

    rows = await CouncilDecisionRepository(db).list_decisions(
        set_id=set_id, limit=limit, offset=offset, kind=loai, status=trang_thai
    )
    return [CouncilDecisionOut.model_validate(d) for d in rows]


@router.get(
    "/decisions/{decision_id}",
    response_model=CouncilDecisionDetailOut,
    summary="Chi tiết văn bản đã ký: dòng (số dòng + id hồ sơ nội bộ), scan, sự kiện (chỉ admin)",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def get_council_decision(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    decision: models.CouncilDecision = Depends(deps.get_council_decision_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    decision, row, scan, event = await decision_service.decision_detail(db, decision.id)
    return CouncilDecisionDetailOut(
        **CouncilDecisionOut.model_validate(decision).model_dump(),
        dong=[CouncilDecisionRowOut.model_validate(d) for d in row],
        scan=(
            None
            if scan is None
            else {"sha256": scan.sha256, "kich_thuoc": scan.kich_thuoc, "kieu": scan.kieu}
        ),
        su_kien=[CouncilEventOut.model_validate(e) for e in event],
    )


@router.get(
    "/decisions/{decision_id}/scan",
    summary="Tải bản scan của văn bản đã ký (chỉ admin; nhật ký ghi BỀN trước khi trả bytes)",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def download_council_decision_scan(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    decision: models.CouncilDecision = Depends(deps.get_council_decision_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    s = await decision_service.read_scan(db, decision.id)
    await decision_service.log_scan_download(db, s, current_user.id)
    await db.commit()
    log.info("council_decision_scan_downloaded", decision_id=decision.id, actor=current_user.id)
    return Response(
        content=bytes(s.noi_dung),
        media_type=s.kieu,
        headers={
            "Content-Disposition": download_content_disposition(
                "QuyetDinh-%d-scan.pdf" % decision.id
            ),
            **_DOWNLOAD_HEADERS,
        },
    )


@router.post(
    "/decisions/{decision_id}/huy-ghi-nhan",
    response_model=CouncilDecisionWriteOut,
    summary="Huỷ ghi nhận (nhập SAI) — như chưa từng ghi, giữ vết (chỉ admin)",
)
@limiter.limit(RateLimits.ADMIN_WRITE)
async def cancel_council_decision_record(
    request: Request,
    payload: CouncilDecisionCancelIn,
    current_user: models.User = deps.CasbinAuth,
    decision: models.CouncilDecision = Depends(deps.get_council_decision_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    decision, figures, warnings = await decision_service.revoke_record(
        db,
        decision.id,
        reason=payload.ly_do,
        retyped_number=payload.so_go_lai,
        confirmation=payload.xac_nhan,
        actor_id=current_user.id,
    )
    await db.commit()
    log.info(
        "council_decision_record_cancelled",
        decision_id=decision.id,
        actor=current_user.id,
        **{k: v for k, v in figures.items() if isinstance(v, int)},
        so_o_vuot_chi_tieu=len(warnings),
    )
    return _recorded_decision_out(decision, figures, warnings=warnings)


@router.post(
    "/decisions/{decision_id}/huy-hieu-luc",
    response_model=CouncilDecisionWriteOut,
    status_code=201,
    summary="Ghi nhận VĂN BẢN HUỶ của trường cho văn bản này (chỉ admin, kèm scan)",
)
@limiter.limit(RateLimits.ADMIN_WRITE)
async def revoke_council_decision(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    decision: models.CouncilDecision = Depends(deps.get_council_decision_for_admin),
    so_quyet_dinh: str = Form(..., pattern=r"^[0-9]{1,6}$"),
    ngay_ky: date = Form(...),
    scan: UploadFile = File(...),
    db: AsyncSession = Depends(database.get_db),
):
    h, figures = await decision_service.cancel_effect(
        db,
        decision.id,
        decision_number=so_quyet_dinh,
        signing_date=ngay_ky,
        scan=await _read_scan_upload(scan),
        actor_id=current_user.id,
    )
    await db.commit()
    log.info(
        "council_decision_revoked",
        decision_id=decision.id,
        revoking_id=h.id,
        actor=current_user.id,
        so_muc_cho_moi=figures.get("so_muc_cho_moi"),
    )
    return _recorded_decision_out(h, figures)


@router.post(
    "/decisions/{decision_id}/bo-dieu-chinh",
    response_model=CouncilSetDetailOut,
    status_code=201,
    summary="Dựng bộ DỮ LIỆU cho văn bản điều chỉnh của chuỗi Quyết định này (chỉ admin)",
)
@limiter.limit(RateLimits.REPORT_GENERATE)
async def create_council_adjustment_set(
    request: Request,
    payload: CouncilSetCreate,
    current_user: models.User = deps.CasbinAuth,
    decision: models.CouncilDecision = Depends(deps.get_council_decision_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    doc_set, _ = await set_service.create_adjustment_set(
        db,
        database.engine,
        decision.id,
        profile_codes=payload.ma_ho_so,
        academic_year=payload.academic_year,
        params=payload.tham_so_quyet_dinh,
        creator_id=current_user.id,
        confirm_status=payload.xac_nhan_trang_thai,
        can_confirm=True,  # route CHỈ admin (lớp phụ ở deps) — admin được xác nhận
    )
    await db.commit()
    log.info(
        "council_adjustment_set_created",
        set_id=doc_set.id,
        goc_id=decision.id,
        so_ho_so=doc_set.so_ho_so,
        actor=current_user.id,
    )
    return CouncilSetDetailOut.from_set_and_files(doc_set, await set_service.set_file(db, doc_set.id))


@router.post(
    "/decisions/{decision_id}/dieu-chinh",
    response_model=CouncilDecisionWriteOut,
    status_code=201,
    summary="Ghi nhận Quyết định ĐIỀU CHỈNH đã ký (bỏ / thêm dòng của chuỗi; chỉ admin, kèm scan)",
)
@limiter.limit(RateLimits.ADMIN_WRITE)
async def create_council_decision_adjustment(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    decision: models.CouncilDecision = Depends(deps.get_council_decision_for_admin),
    so_quyet_dinh: str = Form(..., pattern=r"^[0-9]{1,6}$"),
    ngay_ky: date = Form(...),
    bo_dong: List[int] = Form([]),
    set_id: Optional[int] = Form(None, ge=1),
    xac_nhan_so_ho_so: Optional[int] = Form(None, ge=1),
    xac_nhan_khop_ban_in: bool = Form(False),
    xac_nhan_trang_thai: Optional[str] = Form(None),
    ghi_chu_mau: Optional[str] = Form(None),
    scan: UploadFile = File(...),
    db: AsyncSession = Depends(database.get_db),
):
    adjusted_decision, warnings = await decision_service.record_adjustment_decision(
        db,
        decision.id,
        decision_number=so_quyet_dinh,
        signing_date=ngay_ky,
        removed_row_ids=bo_dong,
        set_id=set_id,
        confirm_profile_count=xac_nhan_so_ho_so,
        confirm_printed_copy_match=xac_nhan_khop_ban_in,
        confirm_status=_confirmation_json(xac_nhan_trang_thai),
        template_note=ghi_chu_mau,
        scan=await _read_scan_upload(scan),
        actor_id=current_user.id,
    )
    await db.commit()
    log.info(
        "council_decision_adjusted",
        decision_id=adjusted_decision.id,
        goc_id=decision.id,
        so_dong_bo=len(bo_dong),
        actor=current_user.id,
    )
    return _recorded_decision_out(adjusted_decision, warnings=warnings)


@router.post(
    "/sets/{set_id}/dung-lai-ban-ky",
    response_model=CouncilSetDetailOut,
    status_code=201,
    summary="Tái dựng bộ cho KHỚP bản đã ký (bản ký sửa tay — owner C2 / C3; chỉ admin)",
)
@limiter.limit(RateLimits.REPORT_GENERATE)
async def resign_council_document_set(
    request: Request,
    payload: CouncilResignIn,
    current_user: models.User = deps.CasbinAuth,
    doc_set: models.CouncilDocumentSet = Depends(deps.get_council_document_set_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    new_set, _ = await set_service.create_signed_copy_rebuild_set(
        db,
        database.engine,
        doc_set,
        decision_number=payload.so_quyet_dinh,
        signing_date=payload.ngay_ky,
        manual_edit_rows=payload.dong_sua_tay,
        reason=payload.ly_do,
        confirm_other_rows=payload.xac_nhan_dong_khac,
        creator_id=current_user.id,
    )
    await db.commit()
    log.info(
        "council_set_resigned",
        set_id=new_set.id,
        tu_set_id=doc_set.id,
        so_dong_sua_tay=len(payload.dong_sua_tay),
        actor=current_user.id,
    )
    return CouncilSetDetailOut.from_set_and_files(new_set, await set_service.set_file(db, new_set.id))


@router.get(
    "/sets/{set_id}/so-voi-hien-tai",
    summary="So ảnh chụp của bộ với dữ liệu hiện tại — số dòng + TÊN trường đổi (chỉ admin)",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def compare_council_document_set(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    doc_set: models.CouncilDocumentSet = Depends(deps.get_council_document_set_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    out = await set_service.compare_with_current(db, database.engine, doc_set)
    return JSONResponse(content=out, headers={"Cache-Control": "no-store"})


@router.get(
    "/decision-holds",
    response_model=List[CouncilHoldOut],
    summary="Nhóm 'chờ Admin quyết' (em của văn bản bị huỷ — owner C7; chỉ admin)",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def list_council_decision_holds(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    _scope: deps.CouncilDocumentScope = Depends(deps.require_council_document_admin),
    trang_thai: Optional[str] = Query(
        None, pattern=r"^(cho_quyet|da_cho_xet_lai|vo_hieu)$"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(database.get_db),
):
    from ..repositories.council_decision_repository import CouncilDecisionRepository

    rows = await CouncilDecisionRepository(db).list_holds(
        status=trang_thai, limit=limit, offset=offset
    )
    return [
        CouncilHoldOut(
            id=h.id,
            profile_id=h.profile_id,
            decision_row_id=h.decision_row_id,
            stt=d.stt,
            quyet_dinh_id=d.decision_id,
            van_ban_huy_id=h.van_ban_huy_id,
            ly_do_vao=h.ly_do_vao,
            trang_thai=h.trang_thai,
            tao_luc=h.tao_luc,
            quyet_boi_id=h.quyet_boi_id,
            quyet_luc=h.quyet_luc,
            vo_hieu_luc=h.vo_hieu_luc,
        )
        for h, d in rows
    ]


@router.post(
    "/decision-holds/{hold_id}/cho-xet-lai",
    summary="Admin cho phép MỘT em của nhóm chờ được xét lại (owner C7; bắt buộc lý do)",
)
@limiter.limit(RateLimits.ADMIN_WRITE)
async def release_council_decision_hold(
    request: Request,
    payload: CouncilHoldReleaseIn,
    current_user: models.User = deps.CasbinAuth,
    item: models.CouncilDecisionHold = Depends(deps.get_council_decision_hold_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    h, _ = await decision_service.review_hold_again(
        db, item.id, reason=payload.ly_do, actor_id=current_user.id
    )
    await db.commit()
    log.info("council_decision_hold_released", hold_id=h.id, actor=current_user.id)
    return {"id": h.id, "trang_thai": h.trang_thai}


@router.get(
    "/su-kien",
    response_model=List[CouncilEventOut],
    summary="Nhật ký sự kiện độc lập của bộ / văn bản đã ký (chỉ admin)",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def list_council_document_events(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    _scope: deps.CouncilDocumentScope = Depends(deps.require_council_document_admin),
    set_id: Optional[int] = Query(None, ge=1),
    decision_id: Optional[int] = Query(None, ge=1),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(database.get_db),
):
    from ..repositories.council_decision_repository import CouncilDecisionRepository

    rows = await CouncilDecisionRepository(db).list_events(
        set_id=set_id, decision_id=decision_id, limit=limit, offset=offset
    )
    return [CouncilEventOut.model_validate(e) for e in rows]


# ═══════════════════ cờ quyền GIAO DIỆN (lượt F) ════════════════════════════════════════
@router.get(
    "/quyen",
    response_model=CouncilDocumentPermissionsOut,
    summary="Cờ quyền giao diện của người gọi (máy chủ đánh giá chính các cổng của từng route)",
)
@limiter.limit(RateLimits.DATA_READ)
async def get_council_document_permissions(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
):
    """Casbin: admin (wildcard) + manager (template + migration ``hdts20261105``); vai khác
    403 — giao diện coi 403 ở đây là "mọi cờ tắt". Không log gì ngoài log chung."""
    permissions = await deps.council_document_permissions(request, current_user, ENDPOINT_BY_FLAG)
    return CouncilDocumentPermissionsOut(
        permissions=CouncilDocumentPermissions(**permissions)
    )


async def _can_record(request: Request, current_user: models.User) -> bool:
    """§5.8 (Codex lần 18): ``luot_gui_cho`` (mã lượt gửi đang chờ) chỉ cho người có quyền GHI NHẬN — trả lời bằng ĐÚNG
    cờ ``ghi_nhan_qd`` do CÙNG hàm tính cờ của ``GET /quyen`` (cổng thật của route ghi nhận), không suy từ phạm vi admin:
    phạm vi dữ liệu không phải quyền thao tác. Dòng policy ngoài mẫu route ⇒ mọi cờ tắt ⇒ không lộ mã (fail-closed)."""
    # Review max PR #724 (R14): chỉ tính cờ cần dùng (cùng hàm, cùng luật với ``GET /quyen``).
    permissions = await deps.council_document_permissions(
        request, current_user, ENDPOINT_BY_FLAG, only_flag="ghi_nhan_qd"
    )
    return permissions["ghi_nhan_qd"] is True


#: Cờ ↔ HÀM xử lý của ĐÚNG MỘT route (phương thức + đường đọc từ bảng route thật của app, không
#: viết lại ở đây). Thêm route mới vào module ⇒ thêm cờ (test
#: ``test_moi_route_cua_module_co_dung_mot_co`` đỏ nếu quên).
ENDPOINT_BY_FLAG = {
    "xem_mau": list_council_templates,
    "tai_mau_len": upload_council_template,
    "xem_danh_sach_bo": list_council_document_sets,
    "tao_bo": create_council_document_set,
    "xem_chi_tiet_bo": get_council_document_set,
    "tai_tep": download_council_document_file,
    "xoa_bo": delete_council_document_set,
    "xem_ma_ho_so": get_council_document_set_input_codes,
    "xem_nhat_ky_tai": list_council_document_download_log,
    "xem_nhat_ky_xoa": list_council_document_set_deletions,
    # Lượt I (F230)
    "ghi_nhan_qd": create_council_decision,
    "xem_danh_sach_qd": list_council_decisions,
    "xem_chi_tiet_qd": get_council_decision,
    "tai_scan_qd": download_council_decision_scan,
    "huy_ghi_nhan_qd": cancel_council_decision_record,
    "huy_hieu_luc_qd": revoke_council_decision,
    "tao_bo_dieu_chinh": create_council_adjustment_set,
    "ghi_nhan_dieu_chinh": create_council_decision_adjustment,
    "dung_lai_ban_ky": resign_council_document_set,
    "so_bo_voi_hien_tai": compare_council_document_set,
    "xem_nhom_cho": list_council_decision_holds,
    "cho_xet_lai": release_council_decision_hold,
    "xem_su_kien": list_council_document_events,
    # Vòng giao diện — lượt gửi ghi nhận (đặc tả bản 2 mục 3.7)
    "mo_luot_gui": open_council_decision_submission,
    "xem_luot_gui": list_council_decision_submissions,
    "phan_xu_luot_gui": resolve_council_decision_submission,
    # Vòng giao diện — đường chọn hồ sơ (đặc tả 3.1 / 3.2 / 3.10)
    "kiem_truoc": preview_council_document_set,
    "doi_ma": resolve_council_profile_codes,
    "tim_ho_so": search_council_profiles,
    # Vòng giao diện — tải cả bộ (đặc tả 3.6) + người tạo bộ (bộ lọc danh sách)
    "tai_ca_bo": download_council_document_set_zip,
    "xem_nguoi_tao_bo": list_council_document_set_creators,
}
