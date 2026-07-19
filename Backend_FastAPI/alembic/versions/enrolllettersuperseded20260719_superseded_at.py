"""enrollment_letter: cột superseded_at — phân biệt bản hiện hành / đã thay thế

Phát lại giấy cho cùng một hồ sơ tạo row MỚI (versioned history, cố ý). Nhưng
trước đây KHÔNG có gì đánh dấu bản nào còn hiệu lực: N bản đều mang chữ ký Hiệu
trưởng, đều tải lại được, đều "chính thức" ngang nhau. Khi thí sinh cầm bản A
đến trường mà hệ thống hiển thị bản C, không ai chứng minh được bản nào là bản
đã trao — và dữ liệu giữa hai bản có thể khác nhau thật (học phí đã đóng thêm,
ngành tính lại, cửa sổ nhập học đổi).

``superseded_at`` NULL = bản hiện hành. Khi phát bản mới, mọi bản trước của cùng
hồ sơ được đóng dấu thời điểm bị thay thế.

Index một phần trên (profile_id) WHERE superseded_at IS NULL: truy vấn thường
gặp là "bản hiện hành của hồ sơ này", và index chỉ chứa đúng các row đó.

Revision ID: elsuperseded20260719
Revises: enrolllettercasbin20260718
Create Date: 2026-07-19
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "elsuperseded20260719"
down_revision = "enrolllettercasbin20260718"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "enrollment_letter",
        sa.Column(
            "superseded_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="Thời điểm bị bản phát sau thay thế; NULL = bản hiện hành",
        ),
    )
    # Dữ liệu CŨ: mỗi hồ sơ giữ bản mới nhất làm hiện hành, các bản trước đó
    # đánh dấu đã thay thế theo đúng ngữ nghĩa mới (nếu không, mọi bản cũ sẽ
    # hiện ra như thể đều còn hiệu lực).
    op.execute(
        """
        UPDATE enrollment_letter el
        SET superseded_at = newer.generated_at
        FROM (
            SELECT e1.id AS old_id, MAX(e2.generated_at) AS generated_at
            FROM enrollment_letter e1
            JOIN enrollment_letter e2
              ON e2.profile_id = e1.profile_id
             AND e2.generated_at > e1.generated_at
            GROUP BY e1.id
        ) AS newer
        WHERE el.id = newer.old_id
        """
    )
    op.create_index(
        "ix_enrollment_letter_current",
        "enrollment_letter",
        ["profile_id"],
        unique=False,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_enrollment_letter_current", table_name="enrollment_letter")
    op.drop_column("enrollment_letter", "superseded_at")
