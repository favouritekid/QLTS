# app/services/council_decision_status_service.py
"""MỘT nguồn cho câu hỏi "hồ sơ có Quyết định đã ký không" (F230 — lượt I; đặc tả mục 5.4, 8.2).

Module NHẸ: chỉ model + SQLAlchemy, KHÔNG import ``admission_service`` (vòng import đã buộc bộ máy
nguyện vọng chép tay tập trạng thái — ``admission_choice_engine_service.py`` khối
``_QUOTA_OCCUPYING_STATUSES``). Gọi được từ chốt chuyển trạng thái (``admission_state_service``), bộ
máy nguyện vọng, ``admission_service``, service văn bản Hội đồng.

Tình trạng của MỘT hồ sơ (đọc dữ liệu, KHÔNG suy từ trạng thái hồ sơ) — loại trừ nhau theo thứ tự:

* ``HL`` — có dòng Quyết định còn hiệu lực (``DIEU_KIEN_DONG_HIEU_LUC``);
* ``CQ`` — không HL, có mục "chờ Admin quyết" đang mở (owner C7);
* ``XL`` — không HL / CQ, đã được Admin cho xét lại;
* ``KO`` — còn lại.

Độc lập: ``dau_appsheet`` (dấu "Đã trúng tuyển theo QĐ số …" — ``SQL_DAU_APPSHEET``) và
``co_ten_van_ban`` (có tên trong văn bản chưa huỷ ghi nhận — ĐÚNG điều kiện K5a).

Luật (owner): đích ``draft`` / ``rejected`` / ``withdrawal_pending`` / ``withdrawn`` bị CHẶN khi HL
hoặc dấu AppSheet (C4, C5, J1 dòng 12, E1) — trừ cạnh ``withdrawal_pending → withdrawn`` (chốt rút khi
hoàn xong — C3 "trừ khỏi số đã dùng khi rút xong hẳn"). Lần xét mới (dựng bộ, ghi nhận, công bố theo
nguyện vọng) bị CHẶN khi HL / CQ / dấu AppSheet (N10, C7, N11, N13, E1).

Tầng chủ sở hữu luật trạng thái: :func:`kiem_chuyen_trang_thai`, gọi TỪ ``transition`` — chỗ ghi
``profile.status`` DUY NHẤT (``admission_state_service.py``; lint ``check_status_assignment``).
"""
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.council_document import SQL_COT_TINH_TRANG_QD
from app.services.council_set_gate_service import ly_do_tinh_trang_qd
from app.utils.exceptions import QuyetDinhKhoaHoSo

HL = "co_qd_hieu_luc"
CQ = "cho_admin_quyet"
XL = "da_cho_xet_lai"
KO = "chua_co_qd"

#: Đích chuyển trạng thái bị chặn khi hồ sơ có Quyết định hiệu lực / dấu AppSheet.
DICH_BI_KHOA = frozenset({"draft", "rejected", "withdrawal_pending", "withdrawn"})
#: Cạnh được miễn: chốt rút khi hoàn tiền xong (``payment_service`` → ``_finalize_withdrawn``).
CANH_MIEN = frozenset({("withdrawal_pending", "withdrawn")})


@dataclass(frozen=True)
class TinhTrangQd:
    ma: str
    qd_hieu_luc_id: Optional[int] = None
    qd_chuoi_id: Optional[int] = None
    cho_quyet_id: Optional[int] = None
    co_ten_van_ban: bool = False
    dau_appsheet: bool = False

    @property
    def khoa_trang_thai(self) -> bool:
        """Rút / về Nháp / Từ chối bị chặn (C4, C5, J1 dòng 12, E1)."""
        return self.ma == HL or self.dau_appsheet

    @property
    def chan_xet_moi(self) -> bool:
        """Không vào bộ văn bản / Quyết định / lần xét mới (N10, C7, N11, N13, E1) — ĐÚNG luật của cổng
        dựng bộ (:func:`ly_do_tinh_trang_qd`, một nguồn — CLAUDE.md §7), không nới chuỗi nào."""
        return bool(ly_do_tinh_trang_qd(self))

    def payload(self) -> Dict[str, Any]:
        """Phần đi ra client — mã + id văn bản / mục chờ (không dữ liệu cá nhân)."""
        return {
            "tinh_trang_qd": self.ma,
            "quyet_dinh_id": self.qd_hieu_luc_id,
            "muc_cho_id": self.cho_quyet_id,
            "dau_appsheet": self.dau_appsheet,
        }


KHONG_CO = TinhTrangQd(KO)


def tu_hang(h: Any) -> TinhTrangQd:
    """Dựng tình trạng từ một hàng có ĐỦ các cột của ``SQL_COT_TINH_TRANG_QD`` (dùng chung cho hàm hỏi
    và cổng dựng bộ — hai nơi đọc cùng chuỗi SQL)."""
    hl = h["qd_hieu_luc_id"]
    cq = h["cho_quyet_id"]
    if hl is not None:
        ma = HL
    elif cq is not None:
        ma = CQ
    elif h["da_cho_xet_lai"]:
        ma = XL
    else:
        ma = KO
    return TinhTrangQd(
        ma=ma,
        qd_hieu_luc_id=hl,
        qd_chuoi_id=h["qd_chuoi_id"],
        cho_quyet_id=cq,
        co_ten_van_ban=bool(h["co_ten_van_ban"]),
        dau_appsheet=bool(h["dau_appsheet"]),
    )


SQL_TINH_TRANG = text(
    "SELECT p.id AS pid, "
    + SQL_COT_TINH_TRANG_QD
    + " FROM admission_profile p WHERE p.id = ANY(CAST(:ids AS integer[]))"
)


async def khoa_ho_so(db: AsyncSession, profile_ids: Iterable[int]) -> None:
    """``FOR UPDATE`` các hồ sơ theo id TĂNG DẦN trong MỘT câu (thứ tự khoá chung — BS §4.6)."""
    ids = sorted({int(x) for x in profile_ids})
    if ids:
        await db.execute(
            text(
                "SELECT id FROM admission_profile WHERE id = ANY(CAST(:ids AS integer[])) "
                "ORDER BY id FOR UPDATE"
            ),
            {"ids": ids},
        )


async def tinh_trang_qd(
    db: AsyncSession, profile_ids: Iterable[int], *, khoa: bool = False
) -> Dict[int, TinhTrangQd]:
    """{id hồ sơ: tình trạng}. ``khoa`` ⇒ khoá hồ sơ TRƯỚC khi đọc (tuần tự hoá với ghi nhận — vốn
    khoá hồ sơ trước khi chèn dòng). Hồ sơ không tồn tại ⇒ không có trong kết quả."""
    ids = sorted({int(x) for x in profile_ids})
    if not ids:
        return {}
    if khoa:
        await khoa_ho_so(db, ids)
    hang = (await db.execute(SQL_TINH_TRANG, {"ids": ids})).mappings().all()
    return {h["pid"]: tu_hang(h) for h in hang}


async def mot_ho_so(db: AsyncSession, profile_id: int, *, khoa: bool = False) -> TinhTrangQd:
    return (await tinh_trang_qd(db, [profile_id], khoa=khoa)).get(int(profile_id), KHONG_CO)


def _chan(tt: TinhTrangQd, cau: str, viec: str) -> QuyetDinhKhoaHoSo:
    return QuyetDinhKhoaHoSo(
        cau,
        public_payload={**tt.payload(), "thao_tac": viec},
    )


async def kiem_chuyen_trang_thai(
    db: AsyncSession, profile_id: int, tu: Optional[str], den: str
) -> None:
    """CHỐT chuyển trạng thái (tầng chủ sở hữu — gọi từ ``transition``): đích bị khoá + hồ sơ HL / dấu
    AppSheet ⇒ :class:`QuyetDinhKhoaHoSo`. Khoá hồ sơ ``FOR UPDATE`` trước khi đọc."""
    if den not in DICH_BI_KHOA or (tu, den) in CANH_MIEN:
        return
    tt = await mot_ho_so(db, profile_id, khoa=True)
    if tt.khoa_trang_thai:
        raise _chan(
            tt,
            "Hồ sơ đã có tên trong Quyết định đã ký (hoặc mang dấu đã trúng tuyển theo Quyết định "
            "cũ) — không chuyển sang '%s'. Muốn đổi, ghi nhận văn bản điều chỉnh / huỷ trước." % den,
            "chuyen_trang_thai",
        )


async def kiem_som_khoa_trang_thai(
    db: AsyncSession, profile_id: int, viec: str
) -> None:
    """Lớp kiểm SỚM (trước mọi việc khác của hàm rút / huỷ rút / trả về Nháp / tạo link rút) — cùng
    luật với :func:`kiem_chuyen_trang_thai`, báo lỗi trước khi tự lập yêu cầu hoàn / từ chối yêu cầu
    hoàn. Tầng chủ sở hữu vẫn là chốt chuyển trạng thái."""
    tt = await mot_ho_so(db, profile_id, khoa=True)
    if tt.khoa_trang_thai:
        raise _chan(
            tt,
            "Hồ sơ đã có tên trong Quyết định đã ký (hoặc mang dấu đã trúng tuyển theo Quyết định "
            "cũ) — tạm chặn thao tác này trên phần mềm. Cần hoàn tiền ngay thì kế toán lập yêu cầu "
            "hoàn bằng chức năng đang có.",
            viec,
        )


async def kiem_xet_moi(db: AsyncSession, profile_id: int, viec: str) -> None:
    """Công bố theo nguyện vọng (một lần xét) — chặn HL / CQ / dấu AppSheet (N11, C7, E1)."""
    tt = await mot_ho_so(db, profile_id, khoa=True)
    if tt.chan_xet_moi:
        raise _chan(
            tt,
            "Hồ sơ đã có tên trong Quyết định đã ký, đang chờ Admin quyết sau khi Quyết định bị huỷ, "
            "hoặc mang dấu đã trúng tuyển theo Quyết định cũ — không công bố theo nguyện vọng.",
            viec,
        )


async def gan_tinh_trang_qd(db: AsyncSession, profiles: Sequence[Any]) -> None:
    """Gán thuộc tính TẠM ``_tinh_trang_qd`` cho các hồ sơ (một lần đọc gộp) — để hàm tính cờ giao
    diện (đồng bộ) đọc. Cờ là lớp phụ; tầng chủ sở hữu là service."""
    ids = [getattr(p, "id", None) for p in profiles]
    tt = await tinh_trang_qd(db, [i for i in ids if isinstance(i, int)])
    for p in profiles:
        try:
            p._tinh_trang_qd = tt.get(getattr(p, "id", None), KHONG_CO)
        except AttributeError:  # đối tượng không gán được thuộc tính (không xảy ra với ORM)
            pass


def doc_tinh_trang(profile: Any) -> TinhTrangQd:
    """Đọc thuộc tính tạm; chưa gán ⇒ KHONG_CO (như khuôn ``_outstanding_debt_codes``)."""
    tt = getattr(profile, "_tinh_trang_qd", None)
    return tt if isinstance(tt, TinhTrangQd) else KHONG_CO
