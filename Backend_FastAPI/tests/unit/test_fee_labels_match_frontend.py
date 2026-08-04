"""Khoá chống drift nhãn giữa backend (tệp xuất) và frontend (màn hình).

Backend không đọc được TypeScript nên ``app/constants/fee_labels.py`` là bản
sao có chủ đích của ``frontend/src/types/finance.types.ts``. Bản sao thì sớm
muộn cũng lệch — và lệch ở đây rất khó thấy: tệp ghi "Lệ phí xét tuyển" trong
khi màn hình ghi "Lệ phí hồ sơ", Ctrl+F từ tệp về màn hình không ra gì, và
chính lời khuyên "lọc theo cột Loại phí trước khi cộng" trong sheet phụ trở
nên vô dụng.

Test này đọc THẲNG tệp TS và so từng khoá, nên đổi một bên mà quên bên kia là đỏ.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.constants.fee_labels import FEE_STATUS_LABELS, FEE_TYPE_LABELS

_TS_PATH = (
    Path(__file__).resolve().parents[2].parent
    / "frontend"
    / "src"
    / "types"
    / "finance.types.ts"
)


def _parse_ts_record(source: str, const_name: str) -> dict[str, str]:
    """Bóc ``export const NAME: Record<...> = { key: "value", ... }`` từ TS."""
    match = re.search(
        rf"export const {const_name}[^=]*=\s*{{(.*?)}}",
        source,
        re.DOTALL,
    )
    assert match, f"không tìm thấy {const_name} trong {_TS_PATH.name}"
    body = match.group(1)
    return {
        k: v
        for k, v in re.findall(r'(\w+)\s*:\s*"([^"]*)"', body)
    }


@pytest.mark.skipif(
    not _TS_PATH.exists(),
    reason=(
        "Không thấy nguồn frontend (chạy trong image backend không mount "
        "frontend/). Test này chỉ có nghĩa khi có cả hai cây mã."
    ),
)
class TestFeeLabelsMatchFrontend:
    def test_fee_type_labels_match(self):
        ts = _parse_ts_record(_TS_PATH.read_text(encoding="utf-8"), "FEE_TYPE_LABELS")
        assert ts, "FEE_TYPE_LABELS phía frontend rỗng — regex bóc sai?"
        assert FEE_TYPE_LABELS == ts, (
            "Nhãn loại phí lệch giữa backend và frontend.\n"
            f"  backend : {FEE_TYPE_LABELS}\n"
            f"  frontend: {ts}"
        )

    def test_fee_status_labels_match(self):
        ts = _parse_ts_record(
            _TS_PATH.read_text(encoding="utf-8"), "FEE_STATUS_LABELS"
        )
        assert ts, "FEE_STATUS_LABELS phía frontend rỗng — regex bóc sai?"
        assert FEE_STATUS_LABELS == ts, (
            "Nhãn trạng thái khoản phí lệch giữa backend và frontend.\n"
            f"  backend : {FEE_STATUS_LABELS}\n"
            f"  frontend: {ts}"
        )
