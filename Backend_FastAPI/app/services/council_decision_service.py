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
dần — ``quota_occupancy_service.lock_quota_of_set_rows`` → ``lock_quota_cells``, THỨ TỰ CHUẨN). Phê duyệt cũ,
Phê duyệt hàng loạt (khoá trước cả lô) và công bố (khoá trước mọi nguyện vọng) đi CÙNG thứ tự ⇒ không vòng chờ
(F259); bên bị PostgreSQL chọn huỷ ở trường hợp khác ⇒ 409 "thử lại" (đổi so với BS §4.6 "không khoá dòng
chỉ tiêu" — lý do: ``DAC-TA-F230-2B-BO-SUNG-2026-11-10.md``; lượt K: ``DAC-TA-F230-SUA-CUOI-BO-SUNG-2026-11-10.md``).

Ba thao tác sinh / khôi phục dòng Phần B (ghi nhận, điều chỉnh có dòng thêm, huỷ ghi nhận có dòng bật lại) gọi
``check_lock_and_count_set_rows`` DƯỚI khoá, TRƯỚC khi ghi (Q-J1 — owner 10-11: dòng bộ thiếu khoá đếm ⇒ 409 nêu số
dòng). Ghi nhận trả cảnh báo vượt chỉ tiêu theo ngành / đường xét (N9 — không chặn).

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
    SCAN_KIND,
    CouncilDecision,
    CouncilDecisionHold,
    CouncilDecisionScan,
    CouncilDocumentEvent,
    CouncilDocumentSet,
)
from app.repositories.council_decision_repository import (
    CouncilDecisionRepository,
    db_error_codes,
)
from app.repositories.council_document_repository import CouncilDocumentRepository
from app.services import council_decision_submission_service as submission_service
from app.services import council_document_render_service as render_service
from app.services.council_decision_status_service import decision_state
from app.services.council_document_set_service import check_reason
from app.services.council_set_gate_service import (
    WARNING_STATUSES,
    BLOCKING_STATUSES,
    NON_WARNING_STATUSES,
    decision_state_block_reason,
)
from app.services.quota_occupancy_service import (
    SQLSTATE_DEADLOCK,
    CONFLICT_MESSAGE,
    over_quota_warnings,
    lock_quota_of_set_rows,
    check_lock_and_count_set_rows,
)
from app.utils.datetime_helpers import today_vn
from app.utils.exceptions import (
    ConflictError,
    DataValidationError,
    ResourceNotFoundError,
    ServiceError,
)

KNOWN_STATUSES = BLOCKING_STATUSES | WARNING_STATUSES | NON_WARNING_STATUSES
#: Tham số trên giấy ngoài số / ngày Quyết định (BS §3.2 dòng 3) — trường bộ đã in thì phải gõ lại
#: ĐÚNG; trường bộ để trống thì nhận giá trị Admin gõ theo giấy.
PAPER_PARAM_FIELDS = ("so_bien_ban", "ngay_bien_ban", "dot_so", "dot_thang")
DECISION_FILE = "HoiDong/QuyetDinhTrungTuyen-"
#: Thông điệp cố định khi CSDL (tầng chủ sở hữu) chặn — không mang tham số câu lệnh.
_CONSTRAINT_ERRORS = {
    "uq_council_decision_u1_so": "Số Quyết định này đã dùng trong năm của ngày ký.",
    "uq_council_decision_u2_bo": "Bộ văn bản này đã được ghi nhận là một văn bản đã ký.",
    "uq_council_decision_row_u3_ho_so": (
        "Có hồ sơ đã có tên trong một Quyết định khác đang hiệu lực."
    ),
    "uq_council_decision_u4_huy": "Văn bản này đã có một văn bản huỷ còn hiệu lực.",
    "uq_council_decision_hold_h1_cho": "Hồ sơ đã ở nhóm chờ Admin quyết.",
}


# ═══════════════════════════════ kiểm đầu vào ═════════════════════════════════════════════
#: Review max PR #724 (R7): câu khi ngày ký sau hôm nay (giờ VN) — nguyên văn, MSW chép đúng câu này.
SIGN_DATE_AFTER_TODAY_MESSAGE = "Ngày ký không được sau hôm nay."


#: Codex 42 (câu 4): trần độ dài (ký tự) của chuỗi JSON ``xac_nhan_trang_thai`` trên Form. Dữ liệu thật: ≤ ~16 khoá trạng
#: thái ⇒ < 600 ký tự. Trần giữ độ lồng tối đa 512 tầng; với bản dựng đang dùng, JSON hợp lệ lồng 500 tầng ĐO được là đọc
#: được (ca test hai phía) — giới hạn đệ quy C của bộ đọc JSON phụ thuộc bản dựng / nền tảng (Codex 43), nên KHÔNG khẳng định
#: "luôn"; ``except RecursionError`` ở router giữ làm lớp thứ hai. Vượt trần ⇒ router coi là "không đọc được" (cùng đường JSON
#: hỏng) ở cả hai phía (MSW đếm code point như ``len``).
CONFIRMATION_JSON_MAX_CHARS = 1024


def check_decision_number(number: object) -> str:
    if not isinstance(number, str) or not (1 <= len(number) <= 6) or not number.isascii() or not number.isdigit():
        raise DataValidationError("Số Quyết định phải là 1–6 chữ số.")
    # Review max PR #724 (R7, owner 15-11): CẤM số 0 đứng đầu — trước đây '7', '07', '007' là ba số khác nhau trước
    # luật "không trùng số trong năm" (U1). Không tự đổi số người dùng gõ. (Pattern router / CHECK CSDL giữ dạng rộng
    # hơn làm lớp phụ; tầng chủ sở hữu luật là đây.) Owner chốt: số KHÁC "0" mà có 0 đứng đầu ⇒ từ chối; "0" một chữ số
    # vẫn nhận (Codex 42 F337).
    if len(number) > 1 and number[0] == "0":
        raise DataValidationError(render_service.DECISION_NUMBER_LEADING_ZERO_MESSAGE)
    return number


def check_date(date_value: object, name: str = "ngày ký") -> date:
    if isinstance(date_value, datetime) or not isinstance(date_value, date):
        raise DataValidationError("Thiếu %s hoặc %s không hợp lệ." % (name, name))
    # Review max PR #724 (R7, owner 15-11): ngày ký không được sau HÔM NAY theo giờ Việt Nam (năm của ngày ký là phạm
    # vi số Quyết định U1 — ngày tự gõ ở tương lai mở một "năm" giả). Mọi nơi gọi đều truyền ngày ký. Câu là hằng
    # NGUYÊN VĂN (MSW chép nguyên câu — ``test_hop_dong_msw_cau_loi`` đòi có nguyên văn ở máy chủ).
    if date_value > today_vn():
        raise DataValidationError(SIGN_DATE_AFTER_TODAY_MESSAGE)
    return date_value


def check_scan(content: object) -> bytes:
    """Bản scan PDF (J2 bước 5: bắt buộc): không rỗng, ≤ trần kỹ thuật, chữ ký ``%PDF-``."""
    if not isinstance(content, (bytes, bytearray)) or not content:
        raise DataValidationError("Phải kèm bản scan (PDF) của văn bản đã ký.")
    b = bytes(content)
    if len(b) > settings.COUNCIL_DECISION_SCAN_MAX_BYTES:
        raise DataValidationError(
            "Bản scan vượt giới hạn kỹ thuật %d byte." % settings.COUNCIL_DECISION_SCAN_MAX_BYTES
        )
    if not b.startswith(b"%PDF-"):
        raise DataValidationError("Bản scan phải là tệp PDF.")
    return b


def check_status_confirmation(confirmation: object) -> Optional[Dict[str, int]]:
    """``None`` hoặc dict KHÔNG rỗng {trạng thái / mã đếm: số ≥ 1}."""
    if confirmation is None:
        return None
    if not isinstance(confirmation, dict) or not confirmation:
        raise DataValidationError("Xác nhận phải là danh sách {loại: số hồ sơ} không rỗng.")
    out: Dict[str, int] = {}
    for k, v in confirmation.items():
        if not isinstance(k, str) or isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise DataValidationError("Số hồ sơ trong xác nhận phải là số nguyên ≥ 1.")
        out[k] = v
    return dict(sorted(out.items()))


def _check_count_confirmation(
    counts: Dict[str, int],
    row: Dict[str, List[int]],
    confirmation: Optional[Dict[str, int]],
    operation: str,
) -> Optional[Dict[str, int]]:
    """Khuôn "Admin xác nhận ĐÚNG số đếm" (F228 / C3): có gì cần xác nhận mà chưa / lệch ⇒ 409 kèm
    số đếm + số dòng; không có gì mà vẫn gửi ⇒ 409 lệch. Trả số đếm đã xác nhận (để ghi vết)."""
    counts = dict(sorted(counts.items()))
    content = {
        "xac_nhan_can": {
            "so_ho_so_theo_loai": counts,
            "dong_theo_loai": {k: sorted(v) for k, v in sorted(row.items())},
        }
    }
    if not counts:
        if confirmation is not None:
            raise ConflictError(
                "Không còn gì cần xác nhận — gửi lại không kèm xác nhận.",
                public_payload=content,
            )
        return None
    if confirmation is None:
        raise ConflictError(
            "%s: có %d hồ sơ cần Admin xác nhận đúng số đếm theo từng loại rồi gửi lại."
            % (operation, sum(counts.values())),
            public_payload=content,
        )
    if confirmation != counts:
        raise ConflictError(
            "Số hồ sơ theo từng loại đã khác lúc xác nhận — xem lại rồi xác nhận lại.",
            public_payload=content,
        )
    return counts


def _translate_db_error(code: Tuple[Optional[str], Optional[str]], operation: str) -> Exception:
    """Dịch (SQLSTATE, tên ràng buộc) — kết quả của :func:`db_error_codes`, KHÔNG nhận ngoại lệ (chữ của nó có
    thể mang tham số câu lệnh) — thành lỗi miền có thông điệp CỐ ĐỊNH."""
    sqlstate, constraint = code
    if sqlstate == "23505" and constraint in _CONSTRAINT_ERRORS:
        return ConflictError(
            _CONSTRAINT_ERRORS[constraint], public_payload={"rang_buoc": constraint}
        )
    if sqlstate == SQLSTATE_DEADLOCK:  # deadlock — PostgreSQL đã huỷ đúng một giao dịch
        return ConflictError(CONFLICT_MESSAGE)
    return ServiceError("Lỗi CSDL khi %s — không ghi gì." % operation)


def _event(kind, *, actor_id, figures, set_id=None, decision_id=None, hold_id=None):
    return CouncilDocumentEvent(
        loai=kind,
        set_id=set_id,
        decision_id=decision_id,
        hold_id=hold_id,
        nguoi_id=actor_id,
        so_lieu=figures,
    )


def _scan(decision_id: int, b: bytes) -> CouncilDecisionScan:
    return CouncilDecisionScan(
        decision_id=decision_id,
        sha256=hashlib.sha256(b).hexdigest(),
        kich_thuoc=len(b),
        kieu=SCAN_KIND,
        noi_dung=b,
    )


def _json_value(v: Any) -> Any:
    return v.isoformat() if isinstance(v, date) else v


def _compare_params(
    doc_set: CouncilDocumentSet, number: str, signing_date: date, paper_params: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """BS §3.2 — mọi tham số bộ ĐÃ in phải bằng giá trị trên giấy (lệch ⇒ CHẶN: tờ giấy không phải bản
    in của bộ này); trường bộ để trống nhận giá trị Admin gõ. Bộ tái dựng: số / ngày = bản ký đã khai."""
    set_params = doc_set.tham_so_quyet_dinh or {}
    mismatch: List[str] = []
    if doc_set.ban_ky_so_quyet_dinh is not None and (
        doc_set.ban_ky_so_quyet_dinh != number or doc_set.ban_ky_ngay != signing_date
    ):
        mismatch.append("số / ngày của bản ký đã khai khi tái dựng")
    if set_params.get("so_quyet_dinh") is not None and set_params["so_quyet_dinh"] != number:
        mismatch.append("số Quyết định")
    if set_params.get("ngay_quyet_dinh") is not None and set_params["ngay_quyet_dinh"] != signing_date.isoformat():
        mismatch.append("ngày Quyết định")
    paper = {}
    for t in PAPER_PARAM_FIELDS:
        g = _json_value(paper_params.get(t))
        if set_params.get(t) is not None and g != set_params.get(t):
            mismatch.append(t)
        if g is not None:
            paper[t] = g
    if mismatch:
        raise DataValidationError(
            "Giấy đã ký khác bản in của bộ ở: %s — dựng lại bộ đúng tham số trên giấy."
            % ", ".join(mismatch),
            public_payload={"truong_lech": mismatch},
        )
    return paper or None


async def _check_templates_by_signing_date(db: AsyncSession, doc_set: CouncilDocumentSet, signing_date: date) -> None:
    """BS §3.2 (G10): ba mẫu đúng theo NGÀY KÝ (cùng hàm chọn ``effective_template`` của kho mẫu) phải trùng
    id + sha ba mẫu bộ đã dùng — "căn cứ trên văn bản theo ngày ký" (J1 dòng 7)."""
    used_templates = (doc_set.thong_tin_dung or {}).get("mau_da_dung") or {}
    repo = CouncilDocumentRepository(db)
    mismatch = []
    for kind in render_service.TEMPLATE_KINDS:
        m = await repo.effective_template(kind, signing_date)
        d = used_templates.get(kind) or {}
        if m is None or d.get("id") != m.id or d.get("sha256") != m.sha256:
            mismatch.append(kind)
    if mismatch:
        raise DataValidationError(
            "Mẫu đúng theo ngày ký khác mẫu bộ đã dùng (%s) — dựng lại bộ với ngày ký trên giấy."
            % ", ".join(mismatch),
            public_payload={"mau_lech": mismatch},
        )


def _count_status_changes(set_rows, current: Dict[int, str]):
    """C3: em ĐỔI trạng thái so với lúc dựng (``status_luc_dung``) — đếm theo trạng thái hiện tại +
    số dòng; trạng thái lạ (ngoài 15) ⇒ danh sách chặn."""
    counts: Dict[str, int] = {}
    row: Dict[str, List[int]] = {}
    odd: List[int] = []
    for d in set_rows:
        s = current.get(d.profile_id)
        if s not in KNOWN_STATUSES:
            odd.append(d.stt)
            continue
        if s != d.status_luc_dung:
            counts[s] = counts.get(s, 0) + 1
            row.setdefault(s, []).append(d.stt)
    return counts, row, odd


def _block_by_state(set_rows, states, allowed_chain: Optional[int] = None):
    """Dòng bị chặn vì tình trạng Quyết định (HL ở văn bản khác / chờ quyết / dấu AppSheet) — luật là
    ĐÚNG hàm của cổng dựng bộ (:func:`decision_state_block_reason`, CLAUDE.md §7), đọc trên tình trạng của hàm hỏi."""
    out = []
    for d in set_rows:
        t = states.get(d.profile_id)
        if t is None:
            continue
        code = decision_state_block_reason(t, allowed_chain)
        if code:
            out.append(
                {"dong": d.stt, "ly_do": code[0], "ma": code, "quyet_dinh_id": t.effective_decision_id}
            )
    return out


async def _set_decisions_valid(repo, set_id, *, for_adjustment_of: Optional[int]):
    doc_set = await repo.lock_set(set_id)
    if doc_set is None:
        raise ResourceNotFoundError("Không có bộ văn bản này.")
    if for_adjustment_of is None and doc_set.cho_quyet_dinh_goc_id is not None:
        raise DataValidationError(
            "Bộ này dựng làm dữ liệu cho văn bản điều chỉnh — chỉ dùng được khi ghi nhận điều chỉnh."
        )
    if for_adjustment_of is not None and doc_set.cho_quyet_dinh_goc_id != for_adjustment_of:
        raise DataValidationError(
            "Bộ này không dựng cho văn bản điều chỉnh của Quyết định đã chọn."
        )
    row = await repo.set_rows(doc_set.id)
    if len(row) != doc_set.so_ho_so or [d.stt for d in row] != list(range(1, doc_set.so_ho_so + 1)):
        raise DataValidationError(
            "Bộ dựng trước khi có dòng bộ (id hồ sơ) — không ghi nhận được; dựng lại bộ."
        )
    missing = [d.stt for d in row if d.profile_id is None]
    if missing:
        raise DataValidationError(
            "Dòng %s: hồ sơ của dòng bộ không còn — không ghi nhận được."
            % ", ".join(map(str, missing))
        )
    live = await repo.live_documents_of_set(doc_set.id)
    if live:
        raise ConflictError(
            "Bộ này đã được ghi nhận là văn bản đã ký #%d." % live[0].id,
            public_payload={"quyet_dinh_id": live[0].id},
        )
    return doc_set, row


async def _number_not_in_use(repo, number: str, scope: int) -> None:
    in_use = await repo.number_in_use(number, scope)
    if in_use is not None:
        raise ConflictError(
            "Số Quyết định %s đã dùng trong năm %d (văn bản #%d)." % (number, scope, in_use),
            public_payload={"quyet_dinh_id": in_use},
        )


async def _decision_file_sha(db: AsyncSession, set_id: int) -> str:
    file = [
        t
        for t in await CouncilDocumentRepository(db).list_set_files(set_id)
        if t.path.startswith(DECISION_FILE)
    ]
    if len(file) != 1:
        raise ServiceError("Bộ không có đúng một tệp Quyết định — không ghi nhận.")
    return file[0].sha256


# ═══════════════════════════════ ghi nhận trúng tuyển / bổ sung ═══════════════════════════
async def record_decision(
    db: AsyncSession,
    *,
    set_id: int,
    kind: str,
    root_id: Optional[int],
    decision_number: object,
    signing_date: object,
    paper_params: Optional[Dict[str, Any]],
    confirm_profile_count: object,
    confirm_printed_copy_match: object,
    confirm_status: object,
    template_note: Optional[str],
    scan: object,
    actor_id: int,
    submission_code: object,
) -> Tuple[CouncilDecision, List[Dict[str, Any]], bool]:
    """Ghi nhận MỘT Quyết định trúng tuyển / bổ sung đã ký từ bộ ``set_id`` (đặc tả mục 5.3). Trả
    ``(văn bản, cảnh báo vượt chỉ tiêu — N9, rỗng khi không ô nào vượt, lap_lai)``; router commit.

    Vòng giao diện (đặc tả bản 2 mục 3.7.3): ``ma_luot_gui`` (do ``POST /sets/{id}/luot-ghi-nhan`` cấp) — câu CSDL ĐẦU
    TIÊN khoá lượt ``cho_gui`` (đầu thứ tự khoá chung); câu CUỐI chốt ``da_ghi``. Lượt không còn ``cho_gui`` ⇒ nhánh
    CHỈ ĐỌC: gửi lặp đúng nội dung ⇒ trả lại văn bản cũ (``lap_lai`` = True, cảnh báo đọc từ sự kiện đã lưu); còn
    lại 409."""
    number = check_decision_number(decision_number)
    date_value = check_date(signing_date)
    b = check_scan(scan)
    confirmation = check_status_confirmation(confirm_status)
    note = None if template_note in (None, "") else check_reason(template_note, "ghi chú mẫu")
    if kind not in ("trung_tuyen", "bo_sung"):
        raise DataValidationError("Loại văn bản ghi nhận từ bộ: trung_tuyen | bo_sung.")
    if (kind == "bo_sung") != (root_id is not None):
        raise DataValidationError(
            "Quyết định bổ sung phải chọn Quyết định gốc; Quyết định trúng tuyển thì không."
        )
    if confirm_printed_copy_match is not True:
        raise DataValidationError(
            "Admin phải xác nhận danh sách, ngành, điểm từng em trên bản ký khớp bản in của bộ "
            "(C2: bản ký sửa tay ⇒ dựng lại bộ cho khớp bản ký)."
        )
    code = submission_service.check_submission_code(submission_code)
    sha = submission_service.submission_content_sha(
        set_id=set_id,
        kind=kind,
        root_id=root_id,
        decision_number=number,
        signing_date=date_value,
        paper_params=paper_params,
        confirm_profile_count=confirm_profile_count,
        confirm_printed_copy_match=confirm_printed_copy_match,
        confirm_status=confirmation,
        template_note=note,
        sha_scan=hashlib.sha256(b).hexdigest(),
    )
    repo = CouncilDecisionRepository(db)
    try:
        # Lượt gửi: câu CSDL ĐẦU TIÊN, GIỮ ``cho_gui`` (F265) — đầu thứ tự khoá chung.
        submission = await submission_service.lock_pending_submission(db, code=code, set_id=set_id)
        if submission is None:
            # F272: nhánh CHỈ ĐỌC — không khoá thêm gì, router kết thúc giao dịch ngay.
            old_decision_id = submission_service.check_submission_finished(
                await submission_service.read_submission(db, code), set_id=set_id, sha=sha
            )
            old_decision = await repo.decision_by_id(old_decision_id)
            if old_decision is None:
                raise ServiceError("Lượt gửi đã ghi nhưng không đọc được văn bản — không trả.")
            return old_decision, await stored_warnings(db, old_decision_id, "ghi_nhan"), True
        async with db.begin_nested():
            root = None
            if root_id is not None:
                root = await repo.lock_decision(root_id)
                if root is None:
                    raise ResourceNotFoundError("Không có Quyết định gốc này.")
                if root.loai != "trung_tuyen" or root.trang_thai != "hieu_luc":
                    raise ConflictError(
                        "Quyết định gốc phải là Quyết định trúng tuyển đang hiệu lực."
                    )
            doc_set, row = await _set_decisions_valid(repo, set_id, for_adjustment_of=None)
            if (
                isinstance(confirm_profile_count, bool)
                or not isinstance(confirm_profile_count, int)
                or confirm_profile_count != doc_set.so_ho_so
            ):
                raise DataValidationError("Số hồ sơ gõ lại không khớp số hồ sơ của bộ.")
            signed_copy_params = _compare_params(doc_set, number, date_value, paper_params or {})
            await _check_templates_by_signing_date(db, doc_set, date_value)
            if doc_set.ban_ky_so_quyet_dinh is None and date_value < vn_calendar_date(doc_set.tao_luc):
                raise DataValidationError(
                    "Ngày ký trước ngày dựng bộ (giờ Việt Nam) — tờ giấy không thể là bản in của bộ "
                    "này."
                )
            await _number_not_in_use(repo, number, date_value.year)
            pids = [d.profile_id for d in row]
            current = await repo.lock_profiles(pids)
            if set(current) != set(pids):
                raise DataValidationError("Có hồ sơ của bộ không còn — không ghi nhận được.")
            # Chặng 2b: dòng sắp chiếm chỗ (Phần B) ⇒ khoá dòng chỉ tiêu SAU hồ sơ (thứ tự chung).
            await lock_quota_of_set_rows(db, [d.id for d in row])
            # Q-J1 (owner 10-11): dòng bộ thiếu khoá đếm / lệch chuỗi ⇒ CHẶN (dưới khoá, trước ghi).
            await check_lock_and_count_set_rows(db, [(d.stt, d.id) for d in row])
            blocked = _block_by_state(row, await decision_state(db, pids))
            if blocked:
                raise ConflictError(
                    "%d hồ sơ đã có Quyết định hiệu lực / đang chờ Admin quyết / mang dấu trúng tuyển "
                    "theo Quyết định cũ — không ghi nhận Quyết định mới." % len(blocked),
                    public_payload={"dong_bi_chan": blocked},
                )
            counts, status_changed_rows, odd = _count_status_changes(row, current)
            if odd:
                raise DataValidationError(
                    "Dòng %s: trạng thái hồ sơ không xác định — không ghi nhận."
                    % ", ".join(map(str, odd))
                )
            confirmed = _check_count_confirmation(counts, status_changed_rows, confirmation, "Có em đổi trạng thái sau khi dựng bộ")
            decision = CouncilDecision(
                loai=kind,
                can_bo=True,
                set_id=doc_set.id,
                goc_id=root_id,
                so_quyet_dinh=number,
                ngay_ky=date_value,
                pham_vi_so=date_value.year,
                trang_thai="hieu_luc",
                tham_so_ban_ky=signed_copy_params,
                so_ho_so=len(row),
                sha_tep_quyet_dinh=await _decision_file_sha(db, doc_set.id),
                xac_nhan={
                    "so_ho_so": doc_set.so_ho_so,
                    "khop_ban_in": True,
                    "doi_trang_thai": confirmed,
                },
                ghi_chu_mau=note,
                ghi_nhan_boi_id=actor_id,
            )
            await repo.add_objects(decision)
            n = await repo.insert_rows_from_set(decision.id, doc_set.id)
            if n != len(row):
                raise ServiceError("Chép dòng bộ sang Quyết định thiếu dòng — không ghi.")
            # N9 (đặc tả 5.3): ĐÃ chèn dòng — đếm lại các ô của dòng vừa ghi (cùng giao dịch, dưới khoá dòng
            # chỉ tiêu) ⇒ cảnh báo ô bị vượt, KHÔNG chặn (giấy đã ký). Vòng giao diện 3.8: cảnh báo LƯU vào sự
            # kiện ghi nhận (cùng giao dịch) — đọc lại trả đúng bản đã lưu, không tính lại.
            warnings = await over_quota_warnings(db, [d.id for d in row])
            await repo.add_objects(
                _scan(decision.id, b),
                _event(
                    "ghi_nhan",
                    actor_id=actor_id,
                    set_id=doc_set.id,
                    decision_id=decision.id,
                    figures={
                        "loai": kind,
                        "so_ho_so": len(row),
                        "doi_trang_thai": confirmed,
                        "goc_id": root_id,
                        "canh_bao_vuot_chi_tieu": warnings,
                    },
                ),
            )
            # Lượt gửi: câu CUỐI trước commit — MỘT câu đặt đủ cột (F265).
            await submission_service.finalize_recorded(db, submission_id=submission.id, decision_id=decision.id, sha=sha)
    except DBAPIError as e:
        raise _translate_db_error(db_error_codes(e), "ghi nhận Quyết định") from None
    return decision, warnings, False


async def stored_warnings(db: AsyncSession, decision_id: int, event_kind: str) -> List[Dict[str, Any]]:
    """Cảnh báo vượt chỉ tiêu ĐÃ LƯU trong sự kiện (đặc tả 3.8 — đọc lại không tính lại)."""
    figures = (
        await db.execute(
            text(
                "SELECT so_lieu FROM council_document_event WHERE decision_id = :d AND loai = :l "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"d": decision_id, "l": event_kind},
        )
    ).scalar_one_or_none()
    return list((figures or {}).get("canh_bao_vuot_chi_tieu") or [])


async def recorded_decision_detail(db: AsyncSession, decision_id: int) -> CouncilDecision:
    decision = await CouncilDecisionRepository(db).decision_by_id(decision_id)
    if decision is None:
        raise ResourceNotFoundError("Không có văn bản này.")
    return decision


async def root_summary(db: AsyncSession, root_id: Optional[int]) -> Optional[Dict[str, Any]]:
    """``{id, so_quyet_dinh, ngay_ky}`` của Quyết định gốc (DTO ghi nhận — đặc tả 3.8)."""
    if root_id is None:
        return None
    r = (
        await db.execute(
            text("SELECT id, so_quyet_dinh, ngay_ky FROM council_decision WHERE id = :g"), {"g": root_id}
        )
    ).first()
    return None if r is None else {"id": r[0], "so_quyet_dinh": r[1], "ngay_ky": r[2]}


# ═══════════════════════════════ điều chỉnh (C6) ═══════════════════════════════════════════
async def _effective_chain(repo, root_id: int) -> Dict[int, CouncilDecision]:
    return {
        d.id: d
        for d in await repo.chain(root_id)
        if d.loai in ("trung_tuyen", "bo_sung", "dieu_chinh") and d.trang_thai == "hieu_luc"
    }


async def record_adjustment_decision(
    db: AsyncSession,
    root_id: int,
    *,
    decision_number: object,
    signing_date: object,
    removed_row_ids: Sequence[int],
    set_id: Optional[int],
    confirm_profile_count: object,
    confirm_printed_copy_match: object,
    confirm_status: object,
    template_note: Optional[str],
    scan: object,
    actor_id: int,
) -> Tuple[CouncilDecision, None]:
    """Quyết định ĐIỀU CHỈNH (văn thư soạn — C6): bỏ các dòng ``bo_dong`` của chuỗi gốc, thêm mọi dòng
    của bộ ``set_id`` (bộ dữ liệu dựng cho chuỗi này). BỎ trước, THÊM sau trong MỘT giao dịch (U3 là
    chỉ mục duy nhất, kiểm từng dòng — BS §1.3)."""
    number = check_decision_number(decision_number)
    date_value = check_date(signing_date)
    b = check_scan(scan)
    confirmation = check_status_confirmation(confirm_status)
    note = None if template_note in (None, "") else check_reason(template_note, "ghi chú mẫu")
    removed_ids = list(removed_row_ids or [])
    if any(isinstance(x, bool) or not isinstance(x, int) for x in removed_ids) or len(set(removed_ids)) != len(
        removed_ids
    ):
        raise DataValidationError("Danh sách dòng bỏ phải là id dòng, không trùng.")
    if not removed_ids and set_id is None:
        raise DataValidationError("Văn bản điều chỉnh phải bỏ hoặc thêm ít nhất một dòng.")
    repo = CouncilDecisionRepository(db)
    try:
        async with db.begin_nested():
            root = await repo.lock_decision(root_id)
            if root is None:
                raise ResourceNotFoundError("Không có Quyết định này.")
            if root.loai != "trung_tuyen" or root.trang_thai != "hieu_luc":
                raise ConflictError(
                    "Chỉ điều chỉnh được Quyết định trúng tuyển đang hiệu lực."
                )
            doc_set, added_rows = None, []
            if set_id is not None:
                if confirm_printed_copy_match is not True:
                    raise DataValidationError(
                        "Admin phải xác nhận dữ liệu em được thêm / sửa khớp bản ký."
                    )
                doc_set, added_rows = await _set_decisions_valid(repo, set_id, for_adjustment_of=root.id)
                if (
                    isinstance(confirm_profile_count, bool)
                    or not isinstance(confirm_profile_count, int)
                    or confirm_profile_count != doc_set.so_ho_so
                ):
                    raise DataValidationError("Số hồ sơ gõ lại không khớp số hồ sơ của bộ.")
            chain = await _effective_chain(repo, root.id)
            removed_rows = await repo.rows_by_id(removed_ids)
            if len(removed_rows) != len(removed_ids):
                raise DataValidationError("Có dòng bỏ không tồn tại.")
            wrong_rows = [
                d.id
                for d in removed_rows
                if d.decision_id not in chain
                or d.trang_thai_cha != "hieu_luc"
                or d.bi_bo_boi_id is not None
            ]
            if wrong_rows:
                raise ConflictError(
                    "Dòng %s không phải dòng đang hiệu lực của chuỗi Quyết định này."
                    % ", ".join(map(str, wrong_rows)),
                    public_payload={"dong_khong_hop_le": wrong_rows},
                )
            await _number_not_in_use(repo, number, date_value.year)
            added_pids = [d.profile_id for d in added_rows]
            current = await repo.lock_profiles(
                added_pids + [d.profile_id for d in removed_rows if d.profile_id is not None]
            )
            # Chặng 2b: dòng THÊM chiếm chỗ (Phần B); dòng BỎ chỉ trả chỗ ⇒ không cần khoá.
            await lock_quota_of_set_rows(db, [d.id for d in added_rows])
            # Q-J1: dòng THÊM phải đủ khoá đếm + khớp chuỗi (dưới khoá, trước ghi).
            await check_lock_and_count_set_rows(db, [(d.stt, d.id) for d in added_rows])
            states = await decision_state(db, added_pids)
            blocked = _block_by_state(added_rows, states, allowed_chain=root.id)
            removed_id_set = set(removed_ids)
            for d in added_rows:  # em có dòng trong chuỗi thì dòng ấy PHẢI nằm trong danh sách bỏ
                t = states.get(d.profile_id)
                if t is not None and t.effective_decision_id is not None and t.chain_decision_id == root.id:
                    old = await repo.effective_rows_of_profiles([d.profile_id])
                    if old.get(d.profile_id) is None or old[d.profile_id].id not in removed_id_set:
                        blocked.append(
                            {
                                "dong": d.stt,
                                "ly_do": "chua_bo_dong_cu",
                                "quyet_dinh_id": t.effective_decision_id,
                            }
                        )
            if blocked:
                raise ConflictError(
                    "%d hồ sơ của bộ không thêm được vào văn bản điều chỉnh." % len(blocked),
                    public_payload={"dong_bi_chan": blocked},
                )
            counts, status_changed_rows, odd = _count_status_changes(added_rows, current)
            if odd:
                raise DataValidationError("Có trạng thái hồ sơ không xác định — không ghi nhận.")
            confirmed = _check_count_confirmation(counts, status_changed_rows, confirmation, "Có em đổi trạng thái sau khi dựng bộ")
            decision = CouncilDecision(
                loai="dieu_chinh",
                can_bo=doc_set is not None,
                set_id=doc_set.id if doc_set is not None else None,
                goc_id=root.id,
                so_quyet_dinh=number,
                ngay_ky=date_value,
                pham_vi_so=date_value.year,
                trang_thai="hieu_luc",
                so_ho_so=len(added_rows),
                xac_nhan={"doi_trang_thai": confirmed, "so_dong_bo": len(removed_ids)},
                ghi_chu_mau=note,
                ghi_nhan_boi_id=actor_id,
            )
            await repo.add_objects(decision)
            if removed_ids:  # BỎ trước
                await db.execute(
                    text(
                        "UPDATE council_decision_row SET bi_bo_boi_id = :d "
                        "WHERE id = ANY(CAST(:ids AS integer[]))"
                    ),
                    {"d": decision.id, "ids": removed_ids},
                )
            warnings: List[Dict[str, Any]] = []
            if doc_set is not None:  # THÊM sau
                n = await repo.insert_rows_from_set(decision.id, doc_set.id)
                if n != len(added_rows):
                    raise ServiceError("Chép dòng bộ sang văn bản thiếu dòng — không ghi.")
                # K-1 (owner 11-11): dòng THÊM chiếm chỗ (Phần B) ⇒ cảnh báo vượt như ghi nhận, KHÔNG chặn.
                warnings = await over_quota_warnings(db, [d.id for d in added_rows])
            await repo.add_objects(
                _scan(decision.id, b),
                _event(
                    "ghi_nhan_dieu_chinh",
                    actor_id=actor_id,
                    set_id=decision.set_id,
                    decision_id=decision.id,
                    figures={
                        "goc_id": root.id,
                        "so_dong_bo": len(removed_ids),
                        "so_dong_them": len(added_rows),
                        "canh_bao_vuot_chi_tieu": warnings,
                    },
                ),
            )
    except DBAPIError as e:
        raise _translate_db_error(db_error_codes(e), "ghi nhận văn bản điều chỉnh") from None
    return decision, warnings


# ═══════════════════════════════ huỷ hiệu lực (văn bản huỷ của trường) ═════════════════════
async def cancel_effect(
    db: AsyncSession,
    decision_id: int,
    *,
    decision_number: object,
    signing_date: object,
    scan: object,
    actor_id: int,
) -> Tuple[CouncilDecision, Dict[str, int]]:
    """Ghi nhận VĂN BẢN HUỶ của trường trỏ văn bản ``decision_id`` (BS §2; đặc tả 2.3): văn bản đích ⇒
    ``het_hieu_luc`` (CSDL lan xuống dòng — K2); mỗi em có dòng hiệu lực của nó (và, nếu là điều chỉnh,
    em nó đã bỏ mà không còn dòng hiệu lực nào khác) ⇒ nhóm "chờ Admin quyết" (C7). Trả (văn bản huỷ,
    số đếm)."""
    number = check_decision_number(decision_number)
    date_value = check_date(signing_date)
    b = check_scan(scan)
    repo = CouncilDecisionRepository(db)
    try:
        async with db.begin_nested():
            x = await repo.lock_decision(decision_id)
            if x is None:
                raise ResourceNotFoundError("Không có văn bản này.")
            if x.loai == "van_ban_huy":
                raise DataValidationError("Không ghi văn bản huỷ cho một văn bản huỷ.")
            if x.trang_thai != "hieu_luc":
                raise ConflictError("Văn bản này không còn hiệu lực.")
            if x.loai == "trung_tuyen":
                children = [
                    d.id
                    for d in (await _effective_chain(repo, x.id)).values()
                    if d.id != x.id
                ]
                if children:
                    raise ConflictError(
                        "Quyết định còn văn bản bổ sung / điều chỉnh đang hiệu lực (#%s) — ghi "
                        "nhận văn bản huỷ cho từng văn bản đúng như trường ban hành."
                        % ", #".join(map(str, children)),
                        public_payload={"van_ban_con_hieu_luc": children},
                    )
            await _number_not_in_use(repo, number, date_value.year)
            effective_rows = await repo.effective_rows_of_decision(x.id)
            dropped_rows = await repo.rows_dropped_by(x.id) if x.loai == "dieu_chinh" else []
            pids = [d.profile_id for d in effective_rows + dropped_rows if d.profile_id is not None]
            await repo.lock_profiles(pids)
            open_holds = await repo.open_holds(pids)
            other_effective = await repo.effective_rows_of_profiles(
                [d.profile_id for d in dropped_rows if d.profile_id is not None]
            )
            h = CouncilDecision(
                loai="van_ban_huy",
                can_bo=False,
                set_id=None,
                huy_qd_id=x.id,
                so_quyet_dinh=number,
                ngay_ky=date_value,
                pham_vi_so=date_value.year,
                trang_thai="hieu_luc",
                so_ho_so=0,
                ghi_nhan_boi_id=actor_id,
            )
            await repo.add_objects(h)
            x.trang_thai = "het_hieu_luc"
            x.het_hieu_luc_boi_id = h.id
            await db.flush()
            new: Dict[int, CouncilDecisionHold] = {}
            already_in_group = 0
            for d, entry_reason in [(d, "qd_bi_huy") for d in effective_rows] + [
                (d, "bi_bo_boi_van_ban_bi_huy") for d in dropped_rows
            ]:
                p = d.profile_id
                if p is None or p in new:
                    continue
                if p in open_holds:
                    already_in_group += 1
                    continue
                if entry_reason == "bi_bo_boi_van_ban_bi_huy" and p in other_effective:
                    continue  # em đang có Quyết định hiệu lực khác — không cần chờ
                new[p] = CouncilDecisionHold(
                    profile_id=p,
                    decision_row_id=d.id,
                    van_ban_huy_id=h.id,
                    ly_do_vao=entry_reason,
                    trang_thai="cho_quyet",
                )
            figures = {
                "quyet_dinh_bi_huy": x.id,
                "so_dong_tat": len(effective_rows),
                "so_muc_cho_moi": len(new),
                "so_da_o_nhom_cho": already_in_group,
            }
            await repo.add_objects(
                *new.values(),
                _scan(h.id, b),
                _event(
                    "huy_hieu_luc",
                    actor_id=actor_id,
                    set_id=x.set_id,
                    decision_id=h.id,
                    figures=figures,
                ),
            )
    except DBAPIError as e:
        raise _translate_db_error(db_error_codes(e), "ghi nhận văn bản huỷ") from None
    return h, figures


# ═══════════════════════════════ huỷ ghi nhận (nhập sai) ══════════════════════════════════
async def revoke_record(
    db: AsyncSession,
    decision_id: int,
    *,
    reason: object,
    retyped_number: object,
    confirmation: object,
    actor_id: int,
) -> Tuple[CouncilDecision, Dict[str, int], List[Dict[str, Any]]]:
    """Huỷ ghi nhận = văn bản nhập SAI vào phần mềm — như chưa từng ghi, giữ vết (BS §2; đặc tả 2.5).
    Chỉ gỡ được văn bản MỚI NHẤT còn sống của chuỗi. Văn bản huỷ: văn bản đích có hiệu lực lại (CSDL lan
    + U3 chặn nếu em đã ở Quyết định khác); mọi mục chờ nó sinh ⇒ ``vo_hieu`` — trong CÙNG giao dịch."""
    reason = check_reason(reason, "huỷ ghi nhận")
    confirmed = check_status_confirmation(confirmation)
    repo = CouncilDecisionRepository(db)
    figures: Dict[str, int] = {}
    try:
        async with db.begin_nested():
            x = await repo.lock_decision(decision_id)
            if x is None:
                raise ResourceNotFoundError("Không có văn bản này.")
            if retyped_number != x.so_quyet_dinh:
                raise DataValidationError("Số văn bản gõ lại không khớp.")
            if x.trang_thai == "huy_ghi_nhan":
                raise ConflictError("Văn bản đã được huỷ ghi nhận.")
            target = None
            if x.loai == "van_ban_huy":
                target = await repo.lock_decision(x.huy_qd_id)
                chain_root = target.goc_id or target.id
            else:
                chain_root = x.goc_id or x.id
            live = [d for d in await repo.chain(chain_root) if d.trang_thai != "huy_ghi_nhan"]
            after = sorted(d.id for d in live if d.id > x.id)
            if after:
                raise ConflictError(
                    "Có văn bản ghi nhận SAU đã tác động lên chuỗi này (#%s) — huỷ ghi nhận văn bản "
                    "mới nhất trước." % ", #".join(map(str, after)),
                    public_payload={"van_ban_sau": after},
                )
            reactivated: List[Any] = []
            if target is not None:
                reactivated = [
                    d for d in await repo.rows_of_decision(target.id) if d.bi_bo_boi_id is None
                ]
            elif x.loai == "dieu_chinh":
                reactivated = await repo.rows_dropped_by(x.id)
            item = await repo.holds_of_cancelled_decision(x.id) if target is not None else []
            pids = [d.profile_id for d in reactivated if d.profile_id is not None]
            current = await repo.lock_profiles(pids + [m.profile_id for m in item if m.profile_id])
            # Chặng 2b: dòng BẬT LẠI chiếm chỗ lại (Phần B) ⇒ khoá dòng chỉ tiêu của chúng.
            await lock_quota_of_set_rows(db, [d.set_row_id for d in reactivated])
            # Q-J1: dòng BẬT LẠI phải đủ khoá đếm + khớp chuỗi (dưới khoá, trước ghi).
            await check_lock_and_count_set_rows(db, [(d.stt, d.set_row_id) for d in reactivated])
            other = await repo.effective_rows_of_profiles(pids)
            conflicts = [
                {"dong": d.stt, "quyet_dinh_id": other[d.profile_id].decision_id}
                for d in reactivated
                if d.profile_id in other and other[d.profile_id].decision_id != x.id
            ]
            if conflicts:
                raise ConflictError(
                    "%d em đã có tên trong Quyết định khác — phải có văn bản đưa em ra khỏi một trong "
                    "hai Quyết định trước." % len(conflicts),
                    public_payload={"dong_xung_dot": conflicts},
                )
            if target is not None:
                counts: Dict[str, int] = {}
                row: Dict[str, List[int]] = {}
                recheck_items = [m for m in item if m.trang_thai == "da_cho_xet_lai"]
                if recheck_items:
                    counts["da_cho_xet_lai"] = len(recheck_items)
                for d in reactivated:
                    s = current.get(d.profile_id)
                    if s is not None and s not in NON_WARNING_STATUSES:
                        counts[s] = counts.get(s, 0) + 1
                        row.setdefault(s, []).append(d.stt)
                _check_count_confirmation(counts, row, confirmed, "Huỷ ghi nhận văn bản huỷ")
            elif confirmed is not None:
                raise ConflictError("Không còn gì cần xác nhận — gửi lại không kèm xác nhận.")
            time = datetime.now(timezone.utc)
            x.trang_thai = "huy_ghi_nhan"
            x.huy_ghi_nhan_boi_id = actor_id
            x.huy_ghi_nhan_luc = time
            x.ly_do_huy_ghi_nhan = reason
            await db.flush()  # CSDL lan cờ xuống dòng của x (K2)
            if target is not None:
                target.trang_thai = "hieu_luc"
                target.het_hieu_luc_boi_id = None
                await db.flush()  # CSDL lan; U3 chặn cuối
                for m in item:
                    if m.trang_thai != "vo_hieu":
                        m.trang_thai = "vo_hieu"
                        m.vo_hieu_boi_id = actor_id
                        m.vo_hieu_luc = time
                await db.flush()
            elif x.loai == "dieu_chinh" and reactivated:
                await db.execute(  # bật lại dòng điều chỉnh đã bỏ — SAU khi dòng của nó đã tắt
                    text("UPDATE council_decision_row SET bi_bo_boi_id = NULL WHERE bi_bo_boi_id = :d"),
                    {"d": x.id},
                )
            figures = {
                "loai": x.loai,
                "so_dong_bat_lai": len(reactivated),
                "so_muc_cho_vo_hieu": len([m for m in item]),
            }
            # K-1 (owner 11-11): dòng BẬT LẠI chiếm chỗ lại (Phần B) — đã bật ở trên, cùng giao dịch, dưới khoá
            # dòng chỉ tiêu (``lock_quota_of_set_rows``) ⇒ cảnh báo vượt như ghi nhận, KHÔNG chặn.
            warnings = (
                await over_quota_warnings(db, [d.set_row_id for d in reactivated]) if reactivated else []
            )
            await repo.add_objects(
                _event(
                    "huy_ghi_nhan",
                    actor_id=actor_id,
                    set_id=x.set_id,
                    decision_id=x.id,
                    figures={**figures, "canh_bao_vuot_chi_tieu": warnings},
                )
            )
    except DBAPIError as e:
        raise _translate_db_error(db_error_codes(e), "huỷ ghi nhận") from None
    return x, figures, warnings


# ═══════════════════════════════ nhóm chờ — Admin cho xét lại TỪNG em (C7) ═════════════════
async def review_hold_again(
    db: AsyncSession, hold_id: int, *, reason: object, actor_id: int
) -> Tuple[CouncilDecisionHold, None]:
    reason = check_reason(reason, "cho xét lại")
    repo = CouncilDecisionRepository(db)
    try:
        async with db.begin_nested():
            h = await repo.lock_hold(hold_id)
            if h is None:
                raise ResourceNotFoundError("Không có mục chờ này.")
            if h.trang_thai != "cho_quyet":
                raise ConflictError("Mục này không còn ở nhóm chờ Admin quyết.")
            if h.profile_id is not None:
                await repo.lock_profiles([h.profile_id])
            h.trang_thai = "da_cho_xet_lai"
            h.quyet_boi_id = actor_id
            h.quyet_luc = datetime.now(timezone.utc)
            h.ly_do_quyet = reason
            await db.flush()
            await repo.add_objects(
                _event(
                    "cho_xet_lai",
                    actor_id=actor_id,
                    hold_id=h.id,
                    decision_id=h.van_ban_huy_id,
                    figures={"muc_cho_id": h.id, "van_ban_huy_id": h.van_ban_huy_id},
                )
            )
    except DBAPIError as e:
        raise _translate_db_error(db_error_codes(e), "cho xét lại") from None
    return h, None


# ═══════════════════════════════ đọc ═════════════════════════════════════════════════════
# Tóm tắt văn bản đã ký của MỘT bộ (trước: ``tom_tat_qd_cua_bo``) nay ở ``SQL_SET_EXTENDED`` của
# ``council_document_repository`` — MỘT câu cho danh sách + chi tiết bộ (vòng giao diện, đặc tả 3.4 / 3.5).


async def decision_detail(db: AsyncSession, decision_id: int):
    repo = CouncilDecisionRepository(db)
    decision = await repo.decision_by_id(decision_id)
    if decision is None:
        raise ResourceNotFoundError("Không có văn bản này.")
    row = await repo.rows_of_decision(decision_id)
    scan = await repo.decision_scan(decision_id)
    event = await repo.list_events(
        set_id=None, decision_id=decision_id, limit=200, offset=0
    )
    return decision, row, scan, event


async def read_scan(db: AsyncSession, decision_id: int) -> CouncilDecisionScan:
    s = await CouncilDecisionRepository(db).decision_scan(decision_id, with_content=True)
    if s is None:
        raise ResourceNotFoundError("Văn bản này không có bản scan.")
    if hashlib.sha256(bytes(s.noi_dung)).hexdigest() != s.sha256:
        raise ServiceError("Bản scan đã lưu lệch sha256 — không trả.")
    return s


async def log_scan_download(db: AsyncSession, scan: CouncilDecisionScan, actor_id: int) -> None:
    """Nhật ký mỗi lần CẤP bản scan (khuôn J1 dòng 31) — router COMMIT trước khi trả bytes."""
    try:
        await CouncilDecisionRepository(db).add_objects(
            _event(
                "tai_scan",
                actor_id=actor_id,
                decision_id=scan.decision_id,
                figures={"sha256": scan.sha256, "kich_thuoc": scan.kich_thuoc},
            )
        )
    except DBAPIError:
        raise ServiceError("Không ghi được nhật ký tải bản scan — không trả tệp.") from None
