"""Hai bản DDL của trigger `duplicate_guard_version` phải nói y hệt nhau.

Bản A — ``alembic/versions/dupguard20260807_duplicate_guard_version.py`` —
dựng cơ sở dữ liệu THẬT.
Bản B — ``app/models/finance/duplicate_guard_ddl.py`` — dựng cơ sở dữ liệu
TEST (``create_all`` không biết gì về function/trigger).

Vì sao không gộp làm một: migration phải tái lập được trạng thái LỊCH SỬ của
nó; cho nó đọc code hiện tại thì chạy lại bản cũ trên máy mới sẽ dựng ra thứ
của hôm nay. Nhưng hai bản thì trôi khỏi nhau — và ở đây kiểu trôi nguy hiểm
nhất là bản TEST lỏng hơn bản THẬT: mọi ca kiểm vẫn xanh trong khi hàng rào
trên production đã khác.

Nên có ca này. Nó không kiểm SQL đúng hay sai — nó chỉ kiểm hai bên còn là
một. (Memory: ``single-source-of-truth-shared-helper`` — buộc phải có hai bản
thì phải có ca nối chúng.)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.models.finance import duplicate_guard_ddl as ddl

pytestmark = pytest.mark.unit

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "dupguard20260807_duplicate_guard_version.py"
)


def _chuan_hoa(sql: str) -> str:
    """Bỏ khác biệt vô nghĩa: khoảng trắng, thụt lề, dòng trống.

    Cố tình KHÔNG bỏ chữ hoa/thường: `UPDATE fee` và `update fee` chạy như
    nhau, nhưng nếu hai bản khác nhau tới mức đó thì chúng đã được viết lại
    độc lập, và đó đúng là thứ ca này cần bắt.
    """
    return re.sub(r"\s+", " ", sql).strip()


def test_hai_ban_ddl_khong_troi_khoi_nhau():
    van_migration = _MIGRATION.read_text(encoding="utf-8")

    for cau in ddl.CAC_CAU_LENH:
        chuan = _chuan_hoa(cau)
        assert chuan, "câu lệnh rỗng — bản DDL cho create_all đang thiếu"
        # Migration viết cùng câu nhưng thụt lề khác, nên so trên bản đã chuẩn
        # hoá của TOÀN BỘ tệp.
        assert chuan in _chuan_hoa(van_migration), (
            "một câu lệnh có trong bản dùng cho create_all nhưng KHÔNG có "
            f"trong migration:\n\n{cau}\n\n"
            "Sửa một bên thì phải sửa bên kia — nếu không, cơ sở dữ liệu test "
            "và cơ sở dữ liệu thật có hai hàng rào khác nhau, và bản lỏng hơn "
            "là bản mọi ca kiểm đang chạy trên đó."
        )


def test_du_bon_trigger_va_hai_ham():
    """Đếm, để một lần xoá nhầm không lọt qua ca ở trên.

    Ca trên chỉ kiểm "mọi câu của bản B đều có trong bản A". Xoá một câu khỏi
    bản B thì nó vẫn xanh — tập rỗng thoả mãn mọi mệnh đề phổ quát. Ca này
    khoá SỐ LƯỢNG, tức chiều còn lại.
    """
    assert len(ddl.SQL_TRIGGERS) == 4, (
        "phải đủ bốn trigger: payment insert/delete, payment update-of-cột, "
        "refund insert/delete, refund update-of-cột. Thiếu một cái là để hở "
        "đúng một đường làm đổi tập ứng viên mà không ai tăng version."
    )
    assert len(ddl.CAC_CAU_LENH) == 6, "hai hàm + bốn trigger"

    # Và các cột được nghe phải đúng những cột đổi được tập ứng viên. Thêm cột
    # lạ thì token hết hiệu lực vì lý do không liên quan tới tiền; thiếu cột
    # thì tập đổi mà version đứng yên.
    gop = " ".join(ddl.SQL_TRIGGERS)
    for cot in ("invoice_id", "amount", "payment_date", "status"):
        assert f"{cot}" in gop, f"trigger không nghe cột {cot}"
