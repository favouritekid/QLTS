# app/models/finance/duplicate_guard_ddl.py
"""Trigger giữ ``fee.duplicate_guard_version`` — bản dùng cho ``create_all()``.

Vì sao tồn tại bản thứ hai của cùng đoạn DDL:

Cơ sở dữ liệu THẬT dựng bằng Alembic (``dupguard20260807``). Cơ sở dữ liệu
TEST thì không — ``tests/conftest.py`` dựng schema bằng ``Base.metadata.
create_all()``, và ``create_all`` chỉ biết bảng, cột, index; nó không biết gì
về function hay trigger. Không có module này thì mọi ca kiểm "ghi phiếu phải
làm version tăng" sẽ chạy trên một cơ sở dữ liệu KHÔNG có trigger — tức là
xanh vì không có gì để hỏng, đúng kiểu xanh vô nghĩa mà cả đợt này đang tìm
cách xoá.

Hai bản DDL sống ở hai nơi là một nguy cơ có thật (chúng trôi khỏi nhau rồi
bản lỏng hơn thắng), nên có một ca khoá chúng lại:
``tests/unit/test_duplicate_guard_ddl_lockin.py`` so từng câu lệnh sau khi
chuẩn hoá khoảng trắng. Sửa một bên mà quên bên kia là đỏ ngay, không phải
đợi tới lúc một ca race nào đó im lặng mất tác dụng.

Vì sao KHÔNG cho migration ``import`` thẳng module này: một migration phải tái
lập được đúng trạng thái LỊCH SỬ của nó. Nếu nó đọc code hiện tại thì chạy lại
bản cũ trên một máy mới sẽ dựng ra thứ của hôm nay — và lịch sử migration thôi
không còn nói thật.
"""

import re

from sqlalchemy import DDL, event

from app.models.base import Base

#: Hàm trigger cho ``payment``. Đọc ``fee_id`` qua ``invoice`` vì ``payment``
#: không giữ ``fee_id``; xử lý cả vế CŨ lẫn vế MỚI để một phiếu chuyển sang
#: hoá đơn của khoản phí khác làm đổi version của cả hai bên.
SQL_FN_PAYMENT = """
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

#: Hàm trigger cho ``refund_request``: hoàn đủ tiền thì một phiếu thôi không
#: còn là ứng viên, nên tập đổi dù ``payment`` không hề bị chạm.
SQL_FN_REFUND = """
CREATE OR REPLACE FUNCTION bump_duplicate_guard_from_refund()
RETURNS TRIGGER AS $$
DECLARE
    ma_fee INTEGER;
    ma_payment INTEGER;
BEGIN
    ma_payment := COALESCE(NEW.payment_id, OLD.payment_id);
    SELECT i.fee_id INTO ma_fee
    FROM payment p JOIN invoice i ON i.id = p.invoice_id
    WHERE p.id = ma_payment;

    IF ma_fee IS NOT NULL THEN
        UPDATE fee SET duplicate_guard_version = duplicate_guard_version + 1
        WHERE id = ma_fee;
    END IF;

    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
"""

#: Chỉ nghe những cột thật sự đổi được tập ứng viên. Nghe mọi ``UPDATE`` thì
#: một lần sửa ``notes`` cũng làm hết phiếu xác nhận đang lưu hành mất hiệu
#: lực, và người ghi phải xác nhận lại vì một lý do không dính gì tới tiền.
SQL_TRIGGERS = (
    """
CREATE TRIGGER trg_payment_bump_duplicate_guard
AFTER INSERT OR DELETE ON payment
FOR EACH ROW EXECUTE FUNCTION bump_duplicate_guard_from_payment();
""",
    """
CREATE TRIGGER trg_payment_upd_bump_duplicate_guard
AFTER UPDATE OF invoice_id, amount, payment_date, status ON payment
FOR EACH ROW EXECUTE FUNCTION bump_duplicate_guard_from_payment();
""",
    """
CREATE TRIGGER trg_refund_bump_duplicate_guard
AFTER INSERT OR DELETE ON refund_request
FOR EACH ROW EXECUTE FUNCTION bump_duplicate_guard_from_refund();
""",
    """
CREATE TRIGGER trg_refund_upd_bump_duplicate_guard
AFTER UPDATE OF status, amount, payment_id ON refund_request
FOR EACH ROW EXECUTE FUNCTION bump_duplicate_guard_from_refund();
""",
)

#: Thứ tự có ý nghĩa: hàm trước, trigger sau.
CAC_CAU_LENH = (SQL_FN_PAYMENT, SQL_FN_REFUND, *SQL_TRIGGERS)


def _lam_chay_lai_duoc(cau: str) -> str:
    """Làm mỗi câu ``CREATE TRIGGER`` chạy lại được.

    ``create_all()`` được gọi NHIỀU LẦN trong một phiên pytest, và listener ở
    mức metadata chạy theo mỗi lần gọi — kể cả lần không tạo bảng nào (bảng đã
    có thì SQLAlchemy bỏ qua, nhưng ``after_create`` vẫn nổ). Lần thứ hai gặp
    ``CREATE TRIGGER`` trên một trigger đã tồn tại là lỗi cứng, và nó làm hỏng
    cả một loạt ca không liên quan. Đã vấp: 42 lỗi setup ở lượt chạy cả tệp,
    trong khi chạy lẻ từng ca thì xanh.

    Dùng ``CREATE OR REPLACE TRIGGER`` (PostgreSQL 14+), KHÔNG ghép
    ``DROP …; CREATE …`` vào một chuỗi — hai câu trong một ``DDL()`` đi qua
    driver thành một lệnh ghép và vỡ theo những kiểu khó đọc (đã thử: 109 lỗi).
    Một câu là một câu.

    Sửa ở đây chứ không sửa ``SQL_TRIGGERS``: bản đó phải khớp TỪNG KÝ TỰ với
    migration (ca lock-in so chúng), còn migration chạy đúng một lần trên một
    cơ sở dữ liệu chưa có gì. Hai nhu cầu khác nhau, một nguồn văn bản.
    """
    return re.sub(
        r"^\s*CREATE\s+TRIGGER\b",
        "CREATE OR REPLACE TRIGGER",
        cau,
        count=1,
        flags=re.IGNORECASE | re.MULTILINE,
    )


def _dang_ky():
    """Gắn vào ``after_create`` của METADATA, không phải của một bảng.

    Trigger tham chiếu ba bảng (``payment``, ``invoice``, ``fee``) cộng
    ``refund_request``. Gắn vào ``after_create`` của một bảng cụ thể thì thứ tự
    tạo bảng quyết định nó chạy sớm hay muộn — và chạy sớm là lỗi
    ``relation does not exist``. Ở mức metadata, mọi bảng đã có mặt.
    """
    for cau in CAC_CAU_LENH:
        event.listen(
            Base.metadata,
            "after_create",
            # `execute_if(dialect="postgresql")`: các câu này là plpgsql thuần.
            # Không có vế đó thì một lần chạy trên SQLite (nếu về sau ai đó
            # thêm) sẽ vỡ ở chỗ chẳng liên quan gì tới thứ họ đang làm.
            DDL(_lam_chay_lai_duoc(cau)).execute_if(dialect="postgresql"),
        )


_dang_ky()
