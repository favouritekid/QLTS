# app/services/council_decision_status_service.py
"""MỘT nguồn cho câu hỏi "hồ sơ có Quyết định đã ký không" (F230 — lượt I; đặc tả mục 5.4, 8.2).

Module NHẸ: chỉ model + SQLAlchemy, KHÔNG import ``admission_service`` (vòng import đã buộc bộ máy
nguyện vọng chép tay tập trạng thái — ``admission_choice_engine_service.py`` khối
``_QUOTA_OCCUPYING_STATUSES`` — chặng 2b gộp về ``quota_occupancy_service``). Gọi được từ chốt chuyển trạng thái (``admission_state_service``), bộ
máy nguyện vọng, ``admission_service``, service văn bản Hội đồng.

Tình trạng của MỘT hồ sơ (đọc dữ liệu, KHÔNG suy từ trạng thái hồ sơ) — loại trừ nhau theo thứ tự:

* ``HL`` — có dòng Quyết định còn hiệu lực (``EFFECTIVE_ROW_CONDITION``);
* ``CQ`` — không HL, có mục "chờ Admin quyết" đang mở (owner C7);
* ``XL`` — không HL / CQ, đã được Admin cho xét lại;
* ``KO`` — còn lại.

Độc lập: ``dau_appsheet`` (dấu "Đã trúng tuyển theo QĐ số …" — ``SQL_APPSHEET_MARK``) và
``co_ten_van_ban`` (có tên trong văn bản chưa huỷ ghi nhận — ĐÚNG điều kiện K5a).

Luật (owner): đích ``draft`` / ``rejected`` / ``withdrawal_pending`` / ``withdrawn`` bị CHẶN khi HL
hoặc dấu AppSheet (C4, C5, J1 dòng 12, E1) — trừ cạnh ``withdrawal_pending → withdrawn`` (chốt rút khi
hoàn xong — C3 "trừ khỏi số đã dùng khi rút xong hẳn"). Lần xét mới (dựng bộ, ghi nhận, công bố theo
nguyện vọng) bị CHẶN khi HL / CQ / dấu AppSheet (N10, C7, N11, N13, E1).

Tầng chủ sở hữu luật trạng thái: :func:`check_status_transition`, gọi TỪ ``transition`` — chỗ ghi
``profile.status`` DUY NHẤT (``admission_state_service.py``; lint ``check_status_assignment``).
"""
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import SYSTEM_CONSULTATION_METHOD
from app.models.council_document import APPSHEET_MARK_PREFIX, SQL_DECISION_STATE_COLUMNS
from app.services.council_set_gate_service import decision_state_block_reason
from app.utils.exceptions import ProfileLockedByDecisionError

HL = "co_qd_hieu_luc"
CQ = "cho_admin_quyet"
XL = "da_cho_xet_lai"
KO = "chua_co_qd"

#: Đích chuyển trạng thái bị chặn khi hồ sơ có Quyết định hiệu lực / dấu AppSheet.
LOCKED_TARGETS = frozenset({"draft", "rejected", "withdrawal_pending", "withdrawn"})
#: Cạnh được miễn: chốt rút khi hoàn tiền xong (``payment_service`` → ``_finalize_withdrawn``).
EXEMPT_TRANSITIONS = frozenset({("withdrawal_pending", "withdrawn")})


@dataclass(frozen=True)
class DecisionState:
    ma: str
    qd_hieu_luc_id: Optional[int] = None
    qd_chuoi_id: Optional[int] = None
    cho_quyet_id: Optional[int] = None
    co_ten_van_ban: bool = False
    dau_appsheet: bool = False

    @property
    def locks_status(self) -> bool:
        """Rút / về Nháp / Từ chối bị chặn (C4, C5, J1 dòng 12, E1)."""
        return self.ma == HL or self.dau_appsheet

    @property
    def blocks_new_admission(self) -> bool:
        """Không vào bộ văn bản / Quyết định / lần xét mới (N10, C7, N11, N13, E1) — ĐÚNG luật của cổng
        dựng bộ (:func:`decision_state_block_reason`, một nguồn — CLAUDE.md §7), không nới chuỗi nào."""
        return bool(decision_state_block_reason(self))

    def payload(self) -> Dict[str, Any]:
        """Phần đi ra client — mã + id văn bản / mục chờ (không dữ liệu cá nhân)."""
        return {
            "tinh_trang_qd": self.ma,
            "quyet_dinh_id": self.qd_hieu_luc_id,
            "muc_cho_id": self.cho_quyet_id,
            "dau_appsheet": self.dau_appsheet,
        }


NOT_SET = DecisionState(KO)


def from_row(h: Any) -> DecisionState:
    """Dựng tình trạng từ một hàng có ĐỦ các cột của ``SQL_COT_TINH_TRANG_QD`` (dùng chung cho hàm hỏi
    và cổng dựng bộ — hai nơi đọc cùng chuỗi SQL)."""
    hl = h["qd_hieu_luc_id"]
    cq = h["cho_quyet_id"]
    if hl is not None:
        code = HL
    elif cq is not None:
        code = CQ
    elif h["da_cho_xet_lai"]:
        code = XL
    else:
        code = KO
    return DecisionState(
        ma=code,
        qd_hieu_luc_id=hl,
        qd_chuoi_id=h["qd_chuoi_id"],
        cho_quyet_id=cq,
        co_ten_van_ban=bool(h["co_ten_van_ban"]),
        dau_appsheet=bool(h["dau_appsheet"]),
    )


SQL_STATE = text(
    "SELECT p.id AS pid, "
    + SQL_DECISION_STATE_COLUMNS
    + " FROM admission_profile p WHERE p.id = ANY(CAST(:ids AS integer[]))"
)


async def lock_profiles(db: AsyncSession, profile_ids: Iterable[int]) -> None:
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


async def decision_state(
    db: AsyncSession, profile_ids: Iterable[int], *, lock: bool = False
) -> Dict[int, DecisionState]:
    """{id hồ sơ: tình trạng}. ``khoa`` ⇒ khoá hồ sơ TRƯỚC khi đọc (tuần tự hoá với ghi nhận — vốn
    khoá hồ sơ trước khi chèn dòng). Hồ sơ không tồn tại ⇒ không có trong kết quả."""
    ids = sorted({int(x) for x in profile_ids})
    if not ids:
        return {}
    if lock:
        await lock_profiles(db, ids)
    row_no = (await db.execute(SQL_STATE, {"ids": ids})).mappings().all()
    return {h["pid"]: from_row(h) for h in row_no}


async def single_profile(db: AsyncSession, profile_id: int, *, lock: bool = False) -> DecisionState:
    return (await decision_state(db, [profile_id], lock=lock)).get(int(profile_id), NOT_SET)


def _block(tt: DecisionState, cau: str, operation: str) -> ProfileLockedByDecisionError:
    return ProfileLockedByDecisionError(
        cau,
        public_payload={**tt.payload(), "thao_tac": operation},
    )


async def check_status_transition(
    db: AsyncSession, profile_id: int, from_status: Optional[str], to_status: str
) -> None:
    """CHỐT chuyển trạng thái (tầng chủ sở hữu — gọi từ ``transition``): đích bị khoá + hồ sơ HL / dấu
    AppSheet ⇒ :class:`DecisionLocksProfile`. Khoá hồ sơ ``FOR UPDATE`` trước khi đọc."""
    if to_status not in LOCKED_TARGETS or (from_status, to_status) in EXEMPT_TRANSITIONS:
        return
    tt = await single_profile(db, profile_id, lock=True)
    if tt.locks_status:
        raise _block(
            tt,
            "Hồ sơ đã có tên trong Quyết định đã ký (hoặc mang dấu đã trúng tuyển theo Quyết định "
            "cũ) — không chuyển sang '%s'. Muốn đổi, ghi nhận văn bản điều chỉnh / huỷ trước." % to_status,
            "chuyen_trang_thai",
        )


async def early_check_status_lock(
    db: AsyncSession, profile_id: int, operation: str
) -> None:
    """Lớp kiểm SỚM (trước mọi việc khác của hàm rút / huỷ rút / trả về Nháp / tạo link rút) — cùng
    luật với :func:`check_status_transition`, báo lỗi trước khi tự lập yêu cầu hoàn / từ chối yêu cầu
    hoàn. Tầng chủ sở hữu vẫn là chốt chuyển trạng thái."""
    tt = await single_profile(db, profile_id, lock=True)
    if tt.locks_status:
        raise _block(
            tt,
            "Hồ sơ đã có tên trong Quyết định đã ký (hoặc mang dấu đã trúng tuyển theo Quyết định "
            "cũ) — tạm chặn thao tác này trên phần mềm. Cần hoàn tiền ngay thì kế toán lập yêu cầu "
            "hoàn bằng chức năng đang có.",
            operation,
        )


async def check_new_admission(db: AsyncSession, profile_id: int, operation: str) -> None:
    """Công bố theo nguyện vọng (một lần xét) — chặn HL / CQ / dấu AppSheet (N11, C7, E1)."""
    tt = await single_profile(db, profile_id, lock=True)
    if tt.blocks_new_admission:
        raise _block(
            tt,
            "Hồ sơ đã có tên trong Quyết định đã ký, đang chờ Admin quyết sau khi Quyết định bị huỷ, "
            "hoặc mang dấu đã trúng tuyển theo Quyết định cũ — không công bố theo nguyện vọng.",
            operation,
        )


async def attach_decision_state(db: AsyncSession, profiles: Sequence[Any]) -> None:
    """Gán thuộc tính TẠM ``_decision_state`` cho các hồ sơ (một lần đọc gộp) — để hàm tính cờ giao
    diện (đồng bộ) đọc. Cờ là lớp phụ; tầng chủ sở hữu là service."""
    ids = [getattr(p, "id", None) for p in profiles]
    tt = await decision_state(db, [i for i in ids if isinstance(i, int)])
    for p in profiles:
        try:
            p._decision_state = tt.get(getattr(p, "id", None), NOT_SET)
        except AttributeError:  # đối tượng không gán được thuộc tính (không xảy ra với ORM)
            pass


# ═══════════════ ô "Quyết định trúng tuyển" trên trang hồ sơ (vòng giao diện — đặc tả 3.9) ═══════════════
#: Văn bản GẦN NHẤT (id lớn nhất) có tên hồ sơ — mọi trạng thái (giao diện hiện trạng thái kèm theo).
SQL_LATEST_DOCUMENT = text(
    "SELECT d.id, d.loai, d.so_quyet_dinh, d.ngay_ky, d.trang_thai, d.set_id, d.ly_do_huy_ghi_nhan "
    "FROM council_decision_row r JOIN council_decision d ON d.id = r.decision_id "
    "WHERE r.profile_id = :p ORDER BY d.id DESC LIMIT 1"
)
#: Chữ số NGAY SAU tiền tố dấu AppSheet — CÙNG hai nguồn của ``SQL_APPSHEET_MARK`` (lý do trả về của hồ sơ; ghi chú lần
#: tư vấn ``method = system`` của lead), ưu tiên hồ sơ. Không khớp mẫu ⇒ NULL (không đoán).
assert not any(k in APPSHEET_MARK_PREFIX for k in ".^$*+?()[]{}|\\"), "tiền tố dùng trong biểu thức chính quy"
_RE_APPSHEET_DECISION_NUMBER = "^" + APPSHEET_MARK_PREFIX + "([0-9]+)"
SQL_APPSHEET_DECISION_NUMBER = text(
    "SELECT COALESCE(substring(p.revision_reason FROM :re), "
    "(SELECT substring(c.notes FROM :re) FROM consultation c WHERE c.lead_id = p.lead_id "
    "AND c.method = :m AND substring(c.notes FROM :re) IS NOT NULL ORDER BY c.id LIMIT 1)) "
    "FROM admission_profile p WHERE p.id = :p"
)


async def profile_decision_cell(
    db: AsyncSession, profile_id: int, *, view_cancel_reason: bool
) -> Dict[str, Any]:
    """Ô "Quyết định trúng tuyển" của MỘT hồ sơ (đặc tả 3.9) — tình trạng từ CHÍNH :func:`single_profile` (một nguồn, không
    truy vấn thứ hai cho câu hỏi "có Quyết định không"); văn bản gần nhất có tên em; ``ly_do_huy_ghi_nhan`` CHỈ khi
    ``view_cancel_reason`` (quyền do ``deps.py`` tính); dấu AppSheet tách riêng (``dau_appsheet`` + số Quyết định đọc
    được sau tiền tố). Không ghi gì."""
    tt = await single_profile(db, profile_id)
    vb = (await db.execute(SQL_LATEST_DOCUMENT, {"p": int(profile_id)})).mappings().first()
    decision_number = None
    if tt.dau_appsheet:
        decision_number = (
            await db.execute(
                SQL_APPSHEET_DECISION_NUMBER,
                {"p": int(profile_id), "re": _RE_APPSHEET_DECISION_NUMBER, "m": SYSTEM_CONSULTATION_METHOD},
            )
        ).scalar()
    return {
        "tinh_trang": tt.ma,
        "van_ban": (
            None
            if vb is None
            else {
                "id": vb["id"],
                "loai": vb["loai"],
                "so_quyet_dinh": vb["so_quyet_dinh"],
                "ngay_ky": vb["ngay_ky"].isoformat(),
                "trang_thai": vb["trang_thai"],
                "set_id": vb["set_id"],
            }
        ),
        "ly_do_huy_ghi_nhan": (
            vb["ly_do_huy_ghi_nhan"] if (view_cancel_reason and vb is not None) else None
        ),
        "dau_appsheet": tt.dau_appsheet,
        "dau_appsheet_so_qd": decision_number,
    }


def read_decision_state(profile: Any) -> DecisionState:
    """Đọc thuộc tính tạm; chưa gán ⇒ NOT_SET (như khuôn ``_outstanding_debt_codes``)."""
    tt = getattr(profile, "_decision_state", None)
    return tt if isinstance(tt, DecisionState) else NOT_SET
