"""PR #13 — graduation_proof_kind + supplement_due_date trên profile_document.

Phân biệt **Bằng tốt nghiệp THPT chính thức** vs **Giấy CN tốt nghiệp tạm
thời** (Phương án C). Officer khi tick "đã nhận" giấy `bang_tot_nghiep_thpt`
chọn loại; `provisional_cert` → nhập hạn bổ sung bằng chính thức. Cho phép
truy vấn hồ sơ "còn nợ bằng" để nhắc.

- 2 cột mới trên `profile_document` (KHÔNG đụng `applied_rules`):
  * `graduation_proof_kind` String(20) — official_diploma|provisional_cert
  * `supplement_due_date` Date — chỉ set khi kind=provisional_cert
- 2 CHECK constraint giữ invariant (kind hợp lệ; due chỉ khi provisional).
- Data migration: đổi `config_document_type.name` của `bang_tot_nghiep_thpt`
  thành "Bằng tốt nghiệp THPT / Giấy CN tốt nghiệp tạm thời" để officer hiểu
  mục này nhận cả 2 loại giấy. Idempotent (WHERE code); downgrade revert.

Revision ID: gpkind01
Revises: ardockeys01
Create Date: 2026-06-04
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "gpkind01"
down_revision: Union[str, None] = "ardockeys01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


GRAD_DOC_CODE = "bang_tot_nghiep_thpt"
NEW_LABEL = "Bằng tốt nghiệp THPT / Giấy CN tốt nghiệp tạm thời"
OLD_LABEL = "Bằng tốt nghiệp THPT"


def upgrade() -> None:
    op.add_column(
        "profile_document",
        sa.Column(
            "graduation_proof_kind",
            sa.String(length=20),
            nullable=True,
            comment="official_diploma | provisional_cert (NULL nếu N/A)",
        ),
    )
    op.add_column(
        "profile_document",
        sa.Column(
            "supplement_due_date",
            sa.Date(),
            nullable=True,
            comment="Hạn bổ sung bằng — chỉ set khi kind='provisional_cert'",
        ),
    )
    op.create_check_constraint(
        "ck_graduation_proof_kind",
        "profile_document",
        "graduation_proof_kind IS NULL "
        "OR graduation_proof_kind IN ('official_diploma','provisional_cert')",
    )
    op.create_check_constraint(
        "ck_supplement_due_only_provisional",
        "profile_document",
        "supplement_due_date IS NULL "
        "OR graduation_proof_kind = 'provisional_cert'",
    )
    # Data: đổi label doc type (idempotent theo code).
    op.execute(
        sa.text(
            "UPDATE config_document_type SET name = :new WHERE code = :code"
        ).bindparams(new=NEW_LABEL, code=GRAD_DOC_CODE)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE config_document_type SET name = :old WHERE code = :code"
        ).bindparams(old=OLD_LABEL, code=GRAD_DOC_CODE)
    )
    op.drop_constraint(
        "ck_supplement_due_only_provisional", "profile_document", type_="check"
    )
    op.drop_constraint(
        "ck_graduation_proof_kind", "profile_document", type_="check"
    )
    op.drop_column("profile_document", "supplement_due_date")
    op.drop_column("profile_document", "graduation_proof_kind")
