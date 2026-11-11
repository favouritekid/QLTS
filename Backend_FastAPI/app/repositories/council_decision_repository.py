# app/repositories/council_decision_repository.py
"""Truy cập dữ liệu ghi nhận Quyết định đã ký (F230 — lượt I). Chỉ SQL / ORM; luật nghiệp vụ ở
``app/services/council_decision_service.py``. Khoá luôn theo thứ tự: văn bản → mục chờ → bộ → hồ sơ
(id tăng dần) — đặc tả mục 2.2 / 2.5 / 8.5 (BS §4.6) — rồi dòng chỉ tiêu (chặng 2b,
``quota_occupancy_service.khoa_chi_tieu_cua_dong_bo``)."""
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select, text
from sqlalchemy.orm import undefer
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.council_document import (
    DIEU_KIEN_DONG_HIEU_LUC,
    CouncilDecision,
    CouncilDecisionHold,
    CouncilDecisionRow,
    CouncilDecisionScan,
    CouncilDocumentEvent,
    CouncilDocumentSet,
    CouncilDocumentSetRow,
)


def ma_loi_csdl(e: BaseException) -> Tuple[Optional[str], Optional[str]]:
    """(SQLSTATE, tên ràng buộc) của một lỗi CSDL bọc bởi SQLAlchemy / asyncpg; không có ⇒ None.
    KHÔNG đọc thông điệp (có thể mang tham số câu lệnh)."""
    orig = getattr(e, "orig", None)
    nguon = [orig, getattr(orig, "__cause__", None), e]
    sqlstate = None
    rang_buoc = None
    for o in nguon:
        if o is None:
            continue
        for a in ("sqlstate", "pgcode"):
            v = getattr(o, a, None)
            if sqlstate is None and isinstance(v, str):
                sqlstate = v
        v = getattr(o, "constraint_name", None)
        if rang_buoc is None and isinstance(v, str):
            rang_buoc = v
    return sqlstate, rang_buoc


class CouncilDecisionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ───────────────────────────── khoá ─────────────────────────────
    async def khoa_bo(self, set_id: int) -> Optional[CouncilDocumentSet]:
        return (
            await self.db.execute(
                select(CouncilDocumentSet)
                .where(CouncilDocumentSet.id == set_id)
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def khoa_qd(self, decision_id: int) -> Optional[CouncilDecision]:
        return (
            await self.db.execute(
                select(CouncilDecision)
                .where(CouncilDecision.id == decision_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()

    async def khoa_ho_so(self, pids: Sequence[int]) -> Dict[int, str]:
        """Khoá ``FOR UPDATE`` các hồ sơ theo id TĂNG DẦN (một câu) ⇒ {id: trạng thái hiện tại}."""
        ids = sorted({int(p) for p in pids})
        if not ids:
            return {}
        r = await self.db.execute(
            text(
                "SELECT id, status::text AS status FROM admission_profile "
                "WHERE id = ANY(CAST(:ids AS integer[])) ORDER BY id FOR UPDATE"
            ),
            {"ids": ids},
        )
        return {row.id: row.status for row in r}

    async def khoa_muc_cho(self, hold_id: int) -> Optional[CouncilDecisionHold]:
        return (
            await self.db.execute(
                select(CouncilDecisionHold)
                .where(CouncilDecisionHold.id == hold_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()

    # ───────────────────────────── đọc ─────────────────────────────
    async def qd_theo_id(self, decision_id: int) -> Optional[CouncilDecision]:
        return await self.db.get(CouncilDecision, decision_id)

    async def muc_cho_theo_id(self, hold_id: int) -> Optional[CouncilDecisionHold]:
        return await self.db.get(CouncilDecisionHold, hold_id)

    async def dong_bo(self, set_id: int) -> List[CouncilDocumentSetRow]:
        return list(
            (
                await self.db.execute(
                    select(CouncilDocumentSetRow)
                    .where(CouncilDocumentSetRow.set_id == set_id)
                    .order_by(CouncilDocumentSetRow.stt)
                )
            ).scalars()
        )

    async def van_ban_song_cua_bo(self, set_id: int) -> List[CouncilDecision]:
        return list(
            (
                await self.db.execute(
                    select(CouncilDecision)
                    .where(
                        CouncilDecision.set_id == set_id,
                        CouncilDecision.trang_thai != "huy_ghi_nhan",
                    )
                    .order_by(CouncilDecision.id)
                )
            ).scalars()
        )

    async def van_ban_cua_bo(self, set_id: int) -> List[CouncilDecision]:
        return list(
            (
                await self.db.execute(
                    select(CouncilDecision)
                    .where(CouncilDecision.set_id == set_id)
                    .order_by(CouncilDecision.id)
                )
            ).scalars()
        )

    async def so_da_dung(self, so: str, pham_vi: int) -> Optional[int]:
        return (
            await self.db.execute(
                select(CouncilDecision.id).where(
                    CouncilDecision.so_quyet_dinh == so,
                    CouncilDecision.pham_vi_so == pham_vi,
                    CouncilDecision.trang_thai != "huy_ghi_nhan",
                )
            )
        ).scalar_one_or_none()

    async def chuoi(self, goc_id: int) -> List[CouncilDecision]:
        """Gốc + bổ sung / điều chỉnh của gốc + văn bản huỷ trỏ tới bất kỳ văn bản nào trong đó."""
        thanh_vien = list(
            (
                await self.db.execute(
                    select(CouncilDecision)
                    .where(
                        (CouncilDecision.id == goc_id)
                        | (CouncilDecision.goc_id == goc_id)
                    )
                    .order_by(CouncilDecision.id)
                )
            ).scalars()
        )
        ids = [d.id for d in thanh_vien]
        huy = list(
            (
                await self.db.execute(
                    select(CouncilDecision)
                    .where(CouncilDecision.huy_qd_id.in_(ids))
                    .order_by(CouncilDecision.id)
                )
            ).scalars()
        )
        return thanh_vien + huy

    async def dong_hieu_luc_cua_qd(self, decision_id: int) -> List[CouncilDecisionRow]:
        return list(
            (
                await self.db.execute(
                    select(CouncilDecisionRow)
                    .where(
                        CouncilDecisionRow.decision_id == decision_id,
                        text(DIEU_KIEN_DONG_HIEU_LUC),
                    )
                    .order_by(CouncilDecisionRow.stt)
                )
            ).scalars()
        )

    async def dong_cua_qd(self, decision_id: int) -> List[CouncilDecisionRow]:
        return list(
            (
                await self.db.execute(
                    select(CouncilDecisionRow)
                    .where(CouncilDecisionRow.decision_id == decision_id)
                    .order_by(CouncilDecisionRow.stt)
                )
            ).scalars()
        )

    async def dong_bi_bo_boi(self, decision_id: int) -> List[CouncilDecisionRow]:
        return list(
            (
                await self.db.execute(
                    select(CouncilDecisionRow)
                    .where(CouncilDecisionRow.bi_bo_boi_id == decision_id)
                    .order_by(CouncilDecisionRow.id)
                )
            ).scalars()
        )

    async def dong_theo_id(self, ids: Sequence[int]) -> List[CouncilDecisionRow]:
        if not ids:
            return []
        return list(
            (
                await self.db.execute(
                    select(CouncilDecisionRow)
                    .where(CouncilDecisionRow.id.in_(list(ids)))
                    .order_by(CouncilDecisionRow.id)
                )
            ).scalars()
        )

    async def dong_hieu_luc_cua_ho_so(
        self, pids: Sequence[int]
    ) -> Dict[int, CouncilDecisionRow]:
        if not pids:
            return {}
        r = (
            await self.db.execute(
                select(CouncilDecisionRow).where(
                    CouncilDecisionRow.profile_id.in_(list(pids)),
                    text(DIEU_KIEN_DONG_HIEU_LUC),
                )
            )
        ).scalars()
        return {d.profile_id: d for d in r}

    async def muc_cho_cua_qd_huy(self, van_ban_huy_id: int) -> List[CouncilDecisionHold]:
        return list(
            (
                await self.db.execute(
                    select(CouncilDecisionHold)
                    .where(CouncilDecisionHold.van_ban_huy_id == van_ban_huy_id)
                    .order_by(CouncilDecisionHold.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            ).scalars()
        )

    async def muc_cho_dang_mo(self, pids: Sequence[int]) -> Dict[int, CouncilDecisionHold]:
        if not pids:
            return {}
        r = (
            await self.db.execute(
                select(CouncilDecisionHold).where(
                    CouncilDecisionHold.profile_id.in_(list(pids)),
                    CouncilDecisionHold.trang_thai == "cho_quyet",
                )
            )
        ).scalars()
        return {h.profile_id: h for h in r}

    async def ho_so_o_bo_khac(
        self, pids: Sequence[int], tru_set_id: Optional[int] = None
    ) -> Dict[int, int]:
        """{id bộ khác: số hồ sơ trong ``pids`` có mặt ở bộ ấy} — chỉ id + số đếm (báo, không chặn)."""
        if not pids:
            return {}
        q = (
            select(CouncilDocumentSetRow.set_id, CouncilDocumentSetRow.profile_id)
            .where(CouncilDocumentSetRow.profile_id.in_(list(pids)))
        )
        if tru_set_id is not None:
            q = q.where(CouncilDocumentSetRow.set_id != tru_set_id)
        out: Dict[int, int] = {}
        for sid, _ in (await self.db.execute(q)).all():
            out[sid] = out.get(sid, 0) + 1
        return dict(sorted(out.items()))

    async def scan_cua_qd(
        self, decision_id: int, *, kem_noi_dung: bool = False
    ) -> Optional[CouncilDecisionScan]:
        """``noi_dung`` là cột HOÃN (deferred) — chỉ nạp khi ``kem_noi_dung`` (tải bản scan); đọc thuộc
        tính hoãn ngoài ``await`` ⇒ ``MissingGreenlet``."""
        cau = select(CouncilDecisionScan).where(CouncilDecisionScan.decision_id == decision_id)
        if kem_noi_dung:
            cau = cau.options(undefer(CouncilDecisionScan.noi_dung))
        return (await self.db.execute(cau)).scalar_one_or_none()

    async def danh_sach_qd(
        self,
        *,
        set_id: Optional[int],
        limit: int,
        offset: int,
        loai: Optional[str] = None,
        trang_thai: Optional[str] = None,
    ) -> List[CouncilDecision]:
        """Văn bản đã ký, mới trước. Vòng giao diện: lọc ``loai`` / ``trang_thai`` ở máy chủ (giá trị do router
        giới hạn đúng tập CHECK của bảng) — giao diện không lọc lại."""
        q = select(CouncilDecision).order_by(CouncilDecision.id.desc())
        if set_id is not None:
            q = q.where(CouncilDecision.set_id == set_id)
        if loai is not None:
            q = q.where(CouncilDecision.loai == loai)
        if trang_thai is not None:
            q = q.where(CouncilDecision.trang_thai == trang_thai)
        return list((await self.db.execute(q.limit(limit).offset(offset))).scalars())

    async def danh_sach_muc_cho(
        self, *, trang_thai: Optional[str], limit: int, offset: int
    ) -> List[Tuple[CouncilDecisionHold, CouncilDecisionRow]]:
        q = (
            select(CouncilDecisionHold, CouncilDecisionRow)
            .join(
                CouncilDecisionRow,
                CouncilDecisionRow.id == CouncilDecisionHold.decision_row_id,
            )
            .order_by(CouncilDecisionHold.id.desc())
        )
        if trang_thai is not None:
            q = q.where(CouncilDecisionHold.trang_thai == trang_thai)
        return [tuple(r) for r in (await self.db.execute(q.limit(limit).offset(offset))).all()]

    async def danh_sach_su_kien(
        self,
        *,
        set_id: Optional[int],
        decision_id: Optional[int],
        limit: int,
        offset: int,
    ) -> List[CouncilDocumentEvent]:
        q = select(CouncilDocumentEvent).order_by(CouncilDocumentEvent.id.desc())
        if set_id is not None:
            q = q.where(CouncilDocumentEvent.set_id == set_id)
        if decision_id is not None:
            q = q.where(CouncilDocumentEvent.decision_id == decision_id)
        return list((await self.db.execute(q.limit(limit).offset(offset))).scalars())

    # ───────────────────────────── ghi ─────────────────────────────
    async def them(self, *doi_tuong) -> None:
        self.db.add_all(list(doi_tuong))
        await self.db.flush()

    async def chen_dong_tu_bo(
        self, decision_id: int, set_id: int, trang_thai_cha: str = "hieu_luc"
    ) -> int:
        """Chép MỌI dòng của bộ ``set_id`` thành dòng của văn bản ``decision_id`` trong MỘT câu
        (``INSERT … SELECT``) — dòng QĐ = đúng dòng bộ nguồn (``fk_council_decision_row_dong_bo``
        canh ở CSDL). Trả số dòng đã chèn."""
        r = await self.db.execute(
            text(
                "INSERT INTO council_decision_row (decision_id, trang_thai_cha, set_id, "
                "set_row_id, profile_id, stt) SELECT :d, :t, r.set_id, r.id, r.profile_id, "
                "r.stt FROM council_document_set_row r WHERE r.set_id = :s ORDER BY r.stt"
            ),
            {"d": decision_id, "t": trang_thai_cha, "s": set_id},
        )
        return int(r.rowcount or 0)
