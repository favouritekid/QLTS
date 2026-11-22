"""FE = BE: họ 503 fail-closed mà giao diện hiện NGUYÊN câu của máy chủ (Codex N4 22-11 Q1 — PR giao diện riêng).

``frontend/src/lib/api/error-codes.ts`` giữ ``USER_FACING_UNAVAILABLE_ERROR_CODES``: mã 503 có ``detail`` viết cho người dùng
cuối; toast ``handleApiError`` và lỗi tại chỗ của Văn bản Hội đồng hiện ``detail`` của đúng các mã ấy (cùng hai mã 503 của
``T6_PUBLISH_STOP_ERROR_CODES``). Hai nơi giữ cùng một danh sách ⇒ khoá bằng nhau (CLAUDE.md §7): thêm một lớp con
``ServiceUnavailableError`` ở backend (vd ``AuditTrailUnavailable`` của N4) mà quên thêm mã ở giao diện ⇒ ĐỎ — người dùng
sẽ lại thấy câu chung "Lỗi hệ thống" thay vì câu của máy chủ. Không cần CSDL.
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

GOC = Path(__file__).resolve().parents[2]  # Backend_FastAPI/
FE_ERROR_CODES = GOC.parent / "frontend" / "src" / "lib" / "api" / "error-codes.ts"


def _tap_ma_fe(ten: str) -> set:
    """Mã trong ``export const <ten> … = new Set([...])`` — chuỗi chữ VÀ tên hằng ``*_ERROR_CODE`` (tra giá trị trong tệp)."""
    nguon = FE_ERROR_CODES.read_text(encoding="utf-8")
    hang = dict(re.findall(r'export const (\w+)\s*=\s*"([A-Z_]+)"', nguon))
    khoi = re.search(r"export const " + ten + r"\b[^=]*=\s*new Set\(\[(.*?)\]\)", nguon, re.S)
    assert khoi is not None, f"Không thấy {ten} trong error-codes.ts"
    noi_dung = khoi.group(1)
    tap = set(re.findall(r'"([A-Z_]+)"', noi_dung))
    for ten_hang in re.findall(r"\b([A-Z][A-Z0-9_]*_ERROR_CODE)\b", noi_dung):
        assert ten_hang in hang, f"Hằng {ten_hang} không có giá trị chuỗi trong error-codes.ts"
        tap.add(hang[ten_hang])
    return tap


def _ho_503_be() -> set:
    from app.utils import exceptions as ex

    lop, cho = set(), [ex.ServiceUnavailableError]
    while cho:
        c = cho.pop()
        if c not in lop:
            lop.add(c)
            cho.extend(c.__subclasses__())
    lop |= {c for c in vars(ex).values() if inspect.isclass(c) and issubclass(c, ex.ServiceUnavailableError)}
    assert {c.status_code for c in lop} == {503}, sorted((c.__name__, c.status_code) for c in lop)
    return {c.error_code for c in lop}


def test_tap_ma_503_giao_dien_hien_cau_bang_ho_service_unavailable_backend():
    """``USER_FACING_UNAVAILABLE_ERROR_CODES`` ∪ (mã 503 của ``T6_PUBLISH_STOP_ERROR_CODES``) = mã của MỌI lớp
    ``ServiceUnavailableError`` (kể cả lớp gốc)."""
    tap_be = _ho_503_be()
    tap_fe = _tap_ma_fe("USER_FACING_UNAVAILABLE_ERROR_CODES")
    t6_503 = tap_be & _tap_ma_fe("T6_PUBLISH_STOP_ERROR_CODES")
    assert tap_fe | t6_503 == tap_be and not (tap_fe - tap_be), (sorted(tap_fe), sorted(t6_503), sorted(tap_be))
