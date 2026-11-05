# app/services/council_document_set_service.py
"""Tạo + tải lại bộ văn bản Hội đồng (giai đoạn 1 "Lần xét tuyển", PR 1.3 / 1.4 phần lưu).

Tạo bộ = bốn bước, lỗi ở BẤT KỲ bước nào ⇒ không ghi gì:

1. Đọc hồ sơ theo danh sách mã ở MỘT giao dịch ``REPEATABLE READ READ ONLY`` trên kết nối
   riêng (:func:`council_candidate_service.doc_ho_so_theo_ma`) — giao dịch ấy KẾT THÚC trước
   khi dựng; bước ghi (iv) chạy ở giao dịch KHÁC (của request — qua API đã mở từ bước xác
   thực, không bị đóng giữa chừng).
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

Xoá bộ + nhật ký tải (lượt E3 — owner 04-11, J1 dòng 29 / 31): xoá = ghi VẾT XOÁ (id bộ, số hồ
sơ, danh sách tệp + sha, người, lúc, lý do bắt buộc — không CCCD, không DTO) rồi xoá bộ, trong
CÙNG một SAVEPOINT của giao dịch request (hỏng ⇒ không xoá gì, không vết); tải một tệp = ghi
MỘT dòng nhật ký (flush ở đây; router COMMIT trước khi trả bytes — ghi lỗi ⇒ không trả). Hai
bảng vết không có khoá ngoại tới bộ ⇒ sống tiếp khi bộ bị xoá. Kiểm quyền ở ``deps.py``.
"""
import asyncio
import hashlib
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import settings
from app.constants.admission_circular import vn_calendar_date
from app.models.council_document import (
    LY_DO_XOA_TOI_DA,
    CouncilDocumentDownloadLog,
    CouncilDocumentSet,
    CouncilDocumentSetDeletion,
    CouncilDocumentSetFile,
)
from app.repositories import council_candidate_repository as _kho_doc
from app.repositories.council_document_repository import CouncilDocumentRepository
from app.services import council_candidate_service as _ham_doc
from app.services import council_document_render_service as bo_dung
from app.services import council_document_template_service as _kho_mau
from app.services import council_set_gate_service as cong
from app.services.council_candidate_service import doc_ho_so_theo_ma
from app.services.council_document_template_service import (
    TEN_LOAI,
    chon_mau,
    kiem_goi_mau,
)
from app.utils.exceptions import (
    ConflictError,
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
    cong,  # lượt G: cổng quyết hồ sơ nào vào bộ + điểm KV in
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
    xac_nhan_trang_thai: Optional[Dict[str, int]] = None,
    duoc_xac_nhan: bool = False,
) -> Tuple[CouncilDocumentSet, None]:
    """Đọc → cổng dựng bộ → chọn mẫu → dựng → ghi. Trả ``(bộ đã flush, None)``; router commit.
    ``academic_year`` BẮT BUỘC (mã hồ sơ chỉ duy nhất trong một năm học).

    Cổng (lượt G, owner 05-11 — ``council_set_gate_service``): dòng bị CHẶN (F228 trạng thái,
    F229 nguồn ngành / nguyện vọng / điểm, F231 khu vực) ⇒ 400 liệt kê từng dòng; có hồ sơ ở mức
    CẢNH BÁO ⇒ 409 trừ khi ``xac_nhan_trang_thai`` = ĐÚNG số đếm theo trạng thái hiện tại và
    người gọi ``duoc_xac_nhan`` (chỉ admin — ``deps.py`` tính). Lần xác nhận ghi vết vào
    ``thong_tin_dung`` của bộ (ai, lúc nào, bao nhiêu hồ sơ mỗi trạng thái, số dòng)."""
    luc_tao = luc_tao or datetime.now(timezone.utc)
    if PHIEN_BAN_MA is None:
        raise ServiceError(
            "Không đọc được mã nguồn của bộ dựng để ghi phiên bản — không dựng."
        )
    # Chỉ admin được gửi xác nhận — kiểm TRƯỚC khi đọc hồ sơ (không đọc dữ liệu cá nhân cho
    # một yêu cầu không có quyền xác nhận).
    xac_nhan = cong.kiem_dang_xac_nhan(xac_nhan_trang_thai)
    cong.kiem_quyen_xac_nhan(xac_nhan, duoc_xac_nhan)
    # Tham số QĐ quyết cả NGÀY KÝ (chọn mẫu) ⇒ kiểm lại ngay từ đầu, bằng đúng hàm của bộ
    # dựng (bộ dựng còn kiểm lại một lần nữa ở điểm vào của nó).
    tham_so = bo_dung.kiem_lai_tham_so_quyet_dinh(tham_so)

    # BẤT BIẾN GIAO DỊCH (F218 — Codex lần 5 chọn): đọc ở MỘT giao dịch RIÊNG ``REPEATABLE
    # READ READ ONLY`` trên kết nối riêng, đã KẾT THÚC trước khi dựng; ghi ở giao dịch KHÁC
    # (của request). KHÔNG hứa "giao dịch ghi bắt đầu sau mốc chụp": qua API, giao dịch của
    # request đã tự mở từ bước xác thực (đọc người dùng + phiên trên cùng phiên CSDL) và
    # không bị đóng giữa chừng. Test: ``test_ghi_bo_o_giao_dich_khac_giao_dich_doc`` (gọi
    # thẳng) + ``test_qua_api_doc_o_giao_dich_rieng_da_dong_truoc_khi_dung`` (POST /sets thật).
    # (i) đọc — giao dịch riêng, chỉ đọc, đã KẾT THÚC khi hàm này trả về.
    anh = await doc_ho_so_theo_ma(engine, ma_ho_so, academic_year=academic_year)

    # (i-b) cổng dựng bộ (lượt G): chặn / cảnh báo + xác nhận. Không qua ⇒ lỗi miền, KHÔNG ghi.
    if len(anh.kiem) != len(anh.rows):
        raise ServiceError("Thiếu dữ liệu kiểm hồ sơ — không dựng.")
    kq_cong = cong.danh_gia(anh.kiem)
    da_xac_nhan = cong.kiem_va_xac_nhan(
        kq_cong, xac_nhan=xac_nhan, duoc_xac_nhan=duoc_xac_nhan
    )
    # F231: điểm KV in = mức theo NĂM HỌC (cổng đã chặn mọi dòng không có mức).
    if any(m is None for m in kq_cong.diem_kv):
        raise ServiceError("Thiếu mức điểm khu vực sau cổng — không dựng.")
    hang_in = tuple(
        r.model_copy(update={"diem_kv": m}) for r, m in zip(anh.rows, kq_cong.diem_kv)
    )

    # Tối đa MỘT lần DỰNG cùng lúc trên toàn hệ (mọi worker / container cùng CSDL): khoá tư
    # vấn trên giao dịch của request — giữ tới khi router commit / rollback, tự nhả khi lỗi.
    # Trần 16 MB chỉ kiểm SAU khi dựng ⇒ đây là thứ chặn đỉnh RAM do nhiều lần dựng chồng
    # nhau (Codex lần 4). Khoá lấy sau bước đọc (như bản ``8015d068``); thứ tự khoá ↔ đọc
    # KHÔNG thuộc bất biến giao dịch ở trên. Hệ quả: lần thứ hai vẫn đọc hồ sơ (giao dịch chỉ
    # đọc) rồi mới bị từ chối — lỗi miền trước khi chọn mẫu / dựng / ghi.
    if not await CouncilDocumentRepository(db).thu_khoa_dung():
        raise ConflictError(
            "Đang dựng một bộ văn bản khác — chờ bộ ấy xong rồi thử lại."
        )

    # (ii) mẫu theo ngày ký
    ngay_ky = ngay_ky_chon_mau(tham_so, luc_tao)
    mau, mau_da_dung = await chon_mau(db, ngay_ky)
    for loai in bo_dung.LOAI_MAU:
        kiem_goi_mau(getattr(mau, loai), TEN_LOAI[loai])

    # (iii) dựng — CPU vài giây, ngoài event loop
    kq = await asyncio.to_thread(
        bo_dung.render_council_documents, list(hang_in), mau, tham_so
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
    # Lượt G — vết đọc được về sau (không dữ liệu cá nhân): số hồ sơ theo trạng thái lúc chụp;
    # lần xác nhận cảnh báo (owner 05-11: ai, lúc nào, bao nhiêu hồ sơ ở mỗi trạng thái).
    md["trang_thai_ho_so"] = kq_cong.so_theo_trang_thai()
    md["xac_nhan_canh_bao_trang_thai"] = (
        None
        if da_xac_nhan is None
        else {
            "nguoi_xac_nhan_id": nguoi_tao_id,
            "luc": luc_tao.isoformat(),
            "so_ho_so_theo_trang_thai": dict(da_xac_nhan),
            "dong_theo_trang_thai": {
                s: list(d) for s, d in kq_cong.canh_bao.items()
            },
        }
    )
    md["nguon_diem_kv"] = "muc_theo_nam_hoc_cua_ho_so"  # F231 (owner 05-11)
    bo = CouncilDocumentSet(
        nguoi_tao_id=nguoi_tao_id,
        tao_luc=luc_tao,
        moc_chup=anh.giao_dich.moc_chup,
        unit_id=don_vi_cua_bo(anh.don_vi),
        trinh_do=kq.metadata["trinh_do"],
        so_ho_so=len(hang_in),
        so_tep=len(kq.files),
        kich_thuoc_tong=tong,
        tham_so_quyet_dinh=kq.metadata["tham_so_quyet_dinh"],
        ma_ho_so_dau_vao=[r.ma_ho_so for r in hang_in],
        snapshot_dto=[r.model_dump() for r in hang_in],
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


@dataclass(frozen=True)
class TepDaLuu:
    path: str
    sha256: str
    noi_dung: bytes


async def doc_tep_da_luu(db: AsyncSession, set_id: int, thu_tu: int) -> TepDaLuu:
    """Tệp thứ ``thu_tu`` của bộ ``set_id`` = bytes ĐÃ LƯU — KHÔNG dựng lại. Kiểm quyền /
    IDOR ở ``deps.py`` (bộ đã qua ``get_council_document_set_for_user``). Không có ⇒
    ``ResourceNotFoundError``; bytes lệch sha đã lưu ⇒ ``ServiceError`` (không trả)."""
    t = await CouncilDocumentRepository(db).tep_cua_bo(set_id, thu_tu)
    if t is None:
        raise ResourceNotFoundError("Không có tệp này trong bộ văn bản.")
    b = bytes(t.noi_dung)
    if hashlib.sha256(b).hexdigest() != t.sha256:
        raise ServiceError("Tệp đã lưu lệch sha256 — không trả.")
    return TepDaLuu(path=t.path, sha256=t.sha256, noi_dung=b)


async def liet_ke_bo(
    db: AsyncSession,
    *,
    tat_ca: bool,
    chi_don_vi: Optional[int],
    limit: int,
    offset: int,
) -> List[CouncilDocumentSet]:
    """Danh sách bộ (không nạp cột dữ liệu cá nhân). ``tat_ca`` = phạm vi admin; không thì
    CHỈ bộ của đơn vị ``chi_don_vi`` (bộ ``unit_id`` NULL không bao giờ vào). Phạm vi do
    ``deps.py`` quyết; tổ hợp "không tất cả mà không có đơn vị" ⇒ ``ServiceError``
    (fail-closed — không bao giờ hiểu "không có đơn vị" thành "mọi đơn vị")."""
    if not tat_ca and chi_don_vi is None:
        raise ServiceError("Phạm vi xem bộ văn bản không xác định — không liệt kê.")
    return await CouncilDocumentRepository(db).danh_sach_bo(
        chi_don_vi=chi_don_vi, tat_ca=tat_ca, limit=limit, offset=offset
    )


async def tep_cua_bo(db: AsyncSession, set_id: int) -> List[CouncilDocumentSetFile]:
    """Metadata các tệp của một bộ (không bytes), theo thứ tự bộ dựng trả."""
    return await CouncilDocumentRepository(db).danh_sach_tep(set_id)


# ═══════════════════════════════ xoá bộ (Admin) — vết độc lập, cùng giao dịch ═════════════
def kiem_ly_do_xoa(ly_do: object) -> str:
    """Lý do xoá BẮT BUỘC (J1 dòng 29): chuỗi; bỏ khoảng trắng hai đầu; không rỗng; tối đa
    ``LY_DO_XOA_TOI_DA`` ký tự (trần KỸ THUẬT); không ký tự nhóm C ngoài xuống dòng / tab.
    Thông báo không nêu nội dung lý do."""
    if not isinstance(ly_do, str):
        raise DataValidationError("Lý do xoá bộ văn bản phải là chữ.")
    s = ly_do.strip()
    if not s:
        raise DataValidationError("Phải nhập lý do xoá bộ văn bản.")
    if len(s) > LY_DO_XOA_TOI_DA:
        raise DataValidationError(
            "Lý do xoá dài quá giới hạn kỹ thuật %d ký tự." % LY_DO_XOA_TOI_DA
        )
    if any(unicodedata.category(c)[0] == "C" and c not in "\n\r\t" for c in s):
        raise DataValidationError("Lý do xoá có ký tự điều khiển / vô hình — gõ lại.")
    return s


async def xoa_bo_van_ban(
    db: AsyncSession,
    bo: CouncilDocumentSet,
    *,
    ly_do: object,
    nguoi_xoa_id: int,
) -> Tuple[CouncilDocumentSetDeletion, None]:
    """Ghi vết xoá rồi xoá bộ ``bo`` (đã qua kiểm quyền admin ở ``deps.py``) — CÙNG một
    SAVEPOINT: lỗi ở bất kỳ câu nào ⇒ không xoá gì, không còn vết. Trả ``(vết, None)``;
    router commit. Tệp của bộ đi theo ``ON DELETE CASCADE``; nhật ký tải + vết xoá KHÔNG có
    khoá ngoại tới bộ ⇒ còn nguyên."""
    ly_do = kiem_ly_do_xoa(ly_do)
    if isinstance(nguoi_xoa_id, bool) or not isinstance(nguoi_xoa_id, int):
        raise ServiceError("Không xác định được người xoá — không xoá.")
    repo = CouncilDocumentRepository(db)
    tep = await repo.danh_sach_tep(bo.id)  # metadata, KHÔNG nạp bytes
    vet = CouncilDocumentSetDeletion(
        set_id=bo.id,
        so_ho_so=bo.so_ho_so,
        so_tep=len(tep),
        danh_sach_tep=[
            {
                "thu_tu": t.thu_tu,
                "path": t.path,
                "sha256": t.sha256,
                "kich_thuoc": t.kich_thuoc,
            }
            for t in tep
        ],
        nguoi_xoa_id=nguoi_xoa_id,
        ly_do=ly_do,
    )
    set_id = bo.id
    try:
        async with db.begin_nested():
            await repo.them_vet_xoa(vet)
            if await repo.xoa_bo(set_id) != 1:
                raise ServiceError("Bộ văn bản không còn để xoá — không xoá gì.")
    except DBAPIError:
        # Thông báo của trình điều khiển mang tham số câu lệnh (lý do, path) ⇒ không giữ.
        raise ServiceError("Lỗi CSDL khi xoá bộ văn bản — không xoá gì.") from None
    return vet, None


async def liet_ke_vet_xoa(
    db: AsyncSession, *, limit: int, offset: int
) -> List[CouncilDocumentSetDeletion]:
    return await CouncilDocumentRepository(db).danh_sach_vet_xoa(
        limit=limit, offset=offset
    )


# ═══════════════════════════════ danh sách mã đầu vào (Admin) ═════════════════════════════
async def ma_ho_so_dau_vao(db: AsyncSession, set_id: int) -> List[str]:
    """Mã hồ sơ đầu vào ĐÚNG THỨ TỰ của bộ ``set_id`` (DỮ LIỆU CÁ NHÂN — J1 dòng 30: chỉ
    Admin; quyền ở ``deps.py``). Không có ⇒ ``ResourceNotFoundError``."""
    ds = await CouncilDocumentRepository(db).ma_ho_so_dau_vao(set_id)
    if ds is None:
        raise ResourceNotFoundError("Không có bộ văn bản này.")
    if not isinstance(ds, list) or not all(isinstance(m, str) for m in ds):
        raise ServiceError("Danh sách mã đầu vào đã lưu sai dạng — không trả.")
    return ds


# ═══════════════════════════════ nhật ký tải ═══════════════════════════════════════════
async def ghi_nhat_ky_tai(
    db: AsyncSession,
    *,
    set_id: int,
    thu_tu: int,
    tep: TepDaLuu,
    nguoi_tai_id: int,
) -> Tuple[CouncilDocumentDownloadLog, None]:
    """MỘT dòng nhật ký cho lần máy chủ CẤP tệp ``thu_tu`` của bộ ``set_id`` (flush). Router
    COMMIT dòng này TRƯỚC khi trả bytes; lỗi ghi ⇒ ``ServiceError`` ⇒ không trả tệp. Ghi nhận
    việc CẤP tệp, không tuyên bố người dùng đã nhận xong."""
    if isinstance(nguoi_tai_id, bool) or not isinstance(nguoi_tai_id, int):
        raise ServiceError("Không xác định được người tải — không trả tệp.")
    dong = CouncilDocumentDownloadLog(
        set_id=set_id,
        thu_tu=thu_tu,
        path=tep.path,
        sha256=tep.sha256,
        nguoi_tai_id=nguoi_tai_id,
    )
    try:
        await CouncilDocumentRepository(db).them_nhat_ky_tai(dong)
    except DBAPIError:
        raise ServiceError("Không ghi được nhật ký tải tệp — không trả tệp.") from None
    return dong, None


async def liet_ke_nhat_ky_tai(
    db: AsyncSession, *, set_id: Optional[int], limit: int, offset: int
) -> List[CouncilDocumentDownloadLog]:
    """Nhật ký tải (mới trước) — lọc theo id bộ nếu có; bộ ĐÃ XOÁ vẫn lọc được."""
    return await CouncilDocumentRepository(db).danh_sach_nhat_ky_tai(
        set_id=set_id, limit=limit, offset=offset
    )
