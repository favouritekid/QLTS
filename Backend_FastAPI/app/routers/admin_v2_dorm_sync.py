# -*- coding: utf-8 -*-
"""Màn đồng bộ ký túc xá — bối cảnh để dựng màn hình.

🔴 Ranh giới của file này: nó là **adapter**. Nó dựng cấu hình từ ``Settings``
rồi truyền vào lõi ở ``app/services/dorm_sync_service.py``; lõi không đọc biến
môi trường và không biết gì về HTTP. Ngược lại, mọi lỗi nghiệp vụ do lõi ném ra
là exception có kiểu — ``base_app_exception_handler`` dịch sang mã HTTP, router
KHÔNG bắt rồi ném ``HTTPException`` (kiến trúc V3.0).

Hiện có ``GET /context`` và ``POST /preview`` — cả hai CHỈ ĐỌC. Chưa mở lượt
đồng bộ, chưa upsert/finalize, chưa chạm sổ cái ``dorm_sync_operations``.
"""

from __future__ import annotations

import time

import structlog
from fastapi import APIRouter, Depends, Request

from app import models
from app.config import settings
from app.core.deps import require_admin
from app.core.rate_limits import RateLimits, limiter
from app.schemas.dorm_sync import (
    DormSyncContextResponse,
    DormSyncPreviewRequest,
    DormSyncPreviewResponse,
    DormSyncSourceCounts,
    DormSyncWarningRow,
)
from app.services.dorm_sync_config import DormSyncConfig
from app.services.dorm_sync_preview_service import chuan_bi_xem_truoc
from app.services.dorm_sync_service import DormApi

log = structlog.get_logger(__name__)

# 🔴 Khai ĐỦ đường dẫn ở đây, và mount thẳng vào `fastapi_app` — cùng lối với
# các router `admin_v2_*` khác.
#
# Bản trước gắn vào `admin_router` (đang được mount với `prefix="/api"`) nên
# đường thật thành `/api/admin/dorm-sync/...`, lệch contract `/api/v2/admin/...`
# mà frontend sẽ gọi. Lệch prefix không làm test nào đỏ nếu test cũng viết theo
# đường sai — nó chỉ hiện ra thành 404 ở lần bấm đầu tiên trên giao diện.
router = APIRouter(
    prefix="/api/v2/admin/dorm-sync",
    tags=["Admin v2 - Đồng bộ ký túc xá"],
)


@router.get(
    "/context",
    response_model=DormSyncContextResponse,
    summary="Năm học đang mở ở hệ KTX và năm mặc định",
)
# ⚠️ THỨ TỰ CÓ CHỦ ĐÍCH: `@router.get` NGOÀI, `@limiter.limit` TRONG.
#
# Decorator áp từ dưới lên, nên đặt ngược lại thì `router.get` đăng ký hàm
# CHƯA bọc limiter và giới hạn không bao giờ chạy — endpoint trông như có rào
# mà thực tế không giới hạn gì. Repo này đang nợ đúng lỗi đó ở nhiều nơi; đừng
# chép thêm. Ca `test_endpoint_that_su_bi_limiter_boc` khoá vế này lại.
@limiter.limit(RateLimits.ADMIN_READ)
async def lay_boi_canh(
    request: Request,
    current_user: models.User = Depends(require_admin),
) -> DormSyncContextResponse:
    """Trả danh sách năm học ĐANG MỞ ở hệ KTX, kèm năm mặc định.

    🔴 Không có năm nào mở ⇒ danh sách rỗng và ``default_academic_year=None``.
    KHÔNG lùi về năm hiện tại: "hệ KTX chưa mở năm nào" là một trạng thái thật,
    và điền đại một năm ở đây nghĩa là dựng sẵn một lượt ghi vào năm không tồn
    tại bên đích — mà lượt ấy hạ cờ đủ-điều-kiện của cả cohort.

    🔴 Cấu hình thiếu ⇒ ``DormSyncConfigError`` ném ra TRƯỚC khi có gói tin nào
    rời khỏi tiến trình. Không gọi sang KTX với một đích chưa biết.
    """
    # Dựng cấu hình TRƯỚC. `from_settings` đòi cờ `DORM_SYNC_ENABLED` và đủ năm
    # biến; thiếu là ném ngay tại đây, chưa mở kết nối nào.
    cau_hinh = DormSyncConfig.from_settings()

    api = DormApi(
        cau_hinh.supabase_url,
        cau_hinh.supabase_secret_key,
        expected_project_ref=cau_hinh.target_project_ref,
    )
    async with api:
        nam_mo = await api.fetch_open_academic_years()

    log.info(
        "dorm_sync_context_read",
        actor_id=current_user.id,
        so_nam_mo=len(nam_mo),
    )

    return DormSyncContextResponse(
        open_academic_years=list(nam_mo),
        # `nam_mo` đã sắp giảm dần ở lõi, nên phần tử đầu là năm lớn nhất.
        default_academic_year=nam_mo[0] if nam_mo else None,
    )


@router.post(
    "/preview",
    response_model=DormSyncPreviewResponse,
    summary="Xem trước lượt đồng bộ (CHỈ ĐỌC) và cấp phiếu để ghi",
)
# Thứ tự decorator: xem chú thích ở `/context`.
@limiter.limit(RateLimits.ADMIN_READ)
async def xem_truoc(
    request: Request,
    than: DormSyncPreviewRequest,
    current_user: models.User = Depends(require_admin),
) -> DormSyncPreviewResponse:
    """Dựng phụ thuộc, gọi service, chuyển kết quả thành schema.

    🔴 KHÔNG có nghiệp vụ ở đây. Thứ tự các bước — đọc nguồn, kiểm hợp đồng,
    chặn cohort rỗng, kiểm năm còn mở, hỏi đích đúng một lần, rồi mới ký phiếu
    — LÀ hàng rào, và nó sống ở ``chuan_bi_xem_truoc``. Để chuỗi ấy trong hàm
    handler nghĩa là nó chỉ kiểm được qua HTTP, và bước sau (sổ cái, máy trạng
    thái) sẽ chồng thêm vào cùng chỗ.
    """
    ket_qua = await chuan_bi_xem_truoc(
        cau_hinh=DormSyncConfig.from_settings(),
        secret=settings.SECRET_KEY,
        actor_id=current_user.id,
        academic_year=than.academic_year,
        now_ts=int(time.time()),
    )

    return DormSyncPreviewResponse(
        academic_year=ket_qua.academic_year,
        source_count=ket_qua.source_count,
        can_apply=ket_qua.can_apply,
        blocked_reason=ket_qua.blocked_reason,
        counts=(
            DormSyncSourceCounts(**vars(ket_qua.counts))
            if ket_qua.counts is not None
            else None
        ),
        # ⚠️ CHIẾU XUỐNG đúng sáu trường người bấm cần đọc, không đổ nguyên
        # hàng RPC ra ngoài. `assignment_id`, `building_id`, `room_id` là khoá
        # nội bộ của hệ KTX — gửi ra là mở rộng bề mặt dữ liệu cá nhân mà không
        # ai dùng tới, và biến hình dạng bảng bên kia thành hợp đồng công khai
        # của endpoint này.
        warnings=[
            DormSyncWarningRow(
                qlts_profile_id=h["qlts_profile_id"],
                full_name=h["full_name"],
                building_name=h["building_name"],
                room_code=h["room_code"],
                bed_no=h["bed_no"],
                status=h["status"],
            )
            for h in ket_qua.warnings
        ],
        source_hash=ket_qua.source_hash,
        target_fingerprint=ket_qua.target_fingerprint,
        snapshot_hash=ket_qua.snapshot_hash,
        snapshot_version=ket_qua.snapshot_version,
        preview_token=ket_qua.preview_token,
        expires_at=ket_qua.expires_at,
    )
