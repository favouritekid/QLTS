# app/services/council_decision_service.py
"""Ghi nhận Quyết định ĐÃ KÝ (F230 — lượt I). Đặc tả: ``logs-P5/cong-bo-ket-qua/ma-gd1/
DAC-TA-TRIEN-KHAI-F230-2026-11-07.md`` (mục 1–5, 8); thiết kế ``THIET-KE-F230-…`` (gốc + bổ sung lần 9);
owner ``TRA-LOI-OWNER-2026-11-06.md`` mục C (C1–C7) + E1.

Service thuần (không FastAPI): kiểm quyền / IDOR ở ``deps.py``; mọi thao tác ghi chạy trong MỘT SAVEPOINT
của giao dịch request (lỗi ⇒ không còn hàng nào), router commit. Ràng buộc "không trùng / một dòng hiệu lực
/ cờ con theo cha / không xoá" do CSDL giữ (tầng chủ sở hữu — U1–U4, K2, K4, K5); service kiểm TRƯỚC để
trả 409 có số dòng, và dịch vi phạm của CSDL (hai phiên cùng qua phép kiểm) thành 409 cố định.

Thứ tự khoá (đặc tả 8.5, BS §4.6): văn bản → mục chờ → bộ → hồ sơ (id tăng dần, một câu) → [chặng 2b]
dòng chỉ tiêu mà các dòng sắp chiếm chỗ (Phần B): ``offering_academic_info`` → ``admission_path`` (id tăng
dần — ``quota_occupancy_service.khoa_chi_tieu_cua_dong_bo`` → ``khoa_o_chi_tieu``, THỨ TỰ CHUẨN). Phê duyệt cũ,
Phê duyệt hàng loạt (khoá trước cả lô) và công bố (khoá trước mọi nguyện vọng) đi CÙNG thứ tự ⇒ không vòng chờ
(F259); bên bị PostgreSQL chọn huỷ ở trường hợp khác ⇒ 409 "thử lại" (đổi so với BS §4.6 "không khoá dòng
chỉ tiêu" — lý do: ``DAC-TA-F230-2B-BO-SUNG-2026-11-10.md``; lượt K: ``DAC-TA-F230-SUA-CUOI-BO-SUNG-2026-11-10.md``).

Ba thao tác sinh / khôi phục dòng Phần B (ghi nhận, điều chỉnh có dòng thêm, huỷ ghi nhận có dòng bật lại) gọi
``kiem_khoa_dem_dong_bo`` DƯỚI khoá, TRƯỚC khi ghi (Q-J1 — owner 10-11: dòng bộ thiếu khoá đếm ⇒ 409 nêu số
dòng).

Không log dữ liệu cá nhân: chỉ id + số đếm. Lỗi chỉ nêu số dòng (``stt``) + id văn bản, không CCCD.
"""
import hashlib
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants.admission_circular import vn_calendar_date
from app.models.council_document import (
    LOAI_SCAN,
    CouncilDecision,
    CouncilDecisionHold,
    CouncilDecisionScan,
    CouncilDocumentEvent,
    CouncilDocumentSet,
)
from app.repositories.council_decision_repository import (
    CouncilDecisionRepository,
    ma_loi_csdl,
)
from app.repositories.council_document_repository import CouncilDocumentRepository
from app.services import council_document_render_service as bo_dung
from app.services.council_decision_status_service import tinh_trang_qd
from app.services.council_document_set_service import kiem_ly_do
from app.services.council_set_gate_service import (
    TRANG_THAI_CANH_BAO,
    TRANG_THAI_CHAN,
    TRANG_THAI_KHONG_CANH_BAO,
    ly_do_tinh_trang_qd,
)
from app.services.quota_occupancy_service import (
    SQLSTATE_DEADLOCK,
    THONG_DIEP_XUNG_DOT,
    khoa_chi_tieu_cua_dong_bo,
    kiem_khoa_dem_dong_bo,
)
from app.utils.exceptions import (
    ConflictError,
    DataValidationError,
    ResourceNotFoundError,
    ServiceError,
)

TRANG_THAI_DA_BIET = TRANG_THAI_CHAN | TRANG_THAI_CANH_BAO | TRANG_THAI_KHONG_CANH_BAO
#: Tham số trên giấy ngoài số / ngày Quyết định (BS §3.2 dòng 3) — trường bộ đã in thì phải gõ lại
#: ĐÚNG; trường bộ để trống thì nhận giá trị Admin gõ theo giấy.
TRUONG_THAM_SO_GIAY = ("so_bien_ban", "ngay_bien_ban", "dot_so", "dot_thang")
TEP_QUYET_DINH = "HoiDong/QuyetDinhTrungTuyen-"
#: Thông điệp cố định khi CSDL (tầng chủ sở hữu) chặn — không mang tham số câu lệnh.
_LOI_RANG_BUOC = {
    "uq_council_decision_u1_so": "Số Quyết định này đã dùng trong năm của ngày ký.",
    "uq_council_decision_u2_bo": "Bộ văn bản này đã được ghi nhận là một văn bản đã ký.",
    "uq_council_decision_row_u3_ho_so": (
        "Có hồ sơ đã có tên trong một Quyết định khác đang hiệu lực."
    ),
    "uq_council_decision_u4_huy": "Văn bản này đã có một văn bản huỷ còn hiệu lực.",
    "uq_council_decision_hold_h1_cho": "Hồ sơ đã ở nhóm chờ Admin quyết.",
}


# ═══════════════════════════════ kiểm đầu vào ═════════════════════════════════════════════
def kiem_so_quyet_dinh(so: object) -> str:
    if not isinstance(so, str) or not (1 <= len(so) <= 6) or not so.isascii() or not so.isdigit():
        raise DataValidationError("Số Quyết định phải là 1–6 chữ số.")
    return so


def kiem_ngay(ngay: object, ten: str = "ngày ký") -> date:
    if isinstance(ngay, datetime) or not isinstance(ngay, date):
        raise DataValidationError("Thiếu %s hoặc %s không hợp lệ." % (ten, ten))
    return ngay


def kiem_scan(noi_dung: object) -> bytes:
    """Bản scan PDF (J2 bước 5: bắt buộc): không rỗng, ≤ trần kỹ thuật, chữ ký ``%PDF-``."""
    if not isinstance(noi_dung, (bytes, bytearray)) or not noi_dung:
        raise DataValidationError("Phải kèm bản scan (PDF) của văn bản đã ký.")
    b = bytes(noi_dung)
    if len(b) > settings.COUNCIL_DECISION_SCAN_MAX_BYTES:
        raise DataValidationError(
            "Bản scan vượt giới hạn kỹ thuật %d byte." % settings.COUNCIL_DECISION_SCAN_MAX_BYTES
        )
    if not b.startswith(b"%PDF-"):
        raise DataValidationError("Bản scan phải là tệp PDF.")
    return b


def kiem_xac_nhan_trang_thai(xac_nhan: object) -> Optional[Dict[str, int]]:
    """``None`` hoặc dict KHÔNG rỗng {trạng thái / mã đếm: số ≥ 1}."""
    if xac_nhan is None:
        return None
    if not isinstance(xac_nhan, dict) or not xac_nhan:
        raise DataValidationError("Xác nhận phải là danh sách {loại: số hồ sơ} không rỗng.")
    out: Dict[str, int] = {}
    for k, v in xac_nhan.items():
        if not isinstance(k, str) or isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise DataValidationError("Số hồ sơ trong xác nhận phải là số nguyên ≥ 1.")
        out[k] = v
    return dict(sorted(out.items()))


def _kiem_xac_nhan_dem(
    dem: Dict[str, int],
    dong: Dict[str, List[int]],
    xac_nhan: Optional[Dict[str, int]],
    viec: str,
) -> Optional[Dict[str, int]]:
    """Khuôn "Admin xác nhận ĐÚNG số đếm" (F228 / C3): có gì cần xác nhận mà chưa / lệch ⇒ 409 kèm
    số đếm + số dòng; không có gì mà vẫn gửi ⇒ 409 lệch. Trả số đếm đã xác nhận (để ghi vết)."""
    dem = dict(sorted(dem.items()))
    noi_dung = {
        "xac_nhan_can": {
            "so_ho_so_theo_loai": dem,
            "dong_theo_loai": {k: sorted(v) for k, v in sorted(dong.items())},
        }
    }
    if not dem:
        if xac_nhan is not None:
            raise ConflictError(
                "Không còn gì cần xác nhận — gửi lại không kèm xác nhận.",
                public_payload=noi_dung,
            )
        return None
    if xac_nhan is None:
        raise ConflictError(
            "%s: có %d hồ sơ cần Admin xác nhận đúng số đếm theo từng loại rồi gửi lại."
            % (viec, sum(dem.values())),
            public_payload=noi_dung,
        )
    if xac_nhan != dem:
        raise ConflictError(
            "Số hồ sơ theo từng loại đã khác lúc xác nhận — xem lại rồi xác nhận lại.",
            public_payload=noi_dung,
        )
    return dem


def _dich_loi_csdl(ma: Tuple[Optional[str], Optional[str]], viec: str) -> Exception:
    """Dịch (SQLSTATE, tên ràng buộc) — kết quả của :func:`ma_loi_csdl`, KHÔNG nhận ngoại lệ (chữ của nó có
    thể mang tham số câu lệnh) — thành lỗi miền có thông điệp CỐ ĐỊNH."""
    sqlstate, rang_buoc = ma
    if sqlstate == "23505" and rang_buoc in _LOI_RANG_BUOC:
        return ConflictError(
            _LOI_RANG_BUOC[rang_buoc], public_payload={"rang_buoc": rang_buoc}
        )
    if sqlstate == SQLSTATE_DEADLOCK:  # deadlock — PostgreSQL đã huỷ đúng một giao dịch
        return ConflictError(THONG_DIEP_XUNG_DOT)
    return ServiceError("Lỗi CSDL khi %s — không ghi gì." % viec)


def _su_kien(loai, *, nguoi_id, so_lieu, set_id=None, decision_id=None, hold_id=None):
    return CouncilDocumentEvent(
        loai=loai,
        set_id=set_id,
        decision_id=decision_id,
        hold_id=hold_id,
        nguoi_id=nguoi_id,
        so_lieu=so_lieu,
    )


def _scan(decision_id: int, b: bytes) -> CouncilDecisionScan:
    return CouncilDecisionScan(
        decision_id=decision_id,
        sha256=hashlib.sha256(b).hexdigest(),
        kich_thuoc=len(b),
        kieu=LOAI_SCAN,
        noi_dung=b,
    )


def _gia_tri_json(v: Any) -> Any:
    return v.isoformat() if isinstance(v, date) else v


def _so_tham_so(
    bo: CouncilDocumentSet, so: str, ngay_ky: date, tham_so_giay: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """BS §3.2 — mọi tham số bộ ĐÃ in phải bằng giá trị trên giấy (lệch ⇒ CHẶN: tờ giấy không phải bản
    in của bộ này); trường bộ để trống nhận giá trị Admin gõ. Bộ tái dựng: số / ngày = bản ký đã khai."""
    ts = bo.tham_so_quyet_dinh or {}
    lech: List[str] = []
    if bo.ban_ky_so_quyet_dinh is not None and (
        bo.ban_ky_so_quyet_dinh != so or bo.ban_ky_ngay != ngay_ky
    ):
        lech.append("số / ngày của bản ký đã khai khi tái dựng")
    if ts.get("so_quyet_dinh") is not None and ts["so_quyet_dinh"] != so:
        lech.append("số Quyết định")
    if ts.get("ngay_quyet_dinh") is not None and ts["ngay_quyet_dinh"] != ngay_ky.isoformat():
        lech.append("ngày Quyết định")
    giay = {}
    for t in TRUONG_THAM_SO_GIAY:
        g = _gia_tri_json(tham_so_giay.get(t))
        if ts.get(t) is not None and g != ts.get(t):
            lech.append(t)
        if g is not None:
            giay[t] = g
    if lech:
        raise DataValidationError(
            "Giấy đã ký khác bản in của bộ ở: %s — dựng lại bộ đúng tham số trên giấy."
            % ", ".join(lech),
            public_payload={"truong_lech": lech},
        )
    return giay or None


async def _kiem_mau_theo_ngay_ky(db: AsyncSession, bo: CouncilDocumentSet, ngay_ky: date) -> None:
    """BS §3.2 (G10): ba mẫu đúng theo NGÀY KÝ (cùng hàm chọn ``mau_hieu_luc`` của kho mẫu) phải trùng
    id + sha ba mẫu bộ đã dùng — "căn cứ trên văn bản theo ngày ký" (J1 dòng 7)."""
    da_dung = (bo.thong_tin_dung or {}).get("mau_da_dung") or {}
    repo = CouncilDocumentRepository(db)
    lech = []
    for loai in bo_dung.LOAI_MAU:
        m = await repo.mau_hieu_luc(loai, ngay_ky)
        d = da_dung.get(loai) or {}
        if m is None or d.get("id") != m.id or d.get("sha256") != m.sha256:
            lech.append(loai)
    if lech:
        raise DataValidationError(
            "Mẫu đúng theo ngày ký khác mẫu bộ đã dùng (%s) — dựng lại bộ với ngày ký trên giấy."
            % ", ".join(lech),
            public_payload={"mau_lech": lech},
        )


def _dem_doi_trang_thai(dong_bo, hien_tai: Dict[int, str]):
    """C3: em ĐỔI trạng thái so với lúc dựng (``status_luc_dung``) — đếm theo trạng thái hiện tại +
    số dòng; trạng thái lạ (ngoài 15) ⇒ danh sách chặn."""
    dem: Dict[str, int] = {}
    dong: Dict[str, List[int]] = {}
    la: List[int] = []
    for d in dong_bo:
        s = hien_tai.get(d.profile_id)
        if s not in TRANG_THAI_DA_BIET:
            la.append(d.stt)
            continue
        if s != d.status_luc_dung:
            dem[s] = dem.get(s, 0) + 1
            dong.setdefault(s, []).append(d.stt)
    return dem, dong, la


def _chan_tinh_trang(dong_bo, tt, cho_phep_chuoi: Optional[int] = None):
    """Dòng bị chặn vì tình trạng Quyết định (HL ở văn bản khác / chờ quyết / dấu AppSheet) — luật là
    ĐÚNG hàm của cổng dựng bộ (:func:`ly_do_tinh_trang_qd`, CLAUDE.md §7), đọc trên tình trạng của hàm hỏi."""
    out = []
    for d in dong_bo:
        t = tt.get(d.profile_id)
        if t is None:
            continue
        ma = ly_do_tinh_trang_qd(t, cho_phep_chuoi)
        if ma:
            out.append(
                {"dong": d.stt, "ly_do": ma[0], "ma": ma, "quyet_dinh_id": t.qd_hieu_luc_id}
            )
    return out


async def _bo_qd_hop_le(repo, set_id, *, cho_dieu_chinh_cua: Optional[int]):
    bo = await repo.khoa_bo(set_id)
    if bo is None:
        raise ResourceNotFoundError("Không có bộ văn bản này.")
    if cho_dieu_chinh_cua is None and bo.cho_quyet_dinh_goc_id is not None:
        raise DataValidationError(
            "Bộ này dựng làm dữ liệu cho văn bản điều chỉnh — chỉ dùng được khi ghi nhận điều chỉnh."
        )
    if cho_dieu_chinh_cua is not None and bo.cho_quyet_dinh_goc_id != cho_dieu_chinh_cua:
        raise DataValidationError(
            "Bộ này không dựng cho văn bản điều chỉnh của Quyết định đã chọn."
        )
    dong = await repo.dong_bo(bo.id)
    if len(dong) != bo.so_ho_so or [d.stt for d in dong] != list(range(1, bo.so_ho_so + 1)):
        raise DataValidationError(
            "Bộ dựng trước khi có dòng bộ (id hồ sơ) — không ghi nhận được; dựng lại bộ."
        )
    mat = [d.stt for d in dong if d.profile_id is None]
    if mat:
        raise DataValidationError(
            "Dòng %s: hồ sơ của dòng bộ không còn — không ghi nhận được."
            % ", ".join(map(str, mat))
        )
    song = await repo.van_ban_song_cua_bo(bo.id)
    if song:
        raise ConflictError(
            "Bộ này đã được ghi nhận là văn bản đã ký #%d." % song[0].id,
            public_payload={"quyet_dinh_id": song[0].id},
        )
    return bo, dong


async def _so_chua_dung(repo, so: str, pham_vi: int) -> None:
    dung = await repo.so_da_dung(so, pham_vi)
    if dung is not None:
        raise ConflictError(
            "Số Quyết định %s đã dùng trong năm %d (văn bản #%d)." % (so, pham_vi, dung),
            public_payload={"quyet_dinh_id": dung},
        )


async def _sha_tep_quyet_dinh(db: AsyncSession, set_id: int) -> str:
    tep = [
        t
        for t in await CouncilDocumentRepository(db).danh_sach_tep(set_id)
        if t.path.startswith(TEP_QUYET_DINH)
    ]
    if len(tep) != 1:
        raise ServiceError("Bộ không có đúng một tệp Quyết định — không ghi nhận.")
    return tep[0].sha256


# ═══════════════════════════════ ghi nhận trúng tuyển / bổ sung ═══════════════════════════
async def ghi_nhan_quyet_dinh(
    db: AsyncSession,
    *,
    set_id: int,
    loai: str,
    goc_id: Optional[int],
    so_quyet_dinh: object,
    ngay_ky: object,
    tham_so_giay: Optional[Dict[str, Any]],
    xac_nhan_so_ho_so: object,
    xac_nhan_khop_ban_in: object,
    xac_nhan_trang_thai: object,
    ghi_chu_mau: Optional[str],
    scan: object,
    nguoi_id: int,
) -> Tuple[CouncilDecision, None]:
    """Ghi nhận MỘT Quyết định trúng tuyển / bổ sung đã ký từ bộ ``set_id`` (đặc tả mục 5.3). Trả
    ``(văn bản đã flush, None)``; router commit."""
    so = kiem_so_quyet_dinh(so_quyet_dinh)
    ngay = kiem_ngay(ngay_ky)
    b = kiem_scan(scan)
    xac_nhan = kiem_xac_nhan_trang_thai(xac_nhan_trang_thai)
    ghi_chu = None if ghi_chu_mau in (None, "") else kiem_ly_do(ghi_chu_mau, "ghi chú mẫu")
    if loai not in ("trung_tuyen", "bo_sung"):
        raise DataValidationError("Loại văn bản ghi nhận từ bộ: trung_tuyen | bo_sung.")
    if (loai == "bo_sung") != (goc_id is not None):
        raise DataValidationError(
            "Quyết định bổ sung phải chọn Quyết định gốc; Quyết định trúng tuyển thì không."
        )
    if xac_nhan_khop_ban_in is not True:
        raise DataValidationError(
            "Admin phải xác nhận danh sách, ngành, điểm từng em trên bản ký khớp bản in của bộ "
            "(C2: bản ký sửa tay ⇒ dựng lại bộ cho khớp bản ký)."
        )
    repo = CouncilDecisionRepository(db)
    try:
        async with db.begin_nested():
            goc = None
            if goc_id is not None:
                goc = await repo.khoa_qd(goc_id)
                if goc is None:
                    raise ResourceNotFoundError("Không có Quyết định gốc này.")
                if goc.loai != "trung_tuyen" or goc.trang_thai != "hieu_luc":
                    raise ConflictError(
                        "Quyết định gốc phải là Quyết định trúng tuyển đang hiệu lực."
                    )
            bo, dong = await _bo_qd_hop_le(repo, set_id, cho_dieu_chinh_cua=None)
            if (
                isinstance(xac_nhan_so_ho_so, bool)
                or not isinstance(xac_nhan_so_ho_so, int)
                or xac_nhan_so_ho_so != bo.so_ho_so
            ):
                raise DataValidationError("Số hồ sơ gõ lại không khớp số hồ sơ của bộ.")
            tham_so_ban_ky = _so_tham_so(bo, so, ngay, tham_so_giay or {})
            await _kiem_mau_theo_ngay_ky(db, bo, ngay)
            if bo.ban_ky_so_quyet_dinh is None and ngay < vn_calendar_date(bo.tao_luc):
                raise DataValidationError(
                    "Ngày ký trước ngày dựng bộ (giờ Việt Nam) — tờ giấy không thể là bản in của bộ "
                    "này."
                )
            await _so_chua_dung(repo, so, ngay.year)
            pids = [d.profile_id for d in dong]
            hien_tai = await repo.khoa_ho_so(pids)
            if set(hien_tai) != set(pids):
                raise DataValidationError("Có hồ sơ của bộ không còn — không ghi nhận được.")
            # Chặng 2b: dòng sắp chiếm chỗ (Phần B) ⇒ khoá dòng chỉ tiêu SAU hồ sơ (thứ tự chung).
            await khoa_chi_tieu_cua_dong_bo(db, [d.id for d in dong])
            # Q-J1 (owner 10-11): dòng bộ thiếu khoá đếm / lệch chuỗi ⇒ CHẶN (dưới khoá, trước ghi).
            await kiem_khoa_dem_dong_bo(db, [(d.stt, d.id) for d in dong])
            chan = _chan_tinh_trang(dong, await tinh_trang_qd(db, pids))
            if chan:
                raise ConflictError(
                    "%d hồ sơ đã có Quyết định hiệu lực / đang chờ Admin quyết / mang dấu trúng tuyển "
                    "theo Quyết định cũ — không ghi nhận Quyết định mới." % len(chan),
                    public_payload={"dong_bi_chan": chan},
                )
            dem, dong_tt, la = _dem_doi_trang_thai(dong, hien_tai)
            if la:
                raise DataValidationError(
                    "Dòng %s: trạng thái hồ sơ không xác định — không ghi nhận."
                    % ", ".join(map(str, la))
                )
            da_xn = _kiem_xac_nhan_dem(dem, dong_tt, xac_nhan, "Có em đổi trạng thái sau khi dựng bộ")
            qd = CouncilDecision(
                loai=loai,
                can_bo=True,
                set_id=bo.id,
                goc_id=goc_id,
                so_quyet_dinh=so,
                ngay_ky=ngay,
                pham_vi_so=ngay.year,
                trang_thai="hieu_luc",
                tham_so_ban_ky=tham_so_ban_ky,
                so_ho_so=len(dong),
                sha_tep_quyet_dinh=await _sha_tep_quyet_dinh(db, bo.id),
                xac_nhan={
                    "so_ho_so": bo.so_ho_so,
                    "khop_ban_in": True,
                    "doi_trang_thai": da_xn,
                },
                ghi_chu_mau=ghi_chu,
                ghi_nhan_boi_id=nguoi_id,
            )
            await repo.them(qd)
            n = await repo.chen_dong_tu_bo(qd.id, bo.id)
            if n != len(dong):
                raise ServiceError("Chép dòng bộ sang Quyết định thiếu dòng — không ghi.")
            await repo.them(
                _scan(qd.id, b),
                _su_kien(
                    "ghi_nhan",
                    nguoi_id=nguoi_id,
                    set_id=bo.id,
                    decision_id=qd.id,
                    so_lieu={
                        "loai": loai,
                        "so_ho_so": len(dong),
                        "doi_trang_thai": da_xn,
                        "goc_id": goc_id,
                    },
                ),
            )
    except DBAPIError as e:
        raise _dich_loi_csdl(ma_loi_csdl(e), "ghi nhận Quyết định") from None
    return qd, None


# ═══════════════════════════════ điều chỉnh (C6) ═══════════════════════════════════════════
async def _chuoi_hieu_luc(repo, goc_id: int) -> Dict[int, CouncilDecision]:
    return {
        d.id: d
        for d in await repo.chuoi(goc_id)
        if d.loai in ("trung_tuyen", "bo_sung", "dieu_chinh") and d.trang_thai == "hieu_luc"
    }


async def ghi_nhan_dieu_chinh(
    db: AsyncSession,
    goc_id: int,
    *,
    so_quyet_dinh: object,
    ngay_ky: object,
    bo_dong: Sequence[int],
    set_id: Optional[int],
    xac_nhan_so_ho_so: object,
    xac_nhan_khop_ban_in: object,
    xac_nhan_trang_thai: object,
    ghi_chu_mau: Optional[str],
    scan: object,
    nguoi_id: int,
) -> Tuple[CouncilDecision, None]:
    """Quyết định ĐIỀU CHỈNH (văn thư soạn — C6): bỏ các dòng ``bo_dong`` của chuỗi gốc, thêm mọi dòng
    của bộ ``set_id`` (bộ dữ liệu dựng cho chuỗi này). BỎ trước, THÊM sau trong MỘT giao dịch (U3 là
    chỉ mục duy nhất, kiểm từng dòng — BS §1.3)."""
    so = kiem_so_quyet_dinh(so_quyet_dinh)
    ngay = kiem_ngay(ngay_ky)
    b = kiem_scan(scan)
    xac_nhan = kiem_xac_nhan_trang_thai(xac_nhan_trang_thai)
    ghi_chu = None if ghi_chu_mau in (None, "") else kiem_ly_do(ghi_chu_mau, "ghi chú mẫu")
    ds_bo = list(bo_dong or [])
    if any(isinstance(x, bool) or not isinstance(x, int) for x in ds_bo) or len(set(ds_bo)) != len(
        ds_bo
    ):
        raise DataValidationError("Danh sách dòng bỏ phải là id dòng, không trùng.")
    if not ds_bo and set_id is None:
        raise DataValidationError("Văn bản điều chỉnh phải bỏ hoặc thêm ít nhất một dòng.")
    repo = CouncilDecisionRepository(db)
    try:
        async with db.begin_nested():
            goc = await repo.khoa_qd(goc_id)
            if goc is None:
                raise ResourceNotFoundError("Không có Quyết định này.")
            if goc.loai != "trung_tuyen" or goc.trang_thai != "hieu_luc":
                raise ConflictError(
                    "Chỉ điều chỉnh được Quyết định trúng tuyển đang hiệu lực."
                )
            bo, dong_them = None, []
            if set_id is not None:
                if xac_nhan_khop_ban_in is not True:
                    raise DataValidationError(
                        "Admin phải xác nhận dữ liệu em được thêm / sửa khớp bản ký."
                    )
                bo, dong_them = await _bo_qd_hop_le(repo, set_id, cho_dieu_chinh_cua=goc.id)
                if (
                    isinstance(xac_nhan_so_ho_so, bool)
                    or not isinstance(xac_nhan_so_ho_so, int)
                    or xac_nhan_so_ho_so != bo.so_ho_so
                ):
                    raise DataValidationError("Số hồ sơ gõ lại không khớp số hồ sơ của bộ.")
            chuoi = await _chuoi_hieu_luc(repo, goc.id)
            dong_bo_di = await repo.dong_theo_id(ds_bo)
            if len(dong_bo_di) != len(ds_bo):
                raise DataValidationError("Có dòng bỏ không tồn tại.")
            sai = [
                d.id
                for d in dong_bo_di
                if d.decision_id not in chuoi
                or d.trang_thai_cha != "hieu_luc"
                or d.bi_bo_boi_id is not None
            ]
            if sai:
                raise ConflictError(
                    "Dòng %s không phải dòng đang hiệu lực của chuỗi Quyết định này."
                    % ", ".join(map(str, sai)),
                    public_payload={"dong_khong_hop_le": sai},
                )
            await _so_chua_dung(repo, so, ngay.year)
            pids_them = [d.profile_id for d in dong_them]
            hien_tai = await repo.khoa_ho_so(
                pids_them + [d.profile_id for d in dong_bo_di if d.profile_id is not None]
            )
            # Chặng 2b: dòng THÊM chiếm chỗ (Phần B); dòng BỎ chỉ trả chỗ ⇒ không cần khoá.
            await khoa_chi_tieu_cua_dong_bo(db, [d.id for d in dong_them])
            # Q-J1: dòng THÊM phải đủ khoá đếm + khớp chuỗi (dưới khoá, trước ghi).
            await kiem_khoa_dem_dong_bo(db, [(d.stt, d.id) for d in dong_them])
            tt = await tinh_trang_qd(db, pids_them)
            chan = _chan_tinh_trang(dong_them, tt, cho_phep_chuoi=goc.id)
            bo_ids = set(ds_bo)
            for d in dong_them:  # em có dòng trong chuỗi thì dòng ấy PHẢI nằm trong danh sách bỏ
                t = tt.get(d.profile_id)
                if t is not None and t.qd_hieu_luc_id is not None and t.qd_chuoi_id == goc.id:
                    cu = await repo.dong_hieu_luc_cua_ho_so([d.profile_id])
                    if cu.get(d.profile_id) is None or cu[d.profile_id].id not in bo_ids:
                        chan.append(
                            {
                                "dong": d.stt,
                                "ly_do": "chua_bo_dong_cu",
                                "quyet_dinh_id": t.qd_hieu_luc_id,
                            }
                        )
            if chan:
                raise ConflictError(
                    "%d hồ sơ của bộ không thêm được vào văn bản điều chỉnh." % len(chan),
                    public_payload={"dong_bi_chan": chan},
                )
            dem, dong_tt, la = _dem_doi_trang_thai(dong_them, hien_tai)
            if la:
                raise DataValidationError("Có trạng thái hồ sơ không xác định — không ghi nhận.")
            da_xn = _kiem_xac_nhan_dem(dem, dong_tt, xac_nhan, "Có em đổi trạng thái sau khi dựng bộ")
            dc = CouncilDecision(
                loai="dieu_chinh",
                can_bo=bo is not None,
                set_id=bo.id if bo is not None else None,
                goc_id=goc.id,
                so_quyet_dinh=so,
                ngay_ky=ngay,
                pham_vi_so=ngay.year,
                trang_thai="hieu_luc",
                so_ho_so=len(dong_them),
                xac_nhan={"doi_trang_thai": da_xn, "so_dong_bo": len(ds_bo)},
                ghi_chu_mau=ghi_chu,
                ghi_nhan_boi_id=nguoi_id,
            )
            await repo.them(dc)
            if ds_bo:  # BỎ trước
                await db.execute(
                    text(
                        "UPDATE council_decision_row SET bi_bo_boi_id = :d "
                        "WHERE id = ANY(CAST(:ids AS integer[]))"
                    ),
                    {"d": dc.id, "ids": ds_bo},
                )
            if bo is not None:  # THÊM sau
                n = await repo.chen_dong_tu_bo(dc.id, bo.id)
                if n != len(dong_them):
                    raise ServiceError("Chép dòng bộ sang văn bản thiếu dòng — không ghi.")
            await repo.them(
                _scan(dc.id, b),
                _su_kien(
                    "ghi_nhan_dieu_chinh",
                    nguoi_id=nguoi_id,
                    set_id=dc.set_id,
                    decision_id=dc.id,
                    so_lieu={
                        "goc_id": goc.id,
                        "so_dong_bo": len(ds_bo),
                        "so_dong_them": len(dong_them),
                    },
                ),
            )
    except DBAPIError as e:
        raise _dich_loi_csdl(ma_loi_csdl(e), "ghi nhận văn bản điều chỉnh") from None
    return dc, None


# ═══════════════════════════════ huỷ hiệu lực (văn bản huỷ của trường) ═════════════════════
async def huy_hieu_luc(
    db: AsyncSession,
    decision_id: int,
    *,
    so_quyet_dinh: object,
    ngay_ky: object,
    scan: object,
    nguoi_id: int,
) -> Tuple[CouncilDecision, Dict[str, int]]:
    """Ghi nhận VĂN BẢN HUỶ của trường trỏ văn bản ``decision_id`` (BS §2; đặc tả 2.3): văn bản đích ⇒
    ``het_hieu_luc`` (CSDL lan xuống dòng — K2); mỗi em có dòng hiệu lực của nó (và, nếu là điều chỉnh,
    em nó đã bỏ mà không còn dòng hiệu lực nào khác) ⇒ nhóm "chờ Admin quyết" (C7). Trả (văn bản huỷ,
    số đếm)."""
    so = kiem_so_quyet_dinh(so_quyet_dinh)
    ngay = kiem_ngay(ngay_ky)
    b = kiem_scan(scan)
    repo = CouncilDecisionRepository(db)
    try:
        async with db.begin_nested():
            x = await repo.khoa_qd(decision_id)
            if x is None:
                raise ResourceNotFoundError("Không có văn bản này.")
            if x.loai == "van_ban_huy":
                raise DataValidationError("Không ghi văn bản huỷ cho một văn bản huỷ.")
            if x.trang_thai != "hieu_luc":
                raise ConflictError("Văn bản này không còn hiệu lực.")
            if x.loai == "trung_tuyen":
                con = [
                    d.id
                    for d in (await _chuoi_hieu_luc(repo, x.id)).values()
                    if d.id != x.id
                ]
                if con:
                    raise ConflictError(
                        "Quyết định còn văn bản bổ sung / điều chỉnh đang hiệu lực (#%s) — ghi "
                        "nhận văn bản huỷ cho từng văn bản đúng như trường ban hành."
                        % ", #".join(map(str, con)),
                        public_payload={"van_ban_con_hieu_luc": con},
                    )
            await _so_chua_dung(repo, so, ngay.year)
            dong_hl = await repo.dong_hieu_luc_cua_qd(x.id)
            dong_bi_bo = await repo.dong_bi_bo_boi(x.id) if x.loai == "dieu_chinh" else []
            pids = [d.profile_id for d in dong_hl + dong_bi_bo if d.profile_id is not None]
            await repo.khoa_ho_so(pids)
            dang_mo = await repo.muc_cho_dang_mo(pids)
            hieu_luc_khac = await repo.dong_hieu_luc_cua_ho_so(
                [d.profile_id for d in dong_bi_bo if d.profile_id is not None]
            )
            h = CouncilDecision(
                loai="van_ban_huy",
                can_bo=False,
                set_id=None,
                huy_qd_id=x.id,
                so_quyet_dinh=so,
                ngay_ky=ngay,
                pham_vi_so=ngay.year,
                trang_thai="hieu_luc",
                so_ho_so=0,
                ghi_nhan_boi_id=nguoi_id,
            )
            await repo.them(h)
            x.trang_thai = "het_hieu_luc"
            x.het_hieu_luc_boi_id = h.id
            await db.flush()
            moi: Dict[int, CouncilDecisionHold] = {}
            da_o_nhom = 0
            for d, ly_do_vao in [(d, "qd_bi_huy") for d in dong_hl] + [
                (d, "bi_bo_boi_van_ban_bi_huy") for d in dong_bi_bo
            ]:
                p = d.profile_id
                if p is None or p in moi:
                    continue
                if p in dang_mo:
                    da_o_nhom += 1
                    continue
                if ly_do_vao == "bi_bo_boi_van_ban_bi_huy" and p in hieu_luc_khac:
                    continue  # em đang có Quyết định hiệu lực khác — không cần chờ
                moi[p] = CouncilDecisionHold(
                    profile_id=p,
                    decision_row_id=d.id,
                    van_ban_huy_id=h.id,
                    ly_do_vao=ly_do_vao,
                    trang_thai="cho_quyet",
                )
            so_lieu = {
                "quyet_dinh_bi_huy": x.id,
                "so_dong_tat": len(dong_hl),
                "so_muc_cho_moi": len(moi),
                "so_da_o_nhom_cho": da_o_nhom,
            }
            await repo.them(
                *moi.values(),
                _scan(h.id, b),
                _su_kien(
                    "huy_hieu_luc",
                    nguoi_id=nguoi_id,
                    set_id=x.set_id,
                    decision_id=h.id,
                    so_lieu=so_lieu,
                ),
            )
    except DBAPIError as e:
        raise _dich_loi_csdl(ma_loi_csdl(e), "ghi nhận văn bản huỷ") from None
    return h, so_lieu


# ═══════════════════════════════ huỷ ghi nhận (nhập sai) ══════════════════════════════════
async def huy_ghi_nhan(
    db: AsyncSession,
    decision_id: int,
    *,
    ly_do: object,
    so_go_lai: object,
    xac_nhan: object,
    nguoi_id: int,
) -> Tuple[CouncilDecision, Dict[str, int]]:
    """Huỷ ghi nhận = văn bản nhập SAI vào phần mềm — như chưa từng ghi, giữ vết (BS §2; đặc tả 2.5).
    Chỉ gỡ được văn bản MỚI NHẤT còn sống của chuỗi. Văn bản huỷ: văn bản đích có hiệu lực lại (CSDL lan
    + U3 chặn nếu em đã ở Quyết định khác); mọi mục chờ nó sinh ⇒ ``vo_hieu`` — trong CÙNG giao dịch."""
    ly_do = kiem_ly_do(ly_do, "huỷ ghi nhận")
    xn = kiem_xac_nhan_trang_thai(xac_nhan)
    repo = CouncilDecisionRepository(db)
    so_lieu: Dict[str, int] = {}
    try:
        async with db.begin_nested():
            x = await repo.khoa_qd(decision_id)
            if x is None:
                raise ResourceNotFoundError("Không có văn bản này.")
            if so_go_lai != x.so_quyet_dinh:
                raise DataValidationError("Số văn bản gõ lại không khớp.")
            if x.trang_thai == "huy_ghi_nhan":
                raise ConflictError("Văn bản đã được huỷ ghi nhận.")
            dich = None
            if x.loai == "van_ban_huy":
                dich = await repo.khoa_qd(x.huy_qd_id)
                goc_chuoi = dich.goc_id or dich.id
            else:
                goc_chuoi = x.goc_id or x.id
            song = [d for d in await repo.chuoi(goc_chuoi) if d.trang_thai != "huy_ghi_nhan"]
            sau = sorted(d.id for d in song if d.id > x.id)
            if sau:
                raise ConflictError(
                    "Có văn bản ghi nhận SAU đã tác động lên chuỗi này (#%s) — huỷ ghi nhận văn bản "
                    "mới nhất trước." % ", #".join(map(str, sau)),
                    public_payload={"van_ban_sau": sau},
                )
            bat_lai: List[Any] = []
            if dich is not None:
                bat_lai = [
                    d for d in await repo.dong_cua_qd(dich.id) if d.bi_bo_boi_id is None
                ]
            elif x.loai == "dieu_chinh":
                bat_lai = await repo.dong_bi_bo_boi(x.id)
            muc = await repo.muc_cho_cua_qd_huy(x.id) if dich is not None else []
            pids = [d.profile_id for d in bat_lai if d.profile_id is not None]
            hien_tai = await repo.khoa_ho_so(pids + [m.profile_id for m in muc if m.profile_id])
            # Chặng 2b: dòng BẬT LẠI chiếm chỗ lại (Phần B) ⇒ khoá dòng chỉ tiêu của chúng.
            await khoa_chi_tieu_cua_dong_bo(db, [d.set_row_id for d in bat_lai])
            # Q-J1: dòng BẬT LẠI phải đủ khoá đếm + khớp chuỗi (dưới khoá, trước ghi).
            await kiem_khoa_dem_dong_bo(db, [(d.stt, d.set_row_id) for d in bat_lai])
            khac = await repo.dong_hieu_luc_cua_ho_so(pids)
            xung = [
                {"dong": d.stt, "quyet_dinh_id": khac[d.profile_id].decision_id}
                for d in bat_lai
                if d.profile_id in khac and khac[d.profile_id].decision_id != x.id
            ]
            if xung:
                raise ConflictError(
                    "%d em đã có tên trong Quyết định khác — phải có văn bản đưa em ra khỏi một trong "
                    "hai Quyết định trước." % len(xung),
                    public_payload={"dong_xung_dot": xung},
                )
            if dich is not None:
                dem: Dict[str, int] = {}
                dong: Dict[str, List[int]] = {}
                n_xl = [m for m in muc if m.trang_thai == "da_cho_xet_lai"]
                if n_xl:
                    dem["da_cho_xet_lai"] = len(n_xl)
                for d in bat_lai:
                    s = hien_tai.get(d.profile_id)
                    if s is not None and s not in TRANG_THAI_KHONG_CANH_BAO:
                        dem[s] = dem.get(s, 0) + 1
                        dong.setdefault(s, []).append(d.stt)
                _kiem_xac_nhan_dem(dem, dong, xn, "Huỷ ghi nhận văn bản huỷ")
            elif xn is not None:
                raise ConflictError("Không còn gì cần xác nhận — gửi lại không kèm xác nhận.")
            luc = datetime.now(timezone.utc)
            x.trang_thai = "huy_ghi_nhan"
            x.huy_ghi_nhan_boi_id = nguoi_id
            x.huy_ghi_nhan_luc = luc
            x.ly_do_huy_ghi_nhan = ly_do
            await db.flush()  # CSDL lan cờ xuống dòng của x (K2)
            if dich is not None:
                dich.trang_thai = "hieu_luc"
                dich.het_hieu_luc_boi_id = None
                await db.flush()  # CSDL lan; U3 chặn cuối
                for m in muc:
                    if m.trang_thai != "vo_hieu":
                        m.trang_thai = "vo_hieu"
                        m.vo_hieu_boi_id = nguoi_id
                        m.vo_hieu_luc = luc
                await db.flush()
            elif x.loai == "dieu_chinh" and bat_lai:
                await db.execute(  # bật lại dòng điều chỉnh đã bỏ — SAU khi dòng của nó đã tắt
                    text("UPDATE council_decision_row SET bi_bo_boi_id = NULL WHERE bi_bo_boi_id = :d"),
                    {"d": x.id},
                )
            so_lieu = {
                "loai": x.loai,
                "so_dong_bat_lai": len(bat_lai),
                "so_muc_cho_vo_hieu": len([m for m in muc]),
            }
            await repo.them(
                _su_kien(
                    "huy_ghi_nhan",
                    nguoi_id=nguoi_id,
                    set_id=x.set_id,
                    decision_id=x.id,
                    so_lieu=so_lieu,
                )
            )
    except DBAPIError as e:
        raise _dich_loi_csdl(ma_loi_csdl(e), "huỷ ghi nhận") from None
    return x, so_lieu


# ═══════════════════════════════ nhóm chờ — Admin cho xét lại TỪNG em (C7) ═════════════════
async def cho_xet_lai(
    db: AsyncSession, hold_id: int, *, ly_do: object, nguoi_id: int
) -> Tuple[CouncilDecisionHold, None]:
    ly_do = kiem_ly_do(ly_do, "cho xét lại")
    repo = CouncilDecisionRepository(db)
    try:
        async with db.begin_nested():
            h = await repo.khoa_muc_cho(hold_id)
            if h is None:
                raise ResourceNotFoundError("Không có mục chờ này.")
            if h.trang_thai != "cho_quyet":
                raise ConflictError("Mục này không còn ở nhóm chờ Admin quyết.")
            if h.profile_id is not None:
                await repo.khoa_ho_so([h.profile_id])
            h.trang_thai = "da_cho_xet_lai"
            h.quyet_boi_id = nguoi_id
            h.quyet_luc = datetime.now(timezone.utc)
            h.ly_do_quyet = ly_do
            await db.flush()
            await repo.them(
                _su_kien(
                    "cho_xet_lai",
                    nguoi_id=nguoi_id,
                    hold_id=h.id,
                    decision_id=h.van_ban_huy_id,
                    so_lieu={"muc_cho_id": h.id, "van_ban_huy_id": h.van_ban_huy_id},
                )
            )
    except DBAPIError as e:
        raise _dich_loi_csdl(ma_loi_csdl(e), "cho xét lại") from None
    return h, None


# ═══════════════════════════════ đọc ═════════════════════════════════════════════════════
async def tom_tat_qd_cua_bo(db: AsyncSession, set_id: int) -> Optional[Dict[str, Any]]:
    """Trạng thái + số + ngày + số em của văn bản đã ký (chưa huỷ ghi nhận, mới nhất) của bộ — phần
    Quản lý được xem trên bộ đơn vị mình (J1 dòng 9). Không id hồ sơ."""
    song = await CouncilDecisionRepository(db).van_ban_song_cua_bo(set_id)
    if not song:
        return None
    d = song[-1]
    return {
        "loai": d.loai,
        "trang_thai": d.trang_thai,
        "so_quyet_dinh": d.so_quyet_dinh,
        "ngay_ky": d.ngay_ky.isoformat(),
        "so_ho_so": d.so_ho_so,
    }


async def chi_tiet_qd(db: AsyncSession, decision_id: int):
    repo = CouncilDecisionRepository(db)
    qd = await repo.qd_theo_id(decision_id)
    if qd is None:
        raise ResourceNotFoundError("Không có văn bản này.")
    dong = await repo.dong_cua_qd(decision_id)
    scan = await repo.scan_cua_qd(decision_id)
    su_kien = await repo.danh_sach_su_kien(
        set_id=None, decision_id=decision_id, limit=200, offset=0
    )
    return qd, dong, scan, su_kien


async def doc_scan(db: AsyncSession, decision_id: int) -> CouncilDecisionScan:
    s = await CouncilDecisionRepository(db).scan_cua_qd(decision_id, kem_noi_dung=True)
    if s is None:
        raise ResourceNotFoundError("Văn bản này không có bản scan.")
    if hashlib.sha256(bytes(s.noi_dung)).hexdigest() != s.sha256:
        raise ServiceError("Bản scan đã lưu lệch sha256 — không trả.")
    return s


async def ghi_tai_scan(db: AsyncSession, scan: CouncilDecisionScan, nguoi_id: int) -> None:
    """Nhật ký mỗi lần CẤP bản scan (khuôn J1 dòng 31) — router COMMIT trước khi trả bytes."""
    try:
        await CouncilDecisionRepository(db).them(
            _su_kien(
                "tai_scan",
                nguoi_id=nguoi_id,
                decision_id=scan.decision_id,
                so_lieu={"sha256": scan.sha256, "kich_thuoc": scan.kich_thuoc},
            )
        )
    except DBAPIError:
        raise ServiceError("Không ghi được nhật ký tải bản scan — không trả tệp.") from None
