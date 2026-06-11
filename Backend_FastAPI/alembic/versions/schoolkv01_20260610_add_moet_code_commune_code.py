"""vn_school: add moet_code + commune_code (khóa đối chiếu MOET/QĐ19-2025)

Revision ID: schoolkv01_20260610
Revises: optdocmat01_20260610
Create Date: 2026-06-10

Thêm 2 cột khóa đối chiếu cho ``vn_school``, phục vụ rebuild KV trường từ danh
sách THPT chính thức của MOET (file XLS có Khu Vực + Mã Xã theo QĐ 19/2025) và
đối chiếu ổn định cho các lần cập nhật năm sau:

- ``moet_code``    : mã chính thức = Mã Tỉnh (GSO, 2 số) + Mã Trường (3 số) = 5
                     số (vd '66006' = THPT Buôn Ma Thuột). DUY NHẤT toàn quốc
                     trong danh sách MOET. Khóa đối chiếu CHÍNH cho năm sau.
- ``commune_code`` : mã xã 5 số (= Mã Xã[:5] của XLS, khớp 98%
                     administrative_nodes.code hiện hành). Khóa PHỤ: fallback
                     (commune_code + tên) khi MOET đổi số trường, đồng thời nối
                     trường → xã để reconcile vn_commune_area_map.

Cả 2 nullable (backfill bằng script rebuild_school_kv_from_xls.py, không chặn
dữ liệu cũ). KHÔNG unique-constraint cứng ở DB: dữ liệu hiện có nhiều bản ghi
cũ/dup chưa chuẩn hóa (trước/từ rename) → unique sẽ vỡ; dedup/chuẩn hóa do
script xử lý trước, ràng buộc unique để PR sau khi data đã sạch. Chỉ thêm INDEX
để tra nhanh.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "schoolkv01_20260610"
down_revision: Union[str, None] = "optdocmat01_20260610"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vn_school",
        sa.Column(
            "moet_code",
            sa.String(length=8),
            nullable=True,
            comment=(
                "Mã chính thức MOET = Mã Tỉnh(GSO 2) + Mã Trường(3); "
                "khóa đối chiếu chính"
            ),
        ),
    )
    op.add_column(
        "vn_school",
        sa.Column(
            "commune_code",
            sa.String(length=10),
            nullable=True,
            comment=(
                "Mã xã 5 số (QĐ 19/2025, = administrative_nodes.code); "
                "khóa phụ + nối xã"
            ),
        ),
    )
    op.create_index("ix_vn_school_moet_code", "vn_school", ["moet_code"])
    op.create_index("ix_vn_school_commune_code", "vn_school", ["commune_code"])


def downgrade() -> None:
    op.drop_index("ix_vn_school_commune_code", table_name="vn_school")
    op.drop_index("ix_vn_school_moet_code", table_name="vn_school")
    op.drop_column("vn_school", "commune_code")
    op.drop_column("vn_school", "moet_code")
