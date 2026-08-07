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
import asyncio
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
from app.services.activity_service import log_activity
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
from app.utils.exceptions import (
    BusinessRuleViolation,
    DormSyncOpenNotCreatedError,
    DormSyncTokenError,
)

log = structlog.get_logger(__name__)

# Contract đã duyệt ở plan: `activity_service.log_activity`, KHÔNG phải
# `audit_service.log_audit`.
#
# Hai hệ khác nhau: `log_activity` ghi việc NGƯỜI làm (ai bấm, lúc nào),
# `log_audit` ghi việc TRƯỜNG dữ liệu đổi. Lượt đồng bộ là một thao tác của
# người vận hành, và nó phải nằm cùng chỗ với mọi thao tác khác của họ —
# nếu không thì màn hình nhật ký hoạt động im lặng bỏ sót đúng thao tác
# nguy hiểm nhất trong hệ.
_RESOURCE = "dorm_sync_operation"

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
    api_factory: Optional[Callable[..., Any]] = None,
    cohort_loader: Optional[Callable[..., Any]] = None,
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
    # ⚠️ Phân giải phụ thuộc LÚC GỌI, không phải lúc định nghĩa hàm.
    #
    # `def f(loader=fetch_cohort)` chốt tham chiếu ngay khi module được nạp,
    # nên `monkeypatch.setattr(module, "fetch_cohort", ...)` KHÔNG ăn — và một
    # ca kiểm tưởng đang dùng đồ giả lại đi gọi database thật. Đã mất một
    # lượt chạy vì đúng điều này.
    api_factory = api_factory or DormApi
    cohort_loader = cohort_loader or fetch_cohort

    # 1. Giải phiếu. Chữ ký, phiên bản, TTL, actor — xem `doc_token`.
    claims = doc_token(token, secret=secret, actor_id=actor_id, now_ts=now_ts)

    # 2. Tra sổ.
    so_cai = await lay_theo_operation_id(db, claims.operation_id)
    if so_cai is not None:
        return _xet_so_cai_cu(so_cai, claims, actor_id)

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
        return _xet_so_cai_cu(so_cai, claims, actor_id)

    await log_activity(
        db,
        action="dorm_sync_apply_requested",
        resource_type=_RESOURCE,
        actor_id=actor_id,
        resource_id=so_cai.id,
        # Chỉ SỐ ĐẾM và dấu băm. Họ tên, số điện thoại, mã hồ sơ KHÔNG vào
        # nhật ký — nhật ký được gom về nơi khác và giữ lâu hơn ta nghĩ.
        changes={
            "operation_id": str(claims.operation_id),
            "academic_year": claims.academic_year,
            "source_count": len(rows),
            "snapshot_hash": claims.snapshot_hash,
            "snapshot_version": claims.snapshot_version,
        },
    )

    return KetQuaChuanBi(
        trang_thai=TrangThaiChuanBi.SAN_SANG,
        so_cai=so_cai,
        claims=claims,
        rows=rows,
    )


def _kiem_ket_qua_da_luu(so_cai: DormSyncOperation) -> None:
    """Hàng ``completed`` đọc lại phải DÙNG ĐƯỢC. Fail-closed từng bước.

    🔴 ``result`` là JSONB — nó nhận được cả list, cả số, cả một object thiếu
    trường. Bản trước gọi thẳng ``so_cai.result.get(...)`` và một giá trị list
    làm nổ ``AttributeError`` ra khỏi service: người bấm nhận 500 trần cho một
    sự cố có tên rất rõ là "sổ sách hỏng".

    Con số ở đây đi thẳng vào màn hình "đã đồng bộ xong" và vào sổ đối soát,
    nên nhận bừa là đóng dấu xác nhận lên một thứ ta không đọc được.
    """

    def _hong(vi_sao: str) -> BusinessRuleViolation:
        return BusinessRuleViolation(
            f"Sổ cái ghi lượt #{so_cai.id} đã `completed` nhưng {vi_sao}. "
            "Không kết luận được lượt bên hệ ký túc xá đã tới đâu — phải đối "
            "soát bằng tay."
        )

    if so_cai.ktx_run_id is None:
        raise _hong("thiếu `ktx_run_id`")

    ket_qua = so_cai.result
    if not isinstance(ket_qua, dict):
        raise _hong("`result` không phải object")

    if ket_qua.get("status") != "completed":
        raise _hong(f"`result.status` là {ket_qua.get('status')!r}")

    # 🔴 CỘT và JSON phải nói CÙNG một con số.
    #
    # Hai chỗ ghi cùng một sự thật; lệch nghĩa là một trong hai đã bị sửa, và
    # ta không biết cái nào. Người vận hành dùng `ktx_run_id` để lần ra lượt
    # bên kia — trỏ họ tới sai lượt còn tệ hơn không trỏ gì.
    if ket_qua.get("ktx_run_id") != so_cai.ktx_run_id:
        raise _hong(
            f"cột `ktx_run_id` ({so_cai.ktx_run_id}) khác giá trị trong "
            f"`result` ({ket_qua.get('ktx_run_id')})"
        )

    for ten in ("upserted", "blocked", "deactivated"):
        gia_tri = ket_qua.get(ten)
        # `bool` là lớp con của `int` — `True` không phải một số đếm.
        if not isinstance(gia_tri, int) or isinstance(gia_tri, bool) or gia_tri < 0:
            raise _hong(f"`{ten}` không phải số nguyên không âm")


def _rang_so_cai_voi_phieu(
    so_cai: DormSyncOperation, claims: PreviewTokenClaims, actor_id: int
) -> None:
    """Hàng trong sổ phải nói về ĐÚNG lượt mà phiếu này mô tả.

    🔴 ``operation_id`` khớp là chưa đủ. Nó khớp vì ta tra sổ bằng chính nó —
    một phép so vòng tròn. Những thứ CÒN LẠI mới nói cho ta biết hàng ấy có
    thật sự là lượt của phiếu này không: ai bấm, năm nào, và ảnh chụp nào.

    Lệch nghĩa là hoặc khoá ký đã bị dùng ở nơi khác, hoặc sổ cái bị sửa tay.
    Cả hai đều phải dừng — trả ``DA_XONG`` cho một hàng lệch là nói với người
    bấm rằng việc của họ đã xong, trong khi thứ đã chạy là một việc khác.
    """
    lech = []
    if so_cai.actor_id != actor_id:
        lech.append("người bấm")
    if so_cai.academic_year != claims.academic_year:
        lech.append("năm học")
    if so_cai.snapshot_hash != claims.snapshot_hash:
        lech.append("dấu băm ảnh chụp")
    if so_cai.snapshot_version != claims.snapshot_version:
        lech.append("phiên bản ảnh chụp")

    if lech:
        raise BusinessRuleViolation(
            f"Sổ cái ghi lượt #{so_cai.id} không khớp phiếu xem trước "
            f"({', '.join(lech)}). Dừng để không kết luận về một lượt khác."
        )


def _xet_so_cai_cu(
    so_cai: DormSyncOperation, claims: PreviewTokenClaims, actor_id: int
) -> KetQuaChuanBi:
    """Máy trạng thái cho một ``operation_id`` đã có trong sổ.

    MỘT nơi quyết định, dùng cho cả đường thường lẫn đường thua cuộc đua.
    """
    _rang_so_cai_voi_phieu(so_cai, claims, actor_id)

    if so_cai.status == "completed":
        # Idempotent: cùng phiếu, cùng kết quả. Đây là ca mất phản hồi ở lần
        # bấm trước, hoặc người dùng bấm hai lần — cả hai đều bình thường.
        #
        # 🔴 Nhưng phải KIỂM hàng đó có dùng được không. Một hàng `completed`
        # thiếu `ktx_run_id` hoặc thiếu `result` là sổ sách đã hỏng từ trước;
        # trả nó về như "đã xong" là đóng dấu xác nhận lên đúng cái hỏng đó, và
        # người vận hành mất luôn đường lần ra lượt bên kia.
        _kiem_ket_qua_da_luu(so_cai)
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
    elif so_cai.status == "outcome_unknown":
        thong_diep = (
            "Lượt đồng bộ này kết thúc mà KHÔNG rõ hệ ký túc xá đã ghi tới "
            "đâu. Phải đối soát bằng tay trước khi chạy lượt mới."
        )
    else:
        # 🔴 Fail-closed. CHECK constraint phía database chỉ cho bốn giá trị,
        # nên tới đây nghĩa là ràng buộc đã bị gỡ hoặc ai đó sửa tay. Rơi vào
        # một nhánh mặc định "cho chạy" ở đúng chỗ này là chạy một lượt hạ cờ
        # trên một trạng thái không ai định nghĩa.
        raise BusinessRuleViolation(
            f"Sổ cái ghi lượt #{so_cai.id} ở trạng thái không hợp lệ "
            f"({so_cai.status!r}). Dừng để không chạy trên một trạng thái lạ."
        )

    return KetQuaChuanBi(
        trang_thai=TrangThaiChuanBi.KHONG_CHAY_LAI,
        so_cai=so_cai,
        claims=claims,
        thong_diep=thong_diep,
    )


class KetCuc(StrEnum):
    """Ba kết cục của một lượt ghi. Tập ĐÓNG — sổ cái lưu đúng ba giá trị này.

    Chúng khác nhau ở câu hỏi "hệ ký túc xá đang ở đâu":

    * ``COMPLETED`` — biết chắc đã xong;
    * ``FAILED`` — biết chắc đã hỏng VÀ lượt bên kia đã đóng sổ, nên một phiếu
      mới chạy được;
    * ``OUTCOME_UNKNOWN`` — KHÔNG biết. Đây là kết cục tệ nhất và nó phải có
      tên riêng: gộp vào ``FAILED`` là nói dối rằng bên kia đã sạch, rồi lượt
      sau ghi chồng lên một lượt có thể đang sống và đang khoá năm học.
    """

    COMPLETED = "completed"
    FAILED = "failed"
    OUTCOME_UNKNOWN = "outcome_unknown"


@dataclass(frozen=True)
class KetQuaGhi:
    """Kết quả pha ghi. MỘT nguồn duy nhất cho ``ktx_run_id``.

    🔴 ``ktx_run_id`` là ``None`` khi và chỉ khi chưa mở được lượt nào. Mọi kết
    cục khác đều mang nó — không có nó thì không ai đối soát được với hệ ký túc
    xá, mà đối soát chính là việc duy nhất người vận hành làm được khi kết cục
    là ``OUTCOME_UNKNOWN``.
    """

    ket_cuc: "KetCuc"
    ktx_run_id: Optional[int] = None
    upserted: int = 0
    blocked: int = 0
    deactivated: int = 0
    ly_do: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "ket_cuc", KetCuc(self.ket_cuc))
        # 🔴 Từ chối tổ hợp BẤT KHẢ THI ngay lúc dựng.
        #
        # Một hàng `completed` không có `ktx_run_id` sẽ được lần bấm sau đọc ra
        # rồi trả về như "đã xong" — cho một lượt không ai truy được về đâu.
        if self.ket_cuc is KetCuc.COMPLETED and self.ktx_run_id is None:
            raise ValueError(
                "Kết cục `completed` bắt buộc có `ktx_run_id`: thiếu nó thì lần "
                "bấm sau trả 'đã xong' cho một lượt không truy được."
            )
        if self.ket_cuc is not KetCuc.COMPLETED and self.deactivated:
            raise ValueError(
                "Chỉ lượt `completed` mới có số hạ cờ; lượt hỏng hoặc không rõ "
                "kết quả mà khai con số đó là ghi vào sổ một việc chưa chắc đã "
                "xảy ra."
            )


# Trần thời gian cho lần đối soát khi bị HUỶ. Không có nó thì một tác vụ đang
# bị cancel lại đi chờ một lời gọi mạng khác — và người bấm nút Huỷ thấy giao
# diện treo thêm một phút nữa.
_GIAY_DOI_SOAT_KHI_HUY = 10.0


def _doc_so_ha_co(hang: Any, run_id: int) -> Optional[int]:
    """Số hạ cờ từ hàng ``finalized``. ``None`` = KHÔNG đọc được ⇒ fail-closed.

    🔴 KHÔNG ép về 0. Bản trước dùng ``int((hang or {}).get(...) or 0)``, nên
    một phản hồi thiếu trường — hoặc mang hàng của lượt KHÁC — vẫn được ghi
    ``completed`` với ``deactivated=0``. Con số đó đi vào sổ đối soát và vào
    màn hình; bịa ra 0 là khai rằng "không ai bị hạ cờ" cho một lượt mà ta
    không hề đọc được kết quả.

    ⚠️ Kiểm cả ``id``: một phản hồi mang lượt khác mà nhận bừa thì mọi kết luận
    sau đó nói về sai lượt.
    """
    if not isinstance(hang, dict):
        return None
    if hang.get("id") != run_id:
        return None
    if hang.get("status") != "completed":
        return None
    so = hang.get("deactivated_count")
    # `bool` là lớp con của `int` — `True` không phải một số đếm.
    if not isinstance(so, int) or isinstance(so, bool) or so < 0:
        return None
    return so


async def _doi_soat(api: Any, run_id: int, *, gioi_han: Optional[float] = None):
    """Hỏi lại hệ KTX xem lượt thực sự kết thúc ra sao.

    ⚠️ Chính lời gọi đối soát cũng hỏng được — và khi đó câu trả lời đúng là
    "không biết", không phải "hỏng". Tuyên bố an toàn khi không biết là kiểu sai
    tệ hơn cả im lặng.

    ``gioi_han`` chỉ đặt ở đường bị HUỶ: ở đó ta vẫn muốn biết, nhưng không
    được giữ người bấm lại thêm một lời gọi mạng nữa.
    """
    try:
        goi = api.reconcile_after_failure(run_id)
        if gioi_han is not None:
            return await asyncio.wait_for(goi, timeout=gioi_han)
        return await goi
    except (Exception, asyncio.CancelledError):
        return "unknown", None


async def execute_apply(
    *,
    cau_hinh: DormSyncConfig,
    claims: PreviewTokenClaims,
    rows: List[Any],
    api_factory: Optional[Callable[..., Any]] = None,
    api: Optional[Any] = None,
) -> KetQuaGhi:
    """Ghi sang hệ KTX. KHÔNG nhận session database. Trả ``KetQuaGhi`` cho mọi đường.

    🔴 Không có tham số ``db`` là một ràng buộc, không phải thiếu sót. Lượt này
    mất vài chục giây; ôm một transaction suốt thời gian đó là giữ khoá trên sổ
    cái trong lúc chờ mạng.

    🔴 Bao TRỌN vòng đời context manager. Bản trước đặt ``try`` BÊN TRONG
    ``async with``, nên một lỗi ở ``__aenter__``/``__aexit__`` đi vòng qua toàn
    bộ hàng rào. Ca tệ nhất đã đo được: ``finalize`` thành công rồi việc đóng
    client hỏng — hệ KTX đã đổi thật, mà người gọi không nhận được ``KetQuaGhi``
    nào để đóng sổ. Nay kết quả được tính XONG rồi mới đóng client, và lỗi lúc
    đóng không xoá được kết quả ấy.

    🔴 KHÔNG bắt ``BaseException``. ``KeyboardInterrupt`` và ``SystemExit`` là
    yêu cầu dừng tiến trình, nuốt chúng là biến Ctrl-C thành một lượt vẫn chạy
    tiếp. ``asyncio.CancelledError`` thì xử TƯỜNG MINH: nó xảy ra khi client
    ngắt kết nối giữa chừng, và đúng lúc đó ta VẪN phải biết bên kia ra sao —
    nhưng chỉ được chờ có giới hạn.
    """
    run_id: Optional[int] = None
    upserted = 0
    blocked = 0
    da_mo_client = False

    # 🔴 PHA MỞ, có hàng rào riêng.
    #
    # `DormApi.__init__` chạy hai guard (đường truyền, project ref) và
    # `__aenter__` chỉ dựng `httpx.AsyncClient` — chưa gửi byte nào sang hệ KTX.
    # Hỏng ở đây là CHẮC CHẮN chưa tạo lượt nào, nên kết cục đúng là `FAILED`.
    #
    # Bản trước để chúng bay thẳng ra vì khối `try` bao ngoài chỉ có `finally`,
    # không có `except`. Sau khi commit A đã ghi `running`, router không nhận
    # được `KetQuaGhi` nào, sổ cái nằm lại `running`, và mọi lần bấm sau với
    # cùng phiếu bị chặn vĩnh viễn.
    try:
        if api is None:
            # Phân giải lúc gọi — xem chú thích cùng chủ đề ở `prepare_apply`.
            api = (api_factory or DormApi)(
                cau_hinh.supabase_url,
                cau_hinh.supabase_secret_key,
                expected_project_ref=cau_hinh.target_project_ref,
            )
        await api.__aenter__()
        da_mo_client = True
    except (Exception, asyncio.CancelledError) as loi:
        log.warning("dorm_sync_apply_client_open_failed", loi=type(loi).__name__)
        return KetQuaGhi(ket_cuc=KetCuc.FAILED, ly_do=str(loi))

    try:
        try:
            ket_qua_mo = await api.open_sync_run(
                claims.academic_year,
                str(claims.operation_id),
                raw_count=len(rows),
            )
            run_id = ket_qua_mo.run_id

            # MỘT mốc thời gian cho cả lượt: mọi hàng phải mang cùng
            # ``synced_at``, nếu không thì "đồng bộ lần cuối lúc nào" trở thành
            # một dải giờ trải theo tốc độ chạy của từng lô.
            synced_at = datetime.now(timezone.utc).isoformat()

            for dau in range(0, len(rows), _KICH_THUOC_LO):
                lo = rows[dau : dau + _KICH_THUOC_LO]
                da_ghi, bi_chan = await api.upsert_students(
                    run_id,
                    [build_student_payload(r, run_id, synced_at) for r in lo],
                )
                # ⚠️ Đối soát TỪNG LÔ. Lệch nghĩa là RPC bỏ sót hàng trong im
                # lặng — và hai con số này đi thẳng vào phép kiểm
                # `raw = source + blocked` ở bước hạ cờ.
                if da_ghi + bi_chan != len(lo):
                    raise BusinessRuleViolation(
                        f"Lô {dau // _KICH_THUOC_LO + 1}: gửi {len(lo)} hàng "
                        f"nhưng database báo ghi {da_ghi} + chặn {bi_chan}. "
                        "Dừng trước khi hạ cờ."
                    )
                upserted += da_ghi
                blocked += bi_chan

            # ⚠️ ``source_count`` là EFFECTIVE total — nguồn trừ phần bị chặn.
            deactivated = await api.finalize_sync_run(
                run_id,
                source_count=len(rows) - blocked,
                upserted_count=upserted,
                expected_target_fingerprint=claims.target_fingerprint,
            )

            ket_qua = KetQuaGhi(
                ket_cuc=KetCuc.COMPLETED,
                ktx_run_id=run_id,
                upserted=upserted,
                blocked=blocked,
                deactivated=deactivated,
            )

        except asyncio.CancelledError as loi:
            # Client ngắt giữa chừng. Vẫn phải biết bên kia ra sao — nhưng chỉ
            # chờ có giới hạn: một tác vụ đang bị huỷ mà đi chờ tiếp một lời
            # gọi mạng là giữ người bấm lại thêm một phút nữa.
            ket_qua = await _ket_luan_sau_loi(
                api, run_id, upserted, blocked, loi, gioi_han=_GIAY_DOI_SOAT_KHI_HUY
            )

        except Exception as loi:
            ket_qua = await _ket_luan_sau_loi(api, run_id, upserted, blocked, loi)

    finally:
        if da_mo_client:
            # 🔴 Lỗi ĐÓNG client không được xoá kết quả đã tính.
            #
            # Tới đây hệ KTX đã đổi thật (hoặc đã được đối soát). Một
            # `close failed` là chuyện của socket phía ta; để nó bay ra ngoài
            # là làm router mất `KetQuaGhi` và bỏ sổ cái ở `running`.
            #
            # ⚠️ Bắt CẢ `asyncio.CancelledError`. Nó KHÔNG phải `Exception`, và
            # một lần huỷ rơi đúng vào lúc đóng socket — sau khi `finalize` đã
            # thành công — sẽ xoá sạch kết quả `completed` vừa tính xong.
            # `KeyboardInterrupt`/`SystemExit` vẫn đi tiếp: đó là yêu cầu dừng
            # tiến trình, không phải một sự cố mạng.
            try:
                await api.__aexit__(None, None, None)
            except (Exception, asyncio.CancelledError):
                log.warning("dorm_sync_apply_close_failed", run_id=run_id)

    return ket_qua


async def _ket_luan_sau_loi(
    api: Any,
    run_id: Optional[int],
    upserted: int,
    blocked: int,
    loi: BaseException,
    *,
    gioi_han: Optional[float] = None,
) -> KetQuaGhi:
    """Phân loại một lần chạy hỏng bằng ĐỐI SOÁT, không bằng chuỗi lỗi."""
    if run_id is None:
        # 🔴 Chưa có `run_id` KHÔNG đồng nghĩa "chưa mở được lượt".
        #
        # `open_sync_run` phân biệt hai ca bằng KIỂU: `DormSyncOpenAbsentError`
        # là đã đối soát và biết chắc bên kia sạch; mọi thứ khác — kể cả
        # `DormSyncOpenUnknownError` — nghĩa là một hàng `running` CÓ THỂ đang
        # nằm bên kia và khoá cứng năm học đó.
        #
        # Bản trước gộp cả hai thành `failed`. Đo được: mất ACK lúc POST cộng
        # với lần GET đối soát cũng hỏng ⇒ ghi `failed` cho một lượt có thể
        # đang sống.
        if isinstance(loi, DormSyncOpenNotCreatedError):
            log.warning("dorm_sync_apply_failed_before_open")
            return KetQuaGhi(ket_cuc=KetCuc.FAILED, ly_do=str(loi))

        log.error("dorm_sync_apply_open_outcome_unknown")
        return KetQuaGhi(ket_cuc=KetCuc.OUTCOME_UNKNOWN, ly_do=str(loi))

    outcome, hang = await _doi_soat(api, run_id, gioi_han=gioi_han)

    if outcome == "finalized":
        so_ha_co = _doc_so_ha_co(hang, run_id)
        if so_ha_co is None:
            # Nói "đã xong" mà không đọc nổi kết quả là đóng dấu xác nhận lên
            # một thứ ta không nhìn thấy.
            log.error("dorm_sync_apply_finalized_row_unreadable", run_id=run_id)
            return KetQuaGhi(
                ket_cuc=KetCuc.OUTCOME_UNKNOWN,
                ktx_run_id=run_id,
                upserted=upserted,
                blocked=blocked,
                ly_do=(
                    "Đối soát báo lượt đã đóng sổ nhưng hàng trả về không đọc "
                    "được số liệu."
                ),
            )
        log.info("dorm_sync_apply_completed_despite_client_error", run_id=run_id)
        return KetQuaGhi(
            ket_cuc=KetCuc.COMPLETED,
            ktx_run_id=run_id,
            upserted=upserted,
            blocked=blocked,
            deactivated=so_ha_co,
        )

    if outcome == "marked_failed":
        return KetQuaGhi(
            ket_cuc=KetCuc.FAILED,
            ktx_run_id=run_id,
            upserted=upserted,
            blocked=blocked,
            ly_do=str(loi),
        )

    log.error("dorm_sync_apply_outcome_unknown", run_id=run_id)
    return KetQuaGhi(
        ket_cuc=KetCuc.OUTCOME_UNKNOWN,
        ktx_run_id=run_id,
        upserted=upserted,
        blocked=blocked,
        ly_do=str(loi),
    )


async def record_result(
    db: AsyncSession,
    so_cai: DormSyncOperation,
    *,
    actor_id: int,
    ket_qua: KetQuaGhi,
) -> DormSyncOperation:
    """Đóng sổ + ghi nhật ký. CHỈ ``flush`` — router commit.

    🔴 Nhận ĐÚNG MỘT ``KetQuaGhi``, không nhận rời ``status`` + ``ktx_run_id`` +
    ``ket_qua``. Bản trước nhận cả ba và không kiểm quan hệ giữa chúng — đo
    được: sổ ghi ``ktx_run_id=99`` trong khi JSON kết quả ghi ``42``, và
    ``completed`` được nhận với ``ktx_run_id=None``. Hàng hỏng ấy sau đó được
    lần bấm sau đọc ra như một kết quả hoàn tất.

    Một tham số ⇒ không có hai nguồn để lệch nhau.

    ⚠️ ``commit`` ở đây sẽ chốt sổ cái độc lập với phần còn lại của request, và
    router mất khả năng gộp hai việc vào một transaction.
    """
    ghi_nhan: Dict[str, Any] = {
        "status": str(ket_qua.ket_cuc),
        "ktx_run_id": ket_qua.ktx_run_id,
        "upserted": ket_qua.upserted,
        "blocked": ket_qua.blocked,
        "deactivated": ket_qua.deactivated,
    }
    if ket_qua.ly_do:
        ghi_nhan["ly_do"] = ket_qua.ly_do

    so_cai = await cap_nhat_ket_qua(
        db,
        so_cai,
        status=str(ket_qua.ket_cuc),
        # MỘT nguồn: chính `ket_qua`. Không có tham số thứ hai để lệch.
        ktx_run_id=ket_qua.ktx_run_id,
        result=ghi_nhan,
    )

    await log_activity(
        db,
        action=f"dorm_sync_apply_{ket_qua.ket_cuc}",
        resource_type=_RESOURCE,
        actor_id=actor_id,
        resource_id=so_cai.id,
        changes=ghi_nhan,
    )

    return so_cai
