# app/services/council_document_set_service.py
"""Tạo + tải lại bộ văn bản Hội đồng (giai đoạn 1 "Lần xét tuyển", PR 1.3 / 1.4 phần lưu).

Tạo bộ = bốn bước, lỗi ở BẤT KỲ bước nào ⇒ không ghi gì:

1. Đọc hồ sơ theo danh sách mã ở MỘT giao dịch ``REPEATABLE READ READ ONLY`` trên kết nối
   riêng (:func:`council_candidate_service.doc_ho_so_theo_ma`).
2. Chọn mẫu theo ngày ký = ``ngay_quyet_dinh`` nếu có, không thì ngày tạo theo giờ Việt Nam
   (:func:`council_document_template_service.chon_mau`); kiểm lại gói zip của mẫu đã chọn
   (lớp phụ — tầng chủ sở hữu là lúc tải mẫu lên).
3. Dựng bằng ``render_council_documents`` NGOÀI event loop (``asyncio.to_thread`` — dựng mất
   vài giây CPU).
4. Ghi ``council_document_set`` + mọi tệp (bytes NGUYÊN bộ dựng trả, sha từng tệp) trong
   phiên của request, dưới một SAVEPOINT: service chỉ flush, router commit (lượt E2).

Đơn vị của bộ = ``lead.unit_id`` của hồ sơ — ĐÚNG cột mà kiểm quyền hồ sơ của Quản lý đang
dùng (``admission_service._check_idor_access``; ``DocumentActionPolicy`` cùng nguồn; KHÔNG
dùng ``user_unit_assignment``): mọi hồ sơ cùng MỘT đơn vị ⇒ đơn vị đó, còn lại ⇒ NULL (chỉ
admin xem — J1 dòng 9). Tải lại một tệp = đọc bytes đã lưu, KHÔNG dựng lại.

Phiên bản mã đã dựng (F212): metadata của mỗi bộ ghi sha256 NỘI DUNG các tệp nguồn quyết
định bộ văn bản (bộ dựng, kho mẫu, hàm đọc + SQL, tệp này) — tính từ CHÍNH các tệp đã nạp,
lúc nạp module. Không dùng nhãn ảnh Docker (đã biết rỗng / thiếu).
"""
import asyncio
import hashlib
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import settings
from app.constants.admission_circular import vn_calendar_date
from app.models.council_document import CouncilDocumentSet, CouncilDocumentSetFile
from app.repositories import council_candidate_repository as _kho_doc
from app.repositories.council_document_repository import CouncilDocumentRepository
from app.services import council_candidate_service as _ham_doc
from app.services import council_document_render_service as bo_dung
from app.services import council_document_template_service as _kho_mau
from app.services.council_candidate_service import doc_ho_so_theo_ma
from app.services.council_document_template_service import (
    TEN_LOAI,
    chon_mau,
    kiem_goi_mau,
)
from app.utils.exceptions import (
    DataValidationError,
    ResourceNotFoundError,
    ServiceError,
)

#: Các module mà mã nguồn quyết định NỘI DUNG một bộ văn bản (F212).
MODULE_MA_DUNG = (
    bo_dung,
    _kho_mau,
    _ham_doc,
    _kho_doc,
    sys.modules[__name__],
)


def _tinh_phien_ban_ma() -> Optional[Dict[str, str]]:
    """{tên module: sha256 nội dung tệp nguồn ĐÃ NẠP}; không đọc được tệp ⇒ None (tạo bộ
    sẽ dừng, không dựng một bộ không biết mã nào đã dựng)."""
    try:
        return {
            m.__name__: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
            for m in MODULE_MA_DUNG
        }
    except (OSError, TypeError, AttributeError):  # tệp mất / module không đến từ tệp
        return None


#: Tính MỘT lần lúc nạp module — đúng các tệp mà tiến trình này đang chạy.
PHIEN_BAN_MA = _tinh_phien_ban_ma()


def don_vi_cua_bo(don_vi_ho_so: Sequence[Optional[int]]) -> Optional[int]:
    """Mọi hồ sơ cùng MỘT đơn vị khác NULL ⇒ đơn vị đó; nhiều đơn vị / có NULL / rỗng ⇒
    NULL (bộ chỉ admin xem)."""
    tap = set(don_vi_ho_so)
    if len(tap) == 1:
        (dv,) = tap
        return dv
    return None


def ngay_ky_chon_mau(
    tham_so: Optional[bo_dung.DecisionParams], luc_tao: datetime
) -> date:
    """Ngày ký để chọn mẫu: ngày Quyết định nếu có, không thì ngày tạo theo giờ Việt Nam."""
    if tham_so is not None and tham_so.ngay_quyet_dinh is not None:
        return tham_so.ngay_quyet_dinh
    return vn_calendar_date(luc_tao)


async def tao_bo_van_ban(
    db: AsyncSession,
    engine: AsyncEngine,
    *,
    ma_ho_so: Sequence[str],
    academic_year: Optional[int],
    tham_so: Optional[bo_dung.DecisionParams],
    nguoi_tao_id: Optional[int],
    luc_tao: Optional[datetime] = None,
) -> Tuple[CouncilDocumentSet, None]:
    """Đọc → chọn mẫu → dựng → ghi. Trả ``(bộ đã flush, None)``; router commit.
    ``academic_year`` BẮT BUỘC (mã hồ sơ chỉ duy nhất trong một năm học)."""
    luc_tao = luc_tao or datetime.now(timezone.utc)
    if PHIEN_BAN_MA is None:
        raise ServiceError(
            "Không đọc được mã nguồn của bộ dựng để ghi phiên bản — không dựng."
        )
    # Tham số QĐ quyết cả NGÀY KÝ (chọn mẫu) ⇒ kiểm lại ngay từ đầu, bằng đúng hàm của bộ
    # dựng (bộ dựng còn kiểm lại một lần nữa ở điểm vào của nó).
    tham_so = bo_dung.kiem_lai_tham_so_quyet_dinh(tham_so)

    # (i) đọc — giao dịch riêng, chỉ đọc, đã KẾT THÚC khi hàm này trả về.
    anh = await doc_ho_so_theo_ma(engine, ma_ho_so, academic_year=academic_year)

    # (ii) mẫu theo ngày ký
    ngay_ky = ngay_ky_chon_mau(tham_so, luc_tao)
    mau, mau_da_dung = await chon_mau(db, ngay_ky)
    for loai in bo_dung.LOAI_MAU:
        kiem_goi_mau(getattr(mau, loai), TEN_LOAI[loai])

    # (iii) dựng — CPU vài giây, ngoài event loop
    kq = await asyncio.to_thread(
        bo_dung.render_council_documents, list(anh.rows), mau, tham_so
    )

    tong = sum(len(f.content) for f in kq.files)
    if tong > settings.COUNCIL_SET_MAX_TOTAL_BYTES:
        raise DataValidationError(
            "Bộ văn bản %d byte, vượt giới hạn kỹ thuật %d byte — không lưu."
            % (tong, settings.COUNCIL_SET_MAX_TOTAL_BYTES)
        )
    for f in kq.files:  # bộ dựng tự tính sha; khẳng định lại trước khi lưu
        if hashlib.sha256(f.content).hexdigest() != f.sha256:
            raise ServiceError("sha256 của tệp sinh lệch nội dung — không lưu.")

    # (iv) ghi — phiên của request, SAVEPOINT: hỏng giữa chừng thì không còn hàng nào.
    md = dict(kq.metadata)
    md.pop("ma_ho_so_dau_vao", None)  # đã có cột riêng (PII) — không chép hai nơi
    md.pop("tham_so_quyet_dinh", None)  # đã có cột riêng
    md["mau_da_dung"] = mau_da_dung
    md["ngay_ky_chon_mau"] = ngay_ky.isoformat()
    md["nam_hoc"] = academic_year
    md["phien_ban_ma"] = dict(PHIEN_BAN_MA)
    md["giao_dich_doc"] = {
        "transaction_isolation": anh.giao_dich.transaction_isolation,
        "transaction_read_only": anh.giao_dich.transaction_read_only,
    }
    bo = CouncilDocumentSet(
        nguoi_tao_id=nguoi_tao_id,
        tao_luc=luc_tao,
        moc_chup=anh.giao_dich.moc_chup,
        unit_id=don_vi_cua_bo(anh.don_vi),
        trinh_do=kq.metadata["trinh_do"],
        so_ho_so=len(anh.rows),
        so_tep=len(kq.files),
        kich_thuoc_tong=tong,
        tham_so_quyet_dinh=kq.metadata["tham_so_quyet_dinh"],
        ma_ho_so_dau_vao=[r.ma_ho_so for r in anh.rows],
        snapshot_dto=[r.model_dump() for r in anh.rows],
        thong_tin_dung=md,
    )
    tep = [
        CouncilDocumentSetFile(
            thu_tu=i,
            path=f.path,
            sha256=f.sha256,
            kich_thuoc=len(f.content),
            noi_dung=f.content,
        )
        for i, f in enumerate(kq.files, 1)
    ]
    try:
        async with db.begin_nested():
            await CouncilDocumentRepository(db).them_bo(bo, tep)
    except DBAPIError:
        # Tham số của câu lệnh hỏng mang PII (DTO, mã) + bytes tệp ⇒ không giữ lỗi gốc.
        raise ServiceError("Lỗi CSDL khi lưu bộ văn bản — không lưu gì.") from None
    return bo, None


async def doc_tep_da_luu(db: AsyncSession, set_id: int, path: str) -> Tuple[bytes, str]:
    """(bytes, sha256) của một tệp đã lưu — KHÔNG dựng lại. Kiểm quyền / IDOR ở lượt E2
    (``deps.py``). Không có ⇒ ``ResourceNotFoundError``."""
    t = await CouncilDocumentRepository(db).tep_cua_bo(set_id, path)
    if t is None:
        raise ResourceNotFoundError("Không có tệp này trong bộ văn bản.")
    b = bytes(t.noi_dung)
    if hashlib.sha256(b).hexdigest() != t.sha256:
        raise ServiceError("Tệp đã lưu lệch sha256 — không trả.")
    return b, t.sha256
