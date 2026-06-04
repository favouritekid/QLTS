"""gdpt01: seed doc type giay_cn_hoan_thanh_gdpt (PR #10)

Revision ID: gdpt01
Revises: gppenddip01
Create Date: 2026-06-04

PR #10 — người TRƯỢT tốt nghiệp THPT (``cultural_education_level =
'completed_thpt'``) nộp Giấy chứng nhận hoàn thành chương trình GDPT THAY cho
Bằng tốt nghiệp THPT (đã bị ``_COMPLETED_DIPLOMA_TO_REMOVE`` loại). Đối xứng
với việc loại bằng: ``_COMPLETED_DIPLOMA_TO_ADD`` thêm doc type này khi
re-resolve cho hồ sơ ``completed_thpt``.

Chỉ seed doc type (1 row config_document_type). KHÔNG tạo DocumentGroupItem —
giấy GDPT được caller dựng thành ResolvedDocumentResponse synthetic
(is_mandatory=True, requires_upload=False, paper-only) tại
``admission_path_service.resolve_documents_for_profile``.

Idempotent ``INSERT ... ON CONFLICT (code) DO NOTHING``. ``name`` độc nhất
(cột UNIQUE). Downgrade non-destructive: chỉ xoá row CHƯA được tham chiếu
bởi profile_document / document_group_item (giữ an toàn dữ liệu thật).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "gdpt01"
down_revision: Union[str, None] = "gppenddip01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CODE = "giay_cn_hoan_thanh_gdpt"
_NAME = "Giấy chứng nhận hoàn thành chương trình GDPT"
_DESC = (
    "Cấp cho thí sinh đã hoàn thành chương trình GDPT nhưng chưa tốt nghiệp "
    "THPT (thay cho Bằng tốt nghiệp THPT)."
)
# Cạnh Bằng tốt nghiệp THPT trong thứ tự hiển thị (paper-only, nhóm bằng cấp).
_DISPLAY_ORDER = 45


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            """
            INSERT INTO config_document_type
                (code, name, description, display_order, is_active)
            VALUES (:code, :name, :desc, :display_order, TRUE)
            ON CONFLICT (code) DO NOTHING
            """
        ),
        {
            "code": _CODE,
            "name": _NAME,
            "desc": _DESC,
            "display_order": _DISPLAY_ORDER,
        },
    )
    print(f"[gdpt01] Seeded {result.rowcount} doc type row(s) ({_CODE}).")


def downgrade() -> None:
    conn = op.get_bind()
    # Non-destructive: only drop the seed row if nothing references it yet
    # (no profile_document / document_group_item points at it). Real data
    # created after the seed is preserved.
    result = conn.execute(
        sa.text(
            """
            DELETE FROM config_document_type t
            WHERE t.code = :code
              AND NOT EXISTS (
                  SELECT 1 FROM profile_document pd
                  WHERE pd.document_type_id = t.id
              )
              AND NOT EXISTS (
                  SELECT 1 FROM document_group_item gi
                  WHERE gi.document_type_id = t.id
              )
            """
        ),
        {"code": _CODE},
    )
    print(f"[gdpt01] Removed {result.rowcount} unreferenced doc type row(s).")
