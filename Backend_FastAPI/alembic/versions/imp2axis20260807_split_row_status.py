"""payment_import_row: tách trạng thái KIỂM và trạng thái GHI thành hai trục

Một cột ``status`` với ba giá trị ``matched|warned|error`` đang phải trả lời ba
câu hỏi khác hẳn nhau: dòng này đọc có hợp lệ không, đã ghi tiền chưa, và có
được thử lại không. Trộn chúng lại sinh ra đúng hai lỗi đã gặp:

  * một dòng ĐÃ ghi tiền vẫn mang ``warned``, nên nó vẫn nằm trong tập "chọn
    lại ở lượt sau" và suýt được ghi lần hai;
  * ``failed_count`` cộng dồn theo từng LƯỢT THỬ, nên một dòng bị hàng rào giữ
    lại được đếm cả vào ``warned_count`` lẫn ``failed_count`` — lô #5 trên máy
    dev có đúng một dòng mà sổ ghi thành hai.

Nay hai trục, mỗi trục trả lời đúng một câu hỏi:

  ``validation_status``  matched | warned | error
      Đọc/đối chiếu dòng có ra kết quả dùng được không. KHÔNG đổi sau bước xem
      trước.

  ``commit_status``      pending | duplicate_review_required | committed
                       | failed | not_applicable
      Số phận của dòng ở bước ghi tiền. ``not_applicable`` dành riêng cho dòng
      hỏng từ khâu đọc — nó không có gì để ghi, nên xếp nó vào "chưa ghi" là
      nói rằng nó đang chờ, còn xếp vào "ghi hỏng" là đổ lỗi cho bước ghi.

Bảng chân trị (mọi tổ hợp khác là dữ liệu sai, xem CHECK bên dưới):

  | validation | commit                     | nghĩa                          |
  |------------|----------------------------|--------------------------------|
  | error      | not_applicable             | hỏng từ khâu đọc               |
  | matched    | pending                    | chờ lượt ghi                   |
  | matched    | committed                  | đã ghi                         |
  | matched    | failed                     | thử ghi rồi hỏng               |
  | warned     | pending                    | có cảnh báo, vẫn chờ ghi       |
  | warned     | duplicate_review_required  | hàng rào giữ lại, chờ xác nhận |
  | warned     | committed                  | có cảnh báo NHƯNG đã ghi       |
  | warned     | failed                     | thử ghi rồi hỏng               |

Hai họ đếm riêng ở cấp lô, mỗi họ tự cộng đúng bằng ``row_count``: trộn chúng
là quay lại đúng chỗ ``warned_count + failed_count`` đếm một dòng hai lần.

**Backfill fail-closed.** Chỉ ba nhánh, tất cả suy từ dữ liệu CỨNG:

  * có ``payment_ids`` thật  → ``committed`` (tiền đã vào, không được thử lại);
  * ``validation_status='error'`` → ``not_applicable``;
  * còn lại                  → ``pending``.

KHÔNG suy ``duplicate_review_required`` từ ``warned`` hay từ câu chữ trong
``message``: đoán một dòng "đang chờ xác nhận" là dựng lại một challenge mà
không ai còn giữ phiếu tương ứng, và phiếu cũ (nếu có) đã hết hiệu lực theo
``guard_version`` rồi. Dòng nào thật sự còn bị chặn sẽ tự lộ ra ở lượt ghi kế
tiếp và được cấp phiếu mới.

Revision ID: imp2axis20260807
Revises: dupguard20260807
"""
from alembic import op
import sqlalchemy as sa

revision = "imp2axis20260807"
down_revision = "dupguard20260807"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Trục KIỂM: đổi tên cột cũ. Đổi tên chứ không thêm cột mới rồi chép:
    # dữ liệu giữ nguyên, và không có khoảnh khắc nào hai cột cùng tồn tại để
    # ai đó đọc nhầm cái rỗng.
    op.alter_column(
        "payment_import_row", "status", new_column_name="validation_status"
    )
    op.execute(
        "ALTER TABLE payment_import_row "
        "RENAME CONSTRAINT chk_payment_import_row_status "
        "TO chk_payment_import_row_validation_status"
    )
    op.execute(
        "COMMENT ON COLUMN payment_import_row.validation_status IS "
        "'Kết quả ĐỌC/ĐỐI CHIẾU dòng: matched|warned|error. Không đổi sau bước "
        "xem trước — số phận ở bước ghi nằm ở commit_status.'"
    )

    # ── Trục GHI.
    op.add_column(
        "payment_import_row",
        sa.Column(
            "commit_status",
            sa.String(28),
            nullable=False,
            server_default="pending",
            comment=(
                "Số phận ở bước ghi tiền: pending | duplicate_review_required | "
                "committed | failed | not_applicable. `committed` là quyền quyết "
                "định việc KHÔNG thử lại — khoá idempotency của Payment chỉ là "
                "hàng rào phụ."
            ),
        ),
    )

    op.add_column(
        "payment_import_row",
        sa.Column(
            "duplicate_review_token",
            sa.Text(),
            nullable=True,
            comment=(
                "Phiếu xác nhận nghi trùng do máy chủ cấp cho dòng này ở cuối "
                "lượt ghi. Giao diện gửi lại nguyên văn. Không backfill: phiếu "
                "cũ (nếu từng có) đã hết hiệu lực theo guard_version."
            ),
        ),
    )

    # Backfill — ba nhánh, thứ tự có ý nghĩa: `committed` xét TRƯỚC, vì một dòng
    # đã có tiền thì không được rơi vào bất kỳ nhóm "có thể thử lại" nào.
    op.execute(
        """
        UPDATE payment_import_row
        SET commit_status = 'committed'
        -- CASE chứ không phải `AND` nối tiếp: PostgreSQL KHÔNG hứa thứ tự đánh
        -- giá các vế `AND`, nên planner có quyền chạy `jsonb_array_length`
        -- trước phép kiểm kiểu và vỡ với "cannot get array length of a scalar"
        -- ngay khi có một dòng `payment_ids` không phải mảng. Đã vỡ thật.
        WHERE CASE
            WHEN payment_ids IS NULL THEN false
            WHEN jsonb_typeof(payment_ids) <> 'array' THEN false
            ELSE jsonb_array_length(payment_ids) > 0
        END
        """
    )
    op.execute(
        """
        UPDATE payment_import_row
        SET commit_status = 'not_applicable'
        WHERE validation_status = 'error' AND commit_status <> 'committed'
        """
    )

    op.create_check_constraint(
        "chk_payment_import_row_commit_status",
        "payment_import_row",
        "commit_status IN ('pending', 'duplicate_review_required', "
        "'committed', 'failed', 'not_applicable')",
    )
    # Bảng chân trị ở tầng cơ sở dữ liệu, không chỉ trong tài liệu. Hai tổ hợp
    # vô nghĩa nhất bị chặn cứng: dòng hỏng-từ-khâu-đọc mà lại "đang chờ ghi",
    # và dòng đọc-được mà lại "không có gì để ghi".
    op.create_check_constraint(
        "chk_payment_import_row_two_axes",
        "payment_import_row",
        "(validation_status = 'error') = (commit_status = 'not_applicable')",
    )
    # `committed` ⟺ CÓ mã phiếu — hai chiều. Một dòng "đã ghi" không mã phiếu
    # là mất dấu tiền; một dòng có mã phiếu mà chưa `committed` là tiền đã vào
    # nhưng vẫn nằm trong tập chọn lại. Service đặt hai thứ trong cùng savepoint,
    # nhưng một lần sửa SQL lúc chữa dữ liệu thì không đi qua service.
    # `CASE`, không phải `AND` nối tiếp — cùng dạng biểu thức với backfill ở
    # trên. Ở CHECK thì bản `AND` không vỡ (đã đo: expression short-circuit
    # trái→phải); nó vỡ ở *qual*, tức đúng chỗ backfill đứng. Viết `CASE` cả ở
    # đây để một biểu thức chỉ có MỘT dạng — lần sao chép tiếp theo sang qual sẽ
    # không mang theo cái bẫy.
    op.create_check_constraint(
        "chk_payment_import_row_committed_has_payments",
        "payment_import_row",
        "(commit_status = 'committed') = "
        "(CASE "
        " WHEN payment_ids IS NULL THEN false "
        " WHEN jsonb_typeof(payment_ids) <> 'array' THEN false "
        " ELSE jsonb_array_length(payment_ids) > 0 "
        "END)",
    )
    # `duplicate_review_required` chỉ có nghĩa với dòng CÓ cảnh báo. Dòng
    # `matched` mà "chờ xác nhận trùng" là một trạng thái không ai đọc được.
    op.create_check_constraint(
        "chk_payment_import_row_review_needs_warn",
        "payment_import_row",
        "commit_status <> 'duplicate_review_required' "
        "OR validation_status = 'warned'",
    )

    # ── Họ đếm thứ hai ở cấp lô. Ba cột cũ (matched/warned/failed) giữ nguyên
    # nghĩa KIỂM; bốn cột này nói về GHI. Mỗi họ tự cộng bằng `row_count`.
    for ten, chu_thich in (
        ("committed_row_count", "Số dòng đã ghi được tiền"),
        (
            "review_required_count",
            "Số dòng bị hàng rào nghi trùng giữ lại, đang chờ xác nhận",
        ),
        ("commit_failed_count", "Số dòng đã thử ghi và hỏng"),
        (
            "not_applicable_count",
            "Số dòng hỏng từ khâu đọc — không có gì để ghi",
        ),
    ):
        op.add_column(
            "payment_import_batch",
            sa.Column(
                ten,
                sa.Integer(),
                nullable=False,
                server_default="0",
                comment=chu_thich,
            ),
        )

    # Backfill họ đếm mới từ trạng thái dòng THỰC TẾ, không cộng dồn gì cả.
    op.execute(
        """
        UPDATE payment_import_batch b SET
            committed_row_count = d.committed,
            review_required_count = d.review_required,
            commit_failed_count = d.failed,
            not_applicable_count = d.na
        FROM (
            SELECT batch_id,
                   count(*) FILTER (WHERE commit_status = 'committed') AS committed,
                   count(*) FILTER (WHERE commit_status = 'duplicate_review_required') AS review_required,
                   count(*) FILTER (WHERE commit_status = 'failed') AS failed,
                   count(*) FILTER (WHERE commit_status = 'not_applicable') AS na
            FROM payment_import_row GROUP BY batch_id
        ) d
        WHERE b.id = d.batch_id
        """
    )
    # Và đếm lại luôn họ KIỂM: `failed_count` cũ được cộng dồn theo từng lượt
    # thử nên nó đang nói sai về chính những lô đã đóng.
    op.execute(
        """
        UPDATE payment_import_batch b SET
            matched_count = d.matched,
            warned_count = d.warned,
            failed_count = d.error
        FROM (
            SELECT batch_id,
                   count(*) FILTER (WHERE validation_status = 'matched') AS matched,
                   count(*) FILTER (WHERE validation_status = 'warned') AS warned,
                   count(*) FILTER (WHERE validation_status = 'error') AS error
            FROM payment_import_row GROUP BY batch_id
        ) d
        WHERE b.id = d.batch_id
        """
    )


def downgrade() -> None:
    for ten in (
        "committed_row_count",
        "review_required_count",
        "commit_failed_count",
        "not_applicable_count",
    ):
        op.execute(f"ALTER TABLE payment_import_batch DROP COLUMN IF EXISTS {ten}")

    for ten in (
        "chk_payment_import_row_review_needs_warn",
        "chk_payment_import_row_committed_has_payments",
        "chk_payment_import_row_two_axes",
        "chk_payment_import_row_commit_status",
    ):
        op.execute(f"ALTER TABLE payment_import_row DROP CONSTRAINT IF EXISTS {ten}")
    op.execute(
        "ALTER TABLE payment_import_row DROP COLUMN IF EXISTS duplicate_review_token"
    )
    op.execute("ALTER TABLE payment_import_row DROP COLUMN IF EXISTS commit_status")
    op.execute(
        "ALTER TABLE payment_import_row "
        "RENAME CONSTRAINT chk_payment_import_row_validation_status "
        "TO chk_payment_import_row_status"
    )
    op.alter_column(
        "payment_import_row", "validation_status", new_column_name="status"
    )
