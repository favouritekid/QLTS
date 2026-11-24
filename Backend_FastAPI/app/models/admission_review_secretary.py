# app/models/admission_review_secretary.py
"""GĐ2-C C1 — quyền "Thư ký Hội đồng" gán theo TỪNG người.

Nguồn: QĐB:26 (bảng quyền Ban thư ký + route gán / thu hồi + ``deps.require_review_secretary`` — để GĐ2-C); thiết kế GĐ2-C
22-11 §2.2 (``logs-P5/cong-bo-ket-qua/gd2/gd2c/THIET-KE-GD2-C-2026-11-22.md``); owner C1 22-11 "Không hết hạn, giữ tới khi
Admin thu hồi" ⇒ bảng KHÔNG có cột hết hạn.

* Một dòng = một lần gán. Chỉ THU HỒI, không xoá, không sửa: trigger ở ``admission_review_secretary_ddl.py`` (tầng chủ sở
  hữu bất biến "chỉ thu hồi một lần"). Gán lại sau khi thu hồi = dòng MỚI có lý do.
* Mỗi người tối đa MỘT quyền còn hiệu lực (chỉ mục duy nhất một phần ``revoked_at IS NULL``).
* Ba cột thu hồi (lúc / ai / lý do) cùng NULL hoặc cùng có. Lý do gán và lý do thu hồi không được rỗng.
* Mọi cột người dùng: khoá ngoại ``user.id`` RESTRICT + một dòng ``BLOCK_ACTOR`` trong ``user_deletion_policy`` (K4).

Bản cho ``create_all()`` (CSDL test không chạy Alembic). Bản thật: migration ``gd2c20261122`` chép NGUYÊN câu ``CREATE``;
hai bản khoá bằng ``tests/unit/test_gd2c_c1_ddl_lockin.py`` (tên + chữ) và ``tests/integration/test_gd2c_c1_migration.py``
(lược đồ thật). Không khai quan hệ ORM từ ``User`` sang bảng này: quan hệ không ``passive_deletes`` sẽ tự gán NULL vượt
qua ``RESTRICT``.
"""
from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, Text, text

from .base import Base

#: Điều kiện "quyền còn hiệu lực" — MỘT chữ cho chỉ mục một phần (model + migration) và câu đọc của kho.
ACTIVE_GRANT_WHERE = "revoked_at IS NULL"

#: Chữ CHECK (khai một lần, dùng ở model; migration chép nguyên — test so chữ).
CHECK_REASON = "length(btrim(reason)) > 0"
CHECK_REVOKED_TRIPLE = (
    "(revoked_at IS NULL) = (revoked_by_user_id IS NULL) AND (revoked_at IS NULL) = (revoke_reason IS NULL)"
)
CHECK_REVOKE_REASON = "revoke_reason IS NULL OR length(btrim(revoke_reason)) > 0"


class AdmissionReviewSecretaryGrant(Base):
    """Quyền Thư ký Hội đồng của MỘT người. Không hết hạn (owner C1); hết hiệu lực khi Admin thu hồi hoặc tự thu hồi lúc
    tài khoản bị khoá / đổi sang vai không còn được gán (``review_secretary_service.auto_revoke_reason``)."""

    __tablename__ = "admission_review_secretary_grant"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, index=True)
    granted_by_user_id = Column(Integer, ForeignKey("user.id", ondelete="RESTRICT"), nullable=False, index=True)
    granted_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    reason = Column(Text, nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id = Column(Integer, ForeignKey("user.id", ondelete="RESTRICT"), nullable=True, index=True)
    revoke_reason = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(CHECK_REASON, name="ck_review_secretary_grant_reason"),
        CheckConstraint(CHECK_REVOKED_TRIPLE, name="ck_review_secretary_grant_revoked_triple"),
        CheckConstraint(CHECK_REVOKE_REASON, name="ck_review_secretary_grant_revoke_reason"),
        Index(
            "uq_review_secretary_grant_active_user",
            "user_id",
            unique=True,
            postgresql_where=text(ACTIVE_GRANT_WHERE),
        ),
    )

    def __repr__(self):
        return f"<AdmissionReviewSecretaryGrant id={self.id} user={self.user_id} active={self.revoked_at is None}>"
