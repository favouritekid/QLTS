# app/services/sms_contact_service.py
"""
Business logic SMS Marketing contact domain (PR-2).

Bao gồm: CRUD contact group/contact, membership N-N, consent-event ledger
append-only + projection latest-state dưới row lock, import mobile-only
dedupe global (counts thỏa bất biến §4.4).

Tuân thủ kiến trúc QLTS: KHÔNG import fastapi; raise domain exception (không
HTTPException); chỉ `flush` (router `commit`). SMS marketing KHÔNG qua
dispatch() (§11.8) nên service trả thẳng result, không (result, callback).
"""
import asyncio
import io
import re
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.sms import (
    SmsContact,
    SmsContactGroup,
    SmsContactGroupMember,
    SmsMarketingConsentEvent,
)
from app.repositories.sms_contact_repository import SmsContactRepository
from app.schemas import sms as sms_schemas
from app.utils.exceptions import (
    ConflictError,
    DuplicateResourceError,
    FileSizeError,
    FileTypeError,
    ResourceNotFoundError,
    ValidationError,
)
from app.utils.phone_helpers import (
    is_vietnam_mobile,
    normalize_vietnam_phone,
    normalize_vn_mobile,
    to_zalo_phone,
)
from app.utils.text_helpers import strip_diacritics

# Import giới hạn an toàn
MAX_IMPORT_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
MAX_IMPORT_ROWS = 50000

# Nhận diện cột theo CỤM CON trên header đã bỏ dấu + gộp "_"
# (`_normalize_header`), KHÔNG so bằng danh sách chuỗi cố định: header thật
# luôn có đuôi ("Họ và tên học sinh", "SĐT phụ huynh", "Số điện thoại (Zalo)")
# nên liệt kê tổ hợp là trò đuổi bắt không hồi kết.
#
# ⚠️ TUYỆT ĐỐI KHÔNG thêm "dt": trong danh sách trường "DT" gần như luôn là
# **Dân tộc**, và sau bước bỏ dấu thì "ĐT" (điện thoại) cũng thành "dt" —
# không phân biệt được. Nhận nhầm còn tệ hơn báo thiếu cột: cả file import
# im lặng 0 dòng vì "Kinh"/"Tày" không phải số di động.
_NAME_PHRASES = ("full_name", "fullname", "ho_va_ten", "hovaten", "ho_ten", "hoten")
_PHONE_PHRASES = (
    "so_dien_thoai", "sodienthoai", "dien_thoai", "sdt", "so_dt",
    "phone", "mobile", "so_may",
)
_NOTE_PHRASES = ("ghi_chu", "ghichu", "note", "chu_thich")
# Chỉ khớp CHÍNH XÁC (không phải cụm con) — "ten" là cụm con của "ten_truong",
# "ten_lop", "ten_nganh"… nên dùng làm cụm con sẽ gán bừa.
_NAME_EXACT_FALLBACK = {"ten", "name"}
# Cột "họ" đứng riêng ⇒ file tách họ/tên, ghép sai sẽ mất họ đệm (xem
# `_resolve_columns`).
_SURNAME_EXACT = {"ho", "ho_dem", "hodem", "ho_va_dem"}


def _slugify(name: str) -> str:
    """Sinh slug ASCII (bỏ dấu tiếng Việt) cho group code."""
    s = strip_diacritics(name).lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:50] or "group"


def _normalize_header(col: str) -> str:
    """Chuẩn hóa 1 header về khóa so khớp: bỏ dấu + lower + gộp mọi ký tự
    không phải chữ/số thành '_' (nuốt luôn BOM nếu file CSV có).

    ⚠ Bước bỏ dấu là BẮT BUỘC: thiếu nó thì cụm viết cho tiếng Việt không
    bao giờ khớp header thật ("Họ tên" → "họ_tên" ≠ "ho_ten"), khiến file
    hợp lệ bị từ chối 400 "thiếu cột bắt buộc".
    """
    s = strip_diacritics(str(col or "")).lower().strip()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _resolve_columns(columns: List[str]) -> dict:
    """Map cột thực → cột chuẩn. Trả {chuẩn: thực}.

    Nhiều cột cùng khớp (vd "SĐT học sinh" + "SĐT phụ huynh") → lấy cột đứng
    TRƯỚC trong file, theo quy ước cột chính nằm bên trái.
    """
    found: dict = {}
    # setdefault: 2 header khác nhau có thể chuẩn hóa về CÙNG khóa (vd "Họ tên"
    # và "Ho ten") → giữ cột xuất hiện TRƯỚC thay vì để cột sau ghi đè.
    norm: dict = {}
    for c in columns:
        key = _normalize_header(c)
        if key:
            norm.setdefault(key, c)

    for canonical, phrases in (
        ("full_name", _NAME_PHRASES),
        ("phone", _PHONE_PHRASES),
        ("note", _NOTE_PHRASES),
    ):
        for key, original in norm.items():
            if any(p in key for p in phrases):
                found[canonical] = original
                break

    if "full_name" not in found:
        weak = next(
            (o for k, o in norm.items() if k in _NAME_EXACT_FALLBACK), None
        )
        if weak is not None:
            surname = next(
                (o for k, o in norm.items() if k in _SURNAME_EXACT), None
            )
            # File tách "Họ đệm" + "Tên": nhận cột "Tên" làm full_name sẽ lưu
            # tên cụt ("An", "Bình") mà KHÔNG báo lỗi gì — hỏng dữ liệu âm thầm
            # rồi đem cá nhân hoá nội dung SMS. Thà chặn to tiếng.
            if surname is not None:
                raise ValidationError(
                    detail=(
                        f"File tách cột họ ('{surname}') và tên ('{weak}') — "
                        "gộp thành MỘT cột họ tên đầy đủ (vd 'Họ và tên') "
                        "rồi import lại."
                    )
                )
            found["full_name"] = weak
    return found


def _read_csv_bytes(content: bytes):
    """Đọc CSV chịu được thực tế Excel tiếng Việt.

    Hai cái bẫy khiến file "đúng" vẫn 400:
    - **Dấu phân cách**: Excel bản vi-VN dùng dấu chấm phẩy làm list separator
      nên "CSV (Comma delimited)" lại ghi ra `full_name;phone;note`. Mặc định
      `read_csv` tách bằng dấu phẩy → cả dòng thành MỘT cột → "thiếu cột".
      `sep=None` + engine python để pandas tự dò.
    - **Bảng mã**: Excel có thể ghi ANSI (cp1258) hoặc "Unicode Text" (UTF-16)
      thay vì UTF-8.
    """
    import pandas as pd

    # UTF-16 phải thử TRƯỚC: `latin1` giải mã được mọi chuỗi byte nên nó sẽ
    # nuốt file UTF-16 thành mojibake, rồi báo "thiếu cột" — sai nguyên nhân,
    # người dùng không đời nào đoán ra là do bảng mã.
    encodings = ("utf-8-sig", "cp1258", "latin1")
    if content[:2] in (b"\xff\xfe", b"\xfe\xff"):
        encodings = ("utf-16",) + encodings

    last_error: Exception = ValidationError(detail="File CSV không đọc được")
    for encoding in encodings:
        try:
            return pd.read_csv(
                io.BytesIO(content),
                dtype=str,
                sep=None,
                engine="python",
                encoding=encoding,
            )
        except UnicodeDecodeError as exc:
            last_error = exc
            continue
        except pd.errors.ParserError as exc:
            # Sniffer bó tay (thường là file đúng 1 cột) → ép dấu phẩy.
            last_error = exc
            try:
                return pd.read_csv(
                    io.BytesIO(content), dtype=str, encoding=encoding
                )
            except UnicodeDecodeError:
                continue
    raise last_error


def _clean_phone_cell(phone: str) -> str:
    """Dọn 2 biến dạng do Excel gây ra trước khi validate số.

    1. Lớp bọc chống-ép-kiểu `="0912345678"` (file mẫu của ta dùng đúng cách
       này; Excel hiển thị thành chữ nhưng nếu upload thẳng thì tới đây vẫn
       là chuỗi thô).
    2. Số 0 đầu bị ăn mất khi Excel ép cột SĐT thành số ("0912345678" →
       "912345678") — không vá thì TOÀN BỘ file bị loại "không phải di động
       VN". Chỉ đụng đúng ca 9 chữ số mở đầu bằng đầu số di động VN (3/5/7/
       8/9); số 10 chữ số hay dạng +84 không bị ảnh hưởng.

    Cố ý làm ở tầng import, KHÔNG nới `normalize_vn_mobile` (helper dùng chung
    toàn hệ thống — nới ở đó thì nhập tay/API cũng nhận bừa số thiếu số 0).
    """
    cleaned = phone.strip()
    m = re.fullmatch(r'="?([^"]*)"?', cleaned)
    if m:
        cleaned = m.group(1).strip()
    if re.fullmatch(r"[35789]\d{8}", cleaned):
        return "0" + cleaned
    return cleaned


def _reject_null(patch: dict, fields) -> None:
    """Raise ValidationError nếu PATCH gửi explicit null cho cột NOT NULL.

    `exclude_unset=True` GIỮ explicit null → `setattr(obj, f, None)` →
    IntegrityError 500. Chặn sớm thành 400 cho rõ nghĩa.
    """
    for f in fields:
        if f in patch and patch[f] is None:
            raise ValidationError(detail=f"Trường '{f}' không được null")


class SmsContactService:
    """Service contact group/contact/membership/consent/import."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = SmsContactRepository(db)

    # ===============================================================
    # Contact group
    # ===============================================================
    async def create_group(
        self, data: sms_schemas.SmsContactGroupCreate, user
    ) -> SmsContactGroup:
        code = (data.code or _slugify(data.name)).strip()
        existing = await self.repo.get_group_by_code(code)
        if existing is not None:
            raise DuplicateResourceError(
                detail=f"Mã nhóm '{code}' đã tồn tại"
            )
        try:
            group = await self.repo.create_group(
                {
                    "name": data.name.strip(),
                    "code": code,
                    "group_type": data.group_type,
                    "description": data.description,
                    "created_by_id": getattr(user, "id", None),
                }
            )
        except IntegrityError:  # race UNIQUE(code) → 409 thay vì 500
            raise DuplicateResourceError(
                detail=f"Mã nhóm '{code}' đã tồn tại"
            )
        group.member_count = 0
        return group

    async def get_group(self, group_id: int) -> SmsContactGroup:
        group = await self.repo.get_group(group_id)
        if group is None:
            raise ResourceNotFoundError(detail="Không tìm thấy nhóm liên hệ")
        counts = await self.repo.count_members_by_group([group_id])
        group.member_count = counts.get(group_id, 0)
        return group

    async def list_groups(
        self,
        skip: int,
        limit: int,
        group_type: Optional[str] = None,
        is_active: Optional[bool] = None,
        search: Optional[str] = None,
    ) -> Tuple[int, List[SmsContactGroup]]:
        total, items = await self.repo.list_groups(
            skip=skip,
            limit=limit,
            group_type=group_type,
            is_active=is_active,
            search=search,
        )
        counts = await self.repo.count_members_by_group(
            [g.id for g in items]
        )
        for g in items:
            g.member_count = counts.get(g.id, 0)
        return total, items

    async def update_group(
        self, group_id: int, data: sms_schemas.SmsContactGroupUpdate
    ) -> SmsContactGroup:
        group = await self.repo.get_group(group_id)
        if group is None:
            raise ResourceNotFoundError(detail="Không tìm thấy nhóm liên hệ")
        patch = data.model_dump(exclude_unset=True)
        # name đã strip ở schema; chặn explicit null cho cột NOT NULL.
        _reject_null(patch, ("name", "group_type", "is_active"))
        for key, value in patch.items():
            setattr(group, key, value)
        await self.db.flush()
        # onupdate=func.now() expire updated_at sau UPDATE → refresh để
        # load lại trước khi serialize (tránh lazy-load IO ngoài greenlet).
        await self.db.refresh(group)
        counts = await self.repo.count_members_by_group([group_id])
        group.member_count = counts.get(group_id, 0)
        return group

    # ===============================================================
    # Contact
    # ===============================================================
    def _normalize_mobile(self, phone_raw: str) -> Tuple[str, str]:
        """Normalize + ép mobile-only. Trả (normalized, international).
        Raise ValidationError nếu không phải di động VN hợp lệ."""
        result = normalize_vn_mobile(phone_raw)
        if result is None:
            raise ValidationError(
                detail="Số điện thoại không hợp lệ (chỉ nhận di động VN)"
            )
        return result

    async def create_contact(
        self, data: sms_schemas.SmsContactCreate, user
    ) -> SmsContact:
        normalized, international = self._normalize_mobile(data.phone)
        existing = await self.repo.get_contact_by_phone(normalized)
        if existing is not None:
            raise DuplicateResourceError(
                detail="Số điện thoại đã tồn tại trong danh bạ"
            )
        try:
            return await self.repo.create_contact(
                {
                    "full_name": data.full_name.strip(),
                    "phone_raw": data.phone.strip(),
                    "phone_normalized": normalized,
                    "phone_international": international,
                    "note": data.note,
                    "source_label": data.source_label,
                    "created_by_id": getattr(user, "id", None),
                }
            )
        except IntegrityError:
            # Race TOCTOU: 2 request cùng vượt pre-check → UNIQUE bắt → 409.
            raise DuplicateResourceError(
                detail="Số điện thoại đã tồn tại trong danh bạ"
            )

    async def get_contact(self, contact_id: int) -> SmsContact:
        contact = await self.repo.get_contact(contact_id)
        if contact is None:
            raise ResourceNotFoundError(detail="Không tìm thấy liên hệ")
        return contact

    async def list_contacts(
        self,
        skip: int,
        limit: int,
        search: Optional[str] = None,
        consent_status: Optional[str] = None,
        group_id: Optional[int] = None,
    ) -> Tuple[int, List[SmsContact]]:
        return await self.repo.list_contacts(
            skip=skip,
            limit=limit,
            search=search,
            consent_status=consent_status,
            group_id=group_id,
        )

    async def update_contact(
        self, contact_id: int, data: sms_schemas.SmsContactUpdate
    ) -> SmsContact:
        contact = await self.get_contact(contact_id)
        patch = data.model_dump(exclude_unset=True)
        # full_name đã strip ở schema; chặn explicit null (cột NOT NULL).
        _reject_null(patch, ("full_name",))
        for key, value in patch.items():
            setattr(contact, key, value)
        await self.db.flush()
        # onupdate=func.now() expire updated_at → refresh trước serialize.
        await self.db.refresh(contact)
        return contact

    # ===============================================================
    # Membership
    # ===============================================================
    async def add_contact_to_group(
        self, contact_id: int, group_id: int, note: Optional[str], user
    ) -> SmsContactGroupMember:
        # IDOR/existence: cả contact lẫn group phải tồn tại
        if await self.repo.get_contact(contact_id) is None:
            raise ResourceNotFoundError(detail="Không tìm thấy liên hệ")
        if await self.repo.get_group(group_id) is None:
            raise ResourceNotFoundError(detail="Không tìm thấy nhóm liên hệ")
        existing = await self.repo.get_membership(group_id, contact_id)
        if existing is not None:
            raise DuplicateResourceError(
                detail="Liên hệ đã thuộc nhóm này"
            )
        try:
            return await self.repo.create_membership(
                {
                    "group_id": group_id,
                    "contact_id": contact_id,
                    "note": note,
                    "added_by_id": getattr(user, "id", None),
                }
            )
        except IntegrityError:  # race UNIQUE(group,contact) → 409
            raise DuplicateResourceError(
                detail="Liên hệ đã thuộc nhóm này"
            )

    async def remove_contact_from_group(
        self, contact_id: int, group_id: int
    ) -> None:
        member = await self.repo.get_membership(group_id, contact_id)
        if member is None:
            raise ResourceNotFoundError(
                detail="Liên hệ không thuộc nhóm này"
            )
        await self.repo.delete_membership(member)

    # ===============================================================
    # Consent-event ledger (append-only) + projection latest-state
    # ===============================================================
    @staticmethod
    def _apply_consent_projection(
        contact: SmsContact, event: SmsMarketingConsentEvent
    ) -> None:
        """Đặt projection latest-state trên contact theo 1 event đã chọn."""
        if event.event_type == "granted":
            contact.marketing_consent_status = "granted"
            contact.marketing_consented_at = event.occurred_at
            contact.marketing_consent_basis = event.basis
            contact.marketing_consent_proof_ref = event.proof_reference
            contact.consent_disclosure_version = event.disclosure_version
        else:  # revoked
            contact.marketing_consent_status = "revoked"

    async def _reproject_from_latest(self, contact: SmsContact) -> None:
        """Chiếu projection theo event "mới nhất" của contact.

        Fail-closed (§4.12): event occurred_at CŨ KHÔNG override trạng thái
        mới hơn; khi cùng occurred_at thì REVOKE thắng (repo tie-break).
        Gọi sau khi đã append event (event đã flush nên query thấy).
        """
        event = await self.repo.get_latest_consent_event(contact.id)
        if event is not None:
            self._apply_consent_projection(contact, event)

    async def append_consent_event(
        self, contact_id: int, data: sms_schemas.SmsConsentEventCreate, user
    ) -> SmsMarketingConsentEvent:
        # Row lock chặn race 2 event ghi projection lẫn nhau (§13).
        contact = await self.repo.get_contact_for_update(contact_id)
        if contact is None:
            raise ResourceNotFoundError(detail="Không tìm thấy liên hệ")

        event = await self.repo.create_consent_event(
            {
                "contact_id": contact.id,
                "phone_normalized_snapshot": contact.phone_normalized,
                "event_type": data.event_type,
                "basis": data.basis,
                "revoke_source": data.revoke_source,
                "disclosure_version": data.disclosure_version,
                "proof_reference": data.proof_reference,
                "occurred_at": data.occurred_at,
                "recorded_by_id": getattr(user, "id", None),
                "metadata_json": data.metadata_json,
            }
        )
        # Projection latest-state theo occurred_at (đang giữ lock) — KHÔNG
        # set mù theo event vừa ghi (event cũ không override trạng thái mới).
        await self._reproject_from_latest(contact)
        await self.db.flush()
        return event

    async def list_consent_events(
        self, contact_id: int, skip: int, limit: int
    ) -> Tuple[int, List[SmsMarketingConsentEvent]]:
        # Đảm bảo contact tồn tại (404 nếu không)
        await self.get_contact(contact_id)
        return await self.repo.list_consent_events(
            contact_id, skip=skip, limit=limit
        )

    # ===============================================================
    # Import contacts vào nhóm (mobile-only, dedupe global)
    # ===============================================================
    def _validate_consent_evidence(
        self,
        consent_basis: Optional[str],
        consent_disclosure_version: Optional[str],
        consent_proof_ref: Optional[str],
        consent_obtained_at: Optional[datetime],
    ) -> bool:
        """Hợp lệ hóa bằng chứng consent cấp-lô. Trả True nếu ĐỦ cả 4 →
        áp granted cho mọi contact trong lô (mới + cũ) qua ledger +
        reproject. Nếu CÓ một phần nhưng thiếu → 400 (tránh granted nửa
        vời). Không có gì → False (contact giữ trạng thái hiện tại)."""
        provided = [
            bool(consent_basis),
            bool((consent_disclosure_version or "").strip()),
            bool((consent_proof_ref or "").strip()),
            consent_obtained_at is not None,
        ]
        if not any(provided):
            return False
        if not all(provided):
            raise ValidationError(
                detail="Bằng chứng consent thiếu: cần đủ basis + "
                "disclosure_version + proof_reference + obtained_at"
            )
        valid_basis = {
            "explicit_form", "signed_form", "recorded_call", "imported_proof"
        }
        if consent_basis not in valid_basis:
            raise ValidationError(detail="consent_basis không hợp lệ")
        try:
            sms_schemas.validate_consent_datetime(
                consent_obtained_at, label="consent_obtained_at"
            )
        except ValueError as exc:
            raise ValidationError(detail=str(exc))
        return True

    def _parse_rows(
        self, file_content: bytes, filename: str
    ) -> List[dict]:
        """Đọc CSV/XLSX → list {full_name, phone, note} (giữ số 0 đầu)."""
        import pandas as pd

        if not file_content:
            raise ValidationError(detail="File rỗng")
        if len(file_content) > MAX_IMPORT_FILE_SIZE:
            raise FileSizeError(
                detail=f"File quá lớn (> {MAX_IMPORT_FILE_SIZE // (1024*1024)} MB)"
            )
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        try:
            if ext == "csv":
                df = _read_csv_bytes(file_content)
            elif ext == "xlsx":
                df = pd.read_excel(
                    io.BytesIO(file_content), engine="openpyxl", dtype=str
                )
            else:
                raise FileTypeError(detail="Chỉ nhận file .csv hoặc .xlsx")
        except (FileTypeError, FileSizeError, ValidationError):
            raise
        except Exception as exc:  # noqa: BLE001 — bao lỗi parse thành 400
            raise ValidationError(detail=f"Không đọc được file: {exc}")

        if len(df) > MAX_IMPORT_ROWS:
            raise ValidationError(
                detail=f"File có {len(df)} dòng, tối đa {MAX_IMPORT_ROWS}"
            )
        # dtype=str để ô trống thành NaN — ép về "" để tránh str(NaN)="nan".
        df = df.fillna("")
        colmap = _resolve_columns(list(df.columns))
        if "full_name" not in colmap or "phone" not in colmap:
            raise ValidationError(
                detail="File thiếu cột bắt buộc 'full_name' và 'phone'"
            )
        rows = []
        for _, row in df.iterrows():
            rows.append(
                {
                    "full_name": str(
                        row.get(colmap["full_name"]) or ""
                    ).strip(),
                    "phone": _clean_phone_cell(
                        str(row.get(colmap["phone"]) or "")
                    ),
                    "note": (
                        str(row.get(colmap["note"]) or "").strip()
                        if "note" in colmap
                        else None
                    ),
                }
            )
        return rows

    async def import_contacts(
        self,
        group_id: int,
        file_content: bytes,
        filename: str,
        user,
        source_label: Optional[str] = None,
        consent_basis: Optional[str] = None,
        consent_disclosure_version: Optional[str] = None,
        consent_proof_ref: Optional[str] = None,
        consent_obtained_at: Optional[datetime] = None,
        file_sha256: Optional[str] = None,
    ) -> sms_schemas.SmsImportResult:
        group = await self.repo.get_group(group_id)
        if group is None:
            raise ResourceNotFoundError(detail="Không tìm thấy nhóm liên hệ")
        if source_label and len(source_label) > 255:  # cột String(255)
            raise ValidationError(detail="source_label quá dài (>255 ký tự)")
        if consent_disclosure_version and len(consent_disclosure_version) > 50:
            raise ValidationError(
                detail="consent_disclosure_version quá dài (>50 ký tự)"
            )
        if consent_proof_ref and len(consent_proof_ref) > 512:
            raise ValidationError(
                detail="consent_proof_ref quá dài (>512 ký tự)"
            )

        consent_applied = self._validate_consent_evidence(
            consent_basis,
            consent_disclosure_version,
            consent_proof_ref,
            consent_obtained_at,
        )
        # `_parse_rows` là CPU-bound thuần sync (pandas đọc tới 50.000 dòng,
        # engine="python" để dò dấu phân cách lại chậm hơn engine C khoảng một
        # bậc) → chạy thẳng trong coroutine sẽ treo event loop của worker vài
        # giây, mọi request khác trên worker đó đứng theo.
        rows = await asyncio.to_thread(
            self._parse_rows, file_content, filename or ""
        )

        # --- Phân loại từng dòng (mỗi dòng vào ĐÚNG 1 bucket) ---
        errors: List[sms_schemas.SmsImportRowError] = []
        invalid_count = 0
        duplicate_count = 0
        seen_in_file: set = set()
        valid_rows: List[dict] = []  # {full_name, phone_raw, normalized}
        for idx, r in enumerate(rows):
            line = idx + 2  # +1 header, +1 cho 1-based
            if not r["full_name"]:
                invalid_count += 1
                errors.append(
                    sms_schemas.SmsImportRowError(
                        row_number=line, phone_raw=r["phone"] or None,
                        reason="Thiếu họ tên",
                    )
                )
                continue
            if len(r["full_name"]) > 255:  # cột NOT NULL String(255) → 500
                invalid_count += 1
                errors.append(
                    sms_schemas.SmsImportRowError(
                        row_number=line, phone_raw=r["phone"] or None,
                        reason="Họ tên quá dài (>255 ký tự)",
                    )
                )
                continue
            normalized = normalize_vietnam_phone(r["phone"])
            if not normalized or not is_vietnam_mobile(normalized):
                invalid_count += 1
                errors.append(
                    sms_schemas.SmsImportRowError(
                        row_number=line, phone_raw=r["phone"] or None,
                        reason="Số không phải di động VN hợp lệ",
                    )
                )
                continue
            if normalized in seen_in_file:
                duplicate_count += 1
                errors.append(
                    sms_schemas.SmsImportRowError(
                        row_number=line, phone_raw=r["phone"],
                        reason="Trùng số trong cùng file",
                    )
                )
                continue
            seen_in_file.add(normalized)
            valid_rows.append(
                {
                    "full_name": r["full_name"],
                    # phone_raw chỉ để tham chiếu — cắt theo cột String(32).
                    "phone_raw": r["phone"][:32],
                    "normalized": normalized,
                    "note": r["note"] or None,
                }
            )

        valid_count = len(valid_rows)
        row_count = len(rows)
        phone_to_note = {v["normalized"]: v["note"] for v in valid_rows}

        # --- Dedupe global: tách contact mới vs đã tồn tại ---
        phones = [v["normalized"] for v in valid_rows]
        existing_map = await self.repo.get_contacts_by_phones(phones)

        inserted_count = 0
        new_contacts: List[SmsContact] = []
        phone_to_contact = dict(existing_map)
        for v in valid_rows:
            if v["normalized"] in existing_map:
                continue  # tái dùng, KHÔNG ghi đè identity (B3)
            # Contact mới tạo = 'unknown'; consent áp đồng nhất ở bước sau
            # (cho cả contact cũ) qua ledger + reproject.
            contact = SmsContact(
                full_name=v["full_name"],
                phone_raw=v["phone_raw"],
                phone_normalized=v["normalized"],
                phone_international=to_zalo_phone(v["normalized"]),
                note=v["note"],
                source_label=source_label,
                created_by_id=getattr(user, "id", None),
            )
            self.db.add(contact)
            new_contacts.append(contact)
            inserted_count += 1
        if new_contacts:
            try:
                await self.db.flush()  # lấy id cho membership + consent
            except IntegrityError:
                # Race: import đồng thời chèn cùng phone (UNIQUE) → 409.
                raise ConflictError(
                    detail="Import trùng số đồng thời, vui lòng thử lại"
                )
        for c in new_contacts:
            phone_to_contact[c.phone_normalized] = c

        # --- Membership: thêm mới vs đã là thành viên (giữ note theo nhóm) ---
        all_contact_ids = [
            phone_to_contact[p].id for p in phones if p in phone_to_contact
        ]
        existing_member_ids = (
            await self.repo.get_existing_member_contact_ids(
                group_id, all_contact_ids
            )
        )
        added_member_count = 0
        existing_member_count = 0
        for p in phones:
            contact = phone_to_contact.get(p)
            if contact is None:
                continue
            if contact.id in existing_member_ids:
                existing_member_count += 1
                continue
            self.db.add(
                SmsContactGroupMember(
                    group_id=group_id,
                    contact_id=contact.id,
                    note=phone_to_note.get(p),
                    added_by_id=getattr(user, "id", None),
                )
            )
            existing_member_ids.add(contact.id)
            added_member_count += 1
        if added_member_count:
            try:
                await self.db.flush()
            except IntegrityError:  # race UNIQUE(group,contact) → 409
                raise ConflictError(
                    detail="Import xung đột thành viên đồng thời, thử lại"
                )

        # --- Lưu batch (counts) ---
        batch = await self.repo.create_import_batch(
            {
                "group_id": group_id,
                # file_name = audit metadata → cắt theo cột String(255)
                "file_name": (filename[:255] if filename else None),
                "file_sha256": file_sha256,
                "source_label": source_label,
                "consent_basis": consent_basis if consent_applied else None,
                "consent_disclosure_version": (
                    consent_disclosure_version if consent_applied else None
                ),
                "consent_proof_ref": (
                    consent_proof_ref if consent_applied else None
                ),
                "consent_obtained_at": (
                    consent_obtained_at if consent_applied else None
                ),
                "row_count": row_count,
                "valid_count": valid_count,
                "invalid_count": invalid_count,
                "duplicate_contact_count": duplicate_count,
                "existing_member_count": existing_member_count,
                "inserted_contact_count": inserted_count,
                "added_member_count": added_member_count,
                "skipped_count": invalid_count + duplicate_count,
                "uploaded_by_id": getattr(user, "id", None),
            }
        )

        # --- Consent event + projection cho MỌI contact valid (§4.4) ---
        # Áp bằng chứng cấp-lô cho cả contact mới LẪN cũ (không chỉ contact
        # mới). Projection chiếu theo occurred_at mới nhất → grant của lô
        # KHÔNG phục hồi một revoke có occurred_at mới hơn (fail-closed).
        if consent_applied:
            valid_contacts = [
                phone_to_contact[p] for p in phones if p in phone_to_contact
            ]
            # Lock contact ĐÃ tồn tại trước khi đụng projection (tránh race).
            existing_ids = [
                c.id
                for c in valid_contacts
                if c.phone_normalized in existing_map
            ]
            await self.repo.lock_contacts_by_ids(existing_ids)
            for c in valid_contacts:
                self.db.add(
                    SmsMarketingConsentEvent(
                        contact_id=c.id,
                        phone_normalized_snapshot=c.phone_normalized,
                        event_type="granted",
                        basis=consent_basis,
                        disclosure_version=consent_disclosure_version,
                        proof_reference=consent_proof_ref,
                        occurred_at=consent_obtained_at,
                        recorded_by_id=getattr(user, "id", None),
                        import_batch_id=batch.id,
                    )
                )
            await self.db.flush()
            # Bulk reproject (1 query DISTINCT ON) — tránh N+1 ở lô lớn.
            latest = (
                await self.repo.get_latest_consent_events_for_contacts(
                    [c.id for c in valid_contacts]
                )
            )
            for c in valid_contacts:
                event = latest.get(c.id)
                if event is not None:
                    self._apply_consent_projection(c, event)
            await self.db.flush()

        return sms_schemas.SmsImportResult(
            batch_id=batch.id,
            group_id=group_id,
            file_name=filename,
            row_count=row_count,
            valid_count=valid_count,
            invalid_count=invalid_count,
            duplicate_contact_count=duplicate_count,
            existing_member_count=existing_member_count,
            inserted_contact_count=inserted_count,
            added_member_count=added_member_count,
            skipped_count=invalid_count + duplicate_count,
            consent_applied=consent_applied,
            errors=errors,
        )
