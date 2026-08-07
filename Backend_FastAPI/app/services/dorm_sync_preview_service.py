# -*- coding: utf-8 -*-
"""Điều phối bước XEM TRƯỚC. Toàn bộ nghiệp vụ nằm ở đây, không ở router.

🔴 Vì sao tách khỏi router: thứ tự các bước ở đây LÀ hàng rào — đọc nguồn, kiểm
hợp đồng, chặn cohort rỗng, kiểm năm còn mở, hỏi đích đúng một lần, rồi mới ký
phiếu. Để chuỗi ấy sống trong hàm handler nghĩa là nó chỉ kiểm được qua HTTP,
và bước sau (sổ cái, máy trạng thái) sẽ chồng thêm vào cùng chỗ cho tới lúc
không ai đọc nổi thứ tự nữa.

Router chỉ còn hai việc: dựng phụ thuộc, và chuyển kết quả thành schema.

⚠️ Module này không đọc biến môi trường và không biết gì về HTTP. Cấu hình,
khoá ký và mốc thời gian đều truyền vào tường minh — cùng lý do với
``DormSyncConfig`` và ``phat_hanh_token``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

import structlog

from app.services.dorm_sync_config import DormSyncConfig
from app.services.dorm_sync_service import (
    DormApi,
    assert_payload_contract,
    fetch_cohort,
)
from app.services.dorm_sync_snapshot import (
    SoLieuNguon,
    assert_snapshot_contract,
    build_source_snapshot,
    dem_so_lieu_nguon,
    hash_source_snapshot,
    phat_hanh_token,
)
from app.utils.exceptions import BusinessRuleViolation

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class KetQuaXemTruoc:
    """Kết quả bước xem trước — chưa ghi gì sang hệ KTX."""

    academic_year: int
    source_count: int
    can_apply: bool
    blocked_reason: Optional[str] = None
    counts: Optional[SoLieuNguon] = None
    warnings: Tuple[Dict[str, Any], ...] = ()
    source_hash: Optional[str] = None
    target_fingerprint: Optional[str] = None
    snapshot_hash: Optional[str] = None
    snapshot_version: Optional[int] = None
    preview_token: Optional[str] = None
    expires_at: Optional[int] = None




async def chuan_bi_xem_truoc(
    *,
    cau_hinh: DormSyncConfig,
    secret: str,
    actor_id: int,
    academic_year: int,
    now_ts: int,
    api_factory: Callable[..., Any] = DormApi,
    cohort_loader: Callable[..., Any] = fetch_cohort,
) -> KetQuaXemTruoc:
    """Đọc nguồn, hỏi đích, ký phiếu. CHỈ ĐỌC — không mở lượt, không ghi.

    Thứ tự dưới đây LÀ hàng rào; đọc từ trên xuống là đọc đúng những gì phải
    đúng trước khi một byte nào rời khỏi tiến trình.
    """
    # 1. Đọc nguồn trong transaction CHỈ ĐỌC.
    #
    # ⚠️ `verify_source=False`: hàng rào định danh nguồn là cổng của bước GHI.
    # Bắt một lượt xem trước khai đủ cấu hình nguồn chỉ khiến người ta bỏ qua
    # bước xem trước — mà xem trước mới là thứ chặn được lần ghi sai.
    rows = await cohort_loader(academic_year)

    # 2. 🔴 Cohort RỖNG: dừng ở đây. Không dựng `DormApi`, không hỏi đích,
    #    không cấp phiếu.
    #
    #    Nguồn rỗng + ghi = hạ cờ TOÀN BỘ học viên của năm đó, mà mọi con số
    #    đều bằng 0 và khớp nhau nên không hàng rào nào phía database nổ. Lượt
    #    kết thúc `completed`, nhìn từ ngoài y hệt một lần chạy thành công.
    #    Cách chặn đúng là không bao giờ cấp phiếu cho ca này.
    if not rows:
        log.warning(
            "dorm_sync_preview_empty_cohort",
            actor_id=actor_id,
            academic_year=academic_year,
        )
        return KetQuaXemTruoc(
            academic_year=academic_year,
            source_count=0,
            can_apply=False,
            blocked_reason=(
                f"Nguồn QLTS không có hồ sơ nào đủ điều kiện cho năm "
                f"{academic_year}. Ghi tiếp sẽ hạ cờ toàn bộ học viên năm này "
                "ở hệ ký túc xá."
            ),
        )

    # 3. 🔴 Hợp đồng dữ liệu, TRƯỚC khi chạm sang KTX.
    #
    #    Cả hai cổng đều phải chạy ở đây chứ không đợi lúc dựng payload: dấu
    #    băm nguồn được tính SAU khi đã hỏi ảnh chụp đích, nên một hàng thiếu
    #    trường sẽ làm ta gửi cả danh sách `qlts_profile_id` sang hệ kia rồi
    #    mới dừng — cho một lượt lẽ ra chặn được ở dòng đầu.
    assert_payload_contract(rows)
    assert_snapshot_contract(rows)

    api = api_factory(
        cau_hinh.supabase_url,
        cau_hinh.supabase_secret_key,
        expected_project_ref=cau_hinh.target_project_ref,
    )
    async with api:
        # 4. Năm học phải còn MỞ bên đích. Ghi vào một năm đã chốt sổ là đổi
        #    dữ liệu của một kỳ đã khoá.
        nam_mo = await api.fetch_open_academic_years()
        if academic_year not in nam_mo:
            raise BusinessRuleViolation(
                f"Năm học {academic_year} không còn mở ở hệ ký túc xá."
            )

        # 5. ĐÚNG MỘT lời gọi cho cả danh sách cảnh báo lẫn dấu vân tay.
        #    Hai lời gọi là hai ảnh chụp — xem `fetch_target_snapshot`.
        snapshot_dich = await api.fetch_target_snapshot(
            academic_year, [r.qlts_profile_id for r in rows]
        )

    dau_bam_nguon = hash_source_snapshot(build_source_snapshot(rows))

    token, claims = phat_hanh_token(
        secret=secret,
        actor_id=actor_id,
        academic_year=academic_year,
        source_hash=dau_bam_nguon,
        target_fingerprint=snapshot_dich.fingerprint,
        now_ts=now_ts,
    )

    # Chỉ log SỐ ĐẾM và dấu băm. Họ tên, số điện thoại, mã hồ sơ KHÔNG đi vào
    # log — log được gom về nơi khác và giữ lâu hơn ta nghĩ.
    log.info(
        "dorm_sync_preview_issued",
        actor_id=actor_id,
        academic_year=academic_year,
        source_count=len(rows),
        warning_count=len(snapshot_dich.rows),
        operation_id=str(claims.operation_id),
    )

    return KetQuaXemTruoc(
        academic_year=academic_year,
        source_count=len(rows),
        can_apply=True,
        counts=dem_so_lieu_nguon(rows),
        warnings=snapshot_dich.rows,
        source_hash=dau_bam_nguon,
        target_fingerprint=snapshot_dich.fingerprint,
        snapshot_hash=claims.snapshot_hash,
        snapshot_version=claims.snapshot_version,
        preview_token=token,
        expires_at=claims.expires_at,
    )
