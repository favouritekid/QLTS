# app/models/admission_review_selection.py
"""GĐ2-C C2 — lựa chọn của Ban thư ký cho từng hồ sơ trong một lần xét NHÁP.

Nguồn: QĐB:12 (Ban thư ký quyết ca đặc biệt từ GĐ2-C), QĐB:18 (cờ "đang ngừng" bắt buộc xử lý trước khi khoá); ĐT3 §3 (bảng
``admission_review_selection``, 5 loại), §11 (``PUT /review-sessions/{id}/selections/{profile_id}``); thiết kế GĐ2-C 22-11 §2.2
(thêm loại thứ sáu cho cờ "đang ngừng"; chỉ thêm; ``supersedes_id``; chỉ ghi khi lần xét ``draft``), §3.1 (thứ tự khoá), §6 hàng
C2; owner C5 22-11 (cờ "đang ngừng" xử lý bằng ĐÚNG hai lựa chọn "Vẫn giữ" / "Loại khỏi lần này"), owner C6 22-11 ("Loại khỏi lần
này" và "Chờ bổ sung" BẮT BUỘC lý do).

* Một dòng = MỘT lần Ban thư ký chọn cho (lần xét, hồ sơ). **Chỉ thêm**: không sửa, không xoá (trigger ở
  ``admission_review_selection_ddl.py`` — tầng chủ sở hữu). "Đổi ý" = dòng MỚI có ``supersedes_id`` trỏ dòng đang hiệu lực.
* Chuỗi thay thế của một (lần xét, hồ sơ) là MỘT đường thẳng: gốc duy nhất (chỉ mục duy nhất một phần ``supersedes_id IS NULL``),
  mỗi dòng bị thay tối đa một lần (UNIQUE ``supersedes_id``), dòng thay đứng SAU dòng bị thay (CHECK ``supersedes_id < id`` ⇒ không
  vòng). Lựa chọn HIỆU LỰC = dòng cuối chuỗi (không dòng nào thay nó).
* ``based_on_run_id`` + ``based_on_row_hash`` = dòng kết quả của lượt ``evaluate`` (đã xong, CÙNG lần xét) mà Ban thư ký nhìn
  khi chọn; ``choice_id`` = NV được xếp của dòng ấy (NULL khi dòng không có NV được xếp). Trigger đòi ba giá trị khớp ĐÚNG dòng
  ``admission_review_row`` (run, hồ sơ) — không ghi được lựa chọn dựa trên một dòng không có thật. Dòng ấy phải là dòng của lượt
  MỚI NHẤT lúc ghi: dịch vụ so, lệch ⇒ 409 ``SELECTION_STALE`` (ĐT3 T9).
* ``note`` = lý do; BẮT BUỘC (không trắng) với "Loại khỏi lần này" và "Chờ bổ sung" (owner C6) — CHECK ở CSDL + kiểm ở dịch vụ.
* ``profile_id`` KHÔNG có khoá ngoại tới hồ sơ — cùng lý do với ``admission_review_row`` (ảnh chụp bất biến: RESTRICT chặn xoá
  hồ sơ nháp, ``SET NULL`` mâu thuẫn bất biến chỉ thêm). Liên kết tới hồ sơ đi qua dòng kết quả (trigger đối chiếu).
* Cột người dùng ``decided_by_user_id``: khoá ngoại ``user.id`` **RESTRICT** + một dòng ``BLOCK_ACTOR`` ở
  ``app/services/user_deletion_policy.py`` (K4).

Bản cho ``create_all()`` (CSDL test không chạy Alembic). Bản thật: migration ``gd2cs20261122`` chép NGUYÊN câu ``CREATE``;
``tests/unit/test_gd2c_c2_ddl_lockin.py`` so tên + chữ, ``tests/integration/test_gd2c_c2_migration.py`` so lược đồ thật. Chữ CHECK
KHÔNG dùng ``%`` và ``::``.
"""
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)

from .base import Base

# ── Sáu loại lựa chọn (ĐT3 §3: 5 loại ca đặc biệt; thiết kế GĐ2-C §2.2 + owner C5: loại thứ sáu "Vẫn giữ" cho cờ đang ngừng) ──
SELECTION_ADMIT_OVER_MAJOR_QUOTA = "admit_over_major_quota"  # trúng vượt chỉ tiêu ngành (dưới trần nhóm — kiểm lúc khoá)
SELECTION_CONSIDER_NEXT_CHOICE = "consider_next_choice"  # xét nguyện vọng kế
SELECTION_DEFER_SUPPLEMENT = "defer_supplement"  # chờ bổ sung — BẮT BUỘC lý do (owner C6)
SELECTION_ADMIT_WITHOUT_ETHNIC_BONUS = "admit_without_ethnic_bonus"  # xét không cộng điểm dân tộc
SELECTION_EXCLUDE_THIS_SESSION = "exclude_this_session"  # loại khỏi lần này — BẮT BUỘC lý do (owner C6); xử lý cờ đang ngừng (C5)
SELECTION_KEEP_DESPITE_INACTIVE = "keep_despite_inactive"  # vẫn giữ dù ngành / loại hình đang ngừng (owner C5)

#: Đúng thứ tự hiển thị. MỘT nguồn cho CHECK dưới, schema API và luật dịch vụ.
SELECTION_KINDS = (
    SELECTION_ADMIT_OVER_MAJOR_QUOTA,
    SELECTION_CONSIDER_NEXT_CHOICE,
    SELECTION_DEFER_SUPPLEMENT,
    SELECTION_ADMIT_WITHOUT_ETHNIC_BONUS,
    SELECTION_EXCLUDE_THIS_SESSION,
    SELECTION_KEEP_DESPITE_INACTIVE,
)
#: Owner C6 22-11: hai loại BẮT BUỘC lý do.
SELECTION_KINDS_REASON_REQUIRED = (SELECTION_DEFER_SUPPLEMENT, SELECTION_EXCLUDE_THIS_SESSION)
#: Owner C5 22-11: cờ "ngành / loại hình đang ngừng" chỉ được xử lý bằng ĐÚNG hai loại này.
SELECTION_KINDS_RESOLVING_INACTIVE = (SELECTION_KEEP_DESPITE_INACTIVE, SELECTION_EXCLUDE_THIS_SESSION)

# ── Chữ CHECK — MỘT bản; migration chép nguyên (test lock-in so theo tên) ─────────────────────────────────────────────────
CHECK_SELECTION_KIND = (
    "kind IN ('admit_over_major_quota','consider_next_choice','defer_supplement','admit_without_ethnic_bonus',"
    "'exclude_this_session','keep_despite_inactive')"
)
CHECK_SELECTION_ROW_HASH = "based_on_row_hash ~ '^[0-9a-f]{64}$'"
#: Lý do (nếu có) không được trắng.
CHECK_SELECTION_NOTE = "note IS NULL OR length(btrim(note)) > 0"
#: Owner C6: "Loại khỏi lần này" và "Chờ bổ sung" BẮT BUỘC lý do (không trắng — cùng :data:`CHECK_SELECTION_NOTE`).
CHECK_SELECTION_NOTE_REQUIRED = "kind NOT IN ('exclude_this_session','defer_supplement') OR note IS NOT NULL"
#: Dòng thay đứng SAU dòng bị thay (id cấp tăng) ⇒ chuỗi thay thế không có vòng, không tự thay chính mình.
CHECK_SELECTION_SUPERSEDES_ORDER = "supersedes_id IS NULL OR supersedes_id < id"

#: Gốc chuỗi thay thế của một (lần xét, hồ sơ) là DUY NHẤT.
ROOT_WHERE = "supersedes_id IS NULL"


class AdmissionReviewSelection(Base):
    __tablename__ = "admission_review_selection"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, nullable=False)
    academic_year = Column(Integer, nullable=False)  # = năm của lần xét (khoá ngoại ghép)
    profile_id = Column(Integer, nullable=False)  # KHÔNG khoá ngoại — xem docstring module
    kind = Column(String(40), nullable=False)
    choice_id = Column(Integer, nullable=True)  # NV được xếp của dòng dựa vào (NULL khi dòng không có NV được xếp)
    based_on_run_id = Column(Integer, nullable=False)
    based_on_row_hash = Column(String(64), nullable=False)
    decided_by_user_id = Column(Integer, nullable=False)
    decided_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    note = Column(Text, nullable=True)
    supersedes_id = Column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("supersedes_id", name="uq_admission_review_selection_supersedes"),
        CheckConstraint(CHECK_SELECTION_KIND, name="ck_admission_review_selection_kind"),
        CheckConstraint(CHECK_SELECTION_ROW_HASH, name="ck_admission_review_selection_row_hash"),
        CheckConstraint(CHECK_SELECTION_NOTE, name="ck_admission_review_selection_note"),
        CheckConstraint(CHECK_SELECTION_NOTE_REQUIRED, name="ck_admission_review_selection_note_required"),
        CheckConstraint(CHECK_SELECTION_SUPERSEDES_ORDER, name="ck_admission_review_selection_supersedes_order"),
        ForeignKeyConstraint(
            ["session_id", "academic_year"],
            ["admission_review_session.id", "admission_review_session.academic_year"],
            ondelete="RESTRICT",
            name="fk_admission_review_selection_session",
        ),
        ForeignKeyConstraint(
            ["based_on_run_id"], ["admission_review_run.id"], ondelete="RESTRICT", name="fk_admission_review_selection_run"
        ),
        ForeignKeyConstraint(
            ["decided_by_user_id"], ["user.id"], ondelete="RESTRICT", name="fk_admission_review_selection_decided_by"
        ),
        ForeignKeyConstraint(
            ["supersedes_id"],
            ["admission_review_selection.id"],
            ondelete="RESTRICT",
            name="fk_admission_review_selection_supersedes",
        ),
        Index(
            "uq_admission_review_selection_root",
            "session_id",
            "profile_id",
            unique=True,
            postgresql_where=text(ROOT_WHERE),
        ),
        Index("ix_admission_review_selection_session_profile", "session_id", "profile_id"),
        Index("ix_admission_review_selection_based_on_run_id", "based_on_run_id"),
        Index("ix_admission_review_selection_decided_by_user_id", "decided_by_user_id"),
    )

    def __repr__(self):
        return (
            f"<AdmissionReviewSelection id={self.id} session={self.session_id} profile={self.profile_id} "
            f"kind={self.kind} supersedes={self.supersedes_id}>"
        )
