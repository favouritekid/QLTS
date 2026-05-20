"""q9_07_e4a: profile_document supports priority_evidence category

Revision ID: q9_07_e4a
Revises: q9_07_e0c
Create Date: 2026-05-20

Q9 #07 Phase E.4 — Priority Workbench foundation. ProfileDocument table
trước đây chỉ chứa path documents (linked qua document_type_id FK). Phase
E.4 mở rộng để chứa cả UT evidence documents (linked qua priority_sub_code
text — không có ConfigDocumentType FK riêng vì catalog evidence là free
text trong PriorityObjectConfig.evidence_doc_type).

Changes:
1. ADD COLUMN category VARCHAR(40) NOT NULL DEFAULT 'path' — phân biệt
   path vs priority_evidence rows.
2. ADD COLUMN priority_sub_code VARCHAR(2) NULL — chỉ set khi
   category='priority_evidence'.
3. DROP NOT NULL document_type_id — priority_evidence rows không cần
   ConfigDocumentType FK.
4. DROP existing UNIQUE(profile_id, document_type_id) — không apply cho
   priority_evidence rows (document_type_id NULL).
5. ADD 2 partial UNIQUE indexes (1 cho mỗi category) — preserve
   path uniqueness contract + thêm priority uniqueness contract.
6. ADD CHECK ck_profile_document_category — restrict category enum.
7. ADD CHECK ck_priority_evidence_sub_code — đảm bảo priority_sub_code
   only set khi category='priority_evidence' và ngược lại.

Downtime: ADD COLUMN với DEFAULT trên PostgreSQL ≥ 11 là instant DDL,
không full table rewrite. DROP NOT NULL + DROP CONSTRAINT cũng metadata-
only. Tổng migration <1s, zero downtime.

Backfill: KHÔNG cần. Existing rows tự nhận DEFAULT 'path' (đúng nghiệp
vụ — tất cả profile_document hiện hữu đều là path documents).

Downgrade: reverse all changes — restore uq_profile_document + drop
2 partial indexes + drop CHECK constraints + drop columns + restore
NOT NULL document_type_id. Note: nếu có priority_evidence rows tại
thời điểm downgrade, NOT NULL restore sẽ fail — manually delete
priority_evidence rows trước hoặc skip restore NOT NULL.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers
revision: str = "q9_07_e4a"
down_revision: Union[str, None] = "q9_07_e0c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "profile_document",
        sa.Column(
            "category",
            sa.String(length=40),
            nullable=False,
            server_default=sa.text("'path'"),
            comment="path | priority_evidence",
        ),
    )
    op.add_column(
        "profile_document",
        sa.Column(
            "priority_sub_code",
            sa.String(length=2),
            nullable=True,
            comment="UT sub_code (e.g. '04','07') — only set when category='priority_evidence'",
        ),
    )

    op.alter_column(
        "profile_document",
        "document_type_id",
        existing_type=sa.Integer(),
        nullable=True,
    )

    op.drop_constraint("uq_profile_document", "profile_document", type_="unique")

    op.create_index(
        "uq_profile_document_path",
        "profile_document",
        ["profile_id", "document_type_id"],
        unique=True,
        postgresql_where=sa.text("category = 'path'"),
    )
    op.create_index(
        "uq_profile_document_priority",
        "profile_document",
        ["profile_id", "priority_sub_code"],
        unique=True,
        postgresql_where=sa.text("category = 'priority_evidence'"),
    )

    op.create_check_constraint(
        "ck_profile_document_category",
        "profile_document",
        "category IN ('path','priority_evidence')",
    )
    op.create_check_constraint(
        "ck_priority_evidence_sub_code",
        "profile_document",
        "(category = 'priority_evidence' AND priority_sub_code IS NOT NULL) "
        "OR (category <> 'priority_evidence' AND priority_sub_code IS NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_priority_evidence_sub_code", "profile_document", type_="check"
    )
    op.drop_constraint(
        "ck_profile_document_category", "profile_document", type_="check"
    )

    op.drop_index("uq_profile_document_priority", table_name="profile_document")
    op.drop_index("uq_profile_document_path", table_name="profile_document")

    op.create_unique_constraint(
        "uq_profile_document",
        "profile_document",
        ["profile_id", "document_type_id"],
    )

    op.alter_column(
        "profile_document",
        "document_type_id",
        existing_type=sa.Integer(),
        nullable=False,
    )

    op.drop_column("profile_document", "priority_sub_code")
    op.drop_column("profile_document", "category")
