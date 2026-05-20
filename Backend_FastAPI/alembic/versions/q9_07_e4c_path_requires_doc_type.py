"""q9_07_e4c: enforce category='path' => document_type_id IS NOT NULL

Revision ID: q9_07_e4c
Revises: q9_07_e4b
Create Date: 2026-05-20

Q9 #07 Phase E.4 — hardening sau audit. Migration q9_07_e4a relaxed
``document_type_id`` thành ``nullable=True`` để cho phép category='priority_
evidence' rows (không có ConfigDocumentType FK). Tuy nhiên invariant cũ
"path documents PHẢI có document_type_id" bị mất theo:

- DB chỉ còn FK nullable + CHECK riêng cho ``priority_sub_code``.
- Postgres unique index cho phép multiple NULLs → partial unique
  `uq_profile_document_path(profile_id, document_type_id) WHERE
  category='path'` KHÔNG block multiple path rows với
  document_type_id=NULL (UNIQUE NULL semantics).
- Code path mới (Phase E.4 upload PR-2) phải pass đúng document_type_id;
  nhưng nếu legacy code path lỡ insert path row thiếu document_type_id,
  DB sẽ accept silent → orphan path row, broken invariant.

Fix: thêm CHECK ``ck_path_requires_doc_type`` enforce hard invariant
cho path category. priority_evidence rows không bị ràng buộc (vẫn cho
phép NULL document_type_id since không có FK target).

Invariant matrix sau migration:
| category         | document_type_id | priority_sub_code |
|------------------|------------------|-------------------|
| path             | NOT NULL         | NULL (ck_priority_evidence_sub_code) |
| priority_evidence| any (typically NULL) | NOT NULL (ck_priority_evidence_sub_code) |

Downtime: metadata-only DDL (CHECK constraint), zero downtime.
Existing rows: tất cả path rows hiện hữu đã có document_type_id NOT NULL
(legacy invariant) → migration không break existing data.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers
revision: str = "q9_07_e4c"
down_revision: Union[str, None] = "q9_07_e4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_path_requires_doc_type",
        "profile_document",
        "category <> 'path' OR document_type_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_path_requires_doc_type",
        "profile_document",
        type_="check",
    )
