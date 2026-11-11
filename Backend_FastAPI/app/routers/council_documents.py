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
  route (``deps.quyen_van_ban_hoi_dong`` + ``ENDPOINT_THEO_CO`` cuối tệp), không bảng vai thứ hai.

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
    CouncilDecisionCancelIn,
    CouncilDecisionDetailOut,
    CouncilDecisionOut,
    CouncilDecisionRowOut,
    CouncilDecisionWriteOut,
    CouncilDocumentPermissions,
    CouncilDocumentPermissionsOut,
    CouncilDownloadLogOut,
    CouncilEventOut,
    CouncilHoldOut,
    CouncilHoldReleaseIn,
    CouncilResignIn,
    CouncilSetCreate,
    CouncilSetDelete,
    CouncilSetDeletionOut,
    CouncilSetDetailOut,
    CouncilSetInputCodesOut,
    CouncilSetOut,
    CouncilTemplateOut,
)
from ..services import council_decision_service as qd_vb
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
    duoc_xac_nhan: bool = Depends(deps.get_council_document_confirm_right),
    db: AsyncSession = Depends(database.get_db),
):
    bo, _ = await bo_vb.tao_bo_van_ban(
        db,
        database.engine,
        ma_ho_so=payload.ma_ho_so,
        academic_year=payload.academic_year,
        tham_so=payload.tham_so_quyet_dinh,
        nguoi_tao_id=current_user.id,
        xac_nhan_trang_thai=payload.xac_nhan_trang_thai,
        duoc_xac_nhan=duoc_xac_nhan,
    )
    await db.commit()
    xac_nhan = (bo.thong_tin_dung or {}).get("xac_nhan_canh_bao_trang_thai")
    log.info(
        "council_document_set_created",
        set_id=bo.id,
        so_ho_so=bo.so_ho_so,
        so_tep=bo.so_tep,
        actor=current_user.id,
        # lượt G — chỉ số đếm theo trạng thái (không mã, không số dòng)
        xac_nhan_canh_bao=(xac_nhan or {}).get("so_ho_so_theo_trang_thai"),
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
    return CouncilSetDetailOut.tu_bo_va_tep(
        bo,
        await bo_vb.tep_cua_bo(db, bo.id),
        await qd_vb.tom_tat_qd_cua_bo(db, bo.id),
    )


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


# ═══════════════════ Lượt I (F230) — ghi nhận Quyết định ĐÃ KÝ (CHỈ admin) ═══════════════════
# Quyền: Casbin (admin wildcard; KHÔNG vai nào khác có dòng) + lớp phụ ``require_council_document_admin``
# (trực tiếp hoặc qua ``get_council_document_set_for_admin`` / ``get_council_decision_for_admin`` /
# ``get_council_decision_hold_for_admin``). Route ghi khai trong ``ADMISSION_WRITE_ROUTES`` (đóng băng ⇒
# 503). Log chỉ id + số đếm — không CCCD, không lý do. Bản scan đọc tối đa trần + 1 byte.
def _qd_ghi_out(qd, so_lieu=None, canh_bao=None) -> CouncilDecisionWriteOut:
    return CouncilDecisionWriteOut(
        **CouncilDecisionOut.model_validate(qd).model_dump(),
        so_lieu=so_lieu,
        canh_bao_vuot_chi_tieu=canh_bao or [],
    )


async def _doc_scan(scan: UploadFile) -> bytes:
    return await scan.read(settings.COUNCIL_DECISION_SCAN_MAX_BYTES + 1)


def _json_xac_nhan(gia_tri: Optional[str]):
    """Trường form ``xac_nhan_trang_thai`` (JSON ``{loại: số}``) — sai dạng ⇒ 400 qua service."""
    import json

    if gia_tri is None or gia_tri == "":
        return None
    try:
        return json.loads(gia_tri)
    except ValueError:
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
    db: AsyncSession = Depends(database.get_db),
):
    qd, canh_bao = await qd_vb.ghi_nhan_quyet_dinh(
        db,
        set_id=set_id,
        loai=loai,
        goc_id=goc_id,
        so_quyet_dinh=so_quyet_dinh,
        ngay_ky=ngay_ky,
        tham_so_giay={
            "so_bien_ban": so_bien_ban,
            "ngay_bien_ban": ngay_bien_ban,
            "dot_so": dot_so,
            "dot_thang": dot_thang,
        },
        xac_nhan_so_ho_so=xac_nhan_so_ho_so,
        xac_nhan_khop_ban_in=xac_nhan_khop_ban_in,
        xac_nhan_trang_thai=_json_xac_nhan(xac_nhan_trang_thai),
        ghi_chu_mau=ghi_chu_mau,
        scan=await _doc_scan(scan),
        nguoi_id=current_user.id,
    )
    await db.commit()
    log.info(
        "council_decision_recorded",
        decision_id=qd.id,
        set_id=qd.set_id,
        so_ho_so=qd.so_ho_so,
        actor=current_user.id,
        so_o_vuot_chi_tieu=len(canh_bao),
    )
    return _qd_ghi_out(qd, canh_bao=canh_bao)


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
    db: AsyncSession = Depends(database.get_db),
):
    from ..repositories.council_decision_repository import CouncilDecisionRepository

    ds = await CouncilDecisionRepository(db).danh_sach_qd(
        set_id=set_id, limit=limit, offset=offset
    )
    return [CouncilDecisionOut.model_validate(d) for d in ds]


@router.get(
    "/decisions/{decision_id}",
    response_model=CouncilDecisionDetailOut,
    summary="Chi tiết văn bản đã ký: dòng (số dòng + id hồ sơ nội bộ), scan, sự kiện (chỉ admin)",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def get_council_decision(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    qd: models.CouncilDecision = Depends(deps.get_council_decision_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    qd, dong, scan, su_kien = await qd_vb.chi_tiet_qd(db, qd.id)
    return CouncilDecisionDetailOut(
        **CouncilDecisionOut.model_validate(qd).model_dump(),
        dong=[CouncilDecisionRowOut.model_validate(d) for d in dong],
        scan=(
            None
            if scan is None
            else {"sha256": scan.sha256, "kich_thuoc": scan.kich_thuoc, "kieu": scan.kieu}
        ),
        su_kien=[CouncilEventOut.model_validate(e) for e in su_kien],
    )


@router.get(
    "/decisions/{decision_id}/scan",
    summary="Tải bản scan của văn bản đã ký (chỉ admin; nhật ký ghi BỀN trước khi trả bytes)",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def download_council_decision_scan(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    qd: models.CouncilDecision = Depends(deps.get_council_decision_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    s = await qd_vb.doc_scan(db, qd.id)
    await qd_vb.ghi_tai_scan(db, s, current_user.id)
    await db.commit()
    log.info("council_decision_scan_downloaded", decision_id=qd.id, actor=current_user.id)
    return Response(
        content=bytes(s.noi_dung),
        media_type=s.kieu,
        headers={
            "Content-Disposition": content_disposition_tai_ve(
                "QuyetDinh-%d-scan.pdf" % qd.id
            ),
            **_TIEU_DE_TAI,
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
    qd: models.CouncilDecision = Depends(deps.get_council_decision_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    qd, so_lieu, canh_bao = await qd_vb.huy_ghi_nhan(
        db,
        qd.id,
        ly_do=payload.ly_do,
        so_go_lai=payload.so_go_lai,
        xac_nhan=payload.xac_nhan,
        nguoi_id=current_user.id,
    )
    await db.commit()
    log.info(
        "council_decision_record_cancelled",
        decision_id=qd.id,
        actor=current_user.id,
        **{k: v for k, v in so_lieu.items() if isinstance(v, int)},
        so_o_vuot_chi_tieu=len(canh_bao),
    )
    return _qd_ghi_out(qd, so_lieu, canh_bao=canh_bao)


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
    qd: models.CouncilDecision = Depends(deps.get_council_decision_for_admin),
    so_quyet_dinh: str = Form(..., pattern=r"^[0-9]{1,6}$"),
    ngay_ky: date = Form(...),
    scan: UploadFile = File(...),
    db: AsyncSession = Depends(database.get_db),
):
    h, so_lieu = await qd_vb.huy_hieu_luc(
        db,
        qd.id,
        so_quyet_dinh=so_quyet_dinh,
        ngay_ky=ngay_ky,
        scan=await _doc_scan(scan),
        nguoi_id=current_user.id,
    )
    await db.commit()
    log.info(
        "council_decision_revoked",
        decision_id=qd.id,
        revoking_id=h.id,
        actor=current_user.id,
        so_muc_cho_moi=so_lieu.get("so_muc_cho_moi"),
    )
    return _qd_ghi_out(h, so_lieu)


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
    qd: models.CouncilDecision = Depends(deps.get_council_decision_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    bo, _ = await bo_vb.tao_bo_dieu_chinh(
        db,
        database.engine,
        qd.id,
        ma_ho_so=payload.ma_ho_so,
        academic_year=payload.academic_year,
        tham_so=payload.tham_so_quyet_dinh,
        nguoi_tao_id=current_user.id,
        xac_nhan_trang_thai=payload.xac_nhan_trang_thai,
        duoc_xac_nhan=True,  # route CHỈ admin (lớp phụ ở deps) — admin được xác nhận
    )
    await db.commit()
    log.info(
        "council_adjustment_set_created",
        set_id=bo.id,
        goc_id=qd.id,
        so_ho_so=bo.so_ho_so,
        actor=current_user.id,
    )
    return CouncilSetDetailOut.tu_bo_va_tep(bo, await bo_vb.tep_cua_bo(db, bo.id))


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
    qd: models.CouncilDecision = Depends(deps.get_council_decision_for_admin),
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
    dc, canh_bao = await qd_vb.ghi_nhan_dieu_chinh(
        db,
        qd.id,
        so_quyet_dinh=so_quyet_dinh,
        ngay_ky=ngay_ky,
        bo_dong=bo_dong,
        set_id=set_id,
        xac_nhan_so_ho_so=xac_nhan_so_ho_so,
        xac_nhan_khop_ban_in=xac_nhan_khop_ban_in,
        xac_nhan_trang_thai=_json_xac_nhan(xac_nhan_trang_thai),
        ghi_chu_mau=ghi_chu_mau,
        scan=await _doc_scan(scan),
        nguoi_id=current_user.id,
    )
    await db.commit()
    log.info(
        "council_decision_adjusted",
        decision_id=dc.id,
        goc_id=qd.id,
        so_dong_bo=len(bo_dong),
        actor=current_user.id,
    )
    return _qd_ghi_out(dc, canh_bao=canh_bao)


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
    bo: models.CouncilDocumentSet = Depends(deps.get_council_document_set_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    moi, _ = await bo_vb.tao_bo_dung_lai_ban_ky(
        db,
        database.engine,
        bo,
        so_quyet_dinh=payload.so_quyet_dinh,
        ngay_ky=payload.ngay_ky,
        dong_sua_tay=payload.dong_sua_tay,
        ly_do=payload.ly_do,
        xac_nhan_dong_khac=payload.xac_nhan_dong_khac,
        nguoi_tao_id=current_user.id,
    )
    await db.commit()
    log.info(
        "council_set_resigned",
        set_id=moi.id,
        tu_set_id=bo.id,
        so_dong_sua_tay=len(payload.dong_sua_tay),
        actor=current_user.id,
    )
    return CouncilSetDetailOut.tu_bo_va_tep(moi, await bo_vb.tep_cua_bo(db, moi.id))


@router.get(
    "/sets/{set_id}/so-voi-hien-tai",
    summary="So ảnh chụp của bộ với dữ liệu hiện tại — số dòng + TÊN trường đổi (chỉ admin)",
)
@limiter.limit(RateLimits.ADMIN_READ)
async def compare_council_document_set(
    request: Request,
    current_user: models.User = deps.CasbinAuth,
    bo: models.CouncilDocumentSet = Depends(deps.get_council_document_set_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    out = await bo_vb.so_voi_hien_tai(db, database.engine, bo)
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

    ds = await CouncilDecisionRepository(db).danh_sach_muc_cho(
        trang_thai=trang_thai, limit=limit, offset=offset
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
        for h, d in ds
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
    muc: models.CouncilDecisionHold = Depends(deps.get_council_decision_hold_for_admin),
    db: AsyncSession = Depends(database.get_db),
):
    h, _ = await qd_vb.cho_xet_lai(
        db, muc.id, ly_do=payload.ly_do, nguoi_id=current_user.id
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

    ds = await CouncilDecisionRepository(db).danh_sach_su_kien(
        set_id=set_id, decision_id=decision_id, limit=limit, offset=offset
    )
    return [CouncilEventOut.model_validate(e) for e in ds]


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
    quyen = await deps.quyen_van_ban_hoi_dong(request, current_user, ENDPOINT_THEO_CO)
    return CouncilDocumentPermissionsOut(
        permissions=CouncilDocumentPermissions(**quyen)
    )


#: Cờ ↔ HÀM xử lý của ĐÚNG MỘT route (phương thức + đường đọc từ bảng route thật của app, không
#: viết lại ở đây). Thêm route mới vào module ⇒ thêm cờ (test
#: ``test_moi_route_cua_module_co_dung_mot_co`` đỏ nếu quên).
ENDPOINT_THEO_CO = {
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
}
