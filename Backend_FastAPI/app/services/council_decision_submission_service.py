# app/services/council_decision_submission_service.py
"""Lượt gửi ghi nhận Quyết định — vòng giao diện GĐ1 (đặc tả bản 2 mục 3.7; bản 3 mục 3.7.2, 3.7.6).

Mục đích: mất mạng khi gửi ghi nhận KHÔNG gây ghi đôi và KHÔNG báo sai "chưa ghi". Mã lượt (uuid, không dữ liệu cá
nhân) do máy chủ cấp; trình duyệt không lưu (khôi phục qua id bộ).

Vòng đời (chỉ đổi khi commit; mỗi chuyển là MỘT câu đặt đủ cột — F265):

* mở lượt ⇒ ``cho_gui``;
* ghi nhận: câu CSDL ĐẦU TIÊN khoá lượt ``cho_gui`` (:func:`khoa_luot_cho_gui`, ``FOR UPDATE``, GIỮ ``cho_gui``) —
  ĐẦU thứ tự khoá chung (lượt → văn bản → mục chờ → bộ → hồ sơ → học vụ → đường xét); câu CUỐI trước commit
  :func:`chot_da_ghi` đặt ``da_ghi`` + ``decision_id`` + sha + ``ket_thuc_luc``. Bị từ chối / lỗi ⇒ rollback ⇒ vẫn
  ``cho_gui`` (gửi lại cùng mã được — sha chỉ chốt khi thành công);
* phân xử (:func:`phan_xu`): ``UPDATE … WHERE trang_thai = 'cho_gui'`` dưới ``lock_timeout`` ⇒ ``da_chan`` / đọc lại
  (``da_ghi`` ⇒ trả văn bản; ``da_chan`` ⇒ lặp luỹ đẳng) / hết hạn ⇒ :class:`LuotDangXuLy` (router ROLLBACK trước khi
  trả "đang xử lý").

F272: nhánh "0 dòng" của ghi nhận và của phân xử CHỈ ĐỌC (không ``FOR UPDATE`` / ``FOR SHARE``, không ghi, không khoá
bộ / văn bản) và kết thúc giao dịch ngay — câu ``FOR UPDATE`` / ``UPDATE`` ở READ COMMITTED có thể đã khoá phiên bản
mới nhất của một lượt đã kết thúc rồi mới thấy nó không còn ``cho_gui`` (giữ khoá tới hết giao dịch); xoá bộ (dây chuyền
``SET NULL``) có thể phải CHỜ khoá ấy, nhưng không có cạnh chờ ngược.
"""
import hashlib
import json
import uuid
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.council_document import CouncilDecisionSubmission
from app.repositories.council_decision_repository import ma_loi_csdl
from app.utils.exceptions import ConflictError, ResourceNotFoundError, ServiceError

#: Tên chỉ mục duy nhất một phần "mỗi bộ tối đa một lượt chưa rõ".
CHI_MUC_MOT_CHO_GUI = "uq_council_decision_submission_cho_gui"
#: Trần chờ khoá của phân xử (đặc tả 3.7.4).
TRAN_CHO_PHAN_XU = "5s"
#: Số lần thử mở lượt khi lượt cũ vừa kết thúc giữa câu chèn và câu đọc (bản 3 mục 3.7.2).
SO_LAN_THU_MO = 3

CHUA_GHI_DA_CHAN = "chua_ghi_da_chan"
DA_GHI = "da_ghi"
DANG_XU_LY = "dang_xu_ly"


class LuotDangXuLy(Exception):
    """Phân xử hết ``lock_timeout`` (55P03): giao dịch ghi nhận đang giữ lượt. Router PHẢI rollback rồi trả
    ``dang_xu_ly`` — không kết luận gì."""


def kiem_ma_luot(ma: object) -> uuid.UUID:
    try:
        return uuid.UUID(str(ma))
    except (ValueError, TypeError, AttributeError):
        raise ConflictError(
            "Mã lượt gửi không hợp lệ.", public_payload={"ma_loi": "luot_khong_hop_le"}
        ) from None


def sha_noi_dung_gui(
    *,
    set_id: int,
    loai: str,
    goc_id: Optional[int],
    so_quyet_dinh: str,
    ngay_ky: date,
    tham_so_giay: Optional[Dict[str, Any]],
    xac_nhan_so_ho_so: object,
    xac_nhan_khop_ban_in: object,
    xac_nhan_trang_thai: Optional[Dict[str, int]],
    ghi_chu_mau: Optional[str],
    sha_scan: str,
) -> str:
    """sha256 của dạng JSON CHUẨN (khoá sắp xếp, không khoảng trắng) mọi thứ đã gửi trong một lần ghi nhận — gồm sha
    của tệp scan (không phải bytes). Cùng mã + cùng sha ⇒ gửi lặp (trả lại bản cũ); khác sha ⇒ 409."""
    ts = {
        k: (v.isoformat() if isinstance(v, date) else v)
        for k, v in sorted((tham_so_giay or {}).items())
    }
    goi = {
        "set_id": set_id,
        "loai": loai,
        "goc_id": goc_id,
        "so_quyet_dinh": so_quyet_dinh,
        "ngay_ky": ngay_ky.isoformat(),
        "tham_so_giay": ts,
        "xac_nhan_so_ho_so": xac_nhan_so_ho_so,
        "xac_nhan_khop_ban_in": xac_nhan_khop_ban_in,
        "xac_nhan_trang_thai": dict(sorted((xac_nhan_trang_thai or {}).items())),
        "ghi_chu_mau": ghi_chu_mau,
        "sha_scan": sha_scan,
    }
    return hashlib.sha256(
        json.dumps(goi, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


async def _luot_cho_gui_cua_bo(db: AsyncSession, set_id: int) -> Optional[CouncilDecisionSubmission]:
    return (
        await db.execute(
            select(CouncilDecisionSubmission).where(
                CouncilDecisionSubmission.set_id == set_id,
                CouncilDecisionSubmission.trang_thai == "cho_gui",
            )
        )
    ).scalar_one_or_none()


async def mo_luot(db: AsyncSession, *, set_id: int, nguoi_id: int) -> CouncilDecisionSubmission:
    """Mở MỘT lượt ``cho_gui`` cho bộ (flush; router commit rồi mới trả mã). Bộ đang có lượt chưa rõ ⇒ 409
    ``luot_dang_cho`` kèm mã cũ. Lượt cũ vừa kết thúc giữa câu chèn và câu đọc ⇒ thử lại (tối đa
    :data:`SO_LAN_THU_MO` lần) rồi 409 ``luot_dang_thay_doi`` không mã. Bộ không còn (khoá ngoại) ⇒ 404."""
    for _ in range(SO_LAN_THU_MO):
        luot = CouncilDecisionSubmission(
            ma=uuid.uuid4(),
            set_id=set_id,
            set_id_luc_tao=set_id,
            trang_thai="cho_gui",
            nguoi_tao_id=nguoi_id,
        )
        try:
            async with db.begin_nested():
                db.add(luot)
                await db.flush()
            return luot
        except IntegrityError as e:
            sqlstate, rang_buoc = ma_loi_csdl(e)
            if sqlstate == "23503":
                raise ResourceNotFoundError("Không có bộ văn bản này.") from None
            if sqlstate != "23505" or rang_buoc != CHI_MUC_MOT_CHO_GUI:
                raise ServiceError("Lỗi CSDL khi mở lượt gửi ghi nhận — không mở.") from None
        cu = await _luot_cho_gui_cua_bo(db, set_id)
        if cu is not None:
            raise ConflictError(
                "Bộ đang có lượt gửi ghi nhận chưa rõ kết quả — bấm \"Kiểm tra trên máy chủ\" trước.",
                public_payload={
                    "ma_loi": "luot_dang_cho",
                    "ma": str(cu.ma),
                    "tao_luc": cu.tao_luc.isoformat() if cu.tao_luc else None,
                },
            )
    raise ConflictError(
        "Lượt gửi trước của bộ vừa thay đổi — tải lại trạng thái bộ rồi thử lại.",
        public_payload={"ma_loi": "luot_dang_thay_doi", "ma": None},
    )


async def khoa_luot_cho_gui(
    db: AsyncSession, *, ma: uuid.UUID, set_id: int
) -> Optional[CouncilDecisionSubmission]:
    """Câu CSDL ĐẦU TIÊN của ghi nhận: khoá lượt ``cho_gui`` của đúng bộ, GIỮ ``cho_gui`` (F265). Lượt đang bị giao
    dịch ghi khác giữ ⇒ CHỜ; sau commit PostgreSQL đánh giá lại ``trang_thai = 'cho_gui'`` trên bản mới ⇒ None."""
    return (
        await db.execute(
            select(CouncilDecisionSubmission)
            .where(
                CouncilDecisionSubmission.ma == ma,
                CouncilDecisionSubmission.set_id == set_id,
                CouncilDecisionSubmission.trang_thai == "cho_gui",
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def doc_luot(db: AsyncSession, ma: uuid.UUID) -> Optional[CouncilDecisionSubmission]:
    """Đọc KHÔNG khoá (ảnh chụp mới của câu này ở READ COMMITTED) — dùng ở các nhánh "0 dòng" (F272: chỉ đọc)."""
    return (
        await db.execute(
            select(CouncilDecisionSubmission)
            .where(CouncilDecisionSubmission.ma == ma)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


def kiem_luot_da_ket_thuc(cu: Optional[CouncilDecisionSubmission], *, set_id: int, sha: str) -> Optional[int]:
    """Nhánh "0 dòng" của ghi nhận (chỉ đọc). Trả ``decision_id`` khi đây là gửi LẶP đúng nội dung của lượt ``da_ghi``
    (router trả lại văn bản cũ, 200); mọi trường hợp khác ⇒ 409 với mã lỗi riêng."""
    if cu is None or cu.set_id_luc_tao != set_id:
        raise ConflictError(
            "Mã lượt gửi không thuộc bộ này — tải lại trạng thái bộ.",
            public_payload={"ma_loi": "luot_khong_hop_le"},
        )
    if cu.trang_thai == "da_chan":
        raise ConflictError(
            "Lượt gửi này đã bị chặn (chưa ghi) — mở lượt gửi mới.",
            public_payload={"ma_loi": "luot_da_chan"},
        )
    if cu.trang_thai == "da_ghi":
        if cu.noi_dung_sha != sha:
            raise ConflictError(
                "Lượt gửi này ĐÃ ghi nhận với nội dung khác — không ghi lần hai.",
                public_payload={"ma_loi": "luot_da_dung_noi_dung_khac", "decision_id": cu.decision_id},
            )
        return cu.decision_id
    raise ServiceError("Trạng thái lượt gửi không xác định — không ghi.")


async def chot_da_ghi(db: AsyncSession, *, luot_id: int, decision_id: int, sha: str) -> None:
    """Câu CUỐI trước commit: MỘT câu đặt đủ ``trang_thai`` + ``decision_id`` + ``noi_dung_sha`` + ``ket_thuc_luc``
    (CHECK kiểm theo câu). Số dòng ≠ 1 ⇒ lỗi (không thể khi đang giữ khoá — chốt fail-closed)."""
    r = await db.execute(
        update(CouncilDecisionSubmission)
        .where(CouncilDecisionSubmission.id == luot_id, CouncilDecisionSubmission.trang_thai == "cho_gui")
        .values(
            trang_thai="da_ghi",
            decision_id=decision_id,
            noi_dung_sha=sha,
            ket_thuc_luc=text("now()"),
        )
        .execution_options(synchronize_session=False)
    )
    if r.rowcount != 1:
        raise ServiceError("Không chốt được lượt gửi ghi nhận — không ghi.")


async def phan_xu(db: AsyncSession, ma: uuid.UUID) -> Tuple[str, Optional[int]]:
    """Phân xử lượt chưa rõ (đặc tả 3.7.4). Trả ``(kết quả, decision_id)``:

    * cập nhật được ⇒ ``(chua_ghi_da_chan, None)`` — router COMMIT rồi mới trả;
    * 0 dòng ⇒ đọc lại: ``da_ghi`` ⇒ ``(da_ghi, id)``; ``da_chan`` ⇒ ``(chua_ghi_da_chan, None)`` (lặp luỹ đẳng);
      không có ⇒ 404;
    * hết ``lock_timeout`` (55P03) ⇒ :class:`LuotDangXuLy` (giao dịch đã hỏng — router ROLLBACK).

    Không nhánh nào suy "chưa ghi" từ 404."""
    await db.execute(text("SET LOCAL lock_timeout = '%s'" % TRAN_CHO_PHAN_XU))
    try:
        r = await db.execute(
            update(CouncilDecisionSubmission)
            .where(CouncilDecisionSubmission.ma == ma, CouncilDecisionSubmission.trang_thai == "cho_gui")
            .values(trang_thai="da_chan", ket_thuc_luc=text("now()"))
            .returning(CouncilDecisionSubmission.id)
            .execution_options(synchronize_session=False)
        )
        da_chan = r.first() is not None
    except DBAPIError as e:
        if ma_loi_csdl(e)[0] == "55P03":
            raise LuotDangXuLy() from None
        raise
    if da_chan:
        return CHUA_GHI_DA_CHAN, None
    cu = await doc_luot(db, ma)
    if cu is None:
        raise ResourceNotFoundError("Không có lượt gửi này.")
    if cu.trang_thai == "da_chan":
        return CHUA_GHI_DA_CHAN, None
    if cu.trang_thai == "da_ghi":
        return DA_GHI, cu.decision_id
    raise ServiceError("Trạng thái lượt gửi không xác định.")


async def luot_cua_bo(db: AsyncSession, set_id: int) -> List[CouncilDecisionSubmission]:
    return list(
        (
            await db.execute(
                select(CouncilDecisionSubmission)
                .where(CouncilDecisionSubmission.set_id == set_id)
                .order_by(CouncilDecisionSubmission.id)
            )
        ).scalars()
    )


async def co_luot_cho_gui(db: AsyncSession, set_id: int) -> Optional[CouncilDecisionSubmission]:
    """Đọc KHÔNG khoá — dùng ở xoá bộ (đã khoá bộ trước): không chờ dòng lượt nào (F272)."""
    return await _luot_cho_gui_cua_bo(db, set_id)
