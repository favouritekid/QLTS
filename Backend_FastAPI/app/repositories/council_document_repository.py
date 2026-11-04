# app/repositories/council_document_repository.py
"""Truy cập dữ liệu kho mẫu + bộ văn bản Hội đồng (giai đoạn 1 "Lần xét tuyển").

Chạy trên phiên của request: repository chỉ ``add`` / ``flush``, router commit. Cột bytes
(``noi_dung``) là deferred — chỉ nạp ở đúng hai chỗ cần bytes (chọn mẫu để dựng, tải lại
một tệp). Không bao giờ log nội dung tệp, danh sách mã hay DTO.
"""
from datetime import date
from typing import List, Optional, Sequence

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.models.council_document import (
    CouncilDocumentDownloadLog,
    CouncilDocumentSet,
    CouncilDocumentSetDeletion,
    CouncilDocumentSetFile,
    CouncilDocumentTemplate,
)

#: Tên miền khoá tư vấn của việc DỰNG bộ văn bản (dạng hai khoá int4: ``hashtext(tên)``,
#: ``0``). Khoá hai-khoá và khoá một-khoá bigint không chồng nhau (tài liệu PostgreSQL);
#: các khoá hai-khoá khác của mã (``invoice_service``, ``public_lead_intake_service``) dùng
#: tên miền / khoá thứ hai khác.
KHOA_DUNG_BO = "council_document_set:dung"


class CouncilDocumentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------------------------------------------------------------- khoá dựng
    async def thu_khoa_dung(self) -> bool:
        """``pg_try_advisory_xact_lock`` trên GIAO DỊCH của phiên này: True = đã giữ khoá
        (tự nhả khi giao dịch commit / rollback — không rò khoá khi request lỗi), False =
        một giao dịch khác (bất kỳ tiến trình nào dùng cùng CSDL) đang giữ."""
        return bool(
            (
                await self.db.execute(
                    text("SELECT pg_try_advisory_xact_lock(hashtext(:ten), 0)"),
                    {"ten": KHOA_DUNG_BO},
                )
            ).scalar_one()
        )

    # ---------------------------------------------------------------- kho mẫu
    async def mau_cung_ngay(
        self, loai: str, hieu_luc_tu: date
    ) -> Optional[CouncilDocumentTemplate]:
        """Mẫu đã có cùng loại + cùng ngày hiệu lực (UNIQUE) — không nạp bytes."""
        return (
            await self.db.execute(
                select(CouncilDocumentTemplate).where(
                    CouncilDocumentTemplate.loai == loai,
                    CouncilDocumentTemplate.hieu_luc_tu == hieu_luc_tu,
                )
            )
        ).scalar_one_or_none()

    async def them_mau(self, mau: CouncilDocumentTemplate) -> CouncilDocumentTemplate:
        self.db.add(mau)
        await self.db.flush()
        return mau

    async def danh_sach_mau(self) -> List[CouncilDocumentTemplate]:
        """Mọi mẫu — KHÔNG nạp bytes (cột deferred). Theo loại, ngày hiệu lực mới trước."""
        return list(
            (
                await self.db.execute(
                    select(CouncilDocumentTemplate).order_by(
                        CouncilDocumentTemplate.loai,
                        CouncilDocumentTemplate.hieu_luc_tu.desc(),
                        CouncilDocumentTemplate.id.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )

    async def mau_hieu_luc(
        self, loai: str, ngay_ky: date
    ) -> Optional[CouncilDocumentTemplate]:
        """Mẫu ``loai`` có ``hieu_luc_tu`` LỚN NHẤT ≤ ``ngay_ky`` (J1 dòng 7), NẠP bytes.
        UNIQUE (loai, hieu_luc_tu) ⇒ kết quả xác định."""
        return (
            await self.db.execute(
                select(CouncilDocumentTemplate)
                .options(undefer(CouncilDocumentTemplate.noi_dung))
                .where(
                    CouncilDocumentTemplate.loai == loai,
                    CouncilDocumentTemplate.hieu_luc_tu <= ngay_ky,
                )
                .order_by(CouncilDocumentTemplate.hieu_luc_tu.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    # ---------------------------------------------------------------- bộ văn bản
    async def them_bo(
        self, bo: CouncilDocumentSet, tep: Sequence[CouncilDocumentSetFile]
    ) -> CouncilDocumentSet:
        """Ghi một bộ + mọi tệp của nó (flush, không commit)."""
        self.db.add(bo)
        await self.db.flush()
        for t in tep:
            t.set_id = bo.id
            self.db.add(t)
        await self.db.flush()
        return bo

    async def bo_theo_id(self, set_id: int) -> Optional[CouncilDocumentSet]:
        """Một bộ — KHÔNG nạp hai cột dữ liệu cá nhân (deferred)."""
        return (
            await self.db.execute(
                select(CouncilDocumentSet).where(CouncilDocumentSet.id == set_id)
            )
        ).scalar_one_or_none()

    async def danh_sach_bo(
        self, *, chi_don_vi: Optional[int], tat_ca: bool, limit: int, offset: int
    ) -> List[CouncilDocumentSet]:
        """Bộ mới trước. ``tat_ca`` ⇒ mọi bộ; không thì CHỈ bộ có ``unit_id == chi_don_vi``
        (bộ ``unit_id`` NULL không bao giờ khớp). Người gọi (service) chặn tổ hợp lạ."""
        q = select(CouncilDocumentSet)
        if not tat_ca:
            q = q.where(CouncilDocumentSet.unit_id == chi_don_vi)
        q = (
            q.order_by(CouncilDocumentSet.tao_luc.desc(), CouncilDocumentSet.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.db.execute(q)).scalars().all())

    async def danh_sach_tep(self, set_id: int) -> List[CouncilDocumentSetFile]:
        """Các tệp của một bộ theo ``thu_tu`` — KHÔNG nạp bytes."""
        return list(
            (
                await self.db.execute(
                    select(CouncilDocumentSetFile)
                    .where(CouncilDocumentSetFile.set_id == set_id)
                    .order_by(CouncilDocumentSetFile.thu_tu)
                )
            )
            .scalars()
            .all()
        )

    async def ma_ho_so_dau_vao(self, set_id: int) -> Optional[List[str]]:
        """Danh sách mã hồ sơ đầu vào ĐÚNG THỨ TỰ của một bộ (cột PII deferred) — chỉ route
        admin dùng; ``None`` khi không có bộ."""
        return (
            await self.db.execute(
                select(CouncilDocumentSet.ma_ho_so_dau_vao).where(
                    CouncilDocumentSet.id == set_id
                )
            )
        ).scalar_one_or_none()

    # ---------------------------------------------------------------- vết xoá
    async def them_vet_xoa(
        self, vet: CouncilDocumentSetDeletion
    ) -> CouncilDocumentSetDeletion:
        self.db.add(vet)
        await self.db.flush()
        return vet

    async def xoa_bo(self, set_id: int) -> int:
        """Xoá MỘT bộ (tệp theo ``ON DELETE CASCADE`` của CSDL); trả số bộ đã xoá. Flush,
        không commit — người gọi giữ vết xoá trong CÙNG giao dịch."""
        kq = await self.db.execute(
            delete(CouncilDocumentSet).where(CouncilDocumentSet.id == set_id)
        )
        return kq.rowcount

    async def danh_sach_vet_xoa(
        self, *, limit: int, offset: int
    ) -> List[CouncilDocumentSetDeletion]:
        return list(
            (
                await self.db.execute(
                    select(CouncilDocumentSetDeletion)
                    .order_by(
                        CouncilDocumentSetDeletion.xoa_luc.desc(),
                        CouncilDocumentSetDeletion.id.desc(),
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )

    # ---------------------------------------------------------------- nhật ký tải
    async def them_nhat_ky_tai(
        self, dong: CouncilDocumentDownloadLog
    ) -> CouncilDocumentDownloadLog:
        self.db.add(dong)
        await self.db.flush()
        return dong

    async def danh_sach_nhat_ky_tai(
        self, *, set_id: Optional[int], limit: int, offset: int
    ) -> List[CouncilDocumentDownloadLog]:
        q = select(CouncilDocumentDownloadLog)
        if set_id is not None:
            q = q.where(CouncilDocumentDownloadLog.set_id == set_id)
        q = (
            q.order_by(
                CouncilDocumentDownloadLog.tai_luc.desc(),
                CouncilDocumentDownloadLog.id.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        return list((await self.db.execute(q)).scalars().all())

    async def tep_cua_bo(
        self, set_id: int, thu_tu: int
    ) -> Optional[CouncilDocumentSetFile]:
        """Một tệp đã lưu, NẠP bytes — tải lại = đọc bytes đã lưu, không dựng lại."""
        return (
            await self.db.execute(
                select(CouncilDocumentSetFile)
                .options(undefer(CouncilDocumentSetFile.noi_dung))
                .where(
                    CouncilDocumentSetFile.set_id == set_id,
                    CouncilDocumentSetFile.thu_tu == thu_tu,
                )
            )
        ).scalar_one_or_none()
