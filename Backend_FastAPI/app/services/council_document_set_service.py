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
import hmac
import json
import sys
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.config import settings
from app.constants.admission_circular import vn_calendar_date
from app.models.council_document import (
    LY_DO_XOA_TOI_DA,
    CouncilDocumentDownloadLog,
    CouncilDocumentEvent,
    CouncilDocumentSet,
    CouncilDocumentSetDeletion,
    CouncilDocumentSetFile,
    CouncilDocumentSetRow,
)
from app.repositories import council_candidate_repository as _kho_doc
from app.repositories.council_decision_repository import (
    CouncilDecisionRepository,
    ma_loi_csdl,
)
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
    """Dựng bộ XÉT MỚI (``POST /sets``) — ĐỦ mọi cổng, KHÔNG nhận tham số nào nới cổng (lượt I, đặc tả
    mục 3.2 P1: test AST khoá lời gọi dưới truyền đúng HẰNG ``None``)."""
    return await _dung_va_ghi_bo(
        db,
        engine,
        ma_ho_so=ma_ho_so,
        academic_year=academic_year,
        tham_so=tham_so,
        nguoi_tao_id=nguoi_tao_id,
        luc_tao=luc_tao,
        xac_nhan_trang_thai=xac_nhan_trang_thai,
        duoc_xac_nhan=duoc_xac_nhan,
        chuoi_qd_cho_phep=None,
    )


async def tao_bo_van_ban_theo_id(
    db: AsyncSession,
    engine: AsyncEngine,
    *,
    profile_ids: Sequence[int],
    phien_ban_kiem: str,
    academic_year: Optional[int],
    tham_so: Optional[bo_dung.DecisionParams],
    nguoi_tao_id: Optional[int],
    luc_tao: Optional[datetime] = None,
    xac_nhan_trang_thai: Optional[Dict[str, int]] = None,
    duoc_xac_nhan: bool = False,
) -> Tuple[CouncilDocumentSet, None]:
    """Dựng bộ XÉT MỚI dạng id (vòng giao diện — ``POST /sets`` với ``profile_ids`` + ``phien_ban_kiem``,
    đặc tả 3.3 + bản 2/3 mục 3.1.1). ĐỦ mọi cổng như :func:`tao_bo_van_ban`, KHÔNG nhận tham số nào nới
    cổng (test AST khoá cả hàm này). Thêm: thứ tự gửi phải là thứ tự chuẩn và dấu phải khớp ⇒ không thì
    409 ``du_lieu_doi_tu_luc_kiem``."""
    if not isinstance(phien_ban_kiem, str) or not phien_ban_kiem:
        raise DataValidationError("Thiếu dấu kiểm trước (phien_ban_kiem).")
    return await _dung_va_ghi_bo(
        db,
        engine,
        ma_ho_so=(),
        academic_year=academic_year,
        tham_so=tham_so,
        nguoi_tao_id=nguoi_tao_id,
        luc_tao=luc_tao,
        xac_nhan_trang_thai=xac_nhan_trang_thai,
        duoc_xac_nhan=duoc_xac_nhan,
        chuoi_qd_cho_phep=None,
        theo_id=YeuCauTheoId(
            profile_ids=tuple(kiem_danh_sach_id(profile_ids)),
            phien_ban_kiem=phien_ban_kiem,
        ),
    )


# ═══════════════ kiểm trước + thứ tự chuẩn (vòng giao diện — đặc tả 3.1, bản 2/3 mục 3.1.1) ═══════════
#: Nhãn dẫn xuất khoá HMAC của dấu kiểm trước — khoá riêng, không dùng thẳng ``SECRET_KEY`` (khuôn
#: ``duplicate_review_token._khoa_ky``). Đổi ``SECRET_KEY`` ⇒ mọi dấu cũ lệch ⇒ 409 ⇒ "Kiểm tra lại".
_NHAN_KHOA_KIEM_TRUOC = b"council-preview-v1"
#: Phần đầu của dữ liệu băm — đổi cách băm thì đổi nhãn này.
DAU_PHIEN_BAN = "pbk-v1"
MUC_DUOC_DUNG = "duoc_dung"
MUC_CAN_XAC_NHAN = "can_xac_nhan"
MUC_BI_CHAN = "bi_chan"
MA_LOI_DOI_TU_LUC_KIEM = "du_lieu_doi_tu_luc_kiem"
CAU_DOI_TU_LUC_KIEM = "Dữ liệu đã đổi từ lúc kiểm — bấm Kiểm tra lại."


@dataclass(frozen=True)
class YeuCauTheoId:
    """``POST /sets`` dạng id: danh sách id ĐÃ kiểm (thứ tự gửi) + dấu kiểm trước nhận lại nguyên văn."""

    profile_ids: Tuple[int, ...]
    phien_ban_kiem: str


@dataclass(frozen=True)
class DongChuan:
    """MỘT dòng sau phép chuẩn hoá (đặc tả bản 3 mục 3.1.1 bước 1–2). Mọi trường trừ ``vi_tri`` vào dấu;
    ``vi_tri`` (chỉ số đầu vào, từ 0) KHÔNG băm — chỉ để biết dòng nào. Không có ``stt`` nguồn nào."""

    vi_tri: int
    pid: int
    don_vi: Optional[int]
    row: bo_dung.CandidateRowV1  # ảnh chụp NGUYÊN (chưa thay điểm KV / ĐT)
    kiem: cong.DuLieuKiem
    muc: str
    ma_ly_do: Tuple[str, ...]  # đã sắp, không trùng
    diem_kv: Optional[str]  # điểm KV IN (cổng)
    luat_ut: Optional[str]
    diem_ut: Optional[str]  # điểm đối tượng IN (cổng)
    tong_xt: float  # tổng điểm xét tuyển tính từ điểm IN — chỉ để sắp / hiển thị
    khoa: Tuple[Any, ...]  # khoá sắp chuẩn: nhóm → trong nhóm → id hồ sơ


def kiem_danh_sach_id(profile_ids: object) -> List[int]:
    """Danh sách id hồ sơ của ``kiem-truoc`` / ``POST /sets`` dạng id: số nguyên dương (không ``bool``),
    1…``COUNCIL_SET_MAX_PROFILES``, không trùng (lỗi nêu SỐ DÒNG)."""
    if not isinstance(profile_ids, (list, tuple)) or not profile_ids:
        raise DataValidationError("Danh sách hồ sơ rỗng.")
    if len(profile_ids) > settings.COUNCIL_SET_MAX_PROFILES:
        raise DataValidationError(
            "Danh sách có %d hồ sơ, vượt giới hạn kỹ thuật %d hồ sơ cho một bộ văn bản."
            % (len(profile_ids), settings.COUNCIL_SET_MAX_PROFILES)
        )
    out: List[int] = []
    gap: Dict[int, int] = {}
    for i, p in enumerate(profile_ids, 1):
        if isinstance(p, bool) or not isinstance(p, int) or p < 1:
            raise DataValidationError("Dòng %d: id hồ sơ không hợp lệ." % i)
        if p in gap:
            raise DataValidationError(
                "Dòng %d trùng hồ sơ với dòng %d — mỗi người một dòng." % (i, gap[p])
            )
        gap[p] = i
        out.append(p)
    return out


def chuan_hoa(anh: "_ham_doc.AnhChupHoSo", kq_cong: "cong.KetQuaCong") -> List[DongChuan]:
    """MỘT phép chuẩn hoá (đặc tả bản 3 mục 3.1.1) — ``kiem-truoc`` và ``POST /sets`` dạng id cùng gọi.

    1. Gom theo dòng: ảnh chụp + dữ liệu kiểm + id + đơn vị + kết quả cổng CỦA RIÊNG dòng ấy (rút từ
       ``KetQuaCong`` bằng ``stt`` nguồn — chỉ dùng ở bước này).
    2. Không giữ giá trị nào phụ thuộc vị trí đầu vào: ``DuLieuKiem.stt`` bỏ ở :func:`dau_kiem_truoc`;
       ``CandidateRowV1`` không có trường vị trí; câu lý do không băm, chỉ mã.
    3. Sắp bằng khoá chung của Quyết định (``khoa_nhom_quyet_dinh`` → ``khoa_trong_nhom_quyet_dinh``) + phá
       hoà cuối bằng id hồ sơ."""
    n = len(anh.rows)
    if not (
        len(anh.kiem) == len(anh.pids) == len(anh.don_vi) == n
        and len(kq_cong.diem_kv) == len(kq_cong.luat_ut) == n
    ):
        raise ServiceError("Ảnh chụp / kết quả cổng không đủ dòng — không kiểm.")
    ma_theo_stt: Dict[int, set] = {}
    for ma, _tt, dong in kq_cong.chan:
        for s in dong:
            ma_theo_stt.setdefault(s, set()).add(ma)
    canh_bao = {s for d in kq_cong.canh_bao.values() for s in d}
    out: List[DongChuan] = []
    for i in range(n):
        k, r, pid = anh.kiem[i], anh.rows[i], anh.pids[i]
        ma = tuple(sorted(ma_theo_stt.get(k.stt, ())))
        muc = (
            MUC_BI_CHAN
            if ma
            else (MUC_CAN_XAC_NHAN if k.stt in canh_bao else MUC_DUOC_DUNG)
        )
        kv = kq_cong.diem_kv[i]
        lu = kq_cong.luat_ut[i]
        ut = cong.diem_ut_in(lu, r.diem_ut)
        # Điểm IN chưa có (dòng bị chặn) ⇒ ô rỗng ⇒ ``so`` đọc 0: vẫn sắp được, như nhau ở hai phía.
        tong = bo_dung.tinh_diem_in(r.tong_diem, kv or "", ut or "").tong_xt
        out.append(
            DongChuan(
                vi_tri=i,
                pid=pid,
                don_vi=anh.don_vi[i],
                row=r,
                kiem=k,
                muc=muc,
                ma_ly_do=ma,
                diem_kv=kv,
                luat_ut=lu,
                diem_ut=ut,
                tong_xt=tong,
                khoa=(
                    bo_dung.khoa_nhom_quyet_dinh(r),
                    bo_dung.khoa_trong_nhom_quyet_dinh(tong, r.ten),
                    pid,
                ),
            )
        )
    out.sort(key=lambda d: d.khoa)
    return out


def _khoa_kiem_truoc() -> bytes:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"), _NHAN_KHOA_KIEM_TRUOC, hashlib.sha256
    ).digest()


def dau_kiem_truoc(dong: Sequence[DongChuan], academic_year: int) -> str:
    """MỘT hàm dấu (đặc tả bản 2 mục 3.1.1 + bản 3): HMAC-SHA256 (khoá suy từ ``SECRET_KEY``) của JSON
    chuẩn (khoá sắp, không khoảng trắng) gồm phần đầu (nhãn, năm học, luật dựng, phiên bản mã dựng) + mỗi
    dòng ĐÃ SẮP: ``stt_chuan``, TOÀN BỘ ảnh chụp in, TOÀN BỘ dữ liệu kiểm trừ ``stt``, id, đơn vị, mức, mã
    lý do, điểm KV / luật ĐT / điểm ĐT in. KHÔNG băm mốc giao dịch. Không ghi dấu vào log."""
    if PHIEN_BAN_MA is None:
        raise ServiceError(
            "Không đọc được mã nguồn của bộ dựng để ghi phiên bản — không kiểm."
        )
    du_lieu = {
        "dau": [DAU_PHIEN_BAN, academic_year, bo_dung.LUAT_RENDER, PHIEN_BAN_MA],
        "dong": [
            {
                "stt_chuan": stt,
                "row": d.row.model_dump(mode="json"),
                "kiem": {k: v for k, v in asdict(d.kiem).items() if k != "stt"},
                "pid": d.pid,
                "don_vi": d.don_vi,
                "muc": d.muc,
                "ma_ly_do": list(d.ma_ly_do),
                "diem_kv": d.diem_kv,
                "luat_ut": d.luat_ut,
                "diem_ut": d.diem_ut,
            }
            for stt, d in enumerate(dong, 1)
        ],
    }
    b = json.dumps(
        du_lieu, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hmac.new(_khoa_kiem_truoc(), b, hashlib.sha256).hexdigest()


def so_voi_kiem_truoc(
    anh: "_ham_doc.AnhChupHoSo",
    kq_cong: "cong.KetQuaCong",
    academic_year: int,
    yeu_cau: YeuCauTheoId,
) -> None:
    """``POST /sets`` dạng id (đặc tả bản 2 mục 3.1.1 bước 2 + 4): thứ tự gửi khác thứ tự chuẩn của ảnh
    chụp, HOẶC dấu tính lại khác dấu đã kiểm (so bằng ``hmac.compare_digest``) ⇒ 409
    ``du_lieu_doi_tu_luc_kiem``. Không tự sắp lại."""
    dc = chuan_hoa(anh, kq_cong)
    dung_thu_tu = [d.pid for d in dc] == list(yeu_cau.profile_ids)
    khop_dau = hmac.compare_digest(
        dau_kiem_truoc(dc, academic_year).encode("ascii"),
        yeu_cau.phien_ban_kiem.encode("utf-8"),
    )
    if not (dung_thu_tu and khop_dau):
        raise ConflictError(
            CAU_DOI_TU_LUC_KIEM, public_payload={"ma_loi": MA_LOI_DOI_TU_LUC_KIEM}
        )


async def kiem_truoc(
    engine: AsyncEngine,
    *,
    profile_ids: Sequence[int],
    academic_year: Optional[int],
    tat_ca: bool,
    chi_don_vi: Optional[int],
    duoc_xac_nhan: bool,
) -> Dict[str, Any]:
    """``POST /sets/kiem-truoc`` (đặc tả 3.1 + bản 2/3 mục 3.1.1): đọc (cùng đường đọc của bộ dựng, lọc phạm
    vi), cổng (``cong.danh_gia`` — không luật thứ hai), chuẩn hoá + dấu. KHÔNG ghi gì, KHÔNG lấy khoá tư vấn
    dựng. Mọi chữ hiển thị (họ tên, ngành, đường xét, điểm in) lấy từ CÙNG ảnh chụp / kết quả cổng đã băm."""
    nam = _ham_doc.kiem_nam_hoc(academic_year)
    ds = kiem_danh_sach_id(profile_ids)
    anh, khong_tim_thay = await _ham_doc.doc_ho_so_kiem_truoc(
        engine, ds, academic_year=nam, tat_ca=tat_ca, chi_don_vi=chi_don_vi
    )
    if anh is None:
        dc: List[DongChuan] = []
        kiem_luc = datetime.now(timezone.utc)
        so_canh_bao: Dict[str, int] = {}
    else:
        kq = cong.danh_gia(anh.kiem)
        dc = chuan_hoa(anh, kq)
        kiem_luc = anh.giao_dich.moc_chup
        so_canh_bao = kq.so_canh_bao()
    dong_out: List[Dict[str, Any]] = []
    nhom: Dict[Tuple[str, str], int] = {}
    for stt, d in enumerate(dc, 1):
        ng = bo_dung.khoa_nhom_quyet_dinh(d.row)
        nhom[ng] = nhom.get(ng, 0) + 1
        dong_out.append(
            {
                "stt": stt,
                "stt_qd": nhom[ng],
                "profile_id": d.pid,
                "ho_ten": ("%s %s" % (d.row.ho.strip(), d.row.ten.strip())).strip(),
                "trang_thai": d.kiem.status if isinstance(d.kiem.status, str) else "",
                "nganh_nhan": ng[0],
                "trinh_do": ng[1],
                "duong_xet_nhan": d.row.phuong_thuc.strip() or None,
                "diem_in": (
                    "%.2f" % d.tong_xt
                    if d.diem_kv is not None and d.diem_ut is not None
                    else None
                ),
                "muc": d.muc,
                "ly_do": [{"ma": m, "cau": cong.LY_DO.get(m, m)} for m in d.ma_ly_do],
            }
        )
    dem_muc = {
        m: sum(1 for d in dc if d.muc == m)
        for m in (MUC_DUOC_DUNG, MUC_CAN_XAC_NHAN, MUC_BI_CHAN)
    }
    return {
        "kiem_luc": kiem_luc,
        "phien_ban_kiem": dau_kiem_truoc(dc, nam),
        "dong": dong_out,
        "khong_tim_thay": khong_tim_thay,
        "tom_tat": {
            "tong": len(dc),
            "duoc_dung": dem_muc[MUC_DUOC_DUNG],
            "can_xac_nhan": dem_muc[MUC_CAN_XAC_NHAN],
            "bi_chan": dem_muc[MUC_BI_CHAN],
            "theo_nganh": [
                {"nganh_nhan": ng[0], "trinh_do": ng[1], "so": so}
                for ng, so in nhom.items()
            ],
            "can_xac_nhan_theo_trang_thai": so_canh_bao,
            "so_nhom": len(nhom),
            "du_kien_so_tep": 2 + 2 * len(nhom),
            "nguoi_goi_duoc_xac_nhan": bool(duoc_xac_nhan),
        },
    }


async def _dung_va_ghi_bo(
    db: AsyncSession,
    engine: AsyncEngine,
    *,
    ma_ho_so: Sequence[str],
    academic_year: Optional[int],
    tham_so: Optional[bo_dung.DecisionParams],
    nguoi_tao_id: Optional[int],
    luc_tao: Optional[datetime],
    xac_nhan_trang_thai: Optional[Dict[str, int]],
    duoc_xac_nhan: bool,
    chuoi_qd_cho_phep: Optional[int],
    theo_id: Optional["YeuCauTheoId"] = None,
) -> Tuple[CouncilDocumentSet, None]:
    """Đọc → cổng dựng bộ → chọn mẫu → dựng → ghi. Trả ``(bộ đã flush, None)``; router commit.
    ``theo_id`` (vòng giao diện — ``POST /sets`` dạng id): đọc theo id thay cho mã, rồi so thứ tự + dấu kiểm
    trước (:func:`so_voi_kiem_truoc`) TRƯỚC cổng chặn / xác nhận; ``ma_ho_so`` khi ấy bỏ qua.
    ``chuoi_qd_cho_phep`` (CHỈ bộ dữ liệu cho văn bản điều chỉnh — :func:`tao_bo_dieu_chinh`) nới đúng
    MỘT phép: hồ sơ có dòng hiệu lực trong chính chuỗi Quyết định ấy; bộ ghi
    ``cho_quyet_dinh_goc_id`` = chuỗi ấy (chỉ dùng được cho điều chỉnh của chuỗi).
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
    # (i) đọc — giao dịch riêng, chỉ đọc, đã KẾT THÚC khi hàm này trả về. Dạng id (vòng giao diện,
    # đặc tả bản 2 mục 3.1.1 bước 1): đọc ĐÚNG MỘT lần; từ đây tới khi ghi không đọc hồ sơ lần nào nữa
    # — mọi thứ (so thứ tự, dấu, cổng, hàng in, dòng bộ) lấy từ CÙNG ``anh``.
    if theo_id is None:
        anh = await doc_ho_so_theo_ma(engine, ma_ho_so, academic_year=academic_year)
    else:
        anh = await _ham_doc.doc_ho_so_theo_id(
            engine, theo_id.profile_ids, academic_year=academic_year
        )

    # (i-b) cổng dựng bộ (lượt G): chặn / cảnh báo + xác nhận. Không qua ⇒ lỗi miền, KHÔNG ghi.
    if len(anh.kiem) != len(anh.rows):
        raise ServiceError("Thiếu dữ liệu kiểm hồ sơ — không dựng.")
    if len(anh.pids) != len(anh.rows):
        raise ServiceError("Thiếu id hồ sơ của dòng — không dựng.")
    kq_cong = cong.danh_gia(anh.kiem, chuoi_qd_cho_phep=chuoi_qd_cho_phep)
    if theo_id is not None:
        # Đặc tả bản 2 mục 3.1.1 bước 2 + 4: thứ tự gửi = thứ tự chuẩn của CHÍNH ảnh chụp này, và dấu tính
        # lại = dấu đã kiểm ⇒ mới đi tiếp tới cổng chặn / xác nhận. Lệch ⇒ 409, không tự sắp lại.
        so_voi_kiem_truoc(anh, kq_cong, academic_year, theo_id)
    da_xac_nhan = cong.kiem_va_xac_nhan(
        kq_cong, xac_nhan=xac_nhan, duoc_xac_nhan=duoc_xac_nhan
    )
    # F231: điểm KV in = mức theo NĂM HỌC (cổng đã chặn mọi dòng không có mức); câu 22: đường
    # xét tắt / không có luật cộng KV ⇒ 0 (cổng tính — ``diem_kv_in``).
    if any(m is None for m in kq_cong.diem_kv):
        raise ServiceError("Thiếu mức điểm khu vực sau cổng — không dựng.")
    # Lượt H2 (owner 06-11): điểm đối tượng in theo công tắc của đường xét — bật thì GIỮ điểm luật v1
    # của DTO, tắt / không có luật thì 0 (cổng tính — ``diem_ut_in``).
    diem_ut = tuple(
        cong.diem_ut_in(lu, r.diem_ut) for lu, r in zip(kq_cong.luat_ut, anh.rows)
    )
    if len(diem_ut) != len(anh.rows) or any(u is None for u in diem_ut):
        raise ServiceError("Thiếu luật cộng điểm đối tượng sau cổng — không dựng.")
    hang_in = tuple(
        r.model_copy(update={"diem_kv": m, "diem_ut": u})
        for r, m, u in zip(anh.rows, kq_cong.diem_kv, diem_ut)
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
            "dong_theo_trang_thai": {s: list(d) for s, d in kq_cong.canh_bao.items()},
        }
    )
    md["nguon_diem_kv"] = "muc_theo_nam_hoc_cua_ho_so"  # F231 (owner 05-11)
    # Câu 22 (owner 06-11): điểm KV in theo luật cộng điểm của đường xét — số hồ sơ theo luật
    # (``cong`` / ``tat`` / ``khong_co_luat``) để đọc lại được vì sao một dòng in 0.
    md["luat_diem_kv"] = "theo_luat_cong_diem_cua_duong_xet"
    md["so_ho_so_theo_luat_kv"] = kq_cong.so_theo_luat_kv()
    # Lượt H2: công tắc đối tượng của đường xét (cách suy + trần giữ luật v1).
    md["luat_diem_ut"] = "cong_tac_doi_tuong_cua_duong_xet_cach_tinh_v1"
    md["so_ho_so_theo_luat_ut"] = kq_cong.so_theo_luat_ut()
    # Lượt I (F230): hồ sơ đang ở bộ khác — BÁO (id bộ + số đếm), không chặn (SPEC §13 câu 4).
    md["ho_so_o_bo_khac"] = {
        str(k): v
        for k, v in (
            await CouncilDecisionRepository(db).ho_so_o_bo_khac(list(anh.pids))
        ).items()
    }
    if chuoi_qd_cho_phep is not None:
        md["cho_quyet_dinh_goc_id"] = chuoi_qd_cho_phep
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
        cho_quyet_dinh_goc_id=chuoi_qd_cho_phep,
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
    dong = [
        _dong_bo_tu_kiem(k, pid, academic_year)
        for k, pid in zip(anh.kiem, anh.pids)
    ]
    su_kien = {
        "so_ho_so": len(hang_in),
        "trang_thai_ho_so": md["trang_thai_ho_so"],
        "xac_nhan_canh_bao": (
            None if da_xac_nhan is None else dict(da_xac_nhan)
        ),
        "ho_so_o_bo_khac": md["ho_so_o_bo_khac"],
    }
    await _ghi_bo_va_dong(
        db,
        bo,
        tep,
        dong,
        loai_su_kien="tao_bo" if chuoi_qd_cho_phep is None else "tao_bo_dieu_chinh",
        so_lieu=su_kien,
        nguoi_id=nguoi_tao_id,
        decision_id=chuoi_qd_cho_phep,
    )
    return bo, None


def _dong_bo_tu_kiem(
    k: "cong.DuLieuKiem", pid: int, academic_year: int
) -> CouncilDocumentSetRow:
    """MỘT dòng bộ từ dữ liệu kiểm ĐÃ ĐỌC trong giao dịch chỉ đọc (id hồ sơ, trạng thái lúc dựng,
    khoá đếm của NV in — ảnh chụp)."""
    if isinstance(pid, bool) or not isinstance(pid, int):
        raise ServiceError("Id hồ sơ của dòng không hợp lệ — không dựng.")
    return CouncilDocumentSetRow(
        stt=k.stt,
        profile_id=pid,
        academic_year=academic_year,
        status_luc_dung=k.status if isinstance(k.status, str) else "(khong_ro)",
        nv_in_id=k.nv_in_id,
        admission_path_id=k.nv_in_path_id,
        academic_info_id=k.nv_in_ai_id,
        offering_id=k.nv_in_offering_id,
        major_id=k.hp_nganh_id,
    )


async def _ghi_bo_va_dong(
    db: AsyncSession,
    bo: CouncilDocumentSet,
    tep: Sequence[CouncilDocumentSetFile],
    dong: Sequence[CouncilDocumentSetRow],
    *,
    loai_su_kien: str,
    so_lieu: Dict[str, object],
    nguoi_id: Optional[int],
    decision_id: Optional[int] = None,
) -> None:
    """Ghi bộ + tệp + dòng bộ + MỘT dòng sự kiện trong CÙNG SAVEPOINT (hỏng ⇒ không còn hàng nào)."""
    if [d.stt for d in dong] != list(range(1, bo.so_ho_so + 1)):
        raise ServiceError("Dòng bộ không khớp số hồ sơ — không lưu.")
    try:
        async with db.begin_nested():
            await CouncilDocumentRepository(db).them_bo(bo, tep)
            for d in dong:
                d.set_id = bo.id
            await CouncilDecisionRepository(db).them(
                *dong,
                CouncilDocumentEvent(
                    loai=loai_su_kien,
                    set_id=bo.id,
                    decision_id=decision_id,
                    nguoi_id=nguoi_id,
                    so_lieu=so_lieu,
                ),
            )
    except DBAPIError:
        # Tham số của câu lệnh hỏng mang PII (DTO, mã) + bytes tệp ⇒ không giữ lỗi gốc.
        raise ServiceError("Lỗi CSDL khi lưu bộ văn bản — không lưu gì.") from None


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


# ═══════════════ danh sách / chi tiết bộ mở rộng + tải cả bộ (vòng giao diện — đặc tả 3.4–3.6) ═══════════════
def _bo_mo_rong_ra(r: Dict[str, Any], *, xem_luot: bool) -> Dict[str, Any]:
    """MỘT hàng của ``SQL_BO_MO_RONG`` → các trường của ``CouncilSetOut``. ``quyet_dinh`` = văn bản chưa huỷ ghi nhận
    mới nhất (``SQL_BO_MO_RONG`` — nguồn duy nhất) — giữ các khoá cũ (loai, trang_thai, so_quyet_dinh, ngay_ky, so_ho_so)
    + ``id`` + ``goc``. ``luot_gui_cho`` CHỈ khi ``xem_luot`` (người có quyền ghi nhận); người khác luôn None."""
    qd = None
    if r["qd_id"] is not None:
        qd = {
            "id": r["qd_id"],
            "loai": r["qd_loai"],
            "trang_thai": r["qd_trang_thai"],
            "so_quyet_dinh": r["qd_so"],
            "ngay_ky": r["qd_ngay_ky"].isoformat(),
            "so_ho_so": r["qd_so_ho_so"],
            "goc": (
                None
                if r["goc_id"] is None
                else {
                    "id": r["goc_id"],
                    "so_quyet_dinh": r["goc_so"],
                    "ngay_ky": r["goc_ngay_ky"].isoformat(),
                }
            ),
        }
    return {
        "id": r["id"],
        "nguoi_tao_id": r["nguoi_tao_id"],
        "tao_luc": r["tao_luc"],
        "moc_chup": r["moc_chup"],
        "unit_id": r["unit_id"],
        "trinh_do": r["trinh_do"],
        "so_ho_so": r["so_ho_so"],
        "so_tep": r["so_tep"],
        "kich_thuoc_tong": r["kich_thuoc_tong"],
        "nam_hoc": None if r["nam_hoc"] is None else int(r["nam_hoc"]),
        "tham_so_quyet_dinh": r["tham_so_quyet_dinh"],
        "nguoi_tao_ten": r["nguoi_tao_ten"],
        "tinh_trang": r["tinh_trang"],
        "quyet_dinh": qd,
        "luot_gui_cho": (
            {"ma": r["luot_ma"], "tao_luc": r["luot_tao_luc"]}
            if xem_luot and r["luot_ma"] is not None
            else None
        ),
    }


async def liet_ke_bo_mo_rong(
    db: AsyncSession,
    *,
    tat_ca: bool,
    chi_don_vi: Optional[int],
    nam_hoc: Optional[int] = None,
    nguoi_tao_id: Optional[int] = None,
    so_quyet_dinh: Optional[str] = None,
    tinh_trang: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """``GET /sets`` (đặc tả 3.4) — MỘT câu (``SQL_BO_MO_RONG``). Phạm vi do ``deps.py`` quyết; "không tất cả mà không có
    đơn vị" ⇒ ``ServiceError`` (fail-closed). ``luot_gui_cho`` chỉ với phạm vi admin (= người có quyền ghi nhận)."""
    if not tat_ca and chi_don_vi is None:
        raise ServiceError("Phạm vi xem bộ văn bản không xác định — không liệt kê.")
    ds = await CouncilDocumentRepository(db).danh_sach_bo_mo_rong(
        tat_ca=tat_ca,
        chi_don_vi=chi_don_vi,
        nam_hoc=nam_hoc,
        nguoi_tao_id=nguoi_tao_id,
        so_quyet_dinh=so_quyet_dinh,
        tinh_trang=tinh_trang,
        limit=limit,
        offset=offset,
    )
    return [_bo_mo_rong_ra(r, xem_luot=tat_ca) for r in ds]


async def chi_tiet_bo_mo_rong(
    db: AsyncSession, set_id: int, *, tat_ca: bool
) -> Dict[str, Any]:
    """``GET /sets/{id}`` (đặc tả 3.5) — CÙNG câu với danh sách (một nguồn cho tình trạng / Quyết định). Bộ đã qua kiểm
    phạm vi ở ``deps.py`` ⇒ đọc theo id không lọc đơn vị."""
    ds = await CouncilDocumentRepository(db).danh_sach_bo_mo_rong(
        tat_ca=True, chi_don_vi=None, set_id=set_id, limit=1, offset=0
    )
    if not ds:
        raise ResourceNotFoundError("Không có bộ văn bản này.")
    return _bo_mo_rong_ra(ds[0], xem_luot=tat_ca)


async def nguoi_tao_bo(
    db: AsyncSession, *, tat_ca: bool, chi_don_vi: Optional[int]
) -> List[Dict[str, Any]]:
    """Người tạo PHÂN BIỆT của các bộ trong phạm vi người gọi (bộ lọc "Người tạo")."""
    if not tat_ca and chi_don_vi is None:
        raise ServiceError("Phạm vi xem bộ văn bản không xác định — không liệt kê.")
    return await CouncilDocumentRepository(db).nguoi_tao_bo(
        tat_ca=tat_ca, chi_don_vi=chi_don_vi
    )


async def ten_nguoi_dung(db: AsyncSession, ids: Sequence[int]) -> Dict[int, str]:
    """{id: tên hiển thị} — nhật ký tải / vết xoá hiện tên thay "Tài khoản #n"."""
    return await CouncilDocumentRepository(db).ten_nguoi_dung(ids)


async def doc_ca_bo(db: AsyncSession, set_id: int) -> List[Tuple[int, TepDaLuu]]:
    """``GET /sets/{id}/tai-ca-bo`` (đặc tả 3.6) bước 1–2: đọc MỌI tệp đã lưu (bytes NGUYÊN, không dựng lại), tính lại
    sha256 TỪNG tệp so cột ``sha256`` — lệch ⇒ ``ServiceError`` "tệp đã lưu hỏng", không trả gì; kiểm lại trần tổng
    ``COUNCIL_SET_MAX_TOTAL_BYTES``. Trả ``[(thu_tu, tệp)]`` theo thứ tự. Kiểm quyền / IDOR ở ``deps.py``."""
    ds = await CouncilDocumentRepository(db).tep_cua_bo_kem_noi_dung(set_id)
    if not ds:
        raise ResourceNotFoundError("Bộ văn bản không có tệp nào.")
    out: List[Tuple[int, TepDaLuu]] = []
    tong = 0
    for t in ds:
        b = bytes(t.noi_dung)
        if hashlib.sha256(b).hexdigest() != t.sha256:
            raise ServiceError(
                "Tệp đã lưu hỏng (thứ tự %d lệch sha256) — không trả bộ." % t.thu_tu
            )
        tong += len(b)
        out.append((t.thu_tu, TepDaLuu(path=t.path, sha256=t.sha256, noi_dung=b)))
    if tong > settings.COUNCIL_SET_MAX_TOTAL_BYTES:
        raise ServiceError(
            "Bộ văn bản %d byte, vượt giới hạn kỹ thuật %d byte — không trả."
            % (tong, settings.COUNCIL_SET_MAX_TOTAL_BYTES)
        )
    return out


def nen_ca_bo(tep: Sequence[TepDaLuu], moc: datetime) -> bytes:
    """Nén ĐÚNG bytes đã lưu thành một tệp zip — tên trong zip = ``path`` đã lưu (không đổi, không dựng lại); giờ của
    mọi mục = ``moc`` (giờ Việt Nam của lúc tạo bộ) ⇒ cùng bộ cho cùng zip. Chạy NGOÀI event loop (CPU)."""
    import io
    import zipfile

    from app.constants.admission_circular import VN_TZ

    gio = moc.astimezone(VN_TZ).timetuple()[:6]
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for t in tep:
            info = zipfile.ZipInfo(t.path, date_time=max(gio, (1980, 1, 1, 0, 0, 0)))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, t.noi_dung)
    return b.getvalue()


# ═══════════════════════════════ xoá bộ (Admin) — vết độc lập, cùng giao dịch ═════════════
def kiem_ly_do(ly_do: object, viec: str) -> str:
    """Lý do / ghi chú BẮT BUỘC của một thao tác (MỘT nguồn — xoá bộ J1 dòng 29; lượt I: huỷ ghi
    nhận, cho xét lại, tái dựng bản ký, ghi chú mẫu): chuỗi; bỏ khoảng trắng hai đầu; không rỗng;
    tối đa ``LY_DO_XOA_TOI_DA`` ký tự (trần KỸ THUẬT); không ký tự nhóm C ngoài xuống dòng / tab.
    Thông báo không nêu nội dung."""
    if not isinstance(ly_do, str):
        raise DataValidationError("Lý do %s phải là chữ." % viec)
    s = ly_do.strip()
    if not s:
        raise DataValidationError("Phải nhập lý do %s." % viec)
    if len(s) > LY_DO_XOA_TOI_DA:
        raise DataValidationError(
            "Lý do %s dài quá giới hạn kỹ thuật %d ký tự." % (viec, LY_DO_XOA_TOI_DA)
        )
    if any(unicodedata.category(c)[0] == "C" and c not in "\n\r\t" for c in s):
        raise DataValidationError(
            "Lý do %s có ký tự điều khiển / vô hình — gõ lại." % viec
        )
    return s


def kiem_ly_do_xoa(ly_do: object) -> str:
    """Lý do xoá bộ BẮT BUỘC (J1 dòng 29) — :func:`kiem_ly_do`."""
    return kiem_ly_do(ly_do, "xoá bộ văn bản")


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
    qd_repo = CouncilDecisionRepository(db)
    # Vòng giao diện (đặc tả bản 2 mục 3.7.6, F269 / F272): câu ĐẦU khoá dòng bộ ``FOR UPDATE`` — mở lượt gửi (INSERT
    # có khoá ngoại ⇒ ``KEY SHARE`` trên bộ) không chen được sau bước kiểm lượt bên dưới.
    if await qd_repo.khoa_bo(bo.id) is None:
        raise ResourceNotFoundError("Không có bộ văn bản này.")
    # Lượt I (F230): bộ của văn bản ĐÃ KÝ còn / hết hiệu lực là hồ sơ lưu trữ ⇒ KHÔNG xoá (J1 dòng 8;
    # số năm lưu chưa có — J5 M1). Báo 409 trước; CSDL chặn cuối (K4 / K5b — đặc tả mục 4.1).
    song = await qd_repo.van_ban_song_cua_bo(bo.id)
    if song:
        raise ConflictError(
            "Bộ văn bản là bản in của Quyết định đã ký (văn bản #%s) — lưu theo hạn lưu trữ, "
            "không xoá. Chỉ xoá được khi mọi ghi nhận của bộ đã huỷ ghi nhận."
            % ", #".join(str(d.id) for d in song),
            public_payload={"quyet_dinh_id": [d.id for d in song]},
        )
    # Lượt gửi chưa rõ kết quả ⇒ 409 (đọc KHÔNG khoá, không chờ dòng lượt nào — F272). CSDL chặn cuối: khoá ngoại
    # ON DELETE SET NULL + CHECK ``ck_council_decision_submission_cho_co_bo``. Lượt đã kết thúc giữ lại (set_id NULL).
    from app.services.council_decision_submission_service import co_luot_cho_gui

    cho = await co_luot_cho_gui(db, bo.id)
    if cho is not None:
        raise ConflictError(
            "Bộ đang có lượt gửi ghi nhận chưa rõ kết quả — phân xử (Kiểm tra trên máy chủ) trước khi xoá.",
            public_payload={"ma_loi": "bo_co_luot_gui_chua_ro", "ma": str(cho.ma)},
        )
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
            # Dòng của các ghi nhận ĐÃ HUỶ trỏ bộ này: dọn liên kết TRƯỚC khi xoá (thứ tự hai hành
            # động tham chiếu của PostgreSQL có thể để ``set_row_id`` trỏ dòng bộ đã xoá — đo lượt I).
            await db.execute(
                text(
                    "UPDATE council_decision_row SET set_row_id = NULL, set_id = NULL "
                    "WHERE set_id = :s AND trang_thai_cha = 'huy_ghi_nhan'"
                ),
                {"s": set_id},
            )
            await qd_repo.them(
                CouncilDocumentEvent(
                    loai="xoa_bo",
                    set_id=set_id,
                    nguoi_id=nguoi_xoa_id,
                    so_lieu={"so_ho_so": bo.so_ho_so, "so_tep": len(tep)},
                )
            )
            if await repo.xoa_bo(set_id) != 1:
                raise ServiceError("Bộ văn bản không còn để xoá — không xoá gì.")
    except DBAPIError as e:
        sqlstate, rang_buoc = ma_loi_csdl(e)
        if sqlstate == "23514" and rang_buoc in (
            "ck_council_decision_k4",
            "ck_council_decision_row_k5b",
        ):
            # Tầng chủ sở hữu (CSDL) chặn — một phiên khác vừa ghi nhận bộ này.
            raise ConflictError(
                "Bộ văn bản là bản in của Quyết định đã ký — không xoá."
            ) from None
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


# ═══════════════════ Lượt I (F230) — bộ cho điều chỉnh · tái dựng bản ký · so với hiện tại ═════════
async def tao_bo_dieu_chinh(
    db: AsyncSession,
    engine: AsyncEngine,
    goc_id: int,
    *,
    ma_ho_so: Sequence[str],
    academic_year: Optional[int],
    tham_so: Optional[bo_dung.DecisionParams],
    nguoi_tao_id: Optional[int],
    xac_nhan_trang_thai: Optional[Dict[str, int]] = None,
    duoc_xac_nhan: bool = False,
) -> Tuple[CouncilDocumentSet, None]:
    """Bộ DỮ LIỆU cho văn bản điều chỉnh của chuỗi ``goc_id`` (C6: văn thư soạn văn bản; phần mềm cần dữ
    liệu của em được thêm / sửa). CÙNG đường dựng bộ (đọc chỉ đọc + đủ cổng), chỉ nới đúng MỘT phép: hồ
    sơ có dòng hiệu lực trong CHÍNH chuỗi ấy (ca "sửa thông tin em C" — BS §1.3)."""
    goc = await CouncilDecisionRepository(db).qd_theo_id(goc_id)
    if goc is None:
        raise ResourceNotFoundError("Không có Quyết định này.")
    if goc.loai != "trung_tuyen" or goc.trang_thai != "hieu_luc":
        raise ConflictError("Chỉ dựng bộ điều chỉnh cho Quyết định trúng tuyển đang hiệu lực.")
    return await _dung_va_ghi_bo(
        db,
        engine,
        ma_ho_so=ma_ho_so,
        academic_year=academic_year,
        tham_so=tham_so,
        nguoi_tao_id=nguoi_tao_id,
        luc_tao=None,
        xac_nhan_trang_thai=xac_nhan_trang_thai,
        duoc_xac_nhan=duoc_xac_nhan,
        chuoi_qd_cho_phep=goc.id,
    )


async def _anh_chup_da_luu(db: AsyncSession, set_id: int) -> List[dict]:
    """Ảnh chụp DTO đã lưu của bộ (cột deferred — đọc tường minh)."""
    from sqlalchemy import select

    ds = (
        await db.execute(
            select(CouncilDocumentSet.snapshot_dto).where(CouncilDocumentSet.id == set_id)
        )
    ).scalar_one()
    if not isinstance(ds, list):
        raise ServiceError("Ảnh chụp đã lưu sai dạng — không dùng.")
    return ds


async def _mau_theo_id(db: AsyncSession, mau_da_dung: Dict[str, Dict[str, object]]):
    """Ba mẫu ĐÚNG như bộ in ban đầu đã dùng (id + sha; kiểm lại gói)."""
    from sqlalchemy import select
    from sqlalchemy.orm import undefer

    from app.models.council_document import CouncilDocumentTemplate

    out = {}
    for loai in bo_dung.LOAI_MAU:
        m = (mau_da_dung or {}).get(loai) or {}
        mau = (
            await db.execute(
                select(CouncilDocumentTemplate)
                .options(undefer(CouncilDocumentTemplate.noi_dung))
                .where(CouncilDocumentTemplate.id == m.get("id"))
            )
        ).scalar_one_or_none()
        if (
            mau is None
            or mau.sha256 != m.get("sha256")
            or hashlib.sha256(bytes(mau.noi_dung)).hexdigest() != mau.sha256
        ):
            raise ServiceError("Không còn đúng mẫu bộ in ban đầu đã dùng — không tái dựng.")
        out[loai] = bytes(mau.noi_dung)
        kiem_goi_mau(out[loai], TEN_LOAI[loai])
    return bo_dung.CouncilTemplates(**out)


def _truong_khac(a: dict, b: dict) -> List[str]:
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


async def tao_bo_dung_lai_ban_ky(
    db: AsyncSession,
    engine: AsyncEngine,
    s0: CouncilDocumentSet,
    *,
    so_quyet_dinh: object,
    ngay_ky: object,
    dong_sua_tay: Sequence[int],
    ly_do: object,
    xac_nhan_dong_khac: Optional[List[Dict[str, object]]],
    nguoi_tao_id: Optional[int],
    luc_tao: Optional[datetime] = None,
) -> Tuple[CouncilDocumentSet, None]:
    """Đường TÁI DỰNG BẢN KÝ (F245 — owner C2 / C3; đặc tả mục 3.1) — RIÊNG, khác dựng bộ xét mới:

    * dòng KHÔNG sửa tay: chép NGUYÊN ảnh chụp + dòng bộ của bộ in ban đầu ``s0`` (ảnh chụp thắng dữ liệu
      sống; ``s0`` đã qua đủ cổng lúc in) — KHÔNG đọc sống, KHÔNG cổng;
    * dòng sửa tay: đọc SỐNG theo id hồ sơ của dòng bộ ``s0`` bằng CÙNG hàm đọc, qua cổng DỮ LIỆU
      (``danh_gia_dung_lai``) — KHÔNG cổng trạng thái F228 (bản ký thắng, trạng thái chỉ liệt kê lúc ghi
      nhận — C3);
    * MỌI dòng qua cổng tình trạng Quyết định (đã có QĐ hiệu lực / chờ quyết / dấu AppSheet ⇒ chặn);
    * Admin xác nhận ĐÚNG danh sách {stt, tên trường khác} (C2 "Admin đối chiếu từng dòng khác");
    * mẫu = ĐÚNG ba mẫu ``s0`` đã dùng; tham số = của ``s0`` + số / ngày trên giấy.

    Lý do tái dựng (D.1 — Codex lần 14): CHỈ nằm ở ``thong_tin_dung.dung_lai_ban_ky.ly_do`` của bộ R (bộ tái
    dựng) — nên MẤT THEO R nếu R bị xoá (xoá được khi R không có văn bản còn / hết hiệu lực — K4). Sự kiện độc lập
    ``dung_lai_ban_ky`` (``council_document_event``) chỉ giữ DẤU THAO TÁC: bộ nguồn, dòng sửa tay, dòng khác,
    người, lúc — KHÔNG giữ lý do (đặc tả 3.1 bước 12: sự kiện không mang chữ tự do).
    """
    from app.services import council_decision_service as qd
    from app.services.council_candidate_service import doc_ho_so_theo_id
    from app.services.council_decision_status_service import tinh_trang_qd

    so = qd.kiem_so_quyet_dinh(so_quyet_dinh)
    ngay = qd.kiem_ngay(ngay_ky)
    # Đặc tả 3.1: thân có ``ly_do``; bước 12 "lý do không ghi vào sự kiện" ⇒ giữ ở thông tin dựng của bộ R
    # (mất theo R nếu R bị xoá — xem docstring).
    ly = kiem_ly_do(ly_do, "tái dựng bản ký")
    luc_tao = luc_tao or datetime.now(timezone.utc)
    if PHIEN_BAN_MA is None:
        raise ServiceError("Không đọc được mã nguồn của bộ dựng để ghi phiên bản — không dựng.")
    if s0.ban_ky_so_quyet_dinh is not None or s0.cho_quyet_dinh_goc_id is not None:
        raise DataValidationError(
            "Chỉ tái dựng từ bộ in ban đầu (không từ bộ tái dựng / bộ dữ liệu điều chỉnh)."
        )
    repo = CouncilDecisionRepository(db)
    dong0 = await repo.dong_bo(s0.id)
    if len(dong0) != s0.so_ho_so or [d.stt for d in dong0] != list(
        range(1, s0.so_ho_so + 1)
    ):
        raise DataValidationError("Bộ in ban đầu dựng trước khi có dòng bộ — không tái dựng.")
    song = await repo.van_ban_song_cua_bo(s0.id)
    if song:
        raise ConflictError(
            "Bộ in ban đầu đã được ghi nhận (văn bản #%d)." % song[0].id,
            public_payload={"quyet_dinh_id": song[0].id},
        )
    sua = list(dong_sua_tay or [])
    if (
        not sua
        or any(isinstance(x, bool) or not isinstance(x, int) for x in sua)
        or len(set(sua)) != len(sua)
        or not all(1 <= x <= s0.so_ho_so for x in sua)
    ):
        raise DataValidationError(
            "Danh sách dòng sửa tay phải là số dòng của bộ (1…%d), không trùng, không rỗng."
            % s0.so_ho_so
        )
    sua = sorted(sua)
    if ngay < vn_calendar_date(s0.tao_luc):
        raise DataValidationError(
            "Ngày ký trước ngày in bộ ban đầu (giờ Việt Nam) — giấy không thể ký trước khi in."
        )
    ts0 = dict(s0.tham_so_quyet_dinh or {})
    if ts0.get("so_quyet_dinh") not in (None, so) or ts0.get("ngay_quyet_dinh") not in (
        None,
        ngay.isoformat(),
    ):
        raise DataValidationError("Số / ngày trên giấy khác số / ngày bộ in ban đầu đã in.")
    mat = [d.stt for d in dong0 if d.profile_id is None]
    if mat:
        raise DataValidationError(
            "Dòng %s: hồ sơ của dòng bộ không còn — không tái dựng." % _dong_txt(mat)
        )
    nam = (s0.thong_tin_dung or {}).get("nam_hoc")
    theo_stt = {d.stt: d for d in dong0}
    anh = await doc_ho_so_theo_id(
        engine, [theo_stt[s].profile_id for s in sua], academic_year=nam
    )
    kq_cong = cong.danh_gia_dung_lai(anh.kiem)
    if kq_cong.chan:
        raise DataValidationError(
            "Dòng sửa tay không dựng lại được từ dữ liệu hiện tại của hồ sơ — xem danh sách.",
            public_payload={
                "kiem_tra_dung_lai": [
                    {
                        "ma": ma,
                        "mo_ta": cong.LY_DO[ma],
                        "trang_thai": tt_,
                        "dong": [sua[i - 1] for i in dong],
                    }
                    for ma, tt_, dong in kq_cong.chan
                ]
            },
        )
    tt = await tinh_trang_qd(db, [d.profile_id for d in dong0])
    chan_qd = qd._chan_tinh_trang(dong0, tt)
    if chan_qd:
        raise ConflictError(
            "%d hồ sơ đã có Quyết định hiệu lực / đang chờ Admin quyết / mang dấu trúng tuyển "
            "theo Quyết định cũ — không tái dựng." % len(chan_qd),
            public_payload={"dong_bi_chan": chan_qd},
        )
    dto0 = await _anh_chup_da_luu(db, s0.id)
    if len(dto0) != s0.so_ho_so:
        raise ServiceError("Ảnh chụp đã lưu thiếu dòng — không tái dựng.")
    song_theo_stt = {}
    for i, s in enumerate(sua):
        r = anh.rows[i]
        song_theo_stt[s] = r.model_copy(
            update={
                "diem_kv": kq_cong.diem_kv[i],
                "diem_ut": cong.diem_ut_in(kq_cong.luat_ut[i], r.diem_ut),
            }
        )
        if song_theo_stt[s].diem_kv is None or song_theo_stt[s].diem_ut is None:
            raise ServiceError("Thiếu điểm ưu tiên in sau cổng — không tái dựng.")
    hang_in = [
        song_theo_stt[d.stt]
        if d.stt in song_theo_stt
        else bo_dung.CandidateRowV1(**dto0[d.stt - 1])
        for d in dong0
    ]
    khac = []
    for s in sua:
        truong = _truong_khac(song_theo_stt[s].model_dump(), dto0[s - 1])
        if not truong:
            raise DataValidationError(
                "Dòng %d khai sửa tay nhưng hồ sơ chưa được sửa (không khác bản in)." % s
            )
        khac.append({"stt": s, "truong": truong})
    if xac_nhan_dong_khac != khac:
        raise ConflictError(
            "Admin đối chiếu từng dòng khác bản in với bản ký rồi gửi lại đúng danh sách.",
            public_payload={"dong_khac": khac},
        )
    mdd = (s0.thong_tin_dung or {}).get("mau_da_dung") or {}
    mau = await _mau_theo_id(db, mdd)
    tham_so = bo_dung.kiem_lai_tham_so_quyet_dinh(
        bo_dung.DecisionParams(**{**ts0, "so_quyet_dinh": so, "ngay_quyet_dinh": ngay})
    )
    if not await CouncilDocumentRepository(db).thu_khoa_dung():
        raise ConflictError("Đang dựng một bộ văn bản khác — chờ bộ ấy xong rồi thử lại.")
    kq = await asyncio.to_thread(bo_dung.render_council_documents, hang_in, mau, tham_so)
    tong = sum(len(f.content) for f in kq.files)
    if tong > settings.COUNCIL_SET_MAX_TOTAL_BYTES:
        raise DataValidationError("Bộ văn bản vượt giới hạn kỹ thuật — không lưu.")
    for f in kq.files:
        if hashlib.sha256(f.content).hexdigest() != f.sha256:
            raise ServiceError("sha256 của tệp sinh lệch nội dung — không lưu.")
    md = dict(kq.metadata)
    md.pop("ma_ho_so_dau_vao", None)
    md.pop("tham_so_quyet_dinh", None)
    md["mau_da_dung"] = mdd
    md["ngay_ky_chon_mau"] = (s0.thong_tin_dung or {}).get("ngay_ky_chon_mau")
    md["nam_hoc"] = nam
    md["phien_ban_ma"] = dict(PHIEN_BAN_MA)
    md["giao_dich_doc"] = {
        "transaction_isolation": anh.giao_dich.transaction_isolation,
        "transaction_read_only": anh.giao_dich.transaction_read_only,
    }
    md["dung_lai_ban_ky"] = {
        "tu_set_id": s0.id,
        "dong_sua_tay": sua,
        "dong_khac": khac,
        "nguoi_xac_nhan_id": nguoi_tao_id,
        "luc": luc_tao.isoformat(),
        "ly_do": ly,
    }
    bo = CouncilDocumentSet(
        nguoi_tao_id=nguoi_tao_id,
        tao_luc=luc_tao,
        moc_chup=anh.giao_dich.moc_chup,
        unit_id=s0.unit_id,
        trinh_do=kq.metadata["trinh_do"],
        so_ho_so=len(hang_in),
        so_tep=len(kq.files),
        kich_thuoc_tong=tong,
        tham_so_quyet_dinh=kq.metadata["tham_so_quyet_dinh"],
        ma_ho_so_dau_vao=[r.ma_ho_so for r in hang_in],
        snapshot_dto=[r.model_dump() for r in hang_in],
        thong_tin_dung=md,
        dung_lai_tu_set_id=s0.id,
        ban_ky_so_quyet_dinh=so,
        ban_ky_ngay=ngay,
    )
    tep = [
        CouncilDocumentSetFile(
            thu_tu=i, path=f.path, sha256=f.sha256, kich_thuoc=len(f.content), noi_dung=f.content
        )
        for i, f in enumerate(kq.files, 1)
    ]
    vi_tri = {s: i for i, s in enumerate(sua)}
    dong = []
    for d in dong0:
        if d.stt in vi_tri:
            r = _dong_bo_tu_kiem(anh.kiem[vi_tri[d.stt]], d.profile_id, nam)
            r.stt = d.stt
        else:
            r = CouncilDocumentSetRow(
                stt=d.stt,
                profile_id=d.profile_id,
                academic_year=d.academic_year,
                status_luc_dung=d.status_luc_dung,
                nv_in_id=d.nv_in_id,
                admission_path_id=d.admission_path_id,
                academic_info_id=d.academic_info_id,
                offering_id=d.offering_id,
                major_id=d.major_id,
            )
        r.status_luc_dung = d.status_luc_dung  # mốc so của C3 = bản đã in và đã ký
        dong.append(r)
    await _ghi_bo_va_dong(
        db,
        bo,
        tep,
        dong,
        loai_su_kien="dung_lai_ban_ky",
        so_lieu={"tu_set_id": s0.id, "dong_sua_tay": sua, "dong_khac": khac},
        nguoi_id=nguoi_tao_id,
    )
    return bo, None


def _dong_txt(ds: Sequence[int]) -> str:
    return ", ".join(str(x) for x in list(ds)[:20]) + (
        " … (+%d)" % (len(ds) - 20) if len(ds) > 20 else ""
    )


async def so_voi_hien_tai(
    db: AsyncSession, engine: AsyncEngine, bo: CouncilDocumentSet
) -> Dict[str, object]:
    """Route chỉ đọc, CHỈ ADMIN (SPEC §11.2 điểm 8; BS §3.2): so ảnh chụp của bộ với dữ liệu HIỆN TẠI
    — tính lại bằng CÙNG hàm của bộ dựng (đọc, cổng dữ liệu, điểm KV / đối tượng in). Trả số dòng + TÊN
    trường đã đổi, không giá trị; dòng không dựng lại được ⇒ mã lý do."""
    from app.services.council_candidate_service import doc_ho_so_theo_id

    repo = CouncilDecisionRepository(db)
    dong = await repo.dong_bo(bo.id)
    if len(dong) != bo.so_ho_so:
        raise DataValidationError("Bộ dựng trước khi có dòng bộ — không so được.")
    co = [d for d in dong if d.profile_id is not None]
    mat = [d.stt for d in dong if d.profile_id is None]
    dto = await _anh_chup_da_luu(db, bo.id)
    khac: List[Dict[str, object]] = []
    khong: List[Dict[str, object]] = []
    if co:
        anh = await doc_ho_so_theo_id(
            engine,
            [d.profile_id for d in co],
            academic_year=(bo.thong_tin_dung or {}).get("nam_hoc"),
        )
        kq = cong.danh_gia_dung_lai(anh.kiem)
        for i, d in enumerate(co):
            ly = cong.ly_do_cua_dong(anh.kiem[i])
            if ly:
                khong.append({"stt": d.stt, "ma": ly})
                continue
            r = anh.rows[i].model_copy(
                update={
                    "diem_kv": kq.diem_kv[i],
                    "diem_ut": cong.diem_ut_in(kq.luat_ut[i], anh.rows[i].diem_ut),
                }
            )
            truong = _truong_khac(r.model_dump(), dto[d.stt - 1])
            if truong:
                khac.append({"stt": d.stt, "truong": truong})
    return {
        "set_id": bo.id,
        "so_dong": bo.so_ho_so,
        "dong_khac": khac,
        "khong_dung_lai_duoc": khong,
        "mat_ho_so": mat,
    }
