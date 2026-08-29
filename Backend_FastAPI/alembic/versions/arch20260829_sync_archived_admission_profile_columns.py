"""Đồng bộ `_archived_admission_profile` với 12 cột đã thêm vào `admission_profile`.

Vì sao cần
----------

`phase1_16` dựng bảng archive với một giao ước viết thẳng trong docstring của
nó::

    Mirror ALL columns of ``admission_profile`` exactly (types + nullability +
    server_default), so cron INSERT can ``SELECT * FROM admission_profile``
    without coercion.

Giao ước ấy đã trôi. Bảng archive có 65 cột, model `AdmissionProfile` có 76 —
lệch 12 cột (11 cột nghiệp vụ + `major_change_requested`), tất cả được thêm vào
bảng nguồn SAU khi `phase1_16` ship, và KHÔNG migration nào `add_column` sang
bảng archive để bù.

Hậu quả nếu để nguyên: `archive_expired_rounds_task` khi được nối (PLAN đang
DEFER sang Phase 3) sẽ chạy đúng câu `INSERT … SELECT * FROM admission_profile`
mà docstring hứa — và câu đó **đổ vì lệch số cột**. Nếu ai đó "sửa" bằng cách
liệt kê cột tường minh cho vừa bảng archive, thì tệ hơn: nó chạy trót lọt và
đánh rơi im lặng 12 cột, trong đó có toàn bộ dấu vết ưu tiên
(`priority_object_codes`, `priority_object_evidence`,
`priority_resolution_snapshot`, `area_resolution_basis`) — thứ duy nhất giải
thích được vì sao một hồ sơ cũ được cộng điểm như thế.

Trạng thái đo được lúc viết migration này (29-08-2026):

* Không nơi nào trong ``app/`` GHI vào bảng archive — chỉ có chú thích
  ``TODO``/``DEFER Phase 3`` ở ``app/models/lead.py:314,365`` và
  ``app/models/offering_admission_round.py:51,92``.
* Vì thế đây là rủi ro TIỀM ẨN, chưa phải mất dữ liệu đang xảy ra. Vá bây giờ
  vì bảng đang RỖNG là lúc rẻ nhất; để tới khi cron chạy rồi mới vá thì phải
  đi lấp dữ liệu đã rơi.

Ràng buộc giữ nguyên theo phase1_16
-----------------------------------

* KHÔNG khoá ngoại — archive phải sống lâu hơn hàng nguồn.
* KHÔNG unique, KHÔNG check — hàng archive ghi theo giao ước cũ không được
  phép bị từ chối khi giao ước hiện tại siết lại.
* Giữ đúng kiểu / nullability / server_default của bảng nguồn, để câu
  ``SELECT *`` khớp cột-đối-cột không cần ép kiểu.

Ba cột NOT NULL (`vocational_qualification`, `priority_object_codes`,
`priority_object_evidence`, `priority_resolution_snapshot`,
`major_change_requested`) đều mang server_default y hệt bản nguồn, nên
`ADD COLUMN … NOT NULL DEFAULT …` an toàn kể cả khi bảng đã có hàng.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "arch20260829"
down_revision: Union[str, None] = "ovp20260811"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "_archived_admission_profile"

# Khai cột NỘI TUYẾN trong từng ``op.add_column`` chứ không gom vào một danh
# sách module-level: ``tests/unit/test_phase1_16_archived_admission_profile.py``
# khoanh vùng bằng AST theo đúng lời gọi nhắm ``TABLE``, nên một danh sách nằm
# ngoài lời gọi sẽ không được đếm. Dạng nội tuyến giữ phép kiểm ấy chính xác —
# và cũng là dạng ``alembic revision --autogenerate`` sinh ra.
#
# Đặc tả lấy từ ``AdmissionProfile.__table__.columns`` (kiểu / nullability /
# server_default), không chép tay.
_TEN_COT = (
    "cultural_education_level",
    "vocational_qualification",
    "permanent_commune_code",
    "area_resolution_basis",
    "priority_object_codes",
    "priority_object_evidence",
    "priority_resolution_snapshot",
    "document_debt",
    "cached_completion",
    "cached_readiness",
    "cached_derived_at",
    "major_change_requested",
)


def _cot_hien_co() -> set:
    bind = op.get_bind()
    inspector = inspect(bind)
    if TABLE not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(TABLE)}


def upgrade() -> None:
    # Guard idempotent theo đúng khuôn phase1_16/phase1_19a: bảng có thể chưa
    # tồn tại, và cột có thể đã được thêm bởi một lần chạy trước — cả hai đều
    # không được làm migration đổ.
    hien_co = _cot_hien_co()
    if not hien_co:
        return

    if "cultural_education_level" not in hien_co:
        op.add_column(
            TABLE, sa.Column("cultural_education_level", sa.String(length=30), nullable=True)
        )
    if "vocational_qualification" not in hien_co:
        op.add_column(
            TABLE,
            sa.Column(
                "vocational_qualification",
                sa.String(length=30),
                nullable=False,
                server_default="none",
            ),
        )
    if "permanent_commune_code" not in hien_co:
        op.add_column(
            TABLE, sa.Column("permanent_commune_code", sa.String(length=20), nullable=True)
        )
    if "area_resolution_basis" not in hien_co:
        op.add_column(
            TABLE, sa.Column("area_resolution_basis", sa.String(length=40), nullable=True)
        )
    if "priority_object_codes" not in hien_co:
        op.add_column(
            TABLE,
            sa.Column(
                "priority_object_codes",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )
    if "priority_object_evidence" not in hien_co:
        op.add_column(
            TABLE,
            sa.Column(
                "priority_object_evidence",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )
    if "priority_resolution_snapshot" not in hien_co:
        op.add_column(
            TABLE,
            sa.Column(
                "priority_resolution_snapshot",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )
    if "document_debt" not in hien_co:
        op.add_column(
            TABLE,
            sa.Column("document_debt", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        )
    if "cached_completion" not in hien_co:
        op.add_column(TABLE, sa.Column("cached_completion", sa.SmallInteger(), nullable=True))
    if "cached_readiness" not in hien_co:
        op.add_column(
            TABLE, sa.Column("cached_readiness", sa.String(length=20), nullable=True)
        )
    if "cached_derived_at" not in hien_co:
        op.add_column(
            TABLE, sa.Column("cached_derived_at", sa.DateTime(timezone=True), nullable=True)
        )
    if "major_change_requested" not in hien_co:
        op.add_column(
            TABLE,
            sa.Column(
                "major_change_requested",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )


def downgrade() -> None:
    hien_co = _cot_hien_co()
    if not hien_co:
        return
    for ten in reversed(_TEN_COT):
        if ten in hien_co:
            op.drop_column(TABLE, ten)
