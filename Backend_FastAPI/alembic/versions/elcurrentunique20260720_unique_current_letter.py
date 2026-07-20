"""enrollment_letter: ix_enrollment_letter_current thành UNIQUE

"Mỗi hồ sơ có ĐÚNG MỘT bản hiện hành" là bất biến mà docstring của migration
``elsuperseded20260719`` và cả giao diện đều tuyên bố — nhãn "bản hiện hành" /
"đã thay thế" trên danh sách chỉ có nghĩa nếu nó đúng. Nhưng bất biến đó trước
giờ CHỈ do application giữ: câu UPDATE đóng dấu ``superseded_at`` cho các bản
cũ chạy trong cùng transaction với INSERT bản mới, trong đúng một hàm.

Mọi writer đi vòng qua hàm đó đều phá được — bulk-issue, script phát lại,
migration backfill, hoặc đơn giản là hai request phát giấy đồng thời cho cùng
một hồ sơ. Hậu quả không phải lỗi kỹ thuật mà là hai tờ giấy cùng mang chữ ký
Hiệu trưởng, cùng được hệ thống gọi là "bản hiện hành", với số tiền hoặc cửa sổ
nhập học có thể khác nhau. Index UNIQUE để DB tự canh thì không lách được, và
với dữ liệu đã có thì hoàn toàn miễn phí (index đã tồn tại, chỉ đổi tính chất).

An toàn của lần đổi này (kiểm 20-07 trước khi viết):
  * production: bảng ``enrollment_letter`` CHƯA tồn tại (tính năng chưa deploy)
    → migration chạy trên bảng rỗng.
  * dev: 2 row / 1 hồ sơ, 0 hồ sơ có nhiều hơn một bản ``superseded_at IS NULL``.
Nếu môi trường nào đó đã lỡ có hồ sơ 2 bản hiện hành, ``CREATE UNIQUE INDEX`` sẽ
FAIL và dừng deploy — đúng hành vi mong muốn: đó là dữ liệu hỏng cần người xem,
không phải thứ để migration tự ý chọn bản nào đúng.

Revision ID: elcurrentunique20260720
Revises: elsuperseded20260719
Create Date: 2026-07-20
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "elcurrentunique20260720"
down_revision = "elsuperseded20260719"
branch_labels = None
depends_on = None

_INDEX = "ix_enrollment_letter_current"
_WHERE = "superseded_at IS NULL"


def upgrade() -> None:
    # DROP + CREATE thay vì tạo index thứ hai: giữ nguyên TÊN nên mọi thứ tham
    # chiếu tới nó (model, autogenerate) không thấy drift.
    op.drop_index(_INDEX, table_name="enrollment_letter")
    # ⚠️ ``postgresql_where`` PHẢI có. Thiếu nó thì index thành UNIQUE trên
    # TOÀN BỘ profile_id, tức mỗi hồ sơ chỉ được phát ĐÚNG MỘT giấy suốt đời —
    # lần phát thứ hai ném IntegrityError. Bản nháp đầu của chính migration này
    # đã đánh rơi mệnh đề đó.
    op.create_index(
        _INDEX,
        "enrollment_letter",
        ["profile_id"],
        unique=True,
        postgresql_where=sa.text(_WHERE),
    )


def downgrade() -> None:
    # Trả về index KHÔNG unique nhưng VẪN partial — đúng trạng thái do
    # ``elsuperseded20260719`` tạo ra, không phải một index toàn bảng.
    op.drop_index(_INDEX, table_name="enrollment_letter")
    op.create_index(
        _INDEX,
        "enrollment_letter",
        ["profile_id"],
        unique=False,
        postgresql_where=sa.text(_WHERE),
    )
