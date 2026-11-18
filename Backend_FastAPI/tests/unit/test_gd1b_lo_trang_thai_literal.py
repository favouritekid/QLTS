"""GĐ1b — ``Literal`` trạng thái lô / kết quả mục ở schema (bổ sung hợp đồng bản 6 C3) = ĐÚNG tập dịch vụ trả ra.

Schema siết hơn thực tế ⇒ response validation 500; lỏng hơn ⇒ OpenAPI / giao diện không biết giá trị mới. Khoá bằng AST:
``TERMINAL_STATUSES`` + mọi ``return "<chuỗi>"`` của ``_derive_status``; kết quả mục = CHECK của bảng + ``pending`` (NULL).
"""
import ast
import inspect
import textwrap
from typing import get_args

import pytest

from app.models.admission_config.document_review import DocumentBulkBatchItem
from app.schemas import document_bulk as sch
from app.services import document_bulk_verify_service as svc

pytestmark = pytest.mark.unit


def _chuoi_tra_ve(fn) -> set:
    cay = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    return {
        n.value.value
        for n in ast.walk(cay)
        if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
    } | {
        # ``return "a" if … else "b"``
        c.value
        for n in ast.walk(cay)
        if isinstance(n, ast.Return) and isinstance(n.value, ast.IfExp)
        for c in (n.value.body, n.value.orelse)
        if isinstance(c, ast.Constant) and isinstance(c.value, str)
    }


def test_literal_trang_thai_lo_bang_tap_dich_vu_suy_ra():
    tap = set(svc.TERMINAL_STATUSES) | _chuoi_tra_ve(svc._derive_status)
    assert set(get_args(sch.BatchStatus)) == tap
    assert len(tap) == 9


def test_literal_ket_qua_muc_bang_check_cua_bang_cong_pending():
    check = next(
        c for c in DocumentBulkBatchItem.__table__.constraints if getattr(c, "name", "") == "ck_document_bulk_batch_item_result"
    )
    trong_check = set(ast.literal_eval("(" + str(check.sqltext).split("IN", 1)[1].strip()[1:-1] + ",)"))
    assert set(get_args(sch.BatchItemResult)) == trong_check | {"pending"}
