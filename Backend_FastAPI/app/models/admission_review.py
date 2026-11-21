# app/models/admission_review.py
"""GĐ2-B — lần xét NHÁP, điểm sàn, lượt chạy kiểm hồ sơ, dòng kết quả (đặc tả GĐ2-B bản 4 §4.2 ``6247a1a8…``; hợp đồng API
bản 4 ``b877fba1…`` §3, §7; kế hoạch triển khai 21-11 + biên bản owner K1–K4 21-11).

* ``admission_review_session`` — một lần xét của MỘT năm tuyển sinh + MỘT đợt. ``draft`` ⇔ còn sửa được; ``cancelled`` (cuối) ⇔
  đủ ba cột huỷ và lý do không trắng; chưa huỷ ⇒ ba cột huỷ trống. ``seq_no`` cấp theo năm (UNIQUE năm + số). Khoá ngoại năm →
  bảng chỉ tiêu năm (năm chưa có bảng ⇒ không tạo được lần xét); khoá ngoại GHÉP (đợt, năm) → đợt ⇒ đợt thuộc đúng năm.
* ``admission_review_floor`` — điểm sàn của một học vụ trong một lần xét. Khoá ngoại GHÉP (lần xét, năm) và (học vụ, năm) ⇒ sàn
  chỉ trỏ học vụ ĐÚNG năm của lần xét (CSDL giữ). Không ``ON UPDATE`` ⇒ dời năm một học vụ đang có sàn vấp khoá ngoại (dịch vụ kiểm
  trước ⇒ 409 ``ACADEMIC_INFO_IN_REVIEW_FLOOR`` — đặc tả §4.3).
* ``admission_review_run`` — một lượt chạy (GĐ2-B chỉ ``evaluate``): ``queued → running → done / failed``; ``done`` / ``failed`` là
  cuối; tối đa MỘT lượt ``queued`` / ``running`` mỗi lần xét (UNIQUE một phần). ``inputs`` chụp GIÁ TRỊ (kể cả mức sàn đã dùng —
  ``inputs.floors``), KHÔNG tham chiếu bảng sàn (P4).
* ``admission_review_row`` — một hồ sơ trong một lượt chạy. ``profile_id`` KHÔNG có khoá ngoại (đặc tả §4.2 "Khác ĐT3 có chủ
  ý": dòng là ảnh chụp bất biến; khoá ngoại RESTRICT sẽ chặn xoá hồ sơ nháp, ``SET NULL`` mâu thuẫn bất biến). "NV được xếp" lưu
  thành các cột ``considered_*`` (khoá đếm: đường xét, học vụ, loại hình + nhãn lúc chạy để sắp / lọc E9 bằng SQL).

Cột người dùng (người tạo / huỷ lần xét, người lưu sàn, người chạy): khoá ngoại ``user.id`` **RESTRICT** + nhóm ``BLOCK_ACTOR``
ở ``app/services/user_deletion_policy.py``.

Bất biến "lần xét đã huỷ không sửa, không xoá; sàn chỉ ghi khi lần xét nháp; lượt chạy chỉ đi tới; lượt / dòng đã xong không sửa,
không xoá" ở TRIGGER (``app/models/admission_review_ddl.py`` — tầng chủ sở hữu, bắt cả SQL tay). Ràng buộc dữ liệu ở CHECK / UNIQUE /
khoá ngoại dưới đây. Migration ``gd2b20261121`` chép NGUYÊN câu ``CREATE`` theo model: ``tests/integration/test_gd2b_migration.py``
so lược đồ sau nâng cấp với CSDL dựng thẳng từ model; ``tests/unit/test_gd2b_ddl_lockin.py`` so tên ràng buộc / chỉ mục / chữ CHECK.

Chữ CHECK KHÔNG dùng ``%`` và ``::`` (cùng quy ước với DDL của dự án; ``text()`` hiểu ``:tên`` là tham số) — so với chuỗi JSON rỗng
viết ``per_choice <> '[]'`` (PostgreSQL tự ép chữ sang ``jsonb``).
"""
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from .base import Base

# ── Danh mục giá trị (hợp đồng API bản 4 §4) ───────────────────────────────────────────────────────────────────────────
REVIEW_SESSION_DRAFT = "draft"
REVIEW_SESSION_CANCELLED = "cancelled"
REVIEW_SESSION_STATUSES = (REVIEW_SESSION_DRAFT, REVIEW_SESSION_CANCELLED)  # C nới ``locked``, ``signed``

REVIEW_RUN_KIND_EVALUATE = "evaluate"
REVIEW_RUN_KINDS = (REVIEW_RUN_KIND_EVALUATE,)  # C nới ``proposal``, ``lock``

REVIEW_RUN_QUEUED = "queued"
REVIEW_RUN_RUNNING = "running"
REVIEW_RUN_DONE = "done"
REVIEW_RUN_FAILED = "failed"
REVIEW_RUN_STATUSES = (REVIEW_RUN_QUEUED, REVIEW_RUN_RUNNING, REVIEW_RUN_DONE, REVIEW_RUN_FAILED)
#: Trạng thái "đang chạy" — UNIQUE một phần: tối đa một lượt như vậy mỗi lần xét.
REVIEW_RUN_ACTIVE_STATUSES = (REVIEW_RUN_QUEUED, REVIEW_RUN_RUNNING)

REVIEW_TAB_AUTO = "auto"
REVIEW_TAB_NEEDS_DECISION = "needs_decision"
REVIEW_TAB_NOT_PASSED = "not_passed"
REVIEW_TAB_INELIGIBLE = "ineligible"
#: Đúng thứ tự hiển thị / sắp của E9 (hợp đồng §2 E9).
REVIEW_TABS = (REVIEW_TAB_AUTO, REVIEW_TAB_NEEDS_DECISION, REVIEW_TAB_NOT_PASSED, REVIEW_TAB_INELIGIBLE)  # C nới ``excluded``

ETHNIC_PRIORITY_STATES = ("not_applicable", "full_evidence", "provisional_by_commune", "undetermined")

# ── Chữ CHECK — MỘT bản; migration chép nguyên (test lock-in so theo tên) ──────────────────────────────────────────────
CHECK_SESSION_STATUS = "status IN ('draft','cancelled')"
CHECK_SESSION_SEQ_NO = "seq_no > 0"
CHECK_SESSION_VERSION = "version >= 1"
#: ``cancelled`` ⇔ ba cột huỷ có giá trị và lý do không trắng (đặc tả §4.2).
CHECK_SESSION_CANCELLED = (
    "(status = 'cancelled') = (cancelled_by_user_id IS NOT NULL AND cancelled_at IS NOT NULL "
    "AND cancel_reason IS NOT NULL AND btrim(cancel_reason) <> '')"
)
#: [ĐX — L1] chưa huỷ ⇒ ba cột huỷ đều trống (khuôn cặp cột khoá của ``admission_quota_table``).
CHECK_SESSION_CANCEL_CLEAR = (
    "status = 'cancelled' OR (cancelled_by_user_id IS NULL AND cancelled_at IS NULL AND cancel_reason IS NULL)"
)

CHECK_FLOOR_SCORE = "floor_score >= 0"

CHECK_RUN_KIND = "kind IN ('evaluate')"
CHECK_RUN_STATUS = "status IN ('queued','running','done','failed')"
#: [ĐX — L1] "CHECK theo trạng thái" (đặc tả §4.2) viết thành bảng kéo theo — trạng thái lạ do ``CHECK_RUN_STATUS`` bắt, không
#: do ràng buộc này. ``failed`` chỉ tới từ ``running`` (trigger) ⇒ có ``started_at``; ``summary`` / ``quota_view`` chỉ có khi ``done``
#: (hợp đồng §3.3 "null khi chưa done"); ``error_code`` chỉ khi ``failed``.
CHECK_RUN_STATE_COLUMNS = (
    "(status <> 'queued' OR (started_at IS NULL AND finished_at IS NULL AND duration_ms IS NULL "
    "AND summary IS NULL AND quota_view IS NULL AND error_code IS NULL)) "
    "AND (status <> 'running' OR (started_at IS NOT NULL AND finished_at IS NULL AND duration_ms IS NULL "
    "AND summary IS NULL AND quota_view IS NULL AND error_code IS NULL)) "
    "AND (status <> 'done' OR (started_at IS NOT NULL AND finished_at IS NOT NULL AND duration_ms IS NOT NULL "
    "AND summary IS NOT NULL AND quota_view IS NOT NULL AND error_code IS NULL)) "
    "AND (status <> 'failed' OR (started_at IS NOT NULL AND finished_at IS NOT NULL AND duration_ms IS NOT NULL "
    "AND summary IS NULL AND quota_view IS NULL AND error_code IS NOT NULL))"
)
CHECK_RUN_DURATION = "duration_ms IS NULL OR duration_ms >= 0"

CHECK_ROW_TAB = "tab IN ('auto','needs_decision','not_passed','ineligible')"
CHECK_ROW_HASH = "row_hash ~ '^[0-9a-f]{64}$'"
#: ``auto`` / ``needs_decision`` ⇔ có NV được xếp (hợp đồng §3.5: ``considered_choice`` ``null`` khi ``not_passed`` / ``ineligible``).
CHECK_ROW_PLACED = "(tab IN ('auto','needs_decision')) = (considered_choice_id IS NOT NULL)"
#: Có NV được xếp ⇒ đủ khoá đếm + ``review_total`` (đặc tả §4.2 "auto / needs_decision ⇒ có NV được xếp + review_total").
CHECK_ROW_PLACED_FIELDS = (
    "considered_choice_id IS NULL OR (considered_display_order IS NOT NULL "
    "AND considered_offering_academic_info_id IS NOT NULL AND considered_offering_id IS NOT NULL "
    "AND considered_admission_path_id IS NOT NULL AND review_total IS NOT NULL)"
)
#: ``needs_decision`` / ``not_passed`` / ``ineligible`` ⇒ có ít nhất một mã lý do.
CHECK_ROW_REASONS = "tab = 'auto' OR cardinality(reason_codes) > 0"
CHECK_ROW_ETHNIC_STATE = (
    "ethnic_priority_state IS NULL OR ethnic_priority_state IN "
    "('not_applicable','full_evidence','provisional_by_commune','undetermined')"
)
#: ``per_choice`` luôn là mảng JSON ⇒ "rỗng" chỉ có MỘT cách viết (``[]``) — điều kiện của :data:`CHECK_ROW_PROFILE_CONDITION`.
CHECK_ROW_PER_CHOICE_ARRAY = "jsonb_typeof(per_choice) = 'array'"
#: Phụ lục kỹ thuật GĐ2-B bản 4 đợt 1 §1 (cờ A13 kèm năm + căn cứ): ``prior_year_findings`` luôn là mảng JSON (rỗng = không có cờ
#: A13). Bất biến "cờ ``same_citizen_admitted_previous_year`` ⇔ mảng khác rỗng" do hàm dựng dòng (L2) giữ, KHÔNG ở CSDL.
CHECK_ROW_PRIOR_YEAR_FINDINGS_ARRAY = "jsonb_typeof(prior_year_findings) = 'array'"
#: (P2) ``ineligible`` vì ĐIỀU KIỆN HỒ SƠ (E1–E7, kể cả ngoài tập xét) ⇒ không tính ưu tiên, không tính điểm. Phân biệt với
#: ``ineligible`` vì DỪNG Ở MỘT NV (§6.5 bước 1, 2, 4, 5, 6 — đã qua E1–E7, đã tính ưu tiên) bằng ``per_choice`` rỗng: hồ sơ
#: trượt E1–E7 "không xét nguyện vọng" ⇒ ``per_choice = []`` (đặc tả §6.2; hợp đồng §3.5), hồ sơ dừng ở NV có ít nhất NV ấy.
CHECK_ROW_PROFILE_CONDITION = (
    "tab <> 'ineligible' OR per_choice <> '[]' OR (ethnic_priority_state IS NULL AND review_total IS NULL)"
)

ACTIVE_RUN_WHERE = "status IN ('queued','running')"


class AdmissionReviewSession(Base):
    __tablename__ = "admission_review_session"

    id = Column(Integer, primary_key=True)
    academic_year = Column(Integer, nullable=False)  # năm tuyển sinh — KHÔNG BAO GIỜ đổi (trigger)
    admission_round_id = Column(Integer, nullable=False)
    seq_no = Column(Integer, nullable=False)  # số nội bộ trong năm; tăng cả với lần xét đã huỷ
    status = Column(String(20), nullable=False, default=REVIEW_SESSION_DRAFT, server_default=text("'draft'"))
    version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    created_by_user_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    cancelled_by_user_id = Column(Integer, nullable=True)
    cancelled_at = Column(DateTime(timezone=True), nullable=True)
    cancel_reason = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("academic_year", "seq_no", name="uq_admission_review_session_year_seq"),
        # Đích của khoá ngoại ghép (lần xét, năm) từ điểm sàn.
        UniqueConstraint("id", "academic_year", name="uq_admission_review_session_id_year"),
        CheckConstraint(CHECK_SESSION_STATUS, name="ck_admission_review_session_status"),
        CheckConstraint(CHECK_SESSION_SEQ_NO, name="ck_admission_review_session_seq_no"),
        CheckConstraint(CHECK_SESSION_VERSION, name="ck_admission_review_session_version"),
        CheckConstraint(CHECK_SESSION_CANCELLED, name="ck_admission_review_session_cancelled"),
        CheckConstraint(CHECK_SESSION_CANCEL_CLEAR, name="ck_admission_review_session_cancel_clear"),
        ForeignKeyConstraint(
            ["academic_year"],
            ["admission_quota_table.academic_year"],
            ondelete="RESTRICT",
            name="fk_admission_review_session_quota_table",
        ),
        ForeignKeyConstraint(
            ["admission_round_id", "academic_year"],
            ["offering_admission_round.id", "offering_admission_round.academic_year"],
            ondelete="RESTRICT",
            name="fk_admission_review_session_round",
        ),
        ForeignKeyConstraint(
            ["created_by_user_id"], ["user.id"], ondelete="RESTRICT", name="fk_admission_review_session_created_by"
        ),
        ForeignKeyConstraint(
            ["cancelled_by_user_id"], ["user.id"], ondelete="RESTRICT", name="fk_admission_review_session_cancelled_by"
        ),
        Index("ix_admission_review_session_created_by_user_id", "created_by_user_id"),
        Index("ix_admission_review_session_cancelled_by_user_id", "cancelled_by_user_id"),
    )

    def __repr__(self):
        return (
            f"<AdmissionReviewSession id={self.id} year={self.academic_year} seq={self.seq_no} "
            f"status={self.status} v={self.version}>"
        )


class AdmissionReviewFloor(Base):
    __tablename__ = "admission_review_floor"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, nullable=False)
    academic_year = Column(Integer, nullable=False)  # = năm của lần xét = năm của học vụ (hai khoá ngoại ghép)
    offering_academic_info_id = Column(Integer, nullable=False)
    floor_score = Column(Numeric(5, 2), nullable=False)  # so với tổng điểm ĐÃ cộng ưu tiên; bằng sàn = đạt (QĐB:15)
    updated_by_user_id = Column(Integer, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        UniqueConstraint("session_id", "offering_academic_info_id", name="uq_admission_review_floor_session_oai"),
        CheckConstraint(CHECK_FLOOR_SCORE, name="ck_admission_review_floor_score"),
        ForeignKeyConstraint(
            ["session_id", "academic_year"],
            ["admission_review_session.id", "admission_review_session.academic_year"],
            ondelete="RESTRICT",
            name="fk_admission_review_floor_session",
        ),
        ForeignKeyConstraint(
            ["offering_academic_info_id", "academic_year"],
            ["offering_academic_info.id", "offering_academic_info.academic_year"],
            ondelete="RESTRICT",
            name="fk_admission_review_floor_oai",
        ),
        ForeignKeyConstraint(
            ["updated_by_user_id"], ["user.id"], ondelete="RESTRICT", name="fk_admission_review_floor_updated_by"
        ),
        # Tra "học vụ này đang có sàn ở lần xét nào" (dời năm học vụ) + kiểm khoá ngoại khi đổi khoá của học vụ.
        Index("ix_admission_review_floor_oai", "offering_academic_info_id"),
        Index("ix_admission_review_floor_updated_by_user_id", "updated_by_user_id"),
    )

    def __repr__(self):
        return (
            f"<AdmissionReviewFloor session={self.session_id} oai={self.offering_academic_info_id} "
            f"floor={self.floor_score}>"
        )


class AdmissionReviewRun(Base):
    __tablename__ = "admission_review_run"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, nullable=False)
    kind = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False)
    rule_version = Column(String(50), nullable=False)  # nhãn bộ luật (chuỗi mờ, vd "gd2b-1")
    requested_by_user_id = Column(Integer, nullable=False)
    requested_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    inputs = Column(JSONB, nullable=False)  # ảnh chụp GIÁ TRỊ đầu vào (năm, phiên bản lần xét, mức sàn, bảng chỉ tiêu, chế độ học phí)
    # ``none_as_null=True`` (tiền lệ ``notification.py``): Python ``None`` ⇒ SQL NULL, KHÔNG phải JSON ``null`` — CHECK theo trạng
    # thái đòi ``IS NULL`` (queued / running / failed); không có cờ này thì ghi tường minh ``None`` sẽ vi phạm CHECK. DDL không đổi.
    summary = Column(JSONB(none_as_null=True), nullable=True)
    quota_view = Column(JSONB(none_as_null=True), nullable=True)
    error_code = Column(String(100), nullable=True)

    __table_args__ = (
        CheckConstraint(CHECK_RUN_KIND, name="ck_admission_review_run_kind"),
        CheckConstraint(CHECK_RUN_STATUS, name="ck_admission_review_run_status"),
        CheckConstraint(CHECK_RUN_STATE_COLUMNS, name="ck_admission_review_run_state_columns"),
        CheckConstraint(CHECK_RUN_DURATION, name="ck_admission_review_run_duration"),
        ForeignKeyConstraint(
            ["session_id"], ["admission_review_session.id"], ondelete="RESTRICT", name="fk_admission_review_run_session"
        ),
        ForeignKeyConstraint(
            ["requested_by_user_id"], ["user.id"], ondelete="RESTRICT", name="fk_admission_review_run_requested_by"
        ),
        # Tối đa MỘT lượt đang chạy mỗi lần xét — lớp cuối sau khoá thử ``pg_try_advisory_xact_lock`` của dịch vụ.
        Index(
            "uq_admission_review_run_session_active",
            "session_id",
            unique=True,
            postgresql_where=text(ACTIVE_RUN_WHERE),
        ),
        Index("ix_admission_review_run_session_id", "session_id"),
        Index("ix_admission_review_run_requested_by_user_id", "requested_by_user_id"),
    )

    def __repr__(self):
        return f"<AdmissionReviewRun id={self.id} session={self.session_id} kind={self.kind} status={self.status}>"


class AdmissionReviewRow(Base):
    __tablename__ = "admission_review_row"

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, nullable=False)
    profile_id = Column(Integer, nullable=False)  # KHÔNG khoá ngoại — xem docstring module
    profile_status = Column(String(20), nullable=False)  # trạng thái hồ sơ LÚC CHẠY (cùng cỡ ``admission_profile.status``)
    tab = Column(String(20), nullable=False)
    reason_codes = Column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    flags = Column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    decision_hints = Column(ARRAY(Text), nullable=False, server_default=text("'{}'"))
    document_gaps = Column(JSONB(none_as_null=True), nullable=True)  # {missing: [mã], not_verified: [mã]} | SQL NULL
    # NV được xếp (``considered_choice`` của hợp đồng §3.5) — khoá đếm + nhãn LÚC CHẠY; NULL khi không có NV được xếp.
    considered_choice_id = Column(Integer, nullable=True)
    considered_display_order = Column(Integer, nullable=True)
    considered_offering_academic_info_id = Column(Integer, nullable=True)
    considered_offering_id = Column(Integer, nullable=True)
    considered_admission_path_id = Column(Integer, nullable=True)
    considered_major_code = Column(String(50), nullable=True)
    considered_major_name = Column(String(255), nullable=True)
    considered_offering_type = Column(String(100), nullable=True)
    subject_total = Column(Numeric(5, 2), nullable=True)
    area_score = Column(Numeric(5, 2), nullable=True)
    object_score = Column(Numeric(5, 2), nullable=True)
    priority_total = Column(Numeric(5, 2), nullable=True)
    review_total = Column(Numeric(5, 2), nullable=True)
    floor_score = Column(Numeric(5, 2), nullable=True)  # GIÁ TRỊ sàn lúc chạy — không tham chiếu bảng sàn (P4)
    rank_in_major = Column(Integer, nullable=True)
    within_seats = Column(Boolean, nullable=True)
    ethnic_priority_state = Column(String(30), nullable=True)
    per_choice = Column(JSONB, nullable=False, server_default=text("'[]'"))
    # Cờ A13 kèm năm + căn cứ (phụ lục đợt 1 §1): [{year, basis: occupying_status | admission_decision, status | null}], năm giảm
    # dần rồi căn cứ; KHÔNG mã hồ sơ cũ, họ tên, CCCD. Rỗng ⇔ không có cờ A13. Vào ``row_hash`` (L2).
    prior_year_findings = Column(JSONB, nullable=False, server_default=text("'[]'"))
    row_hash = Column(String(64), nullable=False)

    __table_args__ = (
        UniqueConstraint("run_id", "profile_id", name="uq_admission_review_row_run_profile"),
        CheckConstraint(CHECK_ROW_TAB, name="ck_admission_review_row_tab"),
        CheckConstraint(CHECK_ROW_HASH, name="ck_admission_review_row_hash"),
        CheckConstraint(CHECK_ROW_PLACED, name="ck_admission_review_row_placed"),
        CheckConstraint(CHECK_ROW_PLACED_FIELDS, name="ck_admission_review_row_placed_fields"),
        CheckConstraint(CHECK_ROW_REASONS, name="ck_admission_review_row_reasons"),
        CheckConstraint(CHECK_ROW_ETHNIC_STATE, name="ck_admission_review_row_ethnic_state"),
        CheckConstraint(CHECK_ROW_PER_CHOICE_ARRAY, name="ck_admission_review_row_per_choice_array"),
        CheckConstraint(
            CHECK_ROW_PRIOR_YEAR_FINDINGS_ARRAY, name="ck_admission_review_row_prior_year_findings_array"
        ),
        CheckConstraint(CHECK_ROW_PROFILE_CONDITION, name="ck_admission_review_row_profile_condition"),
        ForeignKeyConstraint(
            ["run_id"], ["admission_review_run.id"], ondelete="RESTRICT", name="fk_admission_review_row_run"
        ),
    )

    def __repr__(self):
        return f"<AdmissionReviewRow run={self.run_id} profile={self.profile_id} tab={self.tab}>"
