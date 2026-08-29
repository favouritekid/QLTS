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

GIAO ƯỚC GHI ARCHIVE — SỬA LẠI CHO ĐÚNG THỰC ĐO
--------------------------------------------------

Docstring của `phase1_16` hứa parity đủ mạnh để cron ghi bằng
``INSERT INTO archive SELECT * FROM admission_profile``. Lời hứa đó SAI, và
sai từ trước bản vá này — đo read-only trên PostgreSQL dev (29-08-2026):

* THỨ TỰ CỘT KHÁC NHAU: 62 trên 64 cột chung nằm ở ordinal_position khác.
  Ngay cột thứ 3 đã lệch — nguồn là ``citizen_id``, archive là
  ``offering_admission_config_id``.
* ``archived_at`` nằm ở vị trí 65, nên 12 cột migration này thêm vào rơi
  xuống 66..77, tức SAU cột metadata chứ không phải trước.
* ``server_default`` của ``id`` / ``created_at`` / ``updated_at`` KHÁC bản
  nguồn, và khác một cách CỐ Ý: hàng archive phải giữ nguyên dấu thời gian
  và id của hàng gốc, không được sinh lại bằng ``now()`` / ``nextval()``.

HẬU QUẢ THẬT — đo, không suy. Phân loại 63 cặp cột theo vị trí:

  49 cặp  kiểu KHÔNG tương thích  -> Postgres TỪ CHỐI cả câu lệnh
  12 cặp  kiểu tương thích        -> ghi được, và ghi SAI
   2 cặp  khớp tên (id, lead_id)

Nên hôm nay ``SELECT *`` KHÔNG gây hỏng im lặng — nó làm archive job ĐỔ.
Cặp lệch đầu tiên đã đủ::

    ERROR: column "offering_admission_config_id" is of type integer
           but expression is of type character varying

(Trước khi migration này áp, lỗi còn đến sớm hơn ở tầng số lượng: 65 cột
đích so với 77 biểu thức.)

Nhưng đừng đọc điều đó thành "vô hại". 12 cặp còn lại tương thích kiểu, và
ở những cặp ấy Postgres ghi IM LẶNG — đã dựng bản thu nhỏ và đo: hai cột
``varchar`` hoán vị cho ``INSERT 0 1``, không lỗi, giá trị đổi chỗ. Vì thế
lối "sửa" nguy hiểm nhất là thêm ``CAST`` cho vừa bộ kiểu: nó dập tắt đúng
49 cặp đang kêu và để nguyên 12 cặp ghi sai.

Cách sửa đúng là liệt kê CỘT ĐÍCH TƯỜNG MINH, không phải thêm cast. Bất kỳ
đường ghi archive nào — cron ``archive_expired_rounds_task`` hay sửa tay —
BẮT BUỘC viết::

    INSERT INTO _archived_admission_profile (id, lead_id, ...)
    SELECT id, lead_id, ... FROM admission_profile WHERE ...

Cái parity thật sự tồn tại, và là cái migration này khôi phục, là parity
THEO TÊN: mọi cột của ``admission_profile`` đều có mặt trong bảng archive
với CÙNG kiểu, cùng độ dài và cùng nullability. Đã đo: sau bản vá này không
còn cột chung nào lệch ba thuộc tính ấy. Đó chính là điều kiện đủ cho câu
INSERT liệt kê cột ở trên.

``tests/unit/test_phase1_16_archived_admission_profile.py`` khoá cả hai
chiều: parity theo tên/kiểu/nullable, và CẤM mọi ``SELECT *`` ghi vào bảng
archive.

Ràng buộc giữ nguyên theo phase1_16
-----------------------------------

* KHÔNG khoá ngoại — archive phải sống lâu hơn hàng nguồn.
* KHÔNG unique, KHÔNG check — hàng archive ghi theo giao ước cũ không được
  phép bị từ chối khi giao ước hiện tại siết lại.
* Giữ đúng kiểu / nullability của bảng nguồn (KHÔNG phải server_default —
  xem phần giao ước ở trên), để câu INSERT liệt kê cột tường minh khớp
  cột-đối-cột mà không cần ép kiểu.

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


class BangArchiveThieu(RuntimeError):
    """Bảng archive không tồn tại lúc migration này chạy.

    KHÔNG được nuốt: `phase1_16` (tổ tiên trong chuỗi) luôn tạo bảng, nên bảng
    thiếu nghĩa là schema đích đã bị can thiệp ngoài luồng. Nếu chỉ `return`
    thì Alembic vẫn ghi `arch20260829` vào `alembic_version` và báo thành công
    trong khi KHÔNG cột nào được thêm — đúng lớp lỗi "lệnh trả 0 mà việc không
    xảy ra". Lần chạy sau sẽ bỏ qua revision này vĩnh viễn vì nó đã được đánh
    dấu là đã áp.
    """


def _cot_hien_co() -> set:
    """Bộ cột hiện có của bảng archive. NÉM nếu bảng không tồn tại.

    Phân biệt rõ HAI trạng thái, đừng gộp:
      - bảng THIẾU        -> lỗi, dừng migration (hàm này ném)
      - bảng CÓ, cột đã có -> bỏ qua đúng cột đó (người gọi kiểm từng cột)
    """
    bind = op.get_bind()
    inspector = inspect(bind)
    if TABLE not in inspector.get_table_names():
        raise BangArchiveThieu(
            f"Bảng {TABLE!r} không tồn tại. Nó phải được tạo bởi `phase1_16`, "
            "là tổ tiên của revision này. Không thêm cột nào, và KHÔNG đánh dấu "
            "revision là đã áp — hãy kiểm lại lịch sử alembic của CSDL đích."
        )
    return {c["name"] for c in inspector.get_columns(TABLE)}


def upgrade() -> None:
    # Guard idempotent theo đúng khuôn phase1_16/phase1_19a: bảng có thể chưa
    # tồn tại, và cột có thể đã được thêm bởi một lần chạy trước — cả hai đều
    # không được làm migration đổ.
    hien_co = _cot_hien_co()

    if "cultural_education_level" not in hien_co:
        op.add_column(
            TABLE,
            sa.Column(
                "cultural_education_level", sa.String(length=30), nullable=True
            ),
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
            TABLE,
            sa.Column(
                "permanent_commune_code", sa.String(length=20), nullable=True
            ),
        )
    if "area_resolution_basis" not in hien_co:
        op.add_column(
            TABLE,
            sa.Column(
                "area_resolution_basis", sa.String(length=40), nullable=True
            ),
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
            sa.Column(
                "document_debt",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
        )
    if "cached_completion" not in hien_co:
        op.add_column(
            TABLE, sa.Column("cached_completion", sa.SmallInteger(), nullable=True)
        )
    if "cached_readiness" not in hien_co:
        op.add_column(
            TABLE, sa.Column("cached_readiness", sa.String(length=20), nullable=True)
        )
    if "cached_derived_at" not in hien_co:
        op.add_column(
            TABLE,
            sa.Column(
                "cached_derived_at", sa.DateTime(timezone=True), nullable=True
            ),
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
    for ten in reversed(_TEN_COT):
        if ten in hien_co:
            op.drop_column(TABLE, ten)
