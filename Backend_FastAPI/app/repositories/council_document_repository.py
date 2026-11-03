# app/repositories/council_document_repository.py
"""Truy cập dữ liệu kho mẫu + bộ văn bản Hội đồng (giai đoạn 1 "Lần xét tuyển").

Chạy trên phiên của request: repository chỉ ``add`` / ``flush``, router commit. Cột bytes
(``noi_dung``) là deferred — chỉ nạp ở đúng hai chỗ cần bytes (chọn mẫu để dựng, tải lại
một tệp). Không bao giờ log nội dung tệp, danh sách mã hay DTO.
"""
from datetime import date
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.models.council_document import (
    CouncilDocumentSet,
    CouncilDocumentSetFile,
    CouncilDocumentTemplate,
)


class CouncilDocumentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

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

    async def tep_cua_bo(
        self, set_id: int, path: str
    ) -> Optional[CouncilDocumentSetFile]:
        """Một tệp đã lưu, NẠP bytes — tải lại = đọc bytes đã lưu, không dựng lại."""
        return (
            await self.db.execute(
                select(CouncilDocumentSetFile)
                .options(undefer(CouncilDocumentSetFile.noi_dung))
                .where(
                    CouncilDocumentSetFile.set_id == set_id,
                    CouncilDocumentSetFile.path == path,
                )
            )
        ).scalar_one_or_none()
