# -*- coding: utf-8 -*-
"""Bước GHI: chuẩn bị, thực thi, ghi sổ. Ba pha tách rời có chủ đích.

🔴 Vì sao ba hàm chứ không một:

* :func:`prepare_apply` chạm **database QLTS** (sổ cái) và cần một session;
* :func:`execute_apply` chạm **hệ KTX** qua HTTP và KHÔNG được giữ session —
  một lượt đồng bộ mất vài chục giây, và ôm một transaction suốt thời gian đó
  là giữ khoá trên sổ cái trong lúc chờ mạng;
* :func:`record_result` quay lại database để đóng sổ.

Ranh giới ấy cũng là ranh giới của hai loại hỏng. Giữa pha 2 và pha 3 có thể
mất điện: sổ cái ở lại ``running`` trong khi hệ KTX đã ghi xong. Đó là ca
``outcome_unknown``, và nó phải do NGƯỜI xử — xem :func:`prepare_apply`.

⚠️ KHÔNG hàm nào ở đây gọi ``db.commit()``. Router commit (kiến trúc V3.0).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Callable, Dict, List, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dorm_sync_operation import DormSyncOperation
from app.repositories.dorm_sync_operation_repository import (
    cap_nhat_ket_qua,
    chen_neu_chua_co,
    lay_theo_operation_id,
)
from app.services.audit_service import log_audit
from app.services.dorm_sync_config import DormSyncConfig
from app.services.dorm_sync_service import (
    DormApi,
    assert_payload_contract,
    build_student_payload,
    fetch_cohort,
)
from app.services.dorm_sync_snapshot import (
    PreviewTokenClaims,
    assert_snapshot_contract,
    build_source_snapshot,
    doc_token,
    hash_source_snapshot,
)
from app.utils.exceptions import BusinessRuleViolation, DormSyncTokenError

log = structlog.get_logger(__name__)

_ENTITY = "DormSyncOperation"

# Trần một lô, trùng trần của RPC `upsert_students_batch` (guard P0111).
_KICH_THUOC_LO = 200


class TrangThaiChuanBi(StrEnum):
    """Kết luận của pha chuẩn bị. Tập ĐÓNG — nơi gọi rẽ nhánh theo giá trị này."""

    # Chưa từng chạy: sổ cái vừa được mở, đi tiếp sang `execute_apply`.
    SAN_SANG = "san_sang"
    # Đã chạy xong trước đó: trả lại kết quả cũ, KHÔNG chạy lại.
    DA_XONG = "da_xong"
    # Đang chạy, hoặc đã hỏng, hoặc không rõ kết quả: dừng, cần người xử.
    KHONG_CHAY_LAI = "khong_chay_lai"


@dataclass(frozen=True)
class KetQuaChuanBi:
    trang_thai: TrangThaiChuanBi
    so_cai: DormSyncOperation
    claims: PreviewTokenClaims
    # Chỉ có ở `SAN_SANG` — cohort đã đọc và đã đối chiếu dấu băm.
    rows: Optional[List[Any]] = None
    # Chỉ có ở `DA_XONG` / `KHONG_CHAY_LAI`.
    thong_diep: Optional[str] = None


async def prepare_apply(
    db: AsyncSession,
    *,
    token: str,
    secret: str,
    actor_id: int,
    cau_hinh: DormSyncConfig,
    now_ts: int,
    api_factory: Callable[..., Any] = DormApi,
    cohort_loader: Callable[..., Any] = fetch_cohort,
) -> KetQuaChuanBi:
    """Giải phiếu, tra sổ, rồi mới đối chiếu trạng thái. Thứ tự LÀ hàng rào.

    🔴 Tra sổ TRƯỚC khi đọc nguồn. Một ``operation_id`` đã có trong sổ nghĩa là
    lượt này đã chạy (hoặc đang chạy); đọc lại cohort và hỏi lại hệ KTX cho nó
    là làm hai việc tốn kém để rồi vứt đi — và tệ hơn, là chạm sang hệ kia cho
    một thao tác mà câu trả lời đã có sẵn.

    🔴 ``running`` / ``failed`` / ``outcome_unknown`` đều KHÔNG tự chạy lại.
    Ba trạng thái ấy khác nhau, nhưng chung một điều: ta không biết hệ KTX đang
    ở đâu. Tự chạy lại là ghi chồng lên một lượt có thể đang ghi dở — mà mỗi
    lượt hạ cờ đủ-điều-kiện của cả một cohort.
    """
    # 1. Giải phiếu. Chữ ký, phiên bản, TTL, actor — xem `doc_token`.
    claims = doc_token(token, secret=secret, actor_id=actor_id, now_ts=now_ts)

    # 2. Tra sổ.
    so_cai = await lay_theo_operation_id(db, claims.operation_id)
    if so_cai is not None:
        return _xet_so_cai_cu(so_cai, claims)

    # 3. Chưa có trong sổ ⇒ mới được đọc nguồn.
    #
    # ⚠️ `verify_source=True`: đây là bước GHI. Hàng rào định danh nguồn hỏi
    # thẳng database `current_database()` và `system_identifier` — nó chặn ca
    # một stack DEV cầm file secret của hệ KTX THẬT.
    rows = await cohort_loader(
        claims.academic_year,
        verify_source=True,
        expected_source_db=cau_hinh.source_db,
        expected_system_id=cau_hinh.source_system_id,
    )
    assert_payload_contract(rows)
    assert_snapshot_contract(rows)

    # 4. Nguồn phải ĐÚNG thứ đã ký.
    dau_bam_nguon = hash_source_snapshot(build_source_snapshot(rows))
    if dau_bam_nguon != claims.source_hash:
        raise DormSyncTokenError(
            "Nguồn QLTS đã đổi sau khi xem trước "
            f"(ký {claims.source_hash[:12]}…, hiện {dau_bam_nguon[:12]}…)."
        )

    # 5. Đích cũng phải ĐÚNG thứ đã ký.
    #
    # ⚠️ Kiểm ở đây chỉ THU HẸP cửa sổ, không đóng được — khoảng trống nằm
    # giữa lần kiểm này và câu `update` hạ cờ. Chốt thật nằm TRONG transaction
    # của `finalize_sync_run` (P0192). Nhưng vẫn kiểm: hỏng ở đây thì chưa mở
    # lượt nào, còn hỏng ở đó thì phải đi đóng sổ một lượt dở dang.
    api = api_factory(
        cau_hinh.supabase_url,
        cau_hinh.supabase_secret_key,
        expected_project_ref=cau_hinh.target_project_ref,
    )
    async with api:
        snapshot_dich = await api.fetch_target_snapshot(
            claims.academic_year, [r.qlts_profile_id for r in rows]
        )
    if snapshot_dich.fingerprint != claims.target_fingerprint:
        raise DormSyncTokenError(
            "Chỗ ở phía ký túc xá đã đổi sau khi xem trước "
            f"(ký {claims.target_fingerprint[:12]}…, "
            f"hiện {snapshot_dich.fingerprint[:12]}…)."
        )

    # 6. Mở sổ. `ON CONFLICT DO NOTHING RETURNING` — bên thua nhận `None`,
    #    KHÔNG nhận `IntegrityError`.
    so_cai = await chen_neu_chua_co(
        db,
        operation_id=claims.operation_id,
        actor_id=actor_id,
        academic_year=claims.academic_year,
        snapshot_hash=claims.snapshot_hash,
        snapshot_version=claims.snapshot_version,
    )

    if so_cai is None:
        # 🔴 Thua cuộc đua. Một request khác đã mở sổ cho cùng
        # `operation_id` trong lúc ta đang đọc nguồn và hỏi đích.
        #
        # Đọc lại hàng của bên thắng rồi đi qua CHÍNH máy trạng thái ở trên —
        # không xử riêng. Một nhánh riêng cho bên thua là một bản sao của cùng
        # logic, và nó sẽ lệch đúng vào ngày ai đó sửa một bên.
        so_cai = await lay_theo_operation_id(db, claims.operation_id)
        if so_cai is None:
            # Không chèn được mà cũng không đọc được: đừng đoán.
            raise BusinessRuleViolation(
                "Không mở được sổ cái cho lượt đồng bộ này và cũng không đọc "
                "lại được hàng đã có. Dừng để không chạy hai lượt song song."
            )
        log.warning(
            "dorm_sync_apply_lost_race",
            actor_id=actor_id,
            operation_id=str(claims.operation_id),
        )
        return _xet_so_cai_cu(so_cai, claims)

    await log_audit(
        db,
        _ENTITY,
        so_cai.id,
        "dorm_sync_requested",
        actor_user_id=actor_id,
        # Chỉ SỐ ĐẾM và dấu băm. Họ tên, số điện thoại, mã hồ sơ KHÔNG vào
        # nhật ký — nhật ký được gom về nơi khác và giữ lâu hơn ta nghĩ.
        new_value={
            "operation_id": str(claims.operation_id),
            "academic_year": claims.academic_year,
            "source_count": len(rows),
            "snapshot_hash": claims.snapshot_hash,
            "snapshot_version": claims.snapshot_version,
        },
        source="admin_panel",
    )

    return KetQuaChuanBi(
        trang_thai=TrangThaiChuanBi.SAN_SANG,
        so_cai=so_cai,
        claims=claims,
        rows=rows,
    )


def _xet_so_cai_cu(
    so_cai: DormSyncOperation, claims: PreviewTokenClaims
) -> KetQuaChuanBi:
    """Máy trạng thái cho một ``operation_id`` đã có trong sổ.

    MỘT nơi quyết định, dùng cho cả đường thường lẫn đường thua cuộc đua.
    """
    if so_cai.status == "completed":
        # Idempotent: cùng phiếu, cùng kết quả. Đây là ca mất phản hồi ở lần
        # bấm trước, hoặc người dùng bấm hai lần — cả hai đều bình thường.
        return KetQuaChuanBi(
            trang_thai=TrangThaiChuanBi.DA_XONG,
            so_cai=so_cai,
            claims=claims,
            thong_diep="Lượt đồng bộ này đã chạy xong trước đó.",
        )

    if so_cai.status == "running":
        thong_diep = (
            "Lượt đồng bộ này đang chạy. Chờ nó kết thúc; KHÔNG bấm lại — hai "
            "lượt cùng lúc sẽ vướng khoá của hệ ký túc xá."
        )
    elif so_cai.status == "failed":
        thong_diep = (
            "Lượt đồng bộ này đã hỏng. Bấm Xem trước lại để lấy phiếu mới; "
            "phiếu cũ không chạy lại được."
        )
    else:  # outcome_unknown
        thong_diep = (
            "Lượt đồng bộ này kết thúc mà KHÔNG rõ hệ ký túc xá đã ghi tới "
            "đâu. Phải đối soát bằng tay trước khi chạy lượt mới."
        )

    return KetQuaChuanBi(
        trang_thai=TrangThaiChuanBi.KHONG_CHAY_LAI,
        so_cai=so_cai,
        claims=claims,
        thong_diep=thong_diep,
    )


@dataclass(frozen=True)
class KetQuaGhi:
    ktx_run_id: int
    upserted: int
    blocked: int
    deactivated: int


async def execute_apply(
    *,
    cau_hinh: DormSyncConfig,
    claims: PreviewTokenClaims,
    rows: List[Any],
    api_factory: Callable[..., Any] = DormApi,
    api: Optional[Any] = None,
) -> KetQuaGhi:
    """Ghi sang hệ KTX. KHÔNG nhận session database.

    🔴 Không có tham số ``db`` là một ràng buộc, không phải thiếu sót. Lượt này
    mất vài chục giây; ôm một transaction suốt thời gian đó là giữ khoá trên sổ
    cái trong lúc chờ mạng, và mọi request khác đụng cùng hàng sẽ xếp hàng sau
    một cuộc gọi HTTP.

    🔴 Dùng ĐÚNG ``claims.target_fingerprint`` — dấu đã ký ở bước xem trước.
    KHÔNG chụp lại trước khi đóng sổ: chụp lại thì nó luôn khớp, và chốt thành
    phép so một giá trị với chính nó — vẫn xanh, vẫn tốn một lời gọi, và không
    chặn được gì.
    """
    if api is None:
        api = api_factory(
            cau_hinh.supabase_url,
            cau_hinh.supabase_secret_key,
            expected_project_ref=cau_hinh.target_project_ref,
        )

    async with api:
        ket_qua_mo = await api.open_sync_run(
            claims.academic_year,
            str(claims.operation_id),
            raw_count=len(rows),
        )
        run_id = ket_qua_mo.run_id

        # MỘT mốc thời gian cho cả lượt: mọi hàng phải mang cùng ``synced_at``,
        # nếu không thì "đồng bộ lần cuối lúc nào" trở thành một dải giờ trải
        # theo tốc độ chạy của từng lô.
        synced_at = datetime.now(timezone.utc).isoformat()

        upserted = 0
        blocked = 0
        for dau in range(0, len(rows), _KICH_THUOC_LO):
            lo = rows[dau : dau + _KICH_THUOC_LO]
            da_ghi, bi_chan = await api.upsert_students(
                run_id, [build_student_payload(r, run_id, synced_at) for r in lo]
            )
            # ⚠️ Đối soát TỪNG LÔ. Lệch nghĩa là RPC bỏ sót hàng trong im lặng
            # — và hai con số này đi thẳng vào phép kiểm `raw = source +
            # blocked` ở bước hạ cờ, nên phát hiện muộn đồng nghĩa với hạ cờ
            # theo một con số sai.
            if da_ghi + bi_chan != len(lo):
                raise BusinessRuleViolation(
                    f"Lô {dau // _KICH_THUOC_LO + 1}: gửi {len(lo)} hàng nhưng "
                    f"database báo ghi {da_ghi} + chặn {bi_chan}. Dừng trước "
                    "khi hạ cờ."
                )
            upserted += da_ghi
            blocked += bi_chan

        # ⚠️ ``source_count`` là EFFECTIVE total — số hàng thực sự phải ghi sau
        # khi trừ phần bị chặn tái tạo, KHÔNG phải số hàng nguồn. Truyền
        # ``len(rows)`` khi có dù chỉ một hàng bị chặn sẽ làm guard "chưa ghi
        # hết nguồn" phía database từ chối hạ cờ, và thông điệp lúc đó nói về
        # một sự cố không có thật.
        deactivated = await api.finalize_sync_run(
            run_id,
            source_count=len(rows) - blocked,
            upserted_count=upserted,
            expected_target_fingerprint=claims.target_fingerprint,
        )

    return KetQuaGhi(
        ktx_run_id=run_id,
        upserted=upserted,
        blocked=blocked,
        deactivated=deactivated,
    )


async def record_result(
    db: AsyncSession,
    so_cai: DormSyncOperation,
    *,
    actor_id: int,
    status: str,
    ktx_run_id: Optional[int] = None,
    ket_qua: Optional[KetQuaGhi] = None,
    ly_do: Optional[str] = None,
) -> DormSyncOperation:
    """Đóng sổ + ghi nhật ký kết quả. CHỈ ``flush`` — router commit.

    ⚠️ ``commit`` ở đây sẽ chốt sổ cái độc lập với phần còn lại của request, và
    router mất khả năng gộp hai việc vào một transaction — thứ mà bước 12 dựa
    vào để sổ cái và nhật ký không bao giờ nói hai chuyện khác nhau.
    """
    ghi_nhan: Dict[str, Any] = {"status": status}
    if ket_qua is not None:
        ghi_nhan.update(
            {
                "ktx_run_id": ket_qua.ktx_run_id,
                "upserted": ket_qua.upserted,
                "blocked": ket_qua.blocked,
                "deactivated": ket_qua.deactivated,
            }
        )
    if ly_do:
        ghi_nhan["ly_do"] = ly_do

    so_cai = await cap_nhat_ket_qua(
        db,
        so_cai,
        status=status,
        ktx_run_id=ktx_run_id if ktx_run_id is not None else (
            ket_qua.ktx_run_id if ket_qua is not None else None
        ),
        result=ghi_nhan,
    )

    await log_audit(
        db,
        _ENTITY,
        so_cai.id,
        f"dorm_sync_{status}",
        actor_user_id=actor_id,
        new_value=ghi_nhan,
        source="admin_panel",
    )

    return so_cai
