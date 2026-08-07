# -*- coding: utf-8 -*-
"""Màn đồng bộ ký túc xá — bối cảnh để dựng màn hình.

🔴 Ranh giới của file này: nó là **adapter**. Nó dựng cấu hình từ ``Settings``
rồi truyền vào lõi ở ``app/services/dorm_sync_service.py``; lõi không đọc biến
môi trường và không biết gì về HTTP. Ngược lại, mọi lỗi nghiệp vụ do lõi ném ra
là exception có kiểu — ``base_app_exception_handler`` dịch sang mã HTTP, router
KHÔNG bắt rồi ném ``HTTPException`` (kiến trúc V3.0).

⚠️ Bước này CHỈ có ``GET /context``. Chưa mở lượt, chưa đọc cohort, chưa ký
token, chưa chạm sổ cái.
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
    DormSyncWarningRow,
)
from app.services.dorm_sync_config import DormSyncConfig
from app.services.dorm_sync_service import DormApi, fetch_cohort
from app.services.dorm_sync_snapshot import (
    build_source_snapshot,
    hash_source_snapshot,
    phat_hanh_token,
)
from app.utils.exceptions import BusinessRuleViolation

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
    """Đọc nguồn, hỏi đích, rồi cấp một phiếu có chữ ký. KHÔNG ghi gì.

    🔴 Đây là hàng rào cuối trước một lượt hạ cờ. Nó phải trả về ĐÚNG thứ bước
    ghi sẽ dùng — cùng ảnh chụp, cùng dấu vân tay — nếu không thì người bấm
    duyệt một thứ rồi hệ thống ghi một thứ khác.

    ⚠️ Chưa chạm sổ cái, chưa mở ``sync_run``, chưa upsert/finalize. Bước này
    chỉ đọc.
    """
    # 1. Cấu hình TRƯỚC mọi thứ — thiếu là dừng, chưa gói tin nào rời tiến trình.
    cau_hinh = DormSyncConfig.from_settings()

    # 2. Đọc nguồn. `fetch_cohort` chạy trong transaction CHỈ ĐỌC.
    #
    # ⚠️ `verify_source=False`: hàng rào định danh nguồn là cổng của bước GHI.
    # Bắt một lượt xem trước khai đủ cấu hình nguồn chỉ khiến người ta bỏ qua
    # bước xem trước — mà xem trước mới là thứ chặn được lần ghi sai.
    rows = await fetch_cohort(than.academic_year)

    # 3. 🔴 Cohort RỖNG: dừng ở đây. Không dựng `DormApi`, không hỏi đích,
    #    không cấp phiếu.
    #
    #    Nguồn rỗng + ghi = hạ cờ TOÀN BỘ học viên của năm đó, mà mọi con số
    #    đều bằng 0 và khớp nhau nên không hàng rào nào phía database nổ. Lượt
    #    kết thúc `completed`, nhìn từ ngoài y hệt một lần chạy thành công.
    #    Cách chặn đúng là không bao giờ cấp phiếu cho ca này.
    if not rows:
        log.warning(
            "dorm_sync_preview_empty_cohort",
            actor_id=current_user.id,
            academic_year=than.academic_year,
        )
        return DormSyncPreviewResponse(
            academic_year=than.academic_year,
            source_count=0,
            can_apply=False,
            blocked_reason=(
                f"Nguồn QLTS không có hồ sơ nào đủ điều kiện cho năm "
                f"{than.academic_year}. Ghi tiếp sẽ hạ cờ toàn bộ học viên "
                "năm này ở hệ ký túc xá."
            ),
        )

    api = DormApi(
        cau_hinh.supabase_url,
        cau_hinh.supabase_secret_key,
        expected_project_ref=cau_hinh.target_project_ref,
    )
    async with api:
        # 4. Năm học phải còn MỞ bên đích. Ghi vào một năm đã chốt sổ là đổi
        #    dữ liệu của một kỳ đã khoá.
        nam_mo = await api.fetch_open_academic_years()
        if than.academic_year not in nam_mo:
            raise BusinessRuleViolation(
                f"Năm học {than.academic_year} không còn mở ở hệ ký túc xá."
            )

        # 5. ĐÚNG MỘT lời gọi cho cả danh sách cảnh báo lẫn dấu vân tay.
        #    Hai lời gọi là hai ảnh chụp — xem `fetch_target_snapshot`.
        snapshot_dich = await api.fetch_target_snapshot(
            than.academic_year, [r.qlts_profile_id for r in rows]
        )

    # 6. Ảnh chụp NGUỒN + dấu băm. Dùng chung helper với `build_student_payload`.
    dau_bam_nguon = hash_source_snapshot(build_source_snapshot(rows))

    token, claims = phat_hanh_token(
        secret=settings.SECRET_KEY,
        actor_id=current_user.id,
        academic_year=than.academic_year,
        source_hash=dau_bam_nguon,
        target_fingerprint=snapshot_dich.fingerprint,
        now_ts=int(time.time()),
    )

    # Chỉ log SỐ ĐẾM và dấu băm. Họ tên, số điện thoại, mã hồ sơ KHÔNG đi vào
    # log — log được gom về nơi khác và giữ lâu hơn ta nghĩ.
    log.info(
        "dorm_sync_preview_issued",
        actor_id=current_user.id,
        academic_year=than.academic_year,
        source_count=len(rows),
        warning_count=len(snapshot_dich.rows),
        operation_id=str(claims.operation_id),
    )

    return DormSyncPreviewResponse(
        academic_year=than.academic_year,
        source_count=len(rows),
        can_apply=True,
        # ⚠️ CHIẾU XUỐNG đúng sáu trường người bấm cần đọc, không đổ nguyên
        # hàng RPC ra ngoài. `assignment_id`, `building_id`, `room_id` là khoá
        # nội bộ của hệ KTX — gửi ra là mở rộng bề mặt dữ liệu cá nhân mà
        # không ai dùng tới, và biến hình dạng bảng bên kia thành hợp đồng
        # công khai của endpoint này.
        warnings=[
            DormSyncWarningRow(
                qlts_profile_id=h["qlts_profile_id"],
                full_name=h["full_name"],
                building_name=h["building_name"],
                room_code=h["room_code"],
                bed_no=h["bed_no"],
                status=h["status"],
            )
            for h in snapshot_dich.rows
        ],
        source_hash=dau_bam_nguon,
        target_fingerprint=snapshot_dich.fingerprint,
        preview_token=token,
        expires_at=claims.expires_at,
    )
