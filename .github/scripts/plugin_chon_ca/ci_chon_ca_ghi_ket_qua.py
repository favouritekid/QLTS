# -*- coding: utf-8 -*-
"""Plugin pytest cho `.github/workflows/ci-chon-ca.yml`: ghi NGUYÊN báo cáo
từng pha của từng ca ra một tệp JSON-lines.

Bước `chay` của workflow phán quyết từ tệp này, theo node id GỐC
(`report.nodeid`), không qua JUnit. Lý do (Codex 23-11, KD1): ánh xạ
node id → `(classname, name)` của JUnit có VA CHẠM. Ví dụ
`tests/test_a/test_b.py::test_x` và `tests/test_a.py::test_b::test_x` (lớp
`unittest.TestCase` tên `test_b`) cùng ra `("tests.test_a.test_b", "test_x")`,
nên collect cả hai mà chạy một vẫn xanh.

Nạp: `PYTHONPATH=<thư mục này> python -m pytest … -p ci_chon_ca_ghi_ket_qua`,
đích ghi đặt trong biến môi trường `CI_CHON_CA_KET_QUA`. Thư mục này CHỈ có
một module, nên thêm nó vào `PYTHONPATH` không che module nào của bộ test.
`.github/scripts/` thì khác: nó có `tests/`, `fixtures/`, `pr_classify.py`…

Mỗi dòng ghi: `{"nodeid", "when" (setup/call/teardown), "outcome"
(passed/failed/skipped)}`, cộng thêm `"wasxfail"` khi pytest gắn cờ ấy
(xfail ⇒ outcome skipped; xpass không strict ⇒ outcome passed). Không tự
phân loại: luật nằm ở MỘT chỗ, là bước `chay`.

Fail-closed: thiếu biến đích ⇒ `UsageError` ⇒ pytest thoát khác 0.
"""

from __future__ import annotations

import json
import os

import pytest

BIEN_DICH = "CI_CHON_CA_KET_QUA"

_tep = None


def pytest_configure(config):
    global _tep
    duong = os.environ.get(BIEN_DICH)
    if not duong:
        raise pytest.UsageError(
            "ci_chon_ca_ghi_ket_qua: thiếu biến môi trường %s (đường tệp kết quả)" % BIEN_DICH)
    _tep = open(duong, "w", encoding="utf-8")


def pytest_runtest_logreport(report):
    ban_ghi = {"nodeid": report.nodeid, "when": report.when, "outcome": report.outcome}
    if hasattr(report, "wasxfail"):
        ban_ghi["wasxfail"] = str(report.wasxfail)
    _tep.write(json.dumps(ban_ghi, ensure_ascii=False) + "\n")
    _tep.flush()


def pytest_unconfigure(config):
    global _tep
    if _tep is not None:
        _tep.close()
        _tep = None
