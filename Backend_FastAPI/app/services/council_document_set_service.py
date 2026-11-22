# app/services/council_document_set_service.py
"""Tạo + tải lại bộ văn bản Hội đồng (giai đoạn 1 "Lần xét tuyển", PR 1.3 / 1.4 phần lưu).

Tạo bộ = bốn bước, lỗi ở BẤT KỲ bước nào ⇒ không ghi gì:

1. Đọc hồ sơ theo danh sách mã ở MỘT giao dịch ``REPEATABLE READ READ ONLY`` trên kết nối
   riêng (:func:`council_candidate_service.doc_ho_so_theo_ma`) — giao dịch ấy KẾT THÚC trước
   khi dựng; bước ghi (iv) chạy ở giao dịch KHÁC (của request — qua API đã mở từ bước xác
   thực, không bị đóng giữa chừng).
2. Chọn mẫu theo ngày ký = ``ngay_quyet_dinh`` nếu có, không thì ngày tạo theo giờ Việt Nam
   (:func:`council_document_template_service.pick_templates`); kiểm lại gói zip của mẫu đã chọn
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
from app.constants import admission_circular as _circular_constants
from app.constants.admission_circular import vn_calendar_date
from app.models import council_document as _document_models
from app.models.council_document import (
    MAX_DELETE_REASON_LENGTH,
    CouncilDocumentDownloadLog,
    CouncilDocumentEvent,
    CouncilDocumentSet,
    CouncilDocumentSetDeletion,
    CouncilDocumentSetFile,
    CouncilDocumentSetRow,
)
from app.repositories import council_candidate_repository as _candidate_repo
from app.repositories import council_decision_repository as _decision_repo
from app.repositories import council_document_repository as _document_repo
from app.repositories.council_decision_repository import (
    CouncilDecisionRepository,
    db_error_codes,
)
from app.repositories.council_document_repository import CouncilDocumentRepository
from app.services import admission_choice_engine_service as _choice_engine
from app.services import council_candidate_service as _candidate_service
from app.services import council_decision_status_service as _decision_status
from app.services import council_document_render_service as render_service
from app.services import council_document_template_service as _template_service
from app.services import council_set_gate_service as set_gate
from app.services import priority_service as _priority_service
from app.services.council_candidate_service import read_profiles_by_code
from app.services.council_document_template_service import (
    KIND_NAMES,
    pick_templates,
    check_template_package,
)
from app.utils.exceptions import (
    ConflictError,
    DataValidationError,
    ResourceNotFoundError,
    ServiceError,
)

#: Các module mà mã nguồn quyết định NỘI DUNG một bộ văn bản (F212). U4 (ultra GĐ1 — owner 21-11): danh sách khoá bằng
#: ``tests/unit/test_council_phien_ban_ma_bo.py`` — mọi module mà đường đọc + cổng + bộ dựng (6 module lõi đầu) import phải
#: có ở đây hoặc nằm trong danh sách loại trừ CÓ lý do của test. Đổi danh sách ⇒ dấu kiểm trước cũ lệch (409 "Kiểm tra lại")
#: sau lần deploy đầu — đã biết, chấp nhận.
BUILD_CODE_MODULES = (
    render_service,
    _template_service,
    _candidate_service,
    _candidate_repo,
    sys.modules[__name__],
    set_gate,  # lượt G: cổng quyết hồ sơ nào vào bộ + điểm KV in
    _priority_service,  # U4: KV / đối tượng in (resolve_kv_for_profile, select_open_priority_rates, bật / tắt cộng điểm…)
    _choice_engine,  # U4: resolve_effective_bonus_rule — luật cộng điểm của đường xét
    _decision_status,  # U4: from_row / decision_state — tình trạng Quyết định quyết dòng nào bị chặn
    _document_models,  # U4: SQL_DECISION_STATE_COLUMNS (SQL tình trạng Quyết định) + bảng bộ / dòng bộ
    _document_repo,  # đi import: effective_template — mẫu nào được chọn theo ngày
    _decision_repo,  # đi import: dòng bộ của bộ in ban đầu (tái dựng), hồ sơ ở bộ khác (thông tin dựng)
    _circular_constants,  # đi import: vn_calendar_date — ngày (giờ VN) chọn mẫu
)


def _compute_code_versions() -> Optional[Dict[str, str]]:
    """{tên module: sha256 nội dung tệp nguồn ĐÃ NẠP}; không đọc được tệp ⇒ None (tạo bộ
    sẽ dừng, không dựng một bộ không biết mã nào đã dựng)."""
    try:
        return {
            m.__name__: hashlib.sha256(Path(m.__file__).read_bytes()).hexdigest()
            for m in BUILD_CODE_MODULES
        }
    except (OSError, TypeError, AttributeError):  # tệp mất / module không đến từ tệp
        return None


#: Tính MỘT lần lúc nạp module — đúng các tệp mà tiến trình này đang chạy.
CODE_VERSIONS = _compute_code_versions()


def set_unit(profile_units: Sequence[Optional[int]]) -> Optional[int]:
    """Mọi hồ sơ cùng MỘT đơn vị khác NULL ⇒ đơn vị đó; nhiều đơn vị / có NULL / rỗng ⇒
    NULL (bộ chỉ admin xem)."""
    unit_set = set(profile_units)
    if len(unit_set) == 1:
        (unit,) = unit_set
        return unit
    return None


def signing_date_for_template(
    params: Optional[render_service.DecisionParams], created_at: datetime
) -> date:
    """Ngày ký để chọn mẫu: ngày Quyết định nếu có, không thì ngày tạo theo giờ Việt Nam."""
    if params is not None and params.ngay_quyet_dinh is not None:
        return params.ngay_quyet_dinh
    return vn_calendar_date(created_at)


async def create_document_set(
    db: AsyncSession,
    engine: AsyncEngine,
    *,
    profile_codes: Sequence[str],
    academic_year: Optional[int],
    params: Optional[render_service.DecisionParams],
    creator_id: Optional[int],
    created_at: Optional[datetime] = None,
    confirm_status: Optional[Dict[str, int]] = None,
    can_confirm: bool = False,
) -> Tuple[CouncilDocumentSet, None]:
    """Dựng bộ XÉT MỚI (``POST /sets``) — ĐỦ mọi cổng, KHÔNG nhận tham số nào nới cổng (lượt I, đặc tả
    mục 3.2 P1: test AST khoá lời gọi dưới truyền đúng HẰNG ``None``)."""
    return await _build_and_write_set(
        db,
        engine,
        profile_codes=profile_codes,
        academic_year=academic_year,
        params=params,
        creator_id=creator_id,
        created_at=created_at,
        confirm_status=confirm_status,
        can_confirm=can_confirm,
        allowed_decision_chain=None,
    )


async def create_document_set_by_ids(
    db: AsyncSession,
    engine: AsyncEngine,
    *,
    profile_ids: Sequence[int],
    check_signature: str,
    academic_year: Optional[int],
    params: Optional[render_service.DecisionParams],
    creator_id: Optional[int],
    created_at: Optional[datetime] = None,
    confirm_status: Optional[Dict[str, int]] = None,
    can_confirm: bool = False,
) -> Tuple[CouncilDocumentSet, None]:
    """Dựng bộ XÉT MỚI dạng id (vòng giao diện — ``POST /sets`` với ``profile_ids`` + ``phien_ban_kiem``,
    đặc tả 3.3 + bản 2/3 mục 3.1.1). ĐỦ mọi cổng như :func:`tao_bo_van_ban`, KHÔNG nhận tham số nào nới
    cổng (test AST khoá cả hàm này). Thêm: thứ tự gửi phải là thứ tự chuẩn và dấu phải khớp ⇒ không thì
    409 ``du_lieu_doi_tu_luc_kiem``."""
    if not isinstance(check_signature, str) or not check_signature:
        raise DataValidationError("Thiếu dấu kiểm trước (phien_ban_kiem).")
    return await _build_and_write_set(
        db,
        engine,
        profile_codes=(),
        academic_year=academic_year,
        params=params,
        creator_id=creator_id,
        created_at=created_at,
        confirm_status=confirm_status,
        can_confirm=can_confirm,
        allowed_decision_chain=None,
        by_id_request=RequestById(
            profile_ids=tuple(check_id_list(profile_ids)),
            check_signature=check_signature,
        ),
    )


# ═══════════════ kiểm trước + thứ tự chuẩn (vòng giao diện — đặc tả 3.1, bản 2/3 mục 3.1.1) ═══════════
#: Nhãn dẫn xuất khoá HMAC của dấu kiểm trước — khoá riêng, không dùng thẳng ``SECRET_KEY`` (khuôn
#: ``duplicate_review_token._khoa_ky``). Đổi ``SECRET_KEY`` ⇒ mọi dấu cũ lệch ⇒ 409 ⇒ "Kiểm tra lại".
_PREVIEW_KEY_LABEL = b"council-preview-v1"
#: Phần đầu của dữ liệu băm — đổi cách băm thì đổi nhãn này.
SIGNATURE_VERSION_MARK = "pbk-v1"
ITEM_BUILDABLE = "duoc_dung"
ITEM_NEEDS_CONFIRMATION = "can_xac_nhan"
ITEM_BLOCKED = "bi_chan"
CHANGED_SINCE_CHECK_ERROR_CODE = "du_lieu_doi_tu_luc_kiem"
CHANGED_SINCE_CHECK_MESSAGE = "Dữ liệu đã đổi từ lúc kiểm — bấm Kiểm tra lại."


@dataclass(frozen=True)
class RequestById:
    """``POST /sets`` dạng id: danh sách id ĐÃ kiểm (thứ tự gửi) + dấu kiểm trước nhận lại nguyên văn."""

    profile_ids: Tuple[int, ...]
    check_signature: str


@dataclass(frozen=True)
class NormalizedRow:
    """MỘT dòng sau phép chuẩn hoá (đặc tả bản 3 mục 3.1.1 bước 1–2). Mọi trường trừ ``input_index`` vào dấu;
    ``input_index`` (chỉ số đầu vào, từ 0) KHÔNG băm — chỉ để biết dòng nào. Không có ``stt`` nguồn nào."""

    input_index: int
    pid: int
    unit_id: Optional[int]
    row: render_service.CandidateRowV1  # ảnh chụp NGUYÊN (chưa thay điểm KV / ĐT)
    check_data: set_gate.CheckData
    item: str
    reason_codes: Tuple[str, ...]  # đã sắp, không trùng
    area_score: Optional[str]  # điểm KV IN (cổng)
    priority_rule: Optional[str]
    priority_score: Optional[str]  # điểm đối tượng IN (cổng)
    admission_total: float  # tổng điểm xét tuyển tính từ điểm IN — chỉ để sắp / hiển thị
    sort_key: Tuple[Any, ...]  # khoá sắp chuẩn: nhóm → trong nhóm → id hồ sơ


def check_id_list(profile_ids: object) -> List[int]:
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
    first_seen: Dict[int, int] = {}
    for i, p in enumerate(profile_ids, 1):
        # Review max PR #724 (dưới ngưỡng): cận trên int4 — vượt ⇒ 400 tại đây, không 500 ở câu SQL.
        if isinstance(p, bool) or not isinstance(p, int) or p < 1 or p > 2147483647:
            raise DataValidationError("Dòng %d: id hồ sơ không hợp lệ." % i)
        if p in first_seen:
            raise DataValidationError(
                "Dòng %d trùng hồ sơ với dòng %d — mỗi người một dòng." % (i, first_seen[p])
            )
        first_seen[p] = i
        out.append(p)
    return out


def normalize_rows(snapshot: "_candidate_service.ProfileSnapshot", gate_result: "set_gate.GateResult") -> List[NormalizedRow]:
    """MỘT phép chuẩn hoá (đặc tả bản 3 mục 3.1.1) — ``kiem-truoc`` và ``POST /sets`` dạng id cùng gọi.

    1. Gom theo dòng: ảnh chụp + dữ liệu kiểm + id + đơn vị + kết quả cổng CỦA RIÊNG dòng ấy (rút từ
       ``GateResult`` bằng ``stt`` nguồn — chỉ dùng ở bước này).
    2. Không giữ giá trị nào phụ thuộc vị trí đầu vào: ``CheckData.stt`` bỏ ở :func:`preview_signature`;
       ``CandidateRowV1`` không có trường vị trí; câu lý do không băm, chỉ mã.
    3. Sắp bằng khoá chung của Quyết định (``decision_group_key`` → ``decision_in_group_key``) + phá
       hoà cuối bằng id hồ sơ."""
    n = len(snapshot.rows)
    if not (
        len(snapshot.check_data) == len(snapshot.pids) == len(snapshot.unit_ids) == n
        and len(gate_result.area_scores) == len(gate_result.priority_rules) == n
    ):
        raise ServiceError("Ảnh chụp / kết quả cổng không đủ dòng — không kiểm.")
    codes_by_seq: Dict[int, set] = {}
    for code, _status, row in gate_result.blocks:
        for s in row:
            codes_by_seq.setdefault(s, set()).add(code)
    warnings = {s for d in gate_result.warnings.values() for s in d}
    # Review max PR #724 (R10): lỗi DỮ LIỆU mà bước dựng sẽ dừng (một nguồn: ``bo_dung.row_data_error`` /
    # ``group_data_errors``) ⇒ dòng BỊ CHẶN ngay ở bản xem trước, cùng mã ở hai phía (dấu kiểm trước khớp).
    group_errors = render_service.group_data_errors(snapshot.rows)
    out: List[NormalizedRow] = []
    for i in range(n):
        k, r, pid = snapshot.check_data[i], snapshot.rows[i], snapshot.pids[i]
        data_codes = set()
        row_error = render_service.row_data_error(r)
        if row_error is not None:
            data_codes.add(row_error[0])
        if i in group_errors:
            data_codes.add(group_errors[i])
        code = tuple(sorted(set(codes_by_seq.get(k.stt, ())) | data_codes))
        item = (
            ITEM_BLOCKED
            if code
            else (ITEM_NEEDS_CONFIRMATION if k.stt in warnings else ITEM_BUILDABLE)
        )
        area = gate_result.area_scores[i]
        priority_rule = gate_result.priority_rules[i]
        priority = set_gate.printed_priority_score(priority_rule, r.diem_ut)
        # Điểm IN chưa có (dòng bị chặn) ⇒ ô rỗng ⇒ ``so`` đọc 0: vẫn sắp được, như nhau ở hai phía.
        total = render_service.compute_printed_scores(r.tong_diem, area or "", priority or "").admission_total
        out.append(
            NormalizedRow(
                input_index=i,
                pid=pid,
                unit_id=snapshot.unit_ids[i],
                row=r,
                check_data=k,
                item=item,
                reason_codes=code,
                area_score=area,
                priority_rule=priority_rule,
                priority_score=priority,
                admission_total=total,
                sort_key=(
                    render_service.decision_group_key(r),
                    render_service.decision_in_group_key(total, r.ten),
                    pid,
                ),
            )
        )
    out.sort(key=lambda d: d.sort_key)
    return out


def _preview_key() -> bytes:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"), _PREVIEW_KEY_LABEL, hashlib.sha256
    ).digest()


def preview_signature(row: Sequence[NormalizedRow], academic_year: int) -> str:
    """MỘT hàm dấu (đặc tả bản 2 mục 3.1.1 + bản 3): HMAC-SHA256 (khoá suy từ ``SECRET_KEY``) của JSON
    chuẩn (khoá sắp, không khoảng trắng) gồm phần đầu (nhãn, năm học, luật dựng, phiên bản mã dựng) + mỗi
    dòng ĐÃ SẮP: ``stt_chuan``, TOÀN BỘ ảnh chụp in, TOÀN BỘ dữ liệu kiểm trừ ``stt``, id, đơn vị, mức, mã
    lý do, điểm KV / luật ĐT / điểm ĐT in. KHÔNG băm mốc giao dịch. Không ghi dấu vào log."""
    if CODE_VERSIONS is None:
        raise ServiceError(
            "Không đọc được mã nguồn của bộ dựng để ghi phiên bản — không kiểm."
        )
    data = {
        "dau": [SIGNATURE_VERSION_MARK, academic_year, render_service.RENDER_RULE, CODE_VERSIONS],
        "dong": [
            {
                "stt_chuan": seq,
                "row": d.row.model_dump(mode="json"),
                "kiem": {k: v for k, v in asdict(d.check_data).items() if k != "stt"},
                "pid": d.pid,
                "don_vi": d.unit_id,
                "muc": d.item,
                "ma_ly_do": list(d.reason_codes),
                "diem_kv": d.area_score,
                "luat_ut": d.priority_rule,
                "diem_ut": d.priority_score,
            }
            for seq, d in enumerate(row, 1)
        ],
    }
    b = json.dumps(
        data, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hmac.new(_preview_key(), b, hashlib.sha256).hexdigest()


def compare_with_preview(
    snapshot: "_candidate_service.ProfileSnapshot",
    gate_result: "set_gate.GateResult",
    academic_year: int,
    by_id_request: RequestById,
) -> None:
    """``POST /sets`` dạng id (đặc tả bản 2 mục 3.1.1 bước 2 + 4): thứ tự gửi khác thứ tự chuẩn của ảnh
    chụp, HOẶC dấu tính lại khác dấu đã kiểm (so bằng ``hmac.compare_digest``) ⇒ 409
    ``du_lieu_doi_tu_luc_kiem``. Không tự sắp lại."""
    normalized = normalize_rows(snapshot, gate_result)
    in_order = [d.pid for d in normalized] == list(by_id_request.profile_ids)
    signature_matches = hmac.compare_digest(
        preview_signature(normalized, academic_year).encode("ascii"),
        by_id_request.check_signature.encode("utf-8"),
    )
    if not (in_order and signature_matches):
        raise ConflictError(
            CHANGED_SINCE_CHECK_MESSAGE, public_payload={"ma_loi": CHANGED_SINCE_CHECK_ERROR_CODE}
        )


async def preview(
    engine: AsyncEngine,
    *,
    profile_ids: Sequence[int],
    academic_year: Optional[int],
    all_units: bool,
    only_unit_id: Optional[int],
    can_confirm: bool,
) -> Dict[str, Any]:
    """``POST /sets/kiem-truoc`` (đặc tả 3.1 + bản 2/3 mục 3.1.1): đọc (cùng đường đọc của bộ dựng, lọc phạm
    vi), cổng (``cong.evaluate`` — không luật thứ hai), chuẩn hoá + dấu. KHÔNG ghi gì, KHÔNG lấy khoá tư vấn
    dựng. Mọi chữ hiển thị (họ tên, ngành, đường xét, điểm in) lấy từ CÙNG ảnh chụp / kết quả cổng đã băm."""
    year = _candidate_service.check_academic_year(academic_year)
    ids = check_id_list(profile_ids)
    snapshot, not_found = await _candidate_service.read_profiles_for_preview(
        engine, ids, academic_year=year, all_units=all_units, only_unit_id=only_unit_id
    )
    if snapshot is None:
        normalized: List[NormalizedRow] = []
        checked_at = datetime.now(timezone.utc)
        warning_count: Dict[str, int] = {}
    else:
        result = set_gate.evaluate(snapshot.check_data)
        normalized = normalize_rows(snapshot, result)
        checked_at = snapshot.transaction.snapshot_at
        warning_count = result.warning_count()
    rows_out: List[Dict[str, Any]] = []
    group: Dict[Tuple[str, str], int] = {}
    for seq, d in enumerate(normalized, 1):
        group_key = render_service.decision_group_key(d.row)
        group[group_key] = group.get(group_key, 0) + 1
        rows_out.append(
            {
                "stt": seq,
                "stt_qd": group[group_key],
                "profile_id": d.pid,
                "ho_ten": ("%s %s" % (d.row.ho.strip(), d.row.ten.strip())).strip(),
                "trang_thai": d.check_data.status if isinstance(d.check_data.status, str) else "",
                "nganh_nhan": group_key[0],
                "trinh_do": group_key[1],
                "duong_xet_nhan": d.row.phuong_thuc.strip() or None,
                "diem_in": (
                    "%.2f" % d.admission_total
                    if d.area_score is not None and d.priority_score is not None
                    else None
                ),
                "muc": d.item,
                "ly_do": [
                    {"ma": m, "cau": set_gate.BLOCK_REASONS.get(m) or render_service.ROW_DATA_ERROR_REASONS.get(m, m)}
                    for m in d.reason_codes
                ],
            }
        )
    item_counts = {
        m: sum(1 for d in normalized if d.item == m)
        for m in (ITEM_BUILDABLE, ITEM_NEEDS_CONFIRMATION, ITEM_BLOCKED)
    }
    return {
        "kiem_luc": checked_at,
        "phien_ban_kiem": preview_signature(normalized, year),
        "dong": rows_out,
        "khong_tim_thay": not_found,
        "tom_tat": {
            "tong": len(normalized),
            "duoc_dung": item_counts[ITEM_BUILDABLE],
            "can_xac_nhan": item_counts[ITEM_NEEDS_CONFIRMATION],
            "bi_chan": item_counts[ITEM_BLOCKED],
            "theo_nganh": [
                {"nganh_nhan": group_key[0], "trinh_do": group_key[1], "so": number}
                for group_key, number in group.items()
            ],
            "can_xac_nhan_theo_trang_thai": warning_count,
            "so_nhom": len(group),
            "du_kien_so_tep": 2 + 2 * len(group),
            "nguoi_goi_duoc_xac_nhan": bool(can_confirm),
        },
    }


async def _build_and_write_set(
    db: AsyncSession,
    engine: AsyncEngine,
    *,
    profile_codes: Sequence[str],
    academic_year: Optional[int],
    params: Optional[render_service.DecisionParams],
    creator_id: Optional[int],
    created_at: Optional[datetime],
    confirm_status: Optional[Dict[str, int]],
    can_confirm: bool,
    allowed_decision_chain: Optional[int],
    by_id_request: Optional["RequestById"] = None,
) -> Tuple[CouncilDocumentSet, None]:
    """Đọc → cổng dựng bộ → chọn mẫu → dựng → ghi. Trả ``(bộ đã flush, None)``; router commit.
    ``by_id_request`` (vòng giao diện — ``POST /sets`` dạng id): đọc theo id thay cho mã, rồi so thứ tự + dấu kiểm
    trước (:func:`so_voi_kiem_truoc`) TRƯỚC cổng chặn / xác nhận; ``ma_ho_so`` khi ấy bỏ qua.
    ``allowed_decision_chain`` (CHỈ bộ dữ liệu cho văn bản điều chỉnh — :func:`tao_bo_dieu_chinh`) nới đúng
    MỘT phép: hồ sơ có dòng hiệu lực trong chính chuỗi Quyết định ấy; bộ ghi
    ``cho_quyet_dinh_goc_id`` = chuỗi ấy (chỉ dùng được cho điều chỉnh của chuỗi).
    ``academic_year`` BẮT BUỘC (mã hồ sơ chỉ duy nhất trong một năm học).

    Cổng (lượt G, owner 05-11 — ``council_set_gate_service``): dòng bị CHẶN (F228 trạng thái,
    F229 nguồn ngành / nguyện vọng / điểm, F231 khu vực) ⇒ 400 liệt kê từng dòng; có hồ sơ ở mức
    CẢNH BÁO ⇒ 409 trừ khi ``xac_nhan_trang_thai`` = ĐÚNG số đếm theo trạng thái hiện tại và
    người gọi ``can_confirm`` (chỉ admin — ``deps.py`` tính). Lần xác nhận ghi vết vào
    ``thong_tin_dung`` của bộ (ai, lúc nào, bao nhiêu hồ sơ mỗi trạng thái, số dòng)."""
    created_at = created_at or datetime.now(timezone.utc)
    if CODE_VERSIONS is None:
        raise ServiceError(
            "Không đọc được mã nguồn của bộ dựng để ghi phiên bản — không dựng."
        )
    # Chỉ admin được gửi xác nhận — kiểm TRƯỚC khi đọc hồ sơ (không đọc dữ liệu cá nhân cho
    # một yêu cầu không có quyền xác nhận).
    confirmation = set_gate.check_confirmation_shape(confirm_status)
    set_gate.check_confirm_permission(confirmation, can_confirm)
    # Tham số QĐ quyết cả NGÀY KÝ (chọn mẫu) ⇒ kiểm lại ngay từ đầu, bằng đúng hàm của bộ
    # dựng (bộ dựng còn kiểm lại một lần nữa ở điểm vào của nó).
    params = render_service.recheck_decision_params(params)

    # BẤT BIẾN GIAO DỊCH (F218 — Codex lần 5 chọn): đọc ở MỘT giao dịch RIÊNG ``REPEATABLE
    # READ READ ONLY`` trên kết nối riêng, đã KẾT THÚC trước khi dựng; ghi ở giao dịch KHÁC
    # (của request). KHÔNG hứa "giao dịch ghi bắt đầu sau mốc chụp": qua API, giao dịch của
    # request đã tự mở từ bước xác thực (đọc người dùng + phiên trên cùng phiên CSDL) và
    # không bị đóng giữa chừng. Test: ``test_ghi_bo_o_giao_dich_khac_giao_dich_doc`` (gọi
    # thẳng) + ``test_qua_api_doc_o_giao_dich_rieng_da_dong_truoc_khi_dung`` (POST /sets thật).
    # (i) đọc — giao dịch riêng, chỉ đọc, đã KẾT THÚC khi hàm này trả về. Dạng id (vòng giao diện,
    # đặc tả bản 2 mục 3.1.1 bước 1): đọc ĐÚNG MỘT lần; từ đây tới khi ghi không đọc hồ sơ lần nào nữa
    # — mọi thứ (so thứ tự, dấu, cổng, hàng in, dòng bộ) lấy từ CÙNG ``anh``.
    if by_id_request is None:
        snapshot = await read_profiles_by_code(engine, profile_codes, academic_year=academic_year)
    else:
        snapshot = await _candidate_service.read_profiles_by_id(
            engine, by_id_request.profile_ids, academic_year=academic_year
        )

    # (i-b) cổng dựng bộ (lượt G): chặn / cảnh báo + xác nhận. Không qua ⇒ lỗi miền, KHÔNG ghi.
    if len(snapshot.check_data) != len(snapshot.rows):
        raise ServiceError("Thiếu dữ liệu kiểm hồ sơ — không dựng.")
    if len(snapshot.pids) != len(snapshot.rows):
        raise ServiceError("Thiếu id hồ sơ của dòng — không dựng.")
    gate_result = set_gate.evaluate(snapshot.check_data, allowed_decision_chain=allowed_decision_chain)
    if by_id_request is not None:
        # Đặc tả bản 2 mục 3.1.1 bước 2 + 4: thứ tự gửi = thứ tự chuẩn của CHÍNH ảnh chụp này, và dấu tính
        # lại = dấu đã kiểm ⇒ mới đi tiếp tới cổng chặn / xác nhận. Lệch ⇒ 409, không tự sắp lại.
        compare_with_preview(snapshot, gate_result, academic_year, by_id_request)
    confirmation_done = set_gate.check_and_confirm(
        gate_result, confirmation=confirmation, can_confirm=can_confirm
    )
    # F231: điểm KV in = mức theo NĂM HỌC (cổng đã chặn mọi dòng không có mức); câu 22: đường
    # xét tắt / không có luật cộng KV ⇒ 0 (cổng tính — ``printed_area_score``).
    if any(m is None for m in gate_result.area_scores):
        raise ServiceError("Thiếu mức điểm khu vực sau cổng — không dựng.")
    # Lượt H2 (owner 06-11): điểm đối tượng in theo công tắc của đường xét — bật thì GIỮ điểm luật v1
    # của DTO, tắt / không có luật thì 0 (cổng tính — ``printed_priority_score``).
    priority_scores = tuple(
        set_gate.printed_priority_score(priority_rule, r.diem_ut) for priority_rule, r in zip(gate_result.priority_rules, snapshot.rows)
    )
    if len(priority_scores) != len(snapshot.rows) or any(u is None for u in priority_scores):
        raise ServiceError("Thiếu luật cộng điểm đối tượng sau cổng — không dựng.")
    print_rows = tuple(
        r.model_copy(update={"diem_kv": m, "diem_ut": u})
        for r, m, u in zip(snapshot.rows, gate_result.area_scores, priority_scores)
    )

    # Tối đa MỘT lần DỰNG cùng lúc trên toàn hệ (mọi worker / container cùng CSDL): khoá tư
    # vấn trên giao dịch của request — giữ tới khi router commit / rollback, tự nhả khi lỗi.
    # Trần 16 MB chỉ kiểm SAU khi dựng ⇒ đây là thứ chặn đỉnh RAM do nhiều lần dựng chồng
    # nhau (Codex lần 4). Khoá lấy sau bước đọc (như bản ``8015d068``); thứ tự khoá ↔ đọc
    # KHÔNG thuộc bất biến giao dịch ở trên. Hệ quả: lần thứ hai vẫn đọc hồ sơ (giao dịch chỉ
    # đọc) rồi mới bị từ chối — lỗi miền trước khi chọn mẫu / dựng / ghi.
    if not await CouncilDocumentRepository(db).try_build_lock():
        raise ConflictError(
            "Đang dựng một bộ văn bản khác — chờ bộ ấy xong rồi thử lại."
        )

    # (ii) mẫu theo ngày ký
    signing_date = signing_date_for_template(params, created_at)
    template, used_templates = await pick_templates(db, signing_date)
    for kind in render_service.TEMPLATE_KINDS:
        check_template_package(getattr(template, kind), KIND_NAMES[kind])

    # (iii) dựng — CPU vài giây, ngoài event loop
    rendered = await asyncio.to_thread(
        render_service.render_council_documents, list(print_rows), template, params
    )

    total = sum(len(f.content) for f in rendered.files)
    if total > settings.COUNCIL_SET_MAX_TOTAL_BYTES:
        raise DataValidationError(
            "Bộ văn bản %d byte, vượt giới hạn kỹ thuật %d byte — không lưu."
            % (total, settings.COUNCIL_SET_MAX_TOTAL_BYTES)
        )
    for f in rendered.files:  # bộ dựng tự tính sha; khẳng định lại trước khi lưu
        if hashlib.sha256(f.content).hexdigest() != f.sha256:
            raise ServiceError("sha256 của tệp sinh lệch nội dung — không lưu.")

    # (iv) ghi — phiên của request, SAVEPOINT: hỏng giữa chừng thì không còn hàng nào.
    md = dict(rendered.metadata)
    md.pop("ma_ho_so_dau_vao", None)  # đã có cột riêng (PII) — không chép hai nơi
    md.pop("tham_so_quyet_dinh", None)  # đã có cột riêng
    md["mau_da_dung"] = used_templates
    md["ngay_ky_chon_mau"] = signing_date.isoformat()
    md["nam_hoc"] = academic_year
    md["phien_ban_ma"] = dict(CODE_VERSIONS)
    md["giao_dich_doc"] = {
        "transaction_isolation": snapshot.transaction.transaction_isolation,
        "transaction_read_only": snapshot.transaction.transaction_read_only,
    }
    # Lượt G — vết đọc được về sau (không dữ liệu cá nhân): số hồ sơ theo trạng thái lúc chụp;
    # lần xác nhận cảnh báo (owner 05-11: ai, lúc nào, bao nhiêu hồ sơ ở mỗi trạng thái).
    md["trang_thai_ho_so"] = gate_result.count_by_status()
    md["xac_nhan_canh_bao_trang_thai"] = (
        None
        if confirmation_done is None
        else {
            "nguoi_xac_nhan_id": creator_id,
            "luc": created_at.isoformat(),
            "so_ho_so_theo_trang_thai": dict(confirmation_done),
            "dong_theo_trang_thai": {s: list(d) for s, d in gate_result.warnings.items()},
        }
    )
    md["nguon_diem_kv"] = "muc_theo_nam_hoc_cua_ho_so"  # F231 (owner 05-11)
    # Câu 22 (owner 06-11): điểm KV in theo luật cộng điểm của đường xét — số hồ sơ theo luật
    # (``cong`` / ``tat`` / ``khong_co_luat``) để đọc lại được vì sao một dòng in 0.
    md["luat_diem_kv"] = "theo_luat_cong_diem_cua_duong_xet"
    md["so_ho_so_theo_luat_kv"] = gate_result.count_by_area_rule()
    # Lượt H2: công tắc đối tượng của đường xét (cách suy + trần giữ luật v1).
    md["luat_diem_ut"] = "cong_tac_doi_tuong_cua_duong_xet_cach_tinh_v1"
    md["so_ho_so_theo_luat_ut"] = gate_result.count_by_priority_rule()
    # Lượt I (F230): hồ sơ đang ở bộ khác — BÁO (id bộ + số đếm), không chặn (SPEC §13 câu 4).
    md["ho_so_o_bo_khac"] = {
        str(k): v
        for k, v in (
            await CouncilDecisionRepository(db).profiles_in_other_sets(list(snapshot.pids))
        ).items()
    }
    if allowed_decision_chain is not None:
        md["cho_quyet_dinh_goc_id"] = allowed_decision_chain
    doc_set = CouncilDocumentSet(
        nguoi_tao_id=creator_id,
        tao_luc=created_at,
        moc_chup=snapshot.transaction.snapshot_at,
        unit_id=set_unit(snapshot.unit_ids),
        trinh_do=rendered.metadata["trinh_do"],
        so_ho_so=len(print_rows),
        so_tep=len(rendered.files),
        kich_thuoc_tong=total,
        tham_so_quyet_dinh=rendered.metadata["tham_so_quyet_dinh"],
        ma_ho_so_dau_vao=[r.ma_ho_so for r in print_rows],
        snapshot_dto=[r.model_dump() for r in print_rows],
        thong_tin_dung=md,
        cho_quyet_dinh_goc_id=allowed_decision_chain,
    )
    file = [
        CouncilDocumentSetFile(
            thu_tu=i,
            path=f.path,
            sha256=f.sha256,
            kich_thuoc=len(f.content),
            noi_dung=f.content,
        )
        for i, f in enumerate(rendered.files, 1)
    ]
    row = [
        _set_row_from_check(k, pid, academic_year)
        for k, pid in zip(snapshot.check_data, snapshot.pids)
    ]
    event = {
        "so_ho_so": len(print_rows),
        "trang_thai_ho_so": md["trang_thai_ho_so"],
        "xac_nhan_canh_bao": (
            None if confirmation_done is None else dict(confirmation_done)
        ),
        "ho_so_o_bo_khac": md["ho_so_o_bo_khac"],
    }
    await _write_set_and_rows(
        db,
        doc_set,
        file,
        row,
        event_kind="tao_bo" if allowed_decision_chain is None else "tao_bo_dieu_chinh",
        figures=event,
        actor_id=creator_id,
        decision_id=allowed_decision_chain,
    )
    return doc_set, None


def _set_row_from_check(
    k: "set_gate.CheckData", pid: int, academic_year: int
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


async def _write_set_and_rows(
    db: AsyncSession,
    doc_set: CouncilDocumentSet,
    file: Sequence[CouncilDocumentSetFile],
    row: Sequence[CouncilDocumentSetRow],
    *,
    event_kind: str,
    figures: Dict[str, object],
    actor_id: Optional[int],
    decision_id: Optional[int] = None,
) -> None:
    """Ghi bộ + tệp + dòng bộ + MỘT dòng sự kiện trong CÙNG SAVEPOINT (hỏng ⇒ không còn hàng nào)."""
    if [d.stt for d in row] != list(range(1, doc_set.so_ho_so + 1)):
        raise ServiceError("Dòng bộ không khớp số hồ sơ — không lưu.")
    try:
        async with db.begin_nested():
            await CouncilDocumentRepository(db).add_set(doc_set, file)
            for d in row:
                d.set_id = doc_set.id
            await CouncilDecisionRepository(db).add_objects(
                *row,
                CouncilDocumentEvent(
                    loai=event_kind,
                    set_id=doc_set.id,
                    decision_id=decision_id,
                    nguoi_id=actor_id,
                    so_lieu=figures,
                ),
            )
    except DBAPIError:
        # Tham số của câu lệnh hỏng mang PII (DTO, mã) + bytes tệp ⇒ không giữ lỗi gốc.
        raise ServiceError("Lỗi CSDL khi lưu bộ văn bản — không lưu gì.") from None


@dataclass(frozen=True)
class StoredFile:
    path: str
    sha256: str
    content: bytes


async def read_stored_file(db: AsyncSession, set_id: int, order_no: int) -> StoredFile:
    """Tệp thứ ``thu_tu`` của bộ ``set_id`` = bytes ĐÃ LƯU — KHÔNG dựng lại. Kiểm quyền /
    IDOR ở ``deps.py`` (bộ đã qua ``get_council_document_set_for_user``). Không có ⇒
    ``ResourceNotFoundError``; bytes lệch sha đã lưu ⇒ ``ServiceError`` (không trả)."""
    t = await CouncilDocumentRepository(db).set_file(set_id, order_no)
    if t is None:
        raise ResourceNotFoundError("Không có tệp này trong bộ văn bản.")
    b = bytes(t.noi_dung)
    if hashlib.sha256(b).hexdigest() != t.sha256:
        raise ServiceError("Tệp đã lưu lệch sha256 — không trả.")
    return StoredFile(path=t.path, sha256=t.sha256, content=b)


async def list_sets(
    db: AsyncSession,
    *,
    all_units: bool,
    only_unit_id: Optional[int],
    limit: int,
    offset: int,
) -> List[CouncilDocumentSet]:
    """Danh sách bộ (không nạp cột dữ liệu cá nhân). ``all_units`` = phạm vi admin; không thì
    CHỈ bộ của đơn vị ``only_unit_id`` (bộ ``unit_id`` NULL không bao giờ vào). Phạm vi do
    ``deps.py`` quyết; tổ hợp "không tất cả mà không có đơn vị" ⇒ ``ServiceError``
    (fail-closed — không bao giờ hiểu "không có đơn vị" thành "mọi đơn vị")."""
    if not all_units and only_unit_id is None:
        raise ServiceError("Phạm vi xem bộ văn bản không xác định — không liệt kê.")
    return await CouncilDocumentRepository(db).list_sets(
        only_unit_id=only_unit_id, all_units=all_units, limit=limit, offset=offset
    )


async def set_file(db: AsyncSession, set_id: int) -> List[CouncilDocumentSetFile]:
    """Metadata các tệp của một bộ (không bytes), theo thứ tự bộ dựng trả."""
    return await CouncilDocumentRepository(db).list_set_files(set_id)


# ═══════════════ danh sách / chi tiết bộ mở rộng + tải cả bộ (vòng giao diện — đặc tả 3.4–3.6) ═══════════════
def _extended_set_out(r: Dict[str, Any], *, show_submission: bool) -> Dict[str, Any]:
    """MỘT hàng của ``SQL_SET_EXTENDED`` → các trường của ``CouncilSetOut``. ``quyet_dinh`` = văn bản chưa huỷ ghi nhận
    mới nhất (``SQL_SET_EXTENDED`` — nguồn duy nhất) — giữ các khoá cũ (loai, trang_thai, so_quyet_dinh, ngay_ky, so_ho_so)
    + ``id`` + ``goc``. ``luot_gui_cho`` CHỈ khi ``show_submission`` = cờ ``ghi_nhan_qd`` của người gọi (router tính bằng ĐÚNG hàm
    tính cờ của ``GET /quyen`` — §5.8, Codex lần 18: một nguồn cho câu hỏi quyền, không suy từ phạm vi); người khác None."""
    decision_service = None
    if r["qd_id"] is not None:
        decision_service = {
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
        "quyet_dinh": decision_service,
        "luot_gui_cho": (
            {"ma": r["luot_ma"], "tao_luc": r["luot_tao_luc"]}
            if show_submission and r["luot_ma"] is not None
            else None
        ),
    }


async def list_sets_extended(
    db: AsyncSession,
    *,
    all_units: bool,
    only_unit_id: Optional[int],
    show_submission: bool,
    academic_year: Optional[int] = None,
    creator_id: Optional[int] = None,
    decision_number: Optional[str] = None,
    state: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """``GET /sets`` (đặc tả 3.4) — MỘT câu (``SQL_SET_EXTENDED``). Phạm vi do ``deps.py`` quyết; "không tất cả mà không có
    đơn vị" ⇒ ``ServiceError`` (fail-closed). ``luot_gui_cho`` chỉ khi ``show_submission`` (cờ ``ghi_nhan_qd`` — router)."""
    if not all_units and only_unit_id is None:
        raise ServiceError("Phạm vi xem bộ văn bản không xác định — không liệt kê.")
    rows = await CouncilDocumentRepository(db).list_sets_extended(
        all_units=all_units,
        only_unit_id=only_unit_id,
        academic_year=academic_year,
        creator_id=creator_id,
        decision_number=decision_number,
        state=state,
        limit=limit,
        offset=offset,
    )
    return [_extended_set_out(r, show_submission=show_submission) for r in rows]


async def extended_set_detail(
    db: AsyncSession, set_id: int, *, show_submission: bool
) -> Dict[str, Any]:
    """``GET /sets/{id}`` (đặc tả 3.5) — CÙNG câu với danh sách (một nguồn cho tình trạng / Quyết định). Bộ đã qua kiểm
    phạm vi ở ``deps.py`` ⇒ đọc theo id không lọc đơn vị."""
    rows = await CouncilDocumentRepository(db).list_sets_extended(
        all_units=True, only_unit_id=None, set_id=set_id, limit=1, offset=0
    )
    if not rows:
        raise ResourceNotFoundError("Không có bộ văn bản này.")
    return _extended_set_out(rows[0], show_submission=show_submission)


async def set_creators(
    db: AsyncSession, *, all_units: bool, only_unit_id: Optional[int]
) -> List[Dict[str, Any]]:
    """Người tạo PHÂN BIỆT của các bộ trong phạm vi người gọi (bộ lọc "Người tạo")."""
    if not all_units and only_unit_id is None:
        raise ServiceError("Phạm vi xem bộ văn bản không xác định — không liệt kê.")
    return await CouncilDocumentRepository(db).set_creators(
        all_units=all_units, only_unit_id=only_unit_id
    )


async def user_names(db: AsyncSession, ids: Sequence[int]) -> Dict[int, str]:
    """{id: tên hiển thị} — nhật ký tải / vết xoá hiện tên thay "Tài khoản #n"."""
    return await CouncilDocumentRepository(db).user_names(ids)


async def read_whole_set(db: AsyncSession, set_id: int) -> List[Tuple[int, StoredFile]]:
    """``GET /sets/{id}/tai-ca-bo`` (đặc tả 3.6) bước 1–2: đọc MỌI tệp đã lưu (bytes NGUYÊN, không dựng lại), tính lại
    sha256 TỪNG tệp so cột ``sha256`` — lệch ⇒ ``ServiceError`` "tệp đã lưu hỏng", không trả gì; kiểm lại trần tổng
    ``COUNCIL_SET_MAX_TOTAL_BYTES``. Trả ``[(thu_tu, tệp)]`` theo thứ tự. Kiểm quyền / IDOR ở ``deps.py``."""
    files = await CouncilDocumentRepository(db).set_files_with_content(set_id)
    if not files:
        raise ResourceNotFoundError("Bộ văn bản không có tệp nào.")
    out: List[Tuple[int, StoredFile]] = []
    total = 0
    for t in files:
        b = bytes(t.noi_dung)
        if hashlib.sha256(b).hexdigest() != t.sha256:
            raise ServiceError(
                "Tệp đã lưu hỏng (thứ tự %d lệch sha256) — không trả bộ." % t.thu_tu
            )
        total += len(b)
        out.append((t.thu_tu, StoredFile(path=t.path, sha256=t.sha256, content=b)))
    if total > settings.COUNCIL_SET_MAX_TOTAL_BYTES:
        raise ServiceError(
            "Bộ văn bản %d byte, vượt giới hạn kỹ thuật %d byte — không trả."
            % (total, settings.COUNCIL_SET_MAX_TOTAL_BYTES)
        )
    return out


def zip_whole_set(file: Sequence[StoredFile], timestamp: datetime) -> bytes:
    """Nén ĐÚNG bytes đã lưu thành một tệp zip — tên trong zip = ``path`` đã lưu (không đổi, không dựng lại); giờ của
    mọi mục = ``moc`` (giờ Việt Nam của lúc tạo bộ) ⇒ cùng bộ cho cùng zip. Chạy NGOÀI event loop (CPU)."""
    import io
    import zipfile

    from app.constants.admission_circular import VN_TZ

    time_tuple = timestamp.astimezone(VN_TZ).timetuple()[:6]
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for t in file:
            info = zipfile.ZipInfo(t.path, date_time=max(time_tuple, (1980, 1, 1, 0, 0, 0)))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, t.content)
    return b.getvalue()


# ═══════════════════════════════ xoá bộ (Admin) — vết độc lập, cùng giao dịch ═════════════
def check_reason(reason: object, operation: str) -> str:
    """Lý do / ghi chú BẮT BUỘC của một thao tác (MỘT nguồn — xoá bộ J1 dòng 29; lượt I: huỷ ghi
    nhận, cho xét lại, tái dựng bản ký, ghi chú mẫu): chuỗi; bỏ khoảng trắng hai đầu; không rỗng;
    tối đa ``LY_DO_XOA_TOI_DA`` ký tự (trần KỸ THUẬT); không ký tự nhóm C ngoài xuống dòng / tab.
    Thông báo không nêu nội dung."""
    if not isinstance(reason, str):
        raise DataValidationError("Lý do %s phải là chữ." % operation)
    s = reason.strip()
    if not s:
        raise DataValidationError("Phải nhập lý do %s." % operation)
    if len(s) > MAX_DELETE_REASON_LENGTH:
        raise DataValidationError(
            "Lý do %s dài quá giới hạn kỹ thuật %d ký tự." % (operation, MAX_DELETE_REASON_LENGTH)
        )
    if any(unicodedata.category(c)[0] == "C" and c not in "\n\r\t" for c in s):
        raise DataValidationError(
            "Lý do %s có ký tự điều khiển / vô hình — gõ lại." % operation
        )
    return s


def check_delete_reason(reason: object) -> str:
    """Lý do xoá bộ BẮT BUỘC (J1 dòng 29) — :func:`kiem_ly_do`."""
    return check_reason(reason, "xoá bộ văn bản")


async def delete_document_set(
    db: AsyncSession,
    doc_set: CouncilDocumentSet,
    *,
    reason: object,
    deleter_id: int,
) -> Tuple[CouncilDocumentSetDeletion, None]:
    """Ghi vết xoá rồi xoá bộ ``bo`` (đã qua kiểm quyền admin ở ``deps.py``) — CÙNG một
    SAVEPOINT: lỗi ở bất kỳ câu nào ⇒ không xoá gì, không còn vết. Trả ``(vết, None)``;
    router commit. Tệp của bộ đi theo ``ON DELETE CASCADE``; nhật ký tải + vết xoá KHÔNG có
    khoá ngoại tới bộ ⇒ còn nguyên."""
    reason = check_delete_reason(reason)
    if isinstance(deleter_id, bool) or not isinstance(deleter_id, int):
        raise ServiceError("Không xác định được người xoá — không xoá.")
    repo = CouncilDocumentRepository(db)
    decision_repo = CouncilDecisionRepository(db)
    # Vòng giao diện (đặc tả bản 2 mục 3.7.6, F269 / F272): câu ĐẦU khoá dòng bộ ``FOR UPDATE`` — mở lượt gửi (INSERT
    # có khoá ngoại ⇒ ``KEY SHARE`` trên bộ) không chen được sau bước kiểm lượt bên dưới.
    if await decision_repo.lock_set(doc_set.id) is None:
        raise ResourceNotFoundError("Không có bộ văn bản này.")
    # Lượt I (F230): bộ của văn bản ĐÃ KÝ còn / hết hiệu lực là hồ sơ lưu trữ ⇒ KHÔNG xoá (J1 dòng 8;
    # số năm lưu chưa có — J5 M1). Báo 409 trước; CSDL chặn cuối (K4 / K5b — đặc tả mục 4.1).
    live = await decision_repo.live_documents_of_set(doc_set.id)
    if live:
        raise ConflictError(
            "Bộ văn bản là bản in của Quyết định đã ký (văn bản #%s) — lưu theo hạn lưu trữ, "
            "không xoá. Chỉ xoá được khi mọi ghi nhận của bộ đã huỷ ghi nhận."
            % ", #".join(str(d.id) for d in live),
            public_payload={"quyet_dinh_id": [d.id for d in live]},
        )
    # Lượt gửi chưa rõ kết quả ⇒ 409 (đọc KHÔNG khoá, không chờ dòng lượt nào — F272). CSDL chặn cuối: khoá ngoại
    # ON DELETE SET NULL + CHECK ``ck_council_decision_submission_cho_co_bo``. Lượt đã kết thúc giữ lại (set_id NULL).
    from app.services.council_decision_submission_service import has_pending_submission

    location = await has_pending_submission(db, doc_set.id)
    if location is not None:
        raise ConflictError(
            "Bộ đang có lượt gửi ghi nhận chưa rõ kết quả — phân xử (Kiểm tra trên máy chủ) trước khi xoá.",
            public_payload={"ma_loi": "bo_co_luot_gui_chua_ro", "ma": str(location.ma)},
        )
    file = await repo.list_set_files(doc_set.id)  # metadata, KHÔNG nạp bytes
    trace = CouncilDocumentSetDeletion(
        set_id=doc_set.id,
        so_ho_so=doc_set.so_ho_so,
        so_tep=len(file),
        danh_sach_tep=[
            {
                "thu_tu": t.thu_tu,
                "path": t.path,
                "sha256": t.sha256,
                "kich_thuoc": t.kich_thuoc,
            }
            for t in file
        ],
        nguoi_xoa_id=deleter_id,
        ly_do=reason,
    )
    set_id = doc_set.id
    try:
        async with db.begin_nested():
            await repo.add_deletion_trace(trace)
            # Dòng của các ghi nhận ĐÃ HUỶ trỏ bộ này: dọn liên kết TRƯỚC khi xoá (thứ tự hai hành
            # động tham chiếu của PostgreSQL có thể để ``set_row_id`` trỏ dòng bộ đã xoá — đo lượt I).
            await db.execute(
                text(
                    "UPDATE council_decision_row SET set_row_id = NULL, set_id = NULL "
                    "WHERE set_id = :s AND trang_thai_cha = 'huy_ghi_nhan'"
                ),
                {"s": set_id},
            )
            await decision_repo.add_objects(
                CouncilDocumentEvent(
                    loai="xoa_bo",
                    set_id=set_id,
                    nguoi_id=deleter_id,
                    so_lieu={"so_ho_so": doc_set.so_ho_so, "so_tep": len(file)},
                )
            )
            if await repo.delete_set(set_id) != 1:
                raise ServiceError("Bộ văn bản không còn để xoá — không xoá gì.")
    except DBAPIError as e:
        sqlstate, constraint = db_error_codes(e)
        if sqlstate == "23514" and constraint in (
            "ck_council_decision_k4",
            "ck_council_decision_row_k5b",
        ):
            # Tầng chủ sở hữu (CSDL) chặn — một phiên khác vừa ghi nhận bộ này.
            raise ConflictError(
                "Bộ văn bản là bản in của Quyết định đã ký — không xoá."
            ) from None
        # Thông báo của trình điều khiển mang tham số câu lệnh (lý do, path) ⇒ không giữ.
        raise ServiceError("Lỗi CSDL khi xoá bộ văn bản — không xoá gì.") from None
    return trace, None


async def list_deletion_traces(
    db: AsyncSession, *, limit: int, offset: int
) -> List[CouncilDocumentSetDeletion]:
    return await CouncilDocumentRepository(db).list_deletion_traces(
        limit=limit, offset=offset
    )


# ═══════════════════════════════ danh sách mã đầu vào (Admin) ═════════════════════════════
async def input_profile_codes(db: AsyncSession, set_id: int) -> List[str]:
    """Mã hồ sơ đầu vào ĐÚNG THỨ TỰ của bộ ``set_id`` (DỮ LIỆU CÁ NHÂN — J1 dòng 30: chỉ
    Admin; quyền ở ``deps.py``). Không có ⇒ ``ResourceNotFoundError``."""
    codes = await CouncilDocumentRepository(db).input_profile_codes(set_id)
    if codes is None:
        raise ResourceNotFoundError("Không có bộ văn bản này.")
    if not isinstance(codes, list) or not all(isinstance(m, str) for m in codes):
        raise ServiceError("Danh sách mã đầu vào đã lưu sai dạng — không trả.")
    return codes


# ═══════════════════════════════ nhật ký tải ═══════════════════════════════════════════
async def log_download(
    db: AsyncSession,
    *,
    set_id: int,
    order_no: int,
    file: StoredFile,
    downloader_id: int,
) -> Tuple[CouncilDocumentDownloadLog, None]:
    """MỘT dòng nhật ký cho lần máy chủ CẤP tệp ``thu_tu`` của bộ ``set_id`` (flush). Router
    COMMIT dòng này TRƯỚC khi trả bytes; lỗi ghi ⇒ ``ServiceError`` ⇒ không trả tệp. Ghi nhận
    việc CẤP tệp, không tuyên bố người dùng đã nhận xong."""
    if isinstance(downloader_id, bool) or not isinstance(downloader_id, int):
        raise ServiceError("Không xác định được người tải — không trả tệp.")
    row = CouncilDocumentDownloadLog(
        set_id=set_id,
        thu_tu=order_no,
        path=file.path,
        sha256=file.sha256,
        nguoi_tai_id=downloader_id,
    )
    try:
        await CouncilDocumentRepository(db).add_download_log(row)
    except DBAPIError:
        raise ServiceError("Không ghi được nhật ký tải tệp — không trả tệp.") from None
    return row, None


async def list_download_log(
    db: AsyncSession, *, set_id: Optional[int], limit: int, offset: int
) -> List[CouncilDocumentDownloadLog]:
    """Nhật ký tải (mới trước) — lọc theo id bộ nếu có; bộ ĐÃ XOÁ vẫn lọc được."""
    return await CouncilDocumentRepository(db).list_download_log(
        set_id=set_id, limit=limit, offset=offset
    )


# ═══════════════════ Lượt I (F230) — bộ cho điều chỉnh · tái dựng bản ký · so với hiện tại ═════════
async def create_adjustment_set(
    db: AsyncSession,
    engine: AsyncEngine,
    root_id: int,
    *,
    profile_codes: Sequence[str],
    academic_year: Optional[int],
    params: Optional[render_service.DecisionParams],
    creator_id: Optional[int],
    confirm_status: Optional[Dict[str, int]] = None,
    can_confirm: bool = False,
) -> Tuple[CouncilDocumentSet, None]:
    """Bộ DỮ LIỆU cho văn bản điều chỉnh của chuỗi ``goc_id`` (C6: văn thư soạn văn bản; phần mềm cần dữ
    liệu của em được thêm / sửa). CÙNG đường dựng bộ (đọc chỉ đọc + đủ cổng), chỉ nới đúng MỘT phép: hồ
    sơ có dòng hiệu lực trong CHÍNH chuỗi ấy (ca "sửa thông tin em C" — BS §1.3)."""
    root = await CouncilDecisionRepository(db).decision_by_id(root_id)
    if root is None:
        raise ResourceNotFoundError("Không có Quyết định này.")
    if root.loai != "trung_tuyen" or root.trang_thai != "hieu_luc":
        raise ConflictError("Chỉ dựng bộ điều chỉnh cho Quyết định trúng tuyển đang hiệu lực.")
    return await _build_and_write_set(
        db,
        engine,
        profile_codes=profile_codes,
        academic_year=academic_year,
        params=params,
        creator_id=creator_id,
        created_at=None,
        confirm_status=confirm_status,
        can_confirm=can_confirm,
        allowed_decision_chain=root.id,
    )


async def _stored_snapshot(db: AsyncSession, set_id: int) -> List[dict]:
    """Ảnh chụp DTO đã lưu của bộ (cột deferred — đọc tường minh)."""
    from sqlalchemy import select

    rows = (
        await db.execute(
            select(CouncilDocumentSet.snapshot_dto).where(CouncilDocumentSet.id == set_id)
        )
    ).scalar_one()
    if not isinstance(rows, list):
        raise ServiceError("Ảnh chụp đã lưu sai dạng — không dùng.")
    return rows


async def _templates_by_id(db: AsyncSession, used_templates: Dict[str, Dict[str, object]]):
    """Ba mẫu ĐÚNG như bộ in ban đầu đã dùng (id + sha; kiểm lại gói)."""
    from sqlalchemy import select
    from sqlalchemy.orm import undefer

    from app.models.council_document import CouncilDocumentTemplate

    out = {}
    for kind in render_service.TEMPLATE_KINDS:
        m = (used_templates or {}).get(kind) or {}
        template = (
            await db.execute(
                select(CouncilDocumentTemplate)
                .options(undefer(CouncilDocumentTemplate.noi_dung))
                .where(CouncilDocumentTemplate.id == m.get("id"))
            )
        ).scalar_one_or_none()
        if (
            template is None
            or template.sha256 != m.get("sha256")
            or hashlib.sha256(bytes(template.noi_dung)).hexdigest() != template.sha256
        ):
            raise ServiceError("Không còn đúng mẫu bộ in ban đầu đã dùng — không tái dựng.")
        out[kind] = bytes(template.noi_dung)
        check_template_package(out[kind], KIND_NAMES[kind])
    return render_service.CouncilTemplates(**out)


def _differing_fields(a: dict, b: dict) -> List[str]:
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


async def create_signed_copy_rebuild_set(
    db: AsyncSession,
    engine: AsyncEngine,
    s0: CouncilDocumentSet,
    *,
    decision_number: object,
    signing_date: object,
    manual_edit_rows: Sequence[int],
    reason: object,
    confirm_other_rows: Optional[List[Dict[str, object]]],
    creator_id: Optional[int],
    created_at: Optional[datetime] = None,
) -> Tuple[CouncilDocumentSet, None]:
    """Đường TÁI DỰNG BẢN KÝ (F245 — owner C2 / C3; đặc tả mục 3.1) — RIÊNG, khác dựng bộ xét mới:

    * dòng KHÔNG sửa tay: chép NGUYÊN ảnh chụp + dòng bộ của bộ in ban đầu ``s0`` (ảnh chụp thắng dữ liệu
      sống; ``s0`` đã qua đủ cổng lúc in) — KHÔNG đọc sống, KHÔNG cổng;
    * dòng sửa tay: đọc SỐNG theo id hồ sơ của dòng bộ ``s0`` bằng CÙNG hàm đọc, qua cổng DỮ LIỆU
      (``evaluate_rebuild``) — KHÔNG cổng trạng thái F228 (bản ký thắng, trạng thái chỉ liệt kê lúc ghi
      nhận — C3);
    * MỌI dòng qua cổng tình trạng Quyết định (đã có QĐ hiệu lực / chờ quyết / dấu AppSheet ⇒ chặn);
    * Admin xác nhận ĐÚNG danh sách {stt, tên trường khác} (C2 "Admin đối chiếu từng dòng khác");
    * mẫu = ĐÚNG ba mẫu ``s0`` đã dùng; tham số = của ``s0`` + số / ngày trên giấy.

    Lý do tái dựng (D.1 — Codex lần 14): CHỈ nằm ở ``thong_tin_dung.dung_lai_ban_ky.ly_do`` của bộ R (bộ tái
    dựng) — nên MẤT THEO R nếu R bị xoá (xoá được khi R không có văn bản còn / hết hiệu lực — K4). Sự kiện độc lập
    ``dung_lai_ban_ky`` (``council_document_event``) chỉ giữ DẤU THAO TÁC: bộ nguồn, dòng sửa tay, dòng khác,
    người, lúc — KHÔNG giữ lý do (đặc tả 3.1 bước 12: sự kiện không mang chữ tự do).
    """
    from app.services import council_decision_service as decision_service
    from app.services.council_candidate_service import read_profiles_by_id
    from app.services.council_decision_status_service import decision_state

    number = decision_service.check_decision_number(decision_number)
    date_value = decision_service.check_date(signing_date)
    # Đặc tả 3.1: thân có ``ly_do``; bước 12 "lý do không ghi vào sự kiện" ⇒ giữ ở thông tin dựng của bộ R
    # (mất theo R nếu R bị xoá — xem docstring).
    checked_reason = check_reason(reason, "tái dựng bản ký")
    created_at = created_at or datetime.now(timezone.utc)
    if CODE_VERSIONS is None:
        raise ServiceError("Không đọc được mã nguồn của bộ dựng để ghi phiên bản — không dựng.")
    if s0.ban_ky_so_quyet_dinh is not None or s0.cho_quyet_dinh_goc_id is not None:
        raise DataValidationError(
            "Chỉ tái dựng từ bộ in ban đầu (không từ bộ tái dựng / bộ dữ liệu điều chỉnh)."
        )
    repo = CouncilDecisionRepository(db)
    set0_rows = await repo.set_rows(s0.id)
    if len(set0_rows) != s0.so_ho_so or [d.stt for d in set0_rows] != list(
        range(1, s0.so_ho_so + 1)
    ):
        raise DataValidationError("Bộ in ban đầu dựng trước khi có dòng bộ — không tái dựng.")
    live = await repo.live_documents_of_set(s0.id)
    if live:
        raise ConflictError(
            "Bộ in ban đầu đã được ghi nhận (văn bản #%d)." % live[0].id,
            public_payload={"quyet_dinh_id": live[0].id},
        )
    edit = list(manual_edit_rows or [])
    if (
        not edit
        or any(isinstance(x, bool) or not isinstance(x, int) for x in edit)
        or len(set(edit)) != len(edit)
        or not all(1 <= x <= s0.so_ho_so for x in edit)
    ):
        raise DataValidationError(
            "Danh sách dòng sửa tay phải là số dòng của bộ (1…%d), không trùng, không rỗng."
            % s0.so_ho_so
        )
    edit = sorted(edit)
    if date_value < vn_calendar_date(s0.tao_luc):
        raise DataValidationError(
            "Ngày ký trước ngày in bộ ban đầu (giờ Việt Nam) — giấy không thể ký trước khi in."
        )
    original_params = dict(s0.tham_so_quyet_dinh or {})
    if original_params.get("so_quyet_dinh") not in (None, number) or original_params.get("ngay_quyet_dinh") not in (
        None,
        date_value.isoformat(),
    ):
        raise DataValidationError("Số / ngày trên giấy khác số / ngày bộ in ban đầu đã in.")
    # U2 (ultra GĐ1 — owner 21-11 Q2): tham số = của ``s0`` + số / ngày trên giấy, kiểm qua ĐÚNG phần đổi lỗi của
    # ``recheck_decision_params`` (không ``DecisionParams(**…)`` trực tiếp — lỗi pydantic thô thành 500) ⇒ 400 nêu trường sai,
    # cùng luật với ghi nhận (``council_decision_service._compare_params``). Kiểm TRƯỚC khi đọc / dựng / ghi.
    params = render_service.check_decision_param_values(
        {**original_params, "so_quyet_dinh": number, "ngay_quyet_dinh": date_value}
    )
    # U1 (ultra GĐ1 — owner 21-11 Q1: GIỮ G10 + báo sớm): bộ R dùng ĐÚNG ba mẫu ``s0`` đã dùng, mà ghi nhận R đòi mẫu đúng theo
    # NGÀY KÝ (G10) ⇒ kiểm NGAY bằng CÙNG vị từ của ghi nhận, trước khi đọc dữ liệu cá nhân / dựng / lưu: lệch ⇒ 400, KHÔNG lưu
    # bộ R (bộ chết mang dữ liệu cá nhân). Tờ in mẫu cũ phải in lại bằng mẫu mới và ký lại.
    used_templates = (s0.thong_tin_dung or {}).get("mau_da_dung") or {}
    template_mismatch = await decision_service.templates_off_signing_date(db, used_templates, date_value)
    if template_mismatch:
        raise DataValidationError(
            "Mẫu đúng theo ngày ký khác mẫu bộ in ban đầu đã dùng (%s) — tờ in bằng mẫu cũ không ghi nhận được: in lại "
            "bằng mẫu đúng theo ngày ký rồi ký lại; không tái dựng." % ", ".join(template_mismatch),
            public_payload={"mau_lech": template_mismatch},
        )
    missing = [d.stt for d in set0_rows if d.profile_id is None]
    if missing:
        raise DataValidationError(
            "Dòng %s: hồ sơ của dòng bộ không còn — không tái dựng." % _rows_text(missing)
        )
    year = (s0.thong_tin_dung or {}).get("nam_hoc")
    by_seq = {d.stt: d for d in set0_rows}
    snapshot = await read_profiles_by_id(
        engine, [by_seq[s].profile_id for s in edit], academic_year=year
    )
    gate_result = set_gate.evaluate_rebuild(snapshot.check_data)
    if gate_result.blocks:
        raise DataValidationError(
            "Dòng sửa tay không dựng lại được từ dữ liệu hiện tại của hồ sơ — xem danh sách.",
            public_payload={
                "kiem_tra_dung_lai": [
                    {
                        "ma": code,
                        "mo_ta": set_gate.BLOCK_REASONS[code],
                        "trang_thai": status_,
                        "dong": [edit[i - 1] for i in row],
                    }
                    for code, status_, row in gate_result.blocks
                ]
            },
        )
    states = await decision_state(db, [d.profile_id for d in set0_rows])
    block_by_decision = decision_service._block_by_state(set0_rows, states)
    if block_by_decision:
        raise ConflictError(
            "%d hồ sơ đã có Quyết định hiệu lực / đang chờ Admin quyết / mang dấu trúng tuyển "
            "theo Quyết định cũ — không tái dựng." % len(block_by_decision),
            public_payload={"dong_bi_chan": block_by_decision},
        )
    dto0 = await _stored_snapshot(db, s0.id)
    if len(dto0) != s0.so_ho_so:
        raise ServiceError("Ảnh chụp đã lưu thiếu dòng — không tái dựng.")
    live_by_seq = {}
    for i, s in enumerate(edit):
        r = snapshot.rows[i]
        live_by_seq[s] = r.model_copy(
            update={
                "diem_kv": gate_result.area_scores[i],
                "diem_ut": set_gate.printed_priority_score(gate_result.priority_rules[i], r.diem_ut),
            }
        )
        if live_by_seq[s].diem_kv is None or live_by_seq[s].diem_ut is None:
            raise ServiceError("Thiếu điểm ưu tiên in sau cổng — không tái dựng.")
    print_rows = [
        live_by_seq[d.stt]
        if d.stt in live_by_seq
        else render_service.CandidateRowV1(**dto0[d.stt - 1])
        for d in set0_rows
    ]
    other = []
    for s in edit:
        field = _differing_fields(live_by_seq[s].model_dump(), dto0[s - 1])
        if not field:
            raise DataValidationError(
                "Dòng %d khai sửa tay nhưng hồ sơ chưa được sửa (không khác bản in)." % s
            )
        other.append({"stt": s, "truong": field})
    if confirm_other_rows != other:
        raise ConflictError(
            "Admin đối chiếu từng dòng khác bản in với bản ký rồi gửi lại đúng danh sách.",
            public_payload={"dong_khac": other},
        )
    template = await _templates_by_id(db, used_templates)
    if not await CouncilDocumentRepository(db).try_build_lock():
        raise ConflictError("Đang dựng một bộ văn bản khác — chờ bộ ấy xong rồi thử lại.")
    rendered = await asyncio.to_thread(render_service.render_council_documents, print_rows, template, params)
    total = sum(len(f.content) for f in rendered.files)
    if total > settings.COUNCIL_SET_MAX_TOTAL_BYTES:
        raise DataValidationError("Bộ văn bản vượt giới hạn kỹ thuật — không lưu.")
    for f in rendered.files:
        if hashlib.sha256(f.content).hexdigest() != f.sha256:
            raise ServiceError("sha256 của tệp sinh lệch nội dung — không lưu.")
    md = dict(rendered.metadata)
    md.pop("ma_ho_so_dau_vao", None)
    md.pop("tham_so_quyet_dinh", None)
    md["mau_da_dung"] = used_templates
    md["ngay_ky_chon_mau"] = (s0.thong_tin_dung or {}).get("ngay_ky_chon_mau")
    md["nam_hoc"] = year
    md["phien_ban_ma"] = dict(CODE_VERSIONS)
    md["giao_dich_doc"] = {
        "transaction_isolation": snapshot.transaction.transaction_isolation,
        "transaction_read_only": snapshot.transaction.transaction_read_only,
    }
    md["dung_lai_ban_ky"] = {
        "tu_set_id": s0.id,
        "dong_sua_tay": edit,
        "dong_khac": other,
        "nguoi_xac_nhan_id": creator_id,
        "luc": created_at.isoformat(),
        "ly_do": checked_reason,
    }
    doc_set = CouncilDocumentSet(
        nguoi_tao_id=creator_id,
        tao_luc=created_at,
        moc_chup=snapshot.transaction.snapshot_at,
        unit_id=s0.unit_id,
        trinh_do=rendered.metadata["trinh_do"],
        so_ho_so=len(print_rows),
        so_tep=len(rendered.files),
        kich_thuoc_tong=total,
        tham_so_quyet_dinh=rendered.metadata["tham_so_quyet_dinh"],
        ma_ho_so_dau_vao=[r.ma_ho_so for r in print_rows],
        snapshot_dto=[r.model_dump() for r in print_rows],
        thong_tin_dung=md,
        dung_lai_tu_set_id=s0.id,
        ban_ky_so_quyet_dinh=number,
        ban_ky_ngay=date_value,
    )
    file = [
        CouncilDocumentSetFile(
            thu_tu=i, path=f.path, sha256=f.sha256, kich_thuoc=len(f.content), noi_dung=f.content
        )
        for i, f in enumerate(rendered.files, 1)
    ]
    position_of = {s: i for i, s in enumerate(edit)}
    row = []
    for d in set0_rows:
        if d.stt in position_of:
            r = _set_row_from_check(snapshot.check_data[position_of[d.stt]], d.profile_id, year)
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
        row.append(r)
    await _write_set_and_rows(
        db,
        doc_set,
        file,
        row,
        event_kind="dung_lai_ban_ky",
        figures={"tu_set_id": s0.id, "dong_sua_tay": edit, "dong_khac": other},
        actor_id=creator_id,
    )
    return doc_set, None


def _rows_text(numbers: Sequence[int]) -> str:
    return ", ".join(str(x) for x in list(numbers)[:20]) + (
        " … (+%d)" % (len(numbers) - 20) if len(numbers) > 20 else ""
    )


async def compare_with_current(
    db: AsyncSession, engine: AsyncEngine, doc_set: CouncilDocumentSet
) -> Dict[str, object]:
    """Route chỉ đọc, CHỈ ADMIN (SPEC §11.2 điểm 8; BS §3.2): so ảnh chụp của bộ với dữ liệu HIỆN TẠI
    — tính lại bằng CÙNG hàm của bộ dựng (đọc, cổng dữ liệu, điểm KV / đối tượng in). Trả số dòng + TÊN
    trường đã đổi, không giá trị; dòng không dựng lại được ⇒ mã lý do."""
    from app.services.council_candidate_service import read_profiles_by_id

    repo = CouncilDecisionRepository(db)
    row = await repo.set_rows(doc_set.id)
    if len(row) != doc_set.so_ho_so:
        raise DataValidationError("Bộ dựng trước khi có dòng bộ — không so được.")
    present = [d for d in row if d.profile_id is not None]
    missing = [d.stt for d in row if d.profile_id is None]
    dto = await _stored_snapshot(db, doc_set.id)
    other: List[Dict[str, object]] = []
    unmatched: List[Dict[str, object]] = []
    if present:
        snapshot = await read_profiles_by_id(
            engine,
            [d.profile_id for d in present],
            academic_year=(doc_set.thong_tin_dung or {}).get("nam_hoc"),
        )
        result = set_gate.evaluate_rebuild(snapshot.check_data)
        for i, d in enumerate(present):
            checked_reason = set_gate.row_block_reason(snapshot.check_data[i])
            if checked_reason:
                unmatched.append({"stt": d.stt, "ma": checked_reason})
                continue
            r = snapshot.rows[i].model_copy(
                update={
                    "diem_kv": result.area_scores[i],
                    "diem_ut": set_gate.printed_priority_score(result.priority_rules[i], snapshot.rows[i].diem_ut),
                }
            )
            field = _differing_fields(r.model_dump(), dto[d.stt - 1])
            if field:
                other.append({"stt": d.stt, "truong": field})
    return {
        "set_id": doc_set.id,
        "so_dong": doc_set.so_ho_so,
        "dong_khac": other,
        "khong_dung_lai_duoc": unmatched,
        "mat_ho_so": missing,
    }
