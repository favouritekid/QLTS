# app/repositories/council_document_repository.py
"""Truy cập dữ liệu kho mẫu + bộ văn bản Hội đồng (giai đoạn 1 "Lần xét tuyển").

Chạy trên phiên của request: repository chỉ ``add`` / ``flush``, router commit. Cột bytes
(``noi_dung``) là deferred — chỉ nạp ở đúng hai chỗ cần bytes (chọn mẫu để dựng, tải lại
một tệp). Không bao giờ log nội dung tệp, danh sách mã hay DTO.
"""
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

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

#: Vòng giao diện (đặc tả 3.4 / 3.5) — tình trạng của bộ. MỘT nơi tính: biểu thức ``CASE`` trong
#: :data:`SQL_BO_MO_RONG` (danh sách + chi tiết cùng câu).
TINH_TRANG_BO = (
    "chua_ghi_nhan",
    "con_hieu_luc",
    "het_hieu_luc",
    "da_huy_ghi_nhan",
    "chua_xac_dinh",
)

#: Tên hiển thị của MỘT người dùng (bí danh ``u`` của bảng ``"user"``) — MỘT biểu thức cho người tạo bộ, người tải, người
#: xoá: họ tên nếu có, không thì tên đăng nhập.
SQL_TEN_NGUOI_DUNG = "COALESCE(NULLIF(btrim(u.full_name), ''), u.username)"

#: MỘT câu cho danh sách bộ (``GET /sets``) và chi tiết bộ (``GET /sets/{id}``) — không N+1:
#:
#: * ``tinh_trang`` (luật đặc tả 3.4, theo thứ tự): có lượt gửi ``cho_gui`` ⇒ ``chua_xac_dinh``; có văn bản của bộ
#:   ``hieu_luc`` ⇒ ``con_hieu_luc``; ``het_hieu_luc`` ⇒ ``het_hieu_luc``; chỉ có ``huy_ghi_nhan`` ⇒
#:   ``da_huy_ghi_nhan``; còn lại ``chua_ghi_nhan``;
#: * ``qd_*`` = văn bản CHƯA huỷ ghi nhận mới nhất của bộ (trước đây ``tom_tat_qd_cua_bo``: cùng luật — bản ấy đã gỡ, đây là nguồn duy nhất)
#:   + Quyết định gốc của nó (``goc_*``);
#: * ``luot_*`` = lượt gửi đang chờ (UNIQUE một phần ⇒ tối đa một) — service chỉ trả cho người có quyền ghi nhận;
#: * lọc: phạm vi (admin mọi bộ / quản lý đúng đơn vị — bộ ``unit_id`` NULL không bao giờ khớp), id, năm học,
#:   người tạo, số Quyết định (khớp ĐÚNG, trên văn bản hiển thị), tình trạng; mới trước; ``LIMIT`` / ``OFFSET``.
#:
#: Không có cột dữ liệu cá nhân của bộ (``ma_ho_so_dau_vao``, ``snapshot_dto``).
SQL_BO_MO_RONG = text(
    """
WITH b AS (
  SELECT s.id, s.nguoi_tao_id, s.tao_luc, s.moc_chup, s.unit_id, s.trinh_do, s.so_ho_so,
         s.so_tep, s.kich_thuoc_tong, s.thong_tin_dung ->> 'nam_hoc' AS nam_hoc,
         s.tham_so_quyet_dinh,
         {ten} AS nguoi_tao_ten,
         lg.ma::text AS luot_ma, lg.tao_luc AS luot_tao_luc,
         qd.id AS qd_id, qd.loai AS qd_loai, qd.trang_thai AS qd_trang_thai,
         qd.so_quyet_dinh AS qd_so, qd.ngay_ky AS qd_ngay_ky, qd.so_ho_so AS qd_so_ho_so,
         g.id AS goc_id, g.so_quyet_dinh AS goc_so, g.ngay_ky AS goc_ngay_ky,
         CASE
           WHEN lg.ma IS NOT NULL THEN 'chua_xac_dinh'
           WHEN EXISTS (SELECT 1 FROM council_decision d
                        WHERE d.set_id = s.id AND d.trang_thai = 'hieu_luc') THEN 'con_hieu_luc'
           WHEN EXISTS (SELECT 1 FROM council_decision d
                        WHERE d.set_id = s.id AND d.trang_thai = 'het_hieu_luc') THEN 'het_hieu_luc'
           WHEN EXISTS (SELECT 1 FROM council_decision d
                        WHERE d.set_id = s.id AND d.trang_thai = 'huy_ghi_nhan') THEN 'da_huy_ghi_nhan'
           ELSE 'chua_ghi_nhan'
         END AS tinh_trang
  FROM council_document_set s
  LEFT JOIN "user" u ON u.id = s.nguoi_tao_id
  LEFT JOIN LATERAL (
    SELECT l.ma, l.tao_luc FROM council_decision_submission l
    WHERE l.set_id = s.id AND l.trang_thai = 'cho_gui'
    ORDER BY l.id LIMIT 1
  ) lg ON true
  LEFT JOIN LATERAL (
    SELECT d.id, d.loai, d.trang_thai, d.so_quyet_dinh, d.ngay_ky, d.so_ho_so, d.goc_id
    FROM council_decision d
    WHERE d.set_id = s.id AND d.trang_thai <> 'huy_ghi_nhan'
    ORDER BY d.id DESC LIMIT 1
  ) qd ON true
  LEFT JOIN council_decision g ON g.id = qd.goc_id
  WHERE (CAST(:tat_ca AS boolean) OR s.unit_id = CAST(:don_vi AS integer))
    AND (CAST(:set_id AS integer) IS NULL OR s.id = CAST(:set_id AS integer))
    AND (CAST(:nam AS text) IS NULL OR s.thong_tin_dung ->> 'nam_hoc' = CAST(:nam AS text))
    AND (CAST(:nguoi AS integer) IS NULL OR s.nguoi_tao_id = CAST(:nguoi AS integer))
    AND (CAST(:so AS text) IS NULL OR qd.so_quyet_dinh = CAST(:so AS text))
)
SELECT * FROM b
WHERE CAST(:tt AS text) IS NULL OR b.tinh_trang = CAST(:tt AS text)
ORDER BY b.tao_luc DESC, b.id DESC
LIMIT :lim OFFSET :off
""".replace(
        "{ten}", SQL_TEN_NGUOI_DUNG
    )
)

#: Người tạo PHÂN BIỆT của các bộ trong phạm vi người gọi (bộ lọc "Người tạo" của danh sách).
SQL_NGUOI_TAO_BO = text(
    """
SELECT DISTINCT s.nguoi_tao_id AS id, {ten} AS ten
FROM council_document_set s
JOIN "user" u ON u.id = s.nguoi_tao_id
WHERE CAST(:tat_ca AS boolean) OR s.unit_id = CAST(:don_vi AS integer)
ORDER BY ten, id
""".replace(
        "{ten}", SQL_TEN_NGUOI_DUNG
    )
)

#: Tên hiển thị theo id người dùng (nhật ký tải / vết xoá).
SQL_TEN_THEO_ID = text(
    'SELECT u.id, {ten} AS ten FROM "user" u WHERE u.id = ANY(CAST(:ids AS integer[]))'.replace(
        "{ten}", SQL_TEN_NGUOI_DUNG
    )
)


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

    async def danh_sach_bo_mo_rong(
        self,
        *,
        tat_ca: bool,
        chi_don_vi: Optional[int],
        set_id: Optional[int] = None,
        nam_hoc: Optional[int] = None,
        nguoi_tao_id: Optional[int] = None,
        so_quyet_dinh: Optional[str] = None,
        tinh_trang: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """:data:`SQL_BO_MO_RONG` — MỘT câu; mỗi dòng là dict cột. Người gọi (service) chặn tổ hợp phạm vi lạ."""
        rows = await self.db.execute(
            SQL_BO_MO_RONG,
            {
                "tat_ca": tat_ca,
                "don_vi": chi_don_vi,
                "set_id": set_id,
                "nam": None if nam_hoc is None else str(nam_hoc),
                "nguoi": nguoi_tao_id,
                "so": so_quyet_dinh,
                "tt": tinh_trang,
                "lim": limit,
                "off": offset,
            },
        )
        return [dict(r._mapping) for r in rows.all()]

    async def nguoi_tao_bo(
        self, *, tat_ca: bool, chi_don_vi: Optional[int]
    ) -> List[Dict[str, Any]]:
        rows = await self.db.execute(
            SQL_NGUOI_TAO_BO, {"tat_ca": tat_ca, "don_vi": chi_don_vi}
        )
        return [dict(r._mapping) for r in rows.all()]

    async def ten_nguoi_dung(self, ids: Sequence[int]) -> Dict[int, str]:
        ds = sorted({int(i) for i in ids if i is not None})
        if not ds:
            return {}
        return {
            r[0]: r[1]
            for r in (await self.db.execute(SQL_TEN_THEO_ID, {"ids": ds})).all()
        }

    async def tep_cua_bo_kem_noi_dung(self, set_id: int) -> List[CouncilDocumentSetFile]:
        """MỌI tệp của một bộ theo ``thu_tu``, NẠP bytes — chỉ cho "tải cả bộ" (đọc bytes đã lưu, không dựng lại)."""
        return list(
            (
                await self.db.execute(
                    select(CouncilDocumentSetFile)
                    .options(undefer(CouncilDocumentSetFile.noi_dung))
                    .where(CouncilDocumentSetFile.set_id == set_id)
                    .order_by(CouncilDocumentSetFile.thu_tu)
                )
            )
            .scalars()
            .all()
        )

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
