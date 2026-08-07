"""fee.duplicate_guard_version — điểm tuần tự hoá của hàng rào nghi trùng

Một số nguyên tăng dần trên mỗi hàng ``fee``, do TRIGGER cập nhật mỗi khi có
thứ gì có thể làm đổi tập phiếu nghi trùng của khoản phí đó:

  * ``payment`` được thêm, xoá, hoặc đổi ``invoice_id`` / ``amount`` /
    ``payment_date`` / ``status``;
  * ``refund_request`` được thêm, xoá, hoặc đổi ``status`` / ``amount`` —
    hoàn đủ tiền thì một phiếu thôi không còn là ứng viên.

Vì sao TRIGGER chứ không phải một dòng Python trong service: cái ta cần bảo
đảm là "KHÔNG có đường nào ghi phiếu mà không tăng version", và một quy ước ở
tầng service chỉ đúng cho tới khi ai đó viết đường thứ tư. Có bốn đường tạo
``Payment`` trong repo này rồi, cộng với các lần sửa tay bằng SQL lúc chữa dữ
liệu. Trigger là chỗ duy nhất không ai đi vòng được.

Hệ quả về khoá — cố ý: trigger ``UPDATE fee`` nên mọi giao dịch ghi phiếu của
cùng một khoản phí đều phải xếp hàng sau khoá hàng ``fee``. Đó chính là thứ
biến "version" thành một điểm tuần tự hoá thật, thay vì một con số đếm cho
vui. Ba đường ghi phiếu hiện có đều đã khoá ``invoice`` rồi ``fee`` trước khi
chạm ``payment``, tức cùng chiều — trigger không tạo ra thứ tự khoá mới.

Backfill về 1 cho mọi hàng sẵn có: giá trị tuyệt đối không mang ý nghĩa gì,
chỉ có "đổi hay không đổi" mới có. Bắt đầu từ 1 (không phải 0) để một cột
``NULL`` đọc nhầm thành 0 không tình cờ khớp với một token nào đó.

Revision ID: dupguard20260807
Revises: dbte20260803002
"""
from alembic import op
import sqlalchemy as sa

revision = "dupguard20260807"
down_revision = "dbte20260803002"
branch_labels = None
depends_on = None


# Hàm trigger dùng chung cho cả hai bảng. `fee_id` lấy khác nhau nên tách hai
# hàm nhỏ thay vì một hàm với `TG_TABLE_NAME` — rẻ hơn khi đọc, và mỗi hàm chỉ
# nói về đúng một bảng.
_FN_PAYMENT = """
CREATE OR REPLACE FUNCTION bump_duplicate_guard_from_payment()
RETURNS TRIGGER AS $$
DECLARE
    ma_fee_cu  INTEGER;
    ma_fee_moi INTEGER;
BEGIN
    -- Đọc fee qua invoice: `payment` không giữ `fee_id`.
    IF (TG_OP = 'DELETE' OR TG_OP = 'UPDATE') THEN
        SELECT i.fee_id INTO ma_fee_cu FROM invoice i WHERE i.id = OLD.invoice_id;
    END IF;
    IF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
        SELECT i.fee_id INTO ma_fee_moi FROM invoice i WHERE i.id = NEW.invoice_id;
    END IF;

    -- Phiếu chuyển từ hoá đơn của khoản phí này sang khoản phí khác thì CẢ HAI
    -- tập ứng viên đều đổi. Bỏ sót vế cũ là để lại một token còn hiệu lực cho
    -- một tập đã khác.
    IF ma_fee_cu IS NOT NULL THEN
        UPDATE fee SET duplicate_guard_version = duplicate_guard_version + 1
        WHERE id = ma_fee_cu;
    END IF;
    IF ma_fee_moi IS NOT NULL AND ma_fee_moi IS DISTINCT FROM ma_fee_cu THEN
        UPDATE fee SET duplicate_guard_version = duplicate_guard_version + 1
        WHERE id = ma_fee_moi;
    END IF;

    RETURN NULL;  -- AFTER trigger, giá trị trả về bị bỏ qua
END;
$$ LANGUAGE plpgsql;
"""

_FN_REFUND = """
CREATE OR REPLACE FUNCTION bump_duplicate_guard_from_refund()
RETURNS TRIGGER AS $$
DECLARE
    ma_fee_cu  INTEGER;
    ma_fee_moi INTEGER;
BEGIN
    -- Lấy RIÊNG vế cũ và vế mới, không COALESCE. `COALESCE(NEW, OLD)` luôn
    -- chọn NEW ở một `UPDATE`, nên một yêu cầu hoàn chuyển sang phiếu khác chỉ
    -- làm version của khoản phí MỚI nhích. Khoản phí CŨ vừa có một phiếu quay
    -- lại tập ứng viên (không còn được hoàn nữa) mà token cũ của nó vẫn hợp lệ.
    IF (TG_OP = 'DELETE' OR TG_OP = 'UPDATE') THEN
        SELECT i.fee_id INTO ma_fee_cu
        FROM payment p JOIN invoice i ON i.id = p.invoice_id
        WHERE p.id = OLD.payment_id;
    END IF;
    IF (TG_OP = 'INSERT' OR TG_OP = 'UPDATE') THEN
        SELECT i.fee_id INTO ma_fee_moi
        FROM payment p JOIN invoice i ON i.id = p.invoice_id
        WHERE p.id = NEW.payment_id;
    END IF;

    IF ma_fee_cu IS NOT NULL THEN
        UPDATE fee SET duplicate_guard_version = duplicate_guard_version + 1
        WHERE id = ma_fee_cu;
    END IF;
    IF ma_fee_moi IS NOT NULL AND ma_fee_moi IS DISTINCT FROM ma_fee_cu THEN
        UPDATE fee SET duplicate_guard_version = duplicate_guard_version + 1
        WHERE id = ma_fee_moi;
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    op.add_column(
        "fee",
        sa.Column(
            "duplicate_guard_version",
            sa.BigInteger(),
            nullable=False,
            server_default="1",
            comment=(
                "Tăng mỗi khi tập phiếu nghi trùng của khoản phí có thể đã đổi "
                "(trigger trên payment và refund_request). Phiếu xác nhận trùng "
                "do máy chủ cấp mang theo giá trị này; lúc ghi, dưới khoá fee, "
                "hai bên phải khớp TUYỆT ĐỐI. Giá trị tuyệt đối vô nghĩa — chỉ "
                "'có đổi hay không' mới mang thông tin."
            ),
        ),
    )

    op.execute(_FN_PAYMENT)
    op.execute(_FN_REFUND)

    # Chỉ nghe những cột thật sự đổi được tập ứng viên. Nghe mọi UPDATE thì một
    # lần sửa `notes` cũng làm hết token đang lưu hành hết hiệu lực, và người
    # ghi sẽ phải xác nhận lại vì một lý do không liên quan gì tới tiền.
    op.execute(
        """
        CREATE TRIGGER trg_payment_bump_duplicate_guard
        AFTER INSERT OR DELETE ON payment
        FOR EACH ROW EXECUTE FUNCTION bump_duplicate_guard_from_payment();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_payment_upd_bump_duplicate_guard
        AFTER UPDATE OF invoice_id, amount, payment_date, status ON payment
        FOR EACH ROW EXECUTE FUNCTION bump_duplicate_guard_from_payment();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_refund_bump_duplicate_guard
        AFTER INSERT OR DELETE ON refund_request
        FOR EACH ROW EXECUTE FUNCTION bump_duplicate_guard_from_refund();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_refund_upd_bump_duplicate_guard
        AFTER UPDATE OF status, amount, payment_id ON refund_request
        FOR EACH ROW EXECUTE FUNCTION bump_duplicate_guard_from_refund();
        """
    )


def downgrade() -> None:
    # `IF EXISTS` xuyên suốt: bản này thêm một cột, hai hàm và bốn trigger, nên
    # một lần gỡ vỡ giữa chừng sẽ để lại đúng nửa số đó. Đã trả giá một lần với
    # bản `impdup20260806` (gỡ hỏng ở cột thứ hai, mất luôn cột thứ nhất).
    for ten, bang in (
        ("trg_payment_bump_duplicate_guard", "payment"),
        ("trg_payment_upd_bump_duplicate_guard", "payment"),
        ("trg_refund_bump_duplicate_guard", "refund_request"),
        ("trg_refund_upd_bump_duplicate_guard", "refund_request"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {ten} ON {bang}")
    op.execute("DROP FUNCTION IF EXISTS bump_duplicate_guard_from_payment()")
    op.execute("DROP FUNCTION IF EXISTS bump_duplicate_guard_from_refund()")
    op.execute("ALTER TABLE fee DROP COLUMN IF EXISTS duplicate_guard_version")
