# app/models/admission_quota_table.py
"""GĐ2-A — bảng chỉ tiêu năm, nhóm ngành + trần nhóm, thành viên nhóm (đặc tả GĐ2 bản 3 §3, ``4230f936…``; sửa 3.2
``7da4e206…``; GO viết mã owner 18-11, PR đầu gồm GĐ2-0 + GĐ2-A).

* ``admission_quota_table`` — MỘT dòng / năm học (khoá chính ``academic_year``): ``draft`` ⇔ sửa được; ``locked`` ⇔ cột
  khoá có giá trị. Năm sau một bảng riêng (LXM).
* ``admission_quota_group`` — nhóm ngành của năm + ``ceiling`` = trần chỉ tiêu năm của nhóm (số nhà trường giao; phần
  mềm không tự tính — ca biên B20).
* ``admission_quota_group_member`` — một học vụ (``offering_academic_info``: ngành + năm) thuộc ĐÚNG một nhóm
  (UNIQUE học vụ); khoá ngoại GHÉP năm tới học vụ và tới nhóm ⇒ thành viên, nhóm, học vụ cùng một năm do CSDL bảo đảm.
* Chỉ tiêu ngành = cột CÓ SẴN ``offering_academic_info.annual_admission_quota`` (không thêm cột thứ hai).

Bảng khoá ⇒ CSDL chặn sửa chỉ tiêu ngành / nhóm / trần / thành viên của năm ấy: trigger ở
``app/models/admission_quota_ddl.py`` (tầng chủ sở hữu bất biến). Tạo bảng / chỉ mục ở đây; migration ``gd2a20261118``
chép NGUYÊN câu ``CREATE`` (test so lược đồ migration với model).
"""
from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)

from .base import Base

#: Trạng thái bảng chỉ tiêu năm.
QUOTA_TABLE_DRAFT = "draft"
QUOTA_TABLE_LOCKED = "locked"


class AdmissionQuotaTable(Base):
    __tablename__ = "admission_quota_table"

    academic_year = Column(Integer, primary_key=True, autoincrement=False)  # năm tuyển sinh — một bảng / năm
    status = Column(String(10), nullable=False, default=QUOTA_TABLE_DRAFT, server_default=text("'draft'"))
    # Người khoá là "đã từng thao tác" (K4 — ``user_deletion_policy``): RESTRICT, không để CSDL tự gán NULL.
    locked_by_user_id = Column(Integer, ForeignKey("user.id", ondelete="RESTRICT"), nullable=True, index=True)
    locked_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(Integer, nullable=False, default=1, server_default=text("1"))
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    __table_args__ = (
        CheckConstraint("status IN ('draft','locked')", name="ck_admission_quota_table_status"),
        CheckConstraint(
            "(status = 'locked') = (locked_by_user_id IS NOT NULL)", name="ck_admission_quota_table_locked_by"
        ),
        CheckConstraint("(locked_by_user_id IS NULL) = (locked_at IS NULL)", name="ck_admission_quota_table_locked_pair"),
        CheckConstraint("version >= 1", name="ck_admission_quota_table_version"),
    )

    def __repr__(self):
        return f"<AdmissionQuotaTable year={self.academic_year} status={self.status} v={self.version}>"


class AdmissionQuotaGroup(Base):
    __tablename__ = "admission_quota_group"

    id = Column(Integer, primary_key=True)
    academic_year = Column(
        Integer, ForeignKey("admission_quota_table.academic_year", ondelete="RESTRICT"), nullable=False
    )
    code = Column(String(30), nullable=False)
    name = Column(String(255), nullable=False)
    ceiling = Column(Integer, nullable=False)  # trần chỉ tiêu năm của nhóm (số người tối đa) — số nhà trường giao

    __table_args__ = (
        UniqueConstraint("academic_year", "code", name="uq_admission_quota_group_year_code"),
        # Đích của khoá ngoại ghép (nhóm, năm) từ thành viên.
        UniqueConstraint("id", "academic_year", name="uq_admission_quota_group_id_year"),
        CheckConstraint("ceiling >= 0", name="ck_admission_quota_group_ceiling"),
        CheckConstraint("length(btrim(code)) > 0", name="ck_admission_quota_group_code"),
        CheckConstraint("length(btrim(name)) > 0", name="ck_admission_quota_group_name"),
    )

    def __repr__(self):
        return f"<AdmissionQuotaGroup id={self.id} year={self.academic_year} code={self.code!r}>"


class AdmissionQuotaGroupMember(Base):
    __tablename__ = "admission_quota_group_member"

    id = Column(Integer, primary_key=True)
    group_id = Column(Integer, nullable=False)
    offering_academic_info_id = Column(Integer, nullable=False)
    academic_year = Column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("offering_academic_info_id", name="uq_admission_quota_group_member_oai"),
        ForeignKeyConstraint(
            ["group_id", "academic_year"],
            ["admission_quota_group.id", "admission_quota_group.academic_year"],
            ondelete="CASCADE",
            name="fk_admission_quota_group_member_group",
        ),
        ForeignKeyConstraint(
            ["offering_academic_info_id", "academic_year"],
            ["offering_academic_info.id", "offering_academic_info.academic_year"],
            ondelete="RESTRICT",
            name="fk_admission_quota_group_member_oai",
        ),
        Index("ix_admission_quota_group_member_group_id", "group_id"),
    )

    def __repr__(self):
        return f"<AdmissionQuotaGroupMember group={self.group_id} oai={self.offering_academic_info_id}>"
