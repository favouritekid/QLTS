"""DDL của hàng rào nghi trùng phải chạy lại được — kiểm TRỰC TIẾP.

Ca lock-in ở ``tests/unit/test_duplicate_guard_ddl_lockin.py`` chỉ bảo đảm hai
bản DDL giống nhau. Nó KHÔNG nói gì về việc bản ấy chạy lần thứ hai có sống
không — và đó mới là thứ đã hỏng thật.

Chuyện đã xảy ra: ``Base.metadata.create_all()`` được gọi NHIỀU LẦN trong một
phiên pytest, còn listener ``after_create`` nổ theo mỗi lần gọi (kể cả lần
không tạo bảng nào). ``CREATE TRIGGER`` gặp trigger đã tồn tại là lỗi cứng, nên
lượt dựng schema vỡ giữa chừng: cột ``fee.duplicate_guard_version`` không được
tạo, và transaction dựng schema giữ khoá. Hậu quả lộ ra ở chỗ chẳng liên quan —
``TRUNCATE`` của fixture cleanup kẹt với ``INSERT INTO "user"`` của fixture
seed, 26 lần deadlock trong một buổi, cộng một loạt ``connection was closed``.

Chu kỳ deadlock nằm trong harness, nhưng ĐIỀU KIỆN sinh ra nó là DDL ứng dụng
không idempotent. Ca dưới đây khoá đúng điều kiện ấy, thay vì chờ một suite đủ
lớn vô tình tái tạo lại chu kỳ.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.database import engine
from app.models.base import Base

pytestmark = pytest.mark.asyncio

TEN_TRIGGER = {
    "trg_payment_bump_duplicate_guard",
    "trg_payment_upd_bump_duplicate_guard",
    "trg_refund_bump_duplicate_guard",
    "trg_refund_upd_bump_duplicate_guard",
}


async def _dem_trigger(conn) -> set[str]:
    rows = await conn.execute(
        text(
            """
            SELECT t.tgname
            FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            WHERE NOT t.tgisinternal
              AND c.relname IN ('payment', 'refund_request')
            """
        )
    )
    return {r[0] for r in rows}


async def _co_cot(conn) -> bool:
    return bool(
        (
            await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name = 'fee' "
                    "AND column_name = 'duplicate_guard_version'"
                )
            )
        ).first()
    )


class TestDdlChayLaiDuoc:
    async def test_create_all_HAI_LAN_lien_tiep_deu_thanh_cong(self):
        """Hai lượt liên tiếp trên CÙNG schema, cả hai phải commit sạch.

        Lượt thứ hai là lượt đã giết cả một buổi chạy test. Không có ca này thì
        nó chỉ lộ ra khi có đủ tệp chạy chung để ``create_all`` được gọi lần
        thứ hai — tức lộ ra ở một nơi trông chẳng liên quan gì (deadlock ở
        fixture cleanup), và người đọc sẽ đi sửa nhầm chỗ.
        """
        for lan in (1, 2):
            async with engine.begin() as conn:
                # `checkfirst=True` là mặc định và cũng là điều kiện tái hiện:
                # bảng đã có nên SQLAlchemy không tạo bảng nào, NHƯNG listener
                # `after_create` ở mức metadata vẫn chạy.
                await conn.run_sync(Base.metadata.create_all)
            # Ra khỏi `engine.begin()` là đã COMMIT. Lượt nào ném ở đây thì ca
            # đỏ ngay, kèm số lượt — không cần đoán.

        async with engine.connect() as conn:
            assert await _co_cot(conn), (
                "cột `fee.duplicate_guard_version` biến mất sau lượt dựng schema "
                "thứ hai — đúng triệu chứng đã thấy trong log: "
                '`column "duplicate_guard_version" of relation "fee" does not exist`'
            )
            co = await _dem_trigger(conn)
            assert co == TEN_TRIGGER, (
                f"thiếu/thừa trigger sau hai lượt: có {sorted(co)}, "
                f"cần {sorted(TEN_TRIGGER)}"
            )

    async def test_ban_DDL_cho_create_all_dung_CREATE_OR_REPLACE(self):
        """Khoá đúng cơ chế làm nó chạy lại được.

        Ca trên chứng minh KẾT QUẢ (hai lượt đều sống). Ca này chứng minh
        PHƯƠNG TIỆN, vì kết quả kia cũng đạt được bằng những cách tệ hơn — ví
        dụ nuốt lỗi DDL, thứ sẽ để schema dở dang mà không ai biết.

        Cố tình KHÔNG dùng `DROP …; CREATE …` ghép trong một `DDL()`: hai câu
        trong một lệnh đi qua driver thành một lệnh ghép và vỡ theo những kiểu
        khó đọc — đã thử, 109 lỗi.
        """
        from app.models.finance.duplicate_guard_ddl import (
            SQL_TRIGGERS,
            _lam_chay_lai_duoc,
        )

        for cau in SQL_TRIGGERS:
            chay = _lam_chay_lai_duoc(cau)
            assert "CREATE OR REPLACE TRIGGER" in chay
            assert "DROP TRIGGER" not in chay, (
                "đang ghép DROP vào cùng chuỗi DDL — một câu là một câu"
            )
            # Và bản GỐC (dùng để so với migration) phải giữ nguyên `CREATE
            # TRIGGER`: migration chạy đúng một lần trên cơ sở dữ liệu chưa có
            # gì, nên nó không cần — và không được — khác đi.
            assert "CREATE OR REPLACE" not in cau
