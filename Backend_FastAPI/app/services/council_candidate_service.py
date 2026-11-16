# app/services/council_candidate_service.py
"""Hàm đọc hồ sơ cho bộ văn bản Hội đồng (giai đoạn 1 "Lần xét tuyển", PR 1.3 phần đọc).

Vào: danh sách MÃ HỒ SƠ (số CCCD — J1 dòng 8) đúng thứ tự admin đưa + NĂM HỌC tường minh
(CCCD chỉ duy nhất trong một năm học; thiếu năm ⇒ lỗi miền). Ra: ``CandidateRowV1``
đúng thứ tự đó + đơn vị từng hồ sơ + thông tin giao dịch đọc (mức cô lập, chỉ đọc, mốc chụp
— đo NGAY TRONG giao dịch).

* Đọc trong MỘT giao dịch ``REPEATABLE READ READ ONLY`` trên kết nối riêng
  (:func:`app.repositories.council_candidate_repository.read_only_transaction`) — không dùng giao
  dịch của request, không ghi gì; giao dịch này KẾT THÚC khi hàm trả về. Ghi bộ văn bản là
  giao dịch KHÁC, của request (F218).
* Mỗi trường DTO tính như cột cùng tên của truy vấn bộ xuất (luật v1) — SQL ở repository.
* KHÔNG lọc trạng thái, KHÔNG lọc trình độ ở tầng đọc: ảnh chụp giữ đúng bộ xuất; trình độ lạ
  do bộ dựng chặn. Cổng dựng bộ (lượt G — F228 trạng thái, F229 nguồn ngành / nguyện vọng /
  điểm, F231 khu vực) nằm ở ``council_set_gate_service``, chạy trên ``ProfileSnapshot.kiem`` —
  dữ liệu kiểm đọc trong CÙNG giao dịch chỉ đọc này.
* Lỗi đầu vào (mã rỗng, trùng, không khớp ĐÚNG MỘT hồ sơ) ⇒ ``DataValidationError`` nêu SỐ
  THỨ TỰ dòng, KHÔNG nêu giá trị. Lỗi CSDL ⇒ ``ServiceError`` không mang câu SQL / tham số
  (thông báo của trình điều khiển chứa danh sách mã). Không log mã, DTO ở bất kỳ mức nào.
"""
import json
import re
import unicodedata
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Dict, List, Optional, Sequence, Tuple

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from app.config import settings
from app.repositories.council_candidate_repository import (
    TransactionInfo,
    read_check_source,
    read_scope_by_ids,
    read_print_figures,
    read_only_transaction,
    resolve_codes,
)
from app.services.council_document_render_service import (
    CANDIDATE_FIELDS,
    CandidateRowV1,
)
from app.services.council_decision_status_service import from_row
from app.services.council_set_gate_service import CheckData
from app.utils.exceptions import (
    DataValidationError,
    PriorityRateNotConfigured,
    ServiceError,
)

# Độ dài tối đa của một mã đầu vào (CCCD 12 số; CMND cũ 9 số) — giới hạn KỸ THUẬT để chuỗi
# lạ không tới CSDL; luật định dạng nghiệp vụ là ``_RE_DINH_DANG_MA`` dưới đây.
MAX_CODE_LENGTH = 32
# Định dạng mã hồ sơ (owner 04-11, ``Y-TUONG-…`` J1 dòng 28): ĐÚNG 12 chữ số (CCCD) HOẶC
# ĐÚNG 9 chữ số (CMND cũ), chỉ chữ số ASCII 0-9 — lớp ký tự viết tường minh, KHÔNG dùng
# ``\d`` (``\d`` của Python khớp cả chữ số toàn hình / Ả Rập-Ấn). Mã giữ NGUYÊN dạng chuỗi
# (số 0 đầu giữ nguyên), so CHÍNH XÁC với ``citizen_id`` kèm năm học; KHÔNG đệm 0 biến 9
# chữ số thành 12.
_RE_CODE_FORMAT = re.compile(r"[0-9]{12}|[0-9]{9}")
# Số dòng tối đa nêu trong một thông báo lỗi (phần còn lại chỉ đếm).
_MAX_CITED_ROWS = 20


@dataclass(frozen=True)
class ProfileSnapshot:
    rows: Tuple[
        CandidateRowV1, ...
    ]  # = cột cùng tên của bộ xuất (``diem_kv`` theo luật cũ)
    don_vi: Tuple[Optional[int], ...]  # ``lead.unit_id`` từng hồ sơ, cùng thứ tự
    giao_dich: TransactionInfo
    # Dữ liệu cho cổng dựng bộ (lượt G) — cùng giao dịch, cùng thứ tự; KHÔNG ghi gì.
    kiem: Tuple[CheckData, ...] = ()
    # Lượt I (F230): id hồ sơ từng dòng (cột ``pid`` của chính truy vấn đọc), cùng thứ tự — ghi
    # vào dòng bộ để ghi nhận Quyết định nối được về hồ sơ (CCCD sửa được).
    pids: Tuple[int, ...] = ()


async def _area_recompute_mismatch(
    session: AsyncSession, profile: object, snap: dict
) -> Optional[str]:
    """Câu 21 (owner 06-11 — "chặn và liệt kê"): mã lý do nếu KV TÍNH LẠI từ dữ liệu HIỆN TẠI
    của hồ sơ khác KV sẽ in (``kv_resolved`` của ảnh chụp), ``None`` nếu khớp.

    Tính bằng ĐÚNG resolver mà ``freeze_priority_snapshot`` gọi khi chụp (T1 nộp / T6 chấm) —
    ``priority_service.resolve_kv_for_profile`` (năm = năm học hồ sơ qua ``priority_academic_
    year`` bên trong nó; bảng KV xã / trường tra theo năm ấy) — với CÙNG ngữ cảnh trình độ /
    loại hình mà lần chụp đã dùng: ``freeze_priority_snapshot`` ghi ``target_level`` /
    ``admission_type`` vào ảnh chụp khi và chỉ khi chúng khác ``None`` ⇒ đọc lại từ ảnh chụp
    (vắng ⇒ ``None``) tái lập đúng lời gọi, chỉ dữ liệu hồ sơ / danh mục là của hiện tại. So MÃ
    KV (không so ``rule_applied``). Chỉ đọc: resolver chỉ SELECT; giao dịch là READ ONLY ở CSDL.
    Lỗi CSDL ⇒ để nổi lên (hàm gọi đổi thành ``ServiceError``); lỗi khác ⇒ chặn."""
    from app.services.priority_service import resolve_kv_for_profile

    try:
        new_area, _ = await resolve_kv_for_profile(
            profile,
            session,
            target_level=snap.get("target_level"),
            admission_type=snap.get("admission_type"),
        )
    except DBAPIError:
        raise
    # Không tính lại được ⇒ không chứng minh được KV sẽ in còn đúng ⇒ chặn.
    except Exception:  # noqa: BLE001
        return "khu_vuc_khong_tinh_lai_duoc"
    if new_area != snap.get("kv_resolved"):
        return "khu_vuc_doi_sau_anh_chup"
    return None


async def _resolve_area(
    conn: AsyncConnection, check_rows: Sequence[dict]
) -> List[Tuple[Optional[str], Optional[str]]]:
    """F231 — ``(mã lý do chặn | None, mức điểm KV theo NĂM HỌC | None)`` từng dòng.

    Gọi ĐÚNG các helper app dùng khi tính điểm (``priority_service`` — không chép luật):
    ``kv_snapshot_resolved`` (vị từ "KV đã phân giải" của T1 / T6), ``verify_manual_override_
    provenance`` (ấn định thủ công còn hiệu lực — đúng hàm ``freeze_priority_snapshot`` gọi; chỉ
    ĐỌC sổ ``priority_audit_log``), ``priority_academic_year`` (năm = năm học của hồ sơ) và
    ``select_open_priority_rates`` (năm học + ``effective_to IS NULL``, không lọc ngày). KHÔNG
    gọi ``freeze_priority_snapshot`` (hàm GHI) — giao dịch này chỉ đọc. Câu 21: KV không ấn định
    thủ công được TÍNH LẠI chỉ đọc (:func:`_area_recompute_mismatch`) và so với KV sẽ in."""
    from app import models
    from app.services.priority_service import (
        RATE_TABLE_AREA,
        kv_snapshot_resolved,
        priority_academic_year,
        select_open_priority_rates,
        verify_manual_override_provenance,
    )

    looked_up_levels: Dict[Tuple[int, str], Tuple[Optional[str], Optional[str]]] = {}
    session: Optional[AsyncSession] = None
    out: List[Tuple[Optional[str], Optional[str]]] = []
    try:
        for h in check_rows:
            snap = h.get("kv_snapshot")
            if isinstance(snap, str):
                snap = json.loads(snap)
            if not kv_snapshot_resolved(snap):
                out.append(("thieu_khu_vuc", None))
                continue
            if session is None:
                # Phiên ORM trên CHÍNH kết nối đang ở giao dịch chỉ đọc (không mở giao dịch
                # mới, không commit / rollback giao dịch ngoài).
                session = AsyncSession(bind=conn)
            profile = await session.get(models.AdmissionProfile, h["pid"])
            if (
                h.get("area_resolution_basis") == "manual_override"
                or snap.get("rule_applied") == "manual_override"
            ):
                ok, _reason, _ = await verify_manual_override_provenance(session, profile)
                if not ok:
                    out.append(("khu_vuc_thu_cong_khong_hieu_luc", None))
                    continue
            else:
                mismatch = await _area_recompute_mismatch(session, profile, snap)
                if mismatch is not None:
                    out.append((mismatch, None))
                    continue
            year = priority_academic_year(
                SimpleNamespace(academic_year=h.get("academic_year"), id=h.get("pid"))
            )
            kv = snap["kv_resolved"]
            lock = (year, kv)
            if lock not in looked_up_levels:
                try:
                    item = await select_open_priority_rates(
                        conn, table=RATE_TABLE_AREA, academic_year=year, codes=[kv]
                    )
                    looked_up_levels[lock] = (None, str(item[kv]))
                except PriorityRateNotConfigured:
                    looked_up_levels[lock] = ("chua_co_muc_khu_vuc", None)
                except RuntimeError:  # hơn một hàng ĐANG MỞ cùng mã, cùng năm
                    looked_up_levels[lock] = ("muc_khu_vuc_khong_nhat_quan", None)
            out.append(looked_up_levels[lock])
    finally:
        if session is not None:
            await session.close()
    return out


async def _score_add_rules(
    conn: AsyncConnection, path_ids: Sequence[Optional[int]]
) -> List[Tuple[Optional[str], Optional[str]]]:
    """Câu 22 (owner 06-11 — "theo cấu hình đường xét") + lượt H2 (công tắc đối tượng): luật cộng
    điểm của ĐƯỜNG XÉT của nguyện vọng in, từng dòng — ``(KV, đối tượng)``, mỗi phần ``cong`` /
    ``tat`` / ``khong_co_luat`` (``council_set_gate_service.LUAT_KV_*``), ``None`` khi không có đường
    xét / luật không đọc được.

    Đúng đường mã T6: nạp ``AdmissionPath`` kèm ``admission_method`` (như T6 nạp sẵn) trên phiên
    ORM của CHÍNH giao dịch chỉ đọc, ``resolve_effective_bonus_rule`` (override của đường xét, không
    thì mặc định của phương thức; JSON ``null`` qua ORM thành ``None`` ⇒ rơi về phương thức, như
    T6) rồi ``priority_service.area_bonus_enabled`` / ``object_bonus_enabled`` (hai hàm
    ``calculate_priority_bonus`` dùng). Không chép luật bằng SQL ở đây."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.admission_config.admission_path import AdmissionPath
    from app.services.admission_choice_engine_service import (
        resolve_effective_bonus_rule,
    )
    from app.services.council_set_gate_service import (
        AREA_RULE_ADD,
        AREA_RULE_NONE,
        AREA_RULE_OFF,
    )
    from app.services.priority_service import (
        area_bonus_enabled,
        object_bonus_enabled,
    )

    def _level(rule, switch) -> Optional[str]:
        try:
            enabled = switch(rule)
        # Luật không phải dict (dữ liệu lỗi) — T6 cũng hỏng ở đây ⇒ không xác định.
        except Exception:  # noqa: BLE001
            return None
        if enabled:
            return AREA_RULE_ADD
        return AREA_RULE_NONE if rule is None else AREA_RULE_OFF

    ids = sorted({p for p in path_ids if isinstance(p, int)})
    paths: Dict[int, AdmissionPath] = {}
    session = AsyncSession(bind=conn)
    try:
        if ids:
            kq = await session.execute(
                select(AdmissionPath)
                .where(AdmissionPath.id.in_(ids))
                .options(selectinload(AdmissionPath.admission_method))
            )
            paths = {p.id: p for p in kq.scalars()}
        out: List[Tuple[Optional[str], Optional[str]]] = []
        for pid in path_ids:
            p = paths.get(pid) if isinstance(pid, int) else None
            if p is None:
                out.append((None, None))
                continue
            rule = resolve_effective_bonus_rule(p)
            out.append(
                (_level(rule, area_bonus_enabled), _level(rule, object_bonus_enabled))
            )
    finally:
        await session.close()
    return out


def _cite_rows(row: Sequence[int]) -> str:
    s = ", ".join(str(x) for x in row[:_MAX_CITED_ROWS])
    return s + (" … (tổng %d dòng)" % len(row) if len(row) > _MAX_CITED_ROWS else "")


#: Mã loại lỗi của MỘT mã hồ sơ — :func:`loi_mot_ma` (MỘT nguồn luật cho ``POST /sets`` dạng mã và
#: ``POST /sets/doi-ma``). ``doi-ma`` trả thẳng các mã này (+ ``trung`` / ``khong_khop`` / ``nhieu_ho_so``).
CODE_ERROR_NOT_STRING = "khong_phai_chuoi"
CODE_ERROR_EMPTY = "rong"
CODE_ERROR_ODD_CHARACTER = "ky_tu_la"  # quá dài hoặc có ký tự nhóm C (kiểm kỹ thuật)
CODE_ERROR_BAD_FORMAT = "sai_dinh_dang"  # không phải đúng 9 / 12 chữ số ASCII
_CODE_ERROR_MESSAGES = {
    CODE_ERROR_NOT_STRING: "Dòng %d: mã hồ sơ không phải chuỗi.",
    CODE_ERROR_EMPTY: "Dòng %d: mã hồ sơ rỗng.",
    CODE_ERROR_ODD_CHARACTER: "Dòng %d: không phải mã hồ sơ (quá dài hoặc có ký tự điều khiển).",
    CODE_ERROR_BAD_FORMAT: "Dòng %d: mã hồ sơ phải gồm đúng 12 chữ số (CCCD) hoặc đúng 9 chữ số "
    "(CMND), chỉ chữ số 0-9.",
}


def single_code_error(m: object) -> Tuple[Optional[str], Optional[str]]:
    """``(mã đã bỏ khoảng trắng hai đầu | None, mã loại lỗi | None)`` của MỘT mã — theo thứ tự: không
    phải chuỗi → rỗng → quá dài / ký tự nhóm C → sai định dạng (J1 dòng 28). Không kiểm trùng (việc của
    danh sách)."""
    if not isinstance(m, str):
        return None, CODE_ERROR_NOT_STRING
    m = m.strip()
    if not m:
        return m, CODE_ERROR_EMPTY
    if len(m) > MAX_CODE_LENGTH or any(unicodedata.category(c)[0] == "C" for c in m):
        return m, CODE_ERROR_ODD_CHARACTER
    if not _RE_CODE_FORMAT.fullmatch(m):
        return m, CODE_ERROR_BAD_FORMAT
    return m, None


def normalize_codes(code: Sequence[str]) -> List[str]:
    """MỘT nguồn kiểm danh sách mã hồ sơ. Bỏ khoảng trắng hai đầu từng mã; theo thứ tự: rỗng
    / quá dài / có ký tự nhóm C (kiểm kỹ thuật) → sai định dạng (không phải đúng 9 hoặc 12
    chữ số ASCII — J1 dòng 28) → trùng ⇒ lỗi nêu số thứ tự dòng (từ 1), KHÔNG nêu giá trị.
    Luật từng mã: :func:`loi_mot_ma`.
    """
    if not isinstance(code, (list, tuple)):
        raise DataValidationError("Danh sách mã hồ sơ phải là một danh sách.")
    if not code:
        raise DataValidationError("Danh sách mã hồ sơ rỗng.")
    out: List[str] = []
    first_seen: dict = {}
    for i, m in enumerate(code, 1):
        m, error = single_code_error(m)
        if error is not None:
            raise DataValidationError(_CODE_ERROR_MESSAGES[error] % i)
        if m in first_seen:
            raise DataValidationError(
                "Dòng %d trùng mã hồ sơ với dòng %d — mỗi người một dòng." % (i, first_seen[m])
            )
        first_seen[m] = i
        out.append(m)
    return out


#: Review max PR #724 (R5): chữ thay thế ``ma_ho_so`` của dòng CCCD trống (``% pid`` ⇒ riêng từng hồ sơ). Dòng
#: ấy luôn bị cổng chặn (``thieu_ma_ho_so``) nên chữ này chỉ hiện ở bản xem trước / phép so, KHÔNG bao giờ in.
PROFILE_CODE_MISSING = "(chưa có CCCD — hồ sơ %d)"


def _to_dto(stt: int, row_no: dict) -> CandidateRowV1:
    value = {}
    for name in CANDIDATE_FIELDS:
        v = row_no.get(name)
        if not isinstance(v, str):
            raise DataValidationError(
                "Dòng %d, trường %s: không đọc được dạng chữ." % (stt, name)
            )
        value[name] = v
    try:
        return CandidateRowV1(**value)
    except PydanticValidationError as e:
        field = sorted(
            {
                str(error["loc"][0]) if error.get("loc") else "?"
                for error in e.errors(include_url=False, include_input=False)
            }
        )
        raise DataValidationError(
            "Dòng %d: dữ liệu hồ sơ không hợp lệ ở trường %s."
            % (stt, ", ".join(field))
        ) from None


def check_academic_year(academic_year: object) -> int:
    """Năm học TƯỜNG MINH của danh sách mã: CCCD chỉ duy nhất trong một năm học
    (``uq_citizen_academic_year``) ⇒ không có năm thì "mã hồ sơ" không xác định một hồ sơ.
    Không phải số nguyên (kể cả ``bool``) ⇒ ``DataValidationError``."""
    if isinstance(academic_year, bool) or not isinstance(academic_year, int):
        raise DataValidationError(
            "Thiếu năm học (academic_year) hoặc năm học không phải số nguyên — mã hồ sơ "
            "(CCCD) chỉ duy nhất trong một năm học."
        )
    return academic_year


async def read_profiles_by_code(
    engine: AsyncEngine,
    profile_codes: Sequence[str],
    *,
    academic_year: Optional[int],
    max_count: Optional[int] = None,
) -> ProfileSnapshot:
    """Đọc DTO của các hồ sơ có mã ``ma_ho_so`` (đúng thứ tự) THUỘC năm học
    ``academic_year`` trong MỘT giao dịch chỉ đọc."""
    year = check_academic_year(academic_year)
    ds = normalize_codes(profile_codes)
    limits = settings.COUNCIL_SET_MAX_PROFILES if max_count is None else max_count
    if len(ds) > limits:
        raise DataValidationError(
            "Danh sách có %d mã, vượt giới hạn kỹ thuật %d hồ sơ cho một bộ văn bản."
            % (len(ds), limits)
        )
    try:
        async with read_only_transaction(engine) as (conn, tt):
            matches = await resolve_codes(conn, ds, year)
            unmatched = [stt for stt, number, _ in matches if number == 0]
            multi = [stt for stt, number, _ in matches if number > 1]
            if unmatched or multi:
                part = []
                if unmatched:
                    part.append(
                        "dòng %s không có hồ sơ nào mang mã này trong năm học đã chọn"
                        % _cite_rows(unmatched)
                    )
                if multi:
                    part.append("dòng %s khớp NHIỀU hồ sơ cùng mã" % _cite_rows(multi))
                raise DataValidationError(
                    "Mã hồ sơ phải khớp đúng một hồ sơ: %s." % "; ".join(part)
                )
            if [stt for stt, _, _ in matches] != list(range(1, len(ds) + 1)):
                raise ServiceError("Phân giải mã hồ sơ trả sai thứ tự — không đọc.")
            pids = [pid for _, _, pid in matches]
            raw = await _read_raw(conn, pids)
    except DBAPIError:
        # Thông báo của trình điều khiển có câu SQL + tham số (danh sách mã) ⇒ không giữ.
        raise ServiceError("Lỗi CSDL khi đọc hồ sơ cho bộ văn bản.") from None
    return _build_snapshot(raw, pids, tt)


async def read_profiles_by_id(
    engine: AsyncEngine,
    pids: Sequence[int],
    *,
    academic_year: Optional[int],
) -> ProfileSnapshot:
    """Lượt I (F230 — tái dựng bản ký / so bộ với hiện tại): đọc ĐÚNG các hồ sơ ``pids`` (id lấy từ
    dòng bộ — KHÔNG phân giải lại theo CCCD, vì CCCD có thể chính là chỗ sửa) bằng CÙNG truy vấn +
    cùng giao dịch ``REPEATABLE READ READ ONLY`` của :func:`doc_ho_so_theo_ma`. Hồ sơ phải tồn tại và
    thuộc năm học ``academic_year``; dòng ``stt`` của kết quả = vị trí trong ``pids`` (1…)."""
    year = check_academic_year(academic_year)
    ds = [int(p) for p in pids]
    if not ds or len(set(ds)) != len(ds):
        raise ServiceError("Danh sách id hồ sơ rỗng hoặc trùng — không đọc.")
    try:
        async with read_only_transaction(engine) as (conn, tt):
            present = {
                r[0]: r[1]
                for r in (
                    await conn.execute(
                        text(
                            "SELECT id, academic_year FROM admission_profile "
                            "WHERE id = ANY(CAST(:ids AS integer[]))"
                        ),
                        {"ids": ds},
                    )
                ).all()
            }
            sai = [i for i, p in enumerate(ds, 1) if present.get(p) != year]
            if sai:
                raise DataValidationError(
                    "Dòng %s: hồ sơ không còn hoặc không thuộc năm học của bộ — không đọc."
                    % _cite_rows(sai)
                )
            raw = await _read_raw(conn, ds)
    except DBAPIError:
        raise ServiceError("Lỗi CSDL khi đọc hồ sơ cho bộ văn bản.") from None
    return _build_snapshot(raw, ds, tt)


#: Trần ký tự của từ khoá tìm hồ sơ (đặc tả 3.11).
MAX_KEYWORD_LENGTH = 100


def _valid_statuses() -> frozenset:
    from app.services.admission_state_machine import AdmissionStatus

    return frozenset(s.value for s in AdmissionStatus)


async def search_profiles(
    db: AsyncSession,
    *,
    current_user: object,
    academic_year: object,
    keyword: Optional[str],
    major_ids: Optional[Sequence[int]],
    status: Optional[Sequence[str]],
    page: int,
    page_size: int,
) -> Dict[str, object]:
    """Vòng giao diện (đặc tả bản 2 mục 3.11 — ``POST /sets/tim-ho-so``): tìm hồ sơ cho trang chọn bằng ĐÚNG
    ``admission_service.get_profiles(..., lean=True)`` — cùng service / repository / phạm vi đơn vị (IDOR)
    như ``GET /api/admissions``; KHÔNG có truy vấn tìm thứ hai; các bộ lọc điều phối (``unit_id``,
    ``assigned_*``) không mở. Từ khoá KHÔNG bao giờ vào log (router và service không log nó).

    Mỗi dòng chỉ chuyển dạng từ hồ sơ của trang: tên ngành = ``program_name`` (CÙNG cột "Ngành" của màn Hồ
    sơ tuyển sinh — ``lead.offering``); trình độ = ``major_program.degree_level`` của chính ngành ấy; đường
    xét KHÔNG có ở danh sách dạng nhẹ ⇒ ``None``. Ngành / đường xét / điểm IN chính xác chỉ ở ``kiem-truoc``
    (nguồn của bộ dựng)."""
    from app.services import admission_service

    year = check_academic_year(academic_year)
    tk = keyword.strip() if isinstance(keyword, str) else None
    if tk is not None and len(tk) > MAX_KEYWORD_LENGTH:
        raise DataValidationError(
            "Từ khoá tìm quá dài (tối đa %d ký tự)." % MAX_KEYWORD_LENGTH
        )
    tt = list(status) if status else None
    if tt is not None and not set(tt) <= _valid_statuses():
        raise DataValidationError("Bộ lọc trạng thái có giá trị không hợp lệ.")
    profiles, total = await admission_service.get_profiles(
        db=db,
        skip=(page - 1) * page_size,
        limit=page_size,
        current_user=current_user,
        search=tk or None,
        statuses=tt,
        major_ids=list(major_ids) if major_ids else None,
        academic_year=year,
        lean=True,
    )
    row = []
    for p in profiles:
        lead = p.lead
        ct = lead.offering.program if lead is not None and lead.offering else None
        row.append(
            {
                "profile_id": p.id,
                "ho_ten": (p.full_name or "").strip(),
                "cccd": p.citizen_id or "",
                "nganh_nhan": getattr(p, "program_name", None) or "",
                "trinh_do": ((ct.degree_level or "") if ct is not None else "").strip(),
                "duong_xet_nhan": None,
                "trang_thai": p.status,
                "academic_year": p.academic_year,
            }
        )
    return {"tong": total, "page": page, "page_size": page_size, "dong": row}


#: Mã lỗi riêng của ``doi-ma`` (ngoài các mã của :func:`loi_mot_ma`).
CODE_ERROR_DUPLICATE = "trung"
CODE_ERROR_NO_MATCH = "khong_khop"  # không có hồ sơ của năm học / ngoài phạm vi đơn vị (không phân biệt)
CODE_ERROR_MULTIPLE_PROFILES = "nhieu_ho_so"


async def codes_to_ids(
    engine: AsyncEngine,
    profile_codes: Sequence[str],
    *,
    academic_year: Optional[int],
    tat_ca: bool,
    chi_don_vi: Optional[int],
) -> Tuple[List[int], List[Dict[str, object]]]:
    """Vòng giao diện (đặc tả 3.2 — ``POST /sets/doi-ma``, cách phụ "dán mã"): đổi danh sách mã (CCCD) thành
    id hồ sơ. KHÔNG dừng ở dòng lỗi đầu tiên: trả ``(id theo thứ tự các dòng khớp, [{dong, ly_do}])`` —
    chỉ SỐ DÒNG + mã lý do, không giá trị. Luật từng mã = :func:`loi_mot_ma` (cùng nguồn ``POST /sets``);
    trùng ⇒ dòng sau mang ``trung``. Phân giải bằng CÙNG ``resolve_codes`` của ``POST /sets``, trong giao
    dịch chỉ đọc; hồ sơ ngoài phạm vi đơn vị của người gọi ⇒ ``khong_khop`` (như không có — không lộ tồn
    tại). Không ghi gì."""
    year = check_academic_year(academic_year)
    if not tat_ca and chi_don_vi is None:
        raise ServiceError("Phạm vi đọc hồ sơ không xác định — không đọc.")
    if not isinstance(profile_codes, (list, tuple)) or not profile_codes:
        raise DataValidationError("Danh sách mã hồ sơ rỗng.")
    if len(profile_codes) > settings.COUNCIL_SET_MAX_PROFILES:
        raise DataValidationError(
            "Danh sách có %d dòng, vượt giới hạn kỹ thuật %d hồ sơ cho một bộ văn bản."
            % (len(profile_codes), settings.COUNCIL_SET_MAX_PROFILES)
        )
    error_rows: List[Dict[str, object]] = []
    valid: List[Tuple[int, str]] = []
    first_seen: Dict[str, int] = {}
    for i, m in enumerate(profile_codes, 1):
        s, error = single_code_error(m)
        if error is not None:
            error_rows.append({"dong": i, "ly_do": error})
        elif s in first_seen:
            error_rows.append({"dong": i, "ly_do": CODE_ERROR_DUPLICATE})
        else:
            first_seen[s] = i
            valid.append((i, s))
    pids: List[int] = []
    if valid:
        try:
            async with read_only_transaction(engine) as (conn, _tt):
                matches = await resolve_codes(conn, [s for _, s in valid], year)
                if [stt for stt, _, _ in matches] != list(range(1, len(valid) + 1)):
                    raise ServiceError("Phân giải mã hồ sơ trả sai thứ tự — không đọc.")
                pv = await read_scope_by_ids(
                    conn, [pid for _, number, pid in matches if number == 1]
                )
        except DBAPIError:
            raise ServiceError("Lỗi CSDL khi đọc hồ sơ cho bộ văn bản.") from None
        for (i, _), (_, number, pid) in zip(valid, matches):
            if number > 1:
                error_rows.append({"dong": i, "ly_do": CODE_ERROR_MULTIPLE_PROFILES})
            elif (
                number == 0
                or pid not in pv
                or not (tat_ca or pv[pid][1] == chi_don_vi)
            ):
                error_rows.append({"dong": i, "ly_do": CODE_ERROR_NO_MATCH})
            else:
                pids.append(pid)
    return pids, sorted(error_rows, key=lambda d: d["dong"])


async def read_profiles_for_preview(
    engine: AsyncEngine,
    pids: Sequence[int],
    *,
    academic_year: Optional[int],
    tat_ca: bool,
    chi_don_vi: Optional[int],
) -> Tuple[Optional[ProfileSnapshot], List[int]]:
    """Vòng giao diện (đặc tả 3.1 — ``POST /sets/kiem-truoc``): CÙNG giao dịch ``REPEATABLE READ READ
    ONLY`` + cùng phần đọc (:func:`_read_raw` / :func:`_build_snapshot`) với :func:`read_profiles_by_id`, thêm
    MỘT bước lọc trong chính giao dịch ấy: id không có / khác năm học / ngoài phạm vi đơn vị của người gọi
    (``lead.unit_id`` — đúng cột của ``SQL_PRINT_FIGURES``) ⇒ VỊ TRÍ (từ 1) vào danh sách thứ hai, không phân biệt
    ba ca (không lộ hồ sơ có tồn tại). Trả ``(ảnh chụp của các id còn lại theo thứ tự đầu vào | None nếu
    không còn id nào, vị trí bị loại)``. Phạm vi do ``deps.py`` quyết; "không tất cả mà không có đơn vị" ⇒
    ``ServiceError`` (fail-closed)."""
    year = check_academic_year(academic_year)
    if not tat_ca and chi_don_vi is None:
        raise ServiceError("Phạm vi đọc hồ sơ không xác định — không đọc.")
    ds = [int(p) for p in pids]
    if not ds or len(set(ds)) != len(ds):
        raise ServiceError("Danh sách id hồ sơ rỗng hoặc trùng — không đọc.")
    try:
        async with read_only_transaction(engine) as (conn, tt):
            present = await read_scope_by_ids(conn, ds)
            kind = [
                i
                for i, p in enumerate(ds, 1)
                if p not in present
                or present[p][0] != year
                or not (tat_ca or present[p][1] == chi_don_vi)
            ]
            excluded = set(kind)
            kept = [p for i, p in enumerate(ds, 1) if i not in excluded]
            if not kept:
                return None, kind
            raw = await _read_raw(conn, kept)
    except DBAPIError:
        raise ServiceError("Lỗi CSDL khi đọc hồ sơ cho bộ văn bản.") from None
    return _build_snapshot(raw, kept, tt), kind


async def _read_raw(conn: AsyncConnection, pids: Sequence[int]):
    """Phần đọc dùng chung (trong giao dịch chỉ đọc đã mở): số liệu in + dữ liệu kiểm + khu vực +
    luật cộng điểm."""
    row_no = await read_print_figures(conn, pids)
    # Cổng dựng bộ (lượt G): dữ liệu kiểm đọc trong CÙNG giao dịch chỉ đọc, theo đúng
    # nguyện vọng mà truy vấn số liệu in (cột phụ ``nv_in_id``).
    nv_in = {h["stt"]: h.get("nv_in_id") for h in row_no}
    check_rows = await read_check_source(
        conn, pids, [nv_in.get(i) for i in range(1, len(pids) + 1)]
    )
    area = await _resolve_area(conn, check_rows)
    # Câu 22 + lượt H2: luật cộng điểm (KV, đối tượng) của đường xét của nguyện vọng in —
    # cùng giao dịch.
    rule = await _score_add_rules(conn, [h.get("nv_in_path_id") for h in check_rows])
    return row_no, check_rows, area, rule


def _build_snapshot(raw, pids, tt) -> ProfileSnapshot:
    row_no, check_rows, area, rule = raw
    row_count = len(pids)
    # Mỗi hồ sơ đúng MỘT hàng: bảng tham chiếu (địa giới, khu vực) khớp nhiều hàng hiện
    # hành thì bộ xuất in TRÙNG người ⇒ dừng, không tự chọn một hàng.
    counts: dict = {}
    for h in row_no:
        counts[h["stt"]] = counts.get(h["stt"], 0) + 1
    duplicates = sorted(stt for stt, n in counts.items() if n > 1)
    if duplicates:
        raise DataValidationError(
            "Dòng %s: dữ liệu tham chiếu (địa giới / khu vực) khớp nhiều hàng hiện hành "
            "— không dựng." % _cite_rows(duplicates)
        )
    if sorted(counts) != list(range(1, row_count + 1)):
        raise ServiceError("Đọc số liệu hồ sơ thiếu hàng — không dựng.")
    row_no.sort(key=lambda h: h["stt"])
    if (
        [h["stt"] for h in check_rows] != list(range(1, row_count + 1))
        or len(area) != row_count
        or len(rule) != row_count
        or [h["pid"] for h in row_no] != list(pids)
        or [h["pid"] for h in check_rows] != list(pids)
    ):
        raise ServiceError(
            "Đọc dữ liệu kiểm hồ sơ sai thứ tự / thiếu hàng — không dựng."
        )
    figures = {h["stt"]: h for h in row_no}
    # Review max PR #724 (R5): CCCD trống (``COALESCE(citizen_id, '')`` — hồ sơ chưa nhập CCCD) KHÔNG còn làm
    # hỏng cả lô ở ``_to_dto`` (``ma_ho_so`` min_length=1): dòng ấy mang cờ ⇒ cổng chặn ``thieu_ma_ho_so``
    # (POST /sets từ chối như mọi dòng bị chặn — không bao giờ in); DTO của dòng mang chữ thay thế RIÊNG từng
    # hồ sơ (không trùng nhau, để phép kiểm trùng mã không nổ thay cho lý do thật).
    missing_code = {
        h["stt"]
        for h in row_no
        if isinstance(h.get("ma_ho_so"), str) and not h["ma_ho_so"].strip()
    }
    check = tuple(
        CheckData(
            stt=k["stt"],
            status=k["status"],
            uses_choice_engine=k["uses_choice_engine"],
            so_nv=k["so_nv"],
            nv1_id=k["nv1_id"],
            nv_in_id=figures[k["stt"]].get("nv_in_id"),
            so_nv_trung=k["so_nv_trung"],
            nv_trung_id=k["nv_trung_id"],
            hp_co=bool(figures[k["stt"]].get("hp_co")),
            hp_nganh_id=figures[k["stt"]].get("hp_nganh_id"),
            nv_in_nganh_id=k["nv_in_nganh_id"],
            nv_in_path_id=k["nv_in_path_id"],
            nv_in_sg_id=k["nv_in_sg_id"],
            lg_nganh_id=k["lg_nganh_id"],
            lg_path_id=k["lg_path_id"],
            lg_sg_id=k["lg_sg_id"],
            diem_ca_hai_khac=k["diem_ca_hai_khac"],
            diem_chi_nv=k["diem_chi_nv"],
            diem_chi_hs=k["diem_chi_hs"],
            kv_ly_do=kv[0],
            kv_muc=kv[1],
            luat_kv=lk[0],
            luat_ut=lk[1],
            # Lượt I (F230): khoá đếm của NV in + tình trạng Quyết định (biểu thức một nguồn).
            nv_in_ai_id=k["nv_in_ai_id"],
            nv_in_offering_id=k["nv_in_offering_id"],
            qd_hieu_luc_id=tq.qd_hieu_luc_id,
            qd_chuoi_id=tq.qd_chuoi_id,
            cho_quyet_id=tq.cho_quyet_id,
            dau_appsheet=tq.dau_appsheet,
            thieu_ma_ho_so=k["stt"] in missing_code,
        )
        for k, kv, lk, tq in zip(
            check_rows, area, rule, (from_row(k) for k in check_rows)
        )
    )
    return ProfileSnapshot(
        rows=tuple(
            _to_dto(
                h["stt"],
                {**h, "ma_ho_so": PROFILE_CODE_MISSING % h["pid"]} if h["stt"] in missing_code else h,
            )
            for h in row_no
        ),
        don_vi=tuple(h["unit_id"] for h in row_no),
        giao_dich=tt,
        kiem=check,
        pids=tuple(h["pid"] for h in row_no),
    )
