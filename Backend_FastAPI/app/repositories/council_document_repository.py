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
BUILD_LOCK_KEY = "council_document_set:dung"

#: Vòng giao diện (đặc tả 3.4 / 3.5) — tình trạng của bộ. MỘT nơi tính: biểu thức ``CASE`` trong
#: :data:`SQL_SET_EXTENDED` (danh sách + chi tiết cùng câu).
SET_STATE = (
    "chua_ghi_nhan",
    "con_hieu_luc",
    "het_hieu_luc",
    "da_huy_ghi_nhan",
    "chua_xac_dinh",
)

#: Tên hiển thị của MỘT người dùng (bí danh ``u`` của bảng ``"user"``) — MỘT biểu thức cho người tạo bộ, người tải, người
#: xoá: họ tên nếu có, không thì tên đăng nhập.
SQL_USER_NAMES = "COALESCE(NULLIF(btrim(u.full_name), ''), u.username)"

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
SQL_SET_EXTENDED = text(
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
        "{ten}", SQL_USER_NAMES
    )
)

#: Người tạo PHÂN BIỆT của các bộ trong phạm vi người gọi (bộ lọc "Người tạo" của danh sách).
SQL_SET_CREATORS = text(
    """
SELECT DISTINCT s.nguoi_tao_id AS id, {ten} AS ten
FROM council_document_set s
JOIN "user" u ON u.id = s.nguoi_tao_id
WHERE CAST(:tat_ca AS boolean) OR s.unit_id = CAST(:don_vi AS integer)
ORDER BY ten, id
""".replace(
        "{ten}", SQL_USER_NAMES
    )
)

#: Tên hiển thị theo id người dùng (nhật ký tải / vết xoá).
SQL_NAME_BY_ID = text(
    'SELECT u.id, {ten} AS ten FROM "user" u WHERE u.id = ANY(CAST(:ids AS integer[]))'.replace(
        "{ten}", SQL_USER_NAMES
    )
)


class CouncilDocumentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------------------------------------------------------------- khoá dựng
    async def try_build_lock(self) -> bool:
        """``pg_try_advisory_xact_lock`` trên GIAO DỊCH của phiên này: True = đã giữ khoá
        (tự nhả khi giao dịch commit / rollback — không rò khoá khi request lỗi), False =
        một giao dịch khác (bất kỳ tiến trình nào dùng cùng CSDL) đang giữ."""
        return bool(
            (
                await self.db.execute(
                    text("SELECT pg_try_advisory_xact_lock(hashtext(:ten), 0)"),
                    {"ten": BUILD_LOCK_KEY},
                )
            ).scalar_one()
        )

    # ---------------------------------------------------------------- kho mẫu
    async def template_same_date(
        self, kind: str, effective_from: date
    ) -> Optional[CouncilDocumentTemplate]:
        """Mẫu đã có cùng loại + cùng ngày hiệu lực (UNIQUE) — không nạp bytes."""
        return (
            await self.db.execute(
                select(CouncilDocumentTemplate).where(
                    CouncilDocumentTemplate.loai == kind,
                    CouncilDocumentTemplate.hieu_luc_tu == effective_from,
                )
            )
        ).scalar_one_or_none()

    async def add_template(self, template: CouncilDocumentTemplate) -> CouncilDocumentTemplate:
        self.db.add(template)
        await self.db.flush()
        return template

    async def list_templates(self) -> List[CouncilDocumentTemplate]:
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

    async def effective_template(
        self, kind: str, signing_date: date
    ) -> Optional[CouncilDocumentTemplate]:
        """Mẫu ``loai`` có ``hieu_luc_tu`` LỚN NHẤT ≤ ``ngay_ky`` (J1 dòng 7), NẠP bytes.
        UNIQUE (loai, hieu_luc_tu) ⇒ kết quả xác định."""
        return (
            await self.db.execute(
                select(CouncilDocumentTemplate)
                .options(undefer(CouncilDocumentTemplate.noi_dung))
                .where(
                    CouncilDocumentTemplate.loai == kind,
                    CouncilDocumentTemplate.hieu_luc_tu <= signing_date,
                )
                .order_by(CouncilDocumentTemplate.hieu_luc_tu.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    # ---------------------------------------------------------------- bộ văn bản
    async def add_set(
        self, doc_set: CouncilDocumentSet, file: Sequence[CouncilDocumentSetFile]
    ) -> CouncilDocumentSet:
        """Ghi một bộ + mọi tệp của nó (flush, không commit)."""
        self.db.add(doc_set)
        await self.db.flush()
        for t in file:
            t.set_id = doc_set.id
            self.db.add(t)
        await self.db.flush()
        return doc_set

    async def set_by_id(self, set_id: int) -> Optional[CouncilDocumentSet]:
        """Một bộ — KHÔNG nạp hai cột dữ liệu cá nhân (deferred)."""
        return (
            await self.db.execute(
                select(CouncilDocumentSet).where(CouncilDocumentSet.id == set_id)
            )
        ).scalar_one_or_none()

    async def list_sets(
        self, *, only_unit_id: Optional[int], all_units: bool, limit: int, offset: int
    ) -> List[CouncilDocumentSet]:
        """Bộ mới trước. ``all_units`` ⇒ mọi bộ; không thì CHỈ bộ có ``unit_id == only_unit_id``
        (bộ ``unit_id`` NULL không bao giờ khớp). Người gọi (service) chặn tổ hợp lạ."""
        q = select(CouncilDocumentSet)
        if not all_units:
            q = q.where(CouncilDocumentSet.unit_id == only_unit_id)
        q = (
            q.order_by(CouncilDocumentSet.tao_luc.desc(), CouncilDocumentSet.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self.db.execute(q)).scalars().all())

    async def list_sets_extended(
        self,
        *,
        all_units: bool,
        only_unit_id: Optional[int],
        set_id: Optional[int] = None,
        academic_year: Optional[int] = None,
        creator_id: Optional[int] = None,
        decision_number: Optional[str] = None,
        state: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """:data:`SQL_SET_EXTENDED` — MỘT câu; mỗi dòng là dict cột. Người gọi (service) chặn tổ hợp phạm vi lạ."""
        rows = await self.db.execute(
            SQL_SET_EXTENDED,
            {
                "tat_ca": all_units,
                "don_vi": only_unit_id,
                "set_id": set_id,
                "nam": None if academic_year is None else str(academic_year),
                "nguoi": creator_id,
                "so": decision_number,
                "tt": state,
                "lim": limit,
                "off": offset,
            },
        )
        return [dict(r._mapping) for r in rows.all()]

    async def set_creators(
        self, *, all_units: bool, only_unit_id: Optional[int]
    ) -> List[Dict[str, Any]]:
        rows = await self.db.execute(
            SQL_SET_CREATORS, {"tat_ca": all_units, "don_vi": only_unit_id}
        )
        return [dict(r._mapping) for r in rows.all()]

    async def user_names(self, ids: Sequence[int]) -> Dict[int, str]:
        ids_sorted = sorted({int(i) for i in ids if i is not None})
        if not ids_sorted:
            return {}
        return {
            r[0]: r[1]
            for r in (await self.db.execute(SQL_NAME_BY_ID, {"ids": ids_sorted})).all()
        }

    async def set_files_with_content(self, set_id: int) -> List[CouncilDocumentSetFile]:
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

    async def list_set_files(self, set_id: int) -> List[CouncilDocumentSetFile]:
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

    async def input_profile_codes(self, set_id: int) -> Optional[List[str]]:
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
    async def add_deletion_trace(
        self, trace: CouncilDocumentSetDeletion
    ) -> CouncilDocumentSetDeletion:
        self.db.add(trace)
        await self.db.flush()
        return trace

    async def delete_set(self, set_id: int) -> int:
        """Xoá MỘT bộ (tệp theo ``ON DELETE CASCADE`` của CSDL); trả số bộ đã xoá. Flush,
        không commit — người gọi giữ vết xoá trong CÙNG giao dịch."""
        result = await self.db.execute(
            delete(CouncilDocumentSet).where(CouncilDocumentSet.id == set_id)
        )
        return result.rowcount

    async def list_deletion_traces(
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
    async def add_download_log(
        self, row: CouncilDocumentDownloadLog
    ) -> CouncilDocumentDownloadLog:
        self.db.add(row)
        await self.db.flush()
        return row

    async def list_download_log(
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

    async def set_file(
        self, set_id: int, order_no: int
    ) -> Optional[CouncilDocumentSetFile]:
        """Một tệp đã lưu, NẠP bytes — tải lại = đọc bytes đã lưu, không dựng lại."""
        return (
            await self.db.execute(
                select(CouncilDocumentSetFile)
                .options(undefer(CouncilDocumentSetFile.noi_dung))
                .where(
                    CouncilDocumentSetFile.set_id == set_id,
                    CouncilDocumentSetFile.thu_tu == order_no,
                )
            )
        ).scalar_one_or_none()
