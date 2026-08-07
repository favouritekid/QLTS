"""Backfill của `imp2axis20260807` phải FAIL-CLOSED.

Migration này chia mọi dòng nhập lô cũ vào trục GHI. Chỗ nguy hiểm không phải
việc chia sai một dòng — mà là chia sai theo hướng LỎNG: một dòng đã có tiền mà
rơi vào nhóm "có thể thử lại" thì lượt commit kế tiếp sẽ ghi nó lần thứ hai.

Ba nhánh, tất cả suy từ dữ liệu CỨNG:

  * có ``payment_ids`` thật  → ``committed``;
  * ``validation_status='error'`` → ``not_applicable``;
  * còn lại                  → ``pending``.

Và KHÔNG có nhánh nào sinh ra ``duplicate_review_required``. Đoán một dòng
"đang chờ xác nhận" là dựng lại một challenge mà không ai còn giữ phiếu tương
ứng; phiếu cũ (nếu từng có) đã hết hiệu lực theo ``guard_version``. Dòng nào
thật sự còn bị chặn sẽ tự lộ ra ở lượt ghi kế tiếp và được cấp phiếu mới.

Ca ở đây đọc THẲNG văn bản migration. Nghe có vẻ mong manh, nhưng thứ cần khoá
đúng là văn bản ấy: backfill chạy MỘT LẦN trên production rồi thôi, nên không
có đường nào kiểm nó bằng cách chạy lại — và một lần chạy sai thì hậu quả đã
nằm trong dữ liệu.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "imp2axis20260807_split_row_status.py"
)


@pytest.fixture(scope="module")
def van() -> str:
    """Phần CODE của migration, đã cắt docstring đầu tệp.

    Docstring giải thích thiết kế nên nó nhắc tới cả những thứ backfill KHÔNG
    được làm ("không suy `duplicate_review_required` từ `message`"). Quét cả
    docstring thì mọi ca dưới đây đỏ vì chính lời giải thích của chúng — và
    một ca luôn đỏ là một ca sắp bị gỡ.
    """
    raw = _MIGRATION.read_text(encoding="utf-8")
    dau = raw.find('"""')
    cuoi = raw.find('"""', dau + 3)
    return raw[cuoi + 3 :] if dau >= 0 and cuoi > dau else raw


def _chuan_hoa(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def test_khong_backfill_duplicate_review_required(van: str):
    """Nhánh nguy hiểm nhất: KHÔNG được có."""
    than_upgrade = van.split("def downgrade")[0]
    # Soi đúng thứ cần soi: những giá trị được GÁN cho `commit_status`. Tìm
    # chuỗi `'duplicate_review_required'` ở bất kỳ đâu là bắt nhầm cả ràng buộc
    # CHECK (nơi nó phải có mặt, vì đó là danh sách giá trị HỢP LỆ) lẫn chú
    # thích cột.
    duoc_gan = set(re.findall(r"SET\s+commit_status\s*=\s*'(\w+)'", than_upgrade))
    assert duoc_gan, "không tìm thấy câu backfill nào cho commit_status"
    assert duoc_gan <= {"committed", "not_applicable"}, (
        f"backfill đang gán {sorted(duoc_gan - {'committed', 'not_applicable'})} "
        "cho dòng cũ. Riêng 'duplicate_review_required' là nguy hiểm nhất: nó "
        "dựng lại một challenge mà không ai còn giữ phiếu, và dòng đó sẽ đứng "
        "im chờ một xác nhận không bao giờ tới. Nhánh 'pending' đến từ "
        "server_default nên không cần câu UPDATE riêng."
    )


def test_khong_doc_message_de_doan_trang_thai(van: str):
    """Không suy trạng thái từ CÂU CHỮ.

    Câu cảnh báo tiếng Việt trong ``message`` từng là chỗ giao diện bóc mã phiếu
    ra — mong manh và lẫn với cảnh báo của luật khác. Backfill mà đọc nó thì
    một lần sửa câu chữ sẽ đổi cả dữ liệu lịch sử.
    """
    than_upgrade = van.split("def downgrade")[0]
    # Chỉ soi các câu SQL, không soi comment giải thích trong code.
    cau_sql = " ".join(
        d for d in than_upgrade.splitlines() if not d.strip().startswith(("#", "--"))
    )
    assert "message" not in cau_sql.lower(), (
        "backfill đang đọc cột `message` để đoán trạng thái"
    )


def test_committed_xet_TRUOC_va_chi_theo_payment_ids(van: str):
    """Thứ tự ba nhánh có ý nghĩa, và nhánh đầu chỉ nhìn dữ liệu cứng."""
    chuan = _chuan_hoa(van.split("def downgrade")[0])
    i_committed = chuan.find("SET commit_status = 'committed'")
    i_na = chuan.find("SET commit_status = 'not_applicable'")
    assert i_committed > 0 and i_na > 0
    assert i_committed < i_na, (
        "nhánh 'committed' phải chạy TRƯỚC: một dòng đã có tiền không được rơi "
        "vào bất kỳ nhóm có-thể-thử-lại nào, dù nó cũng thoả điều kiện khác"
    )
    # Nhánh committed chỉ được nhìn `payment_ids`.
    doan = chuan[i_committed : i_committed + 400]
    assert "payment_ids" in doan
    assert "validation_status" not in doan, (
        "nhánh 'committed' đang xét thêm trạng thái kiểm — tiền đã vào thì vào "
        "rồi, trục kiểm không đổi được điều đó"
    )


def test_na_khong_ghi_de_len_committed(van: str):
    """Dòng vừa `error` vừa có tiền: tiền thắng.

    Nghe như không xảy ra được, nhưng dữ liệu cũ có: một dòng ghi được tiền rồi
    bị hạ xuống `error` ở lượt sau (bản trước hạ trạng thái khi ghi hỏng). Nếu
    nhánh `not_applicable` ghi đè, dòng ấy mất dấu tiền và ràng buộc hai trục
    cũng từ chối.
    """
    chuan = _chuan_hoa(van.split("def downgrade")[0])
    i_na = chuan.find("SET commit_status = 'not_applicable'")
    doan = chuan[i_na : i_na + 300]
    assert "commit_status <> 'committed'" in doan, (
        "nhánh 'not_applicable' phải loại trừ dòng đã 'committed'"
    )


def test_dem_lai_ca_hai_ho_khong_cong_don(van: str):
    """Backfill counter phải là phép ĐẾM LẠI, không phải phép cộng."""
    than_upgrade = van.split("def downgrade")[0]
    assert "count(*) FILTER" in than_upgrade, "phải đếm lại từ trạng thái dòng"
    assert "+ " not in _chuan_hoa(
        than_upgrade[than_upgrade.find("UPDATE payment_import_batch") :]
    ).replace("+ 1", ""), "backfill counter đang cộng dồn thay vì đếm lại"


def test_dung_CASE_thay_vi_AND_khi_doc_jsonb(van: str):
    """`jsonb_array_length` trên scalar là lỗi runtime, không phải NULL.

    PostgreSQL KHÔNG hứa thứ tự đánh giá các vế `AND`, nên planner có quyền
    chạy `jsonb_array_length` trước phép kiểm kiểu và vỡ ngay khi gặp một dòng
    `payment_ids` không phải mảng. Đã vỡ thật khi chạy bản đầu.
    """
    chuan = _chuan_hoa(van)
    assert "jsonb_typeof" in chuan
    i = chuan.find("SET commit_status = 'committed'")
    doan = chuan[i : i + 400]
    assert "CASE" in doan, (
        "phép lọc `payment_ids` phải dùng CASE để chốt thứ tự đánh giá"
    )
