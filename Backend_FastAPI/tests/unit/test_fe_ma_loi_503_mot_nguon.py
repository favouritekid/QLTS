"""FE = BE: họ 503 fail-closed mà giao diện hiện NGUYÊN câu của máy chủ (Codex N4 22-11 Q1 — PR giao diện riêng).

``frontend/src/lib/api/error-codes.ts`` giữ ``USER_FACING_UNAVAILABLE_ERROR_CODES``: mã 503 có ``detail`` viết cho người dùng
cuối; toast ``handleApiError`` và lỗi tại chỗ của Văn bản Hội đồng hiện ``detail`` của đúng các mã ấy (cùng hai mã 503 của
``T6_PUBLISH_STOP_ERROR_CODES``). Mã họ 503 mà giao diện CỐ Ý không hiện qua đường ấy nằm ở ``LOAI_TRU_503`` dưới đây, mỗi
mã kèm lý do. Mã của MỌI lớp ``ServiceUnavailableError`` (kể cả lớp gốc) phải được PHÂN LOẠI vào một trong các nơi ấy
(CLAUDE.md §7): thêm một lớp con ở backend (vd ``AuditTrailUnavailable`` của N4) mà quên phân loại ⇒ ĐỎ — người dùng sẽ lại
thấy câu chung "Lỗi hệ thống" thay vì câu của máy chủ. Không cần CSDL.

Tập backend KHÔNG phụ thuộc thứ tự nạp (rà hợp nhất 23-11 mục C: lượt 1 dựa vào ``tests/conftest.py`` nạp ``app.main``):
``_ho_503_be`` tự nạp ``app.main`` VÀ mọi module trong ``app/`` khai lớp con của họ (dò AST theo tên lớp cha — module chỉ
được nạp lười trong thân hàm vẫn được tính), rồi CHỈ giữ lớp có ``__module__`` thuộc gói ``app`` (lớp con do một tệp test
dựng ra không lọt vào). Mỗi ca canh MỘT bất biến — khuôn cho bộ chấm đột biến: KHÔNG ``pytest.raises``, KHÔNG
``parametrize``.
"""
from __future__ import annotations

import ast
import functools
import importlib
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

GOC = Path(__file__).resolve().parents[2]  # Backend_FastAPI/
APP = GOC / "app"
FE_ERROR_CODES = GOC.parent / "frontend" / "src" / "lib" / "api" / "error-codes.ts"

# Mã họ 503 mà giao diện CỐ Ý KHÔNG hiện ``detail`` qua ``handleApiError`` / ``userFacingUnavailableDetail`` — mỗi mã MỘT
# lý do (đọc tĩnh 23-11-2026 trên 860eee09). Lớp 503 mới ở backend ⇒ ĐỎ tới khi được phân loại: vào
# ``USER_FACING_UNAVAILABLE_ERROR_CODES`` (giao diện hiện câu của máy chủ) HOẶC vào đây kèm lý do. Mã ở đây mà họ 503
# backend không có ⇒ ĐỎ: lý do mồ côi không được nằm lại.
_LY_DO_LO_CHUA_CAU_HINH = (
    "Luồng lô duyệt giấy có bộ phân loại lỗi RIÊNG (frontend/src/lib/document-review/messages.ts), không gọi"
    " handleApiError: xem trước (describePreviewError) ⇒ 'bản xem trước chưa tạo được'; chạy lô (classifyExecuteError,"
    " mọi 5xx) ⇒ TRA LÔ theo mã, không gửi lại lệnh. detail ('K1 / lock_timeout') là câu kỹ thuật cho người vận hành."
)
_LY_DO_LO_KHOA = (
    "Chỉ phát ở bước chốt lô; describeFinalizeError (document-review/messages.ts) đã có câu riêng cho 503: 'Chưa kiểm"
    " được trạng thái lô — thử lại sau'. Luồng lô không gọi handleApiError."
)
LOAI_TRU_503: dict[str, str] = {
    "BULK_VERIFY_NOT_CONFIGURED": _LY_DO_LO_CHUA_CAU_HINH,
    "BULK_VERIFY_LOCK_UNAVAILABLE": _LY_DO_LO_KHOA,
}


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


def _ten_lop_cha(nut: ast.expr) -> str | None:
    if isinstance(nut, ast.Name):
        return nut.id
    if isinstance(nut, ast.Attribute):
        return nut.attr
    return None


def _ten_mo_dun(tep: Path) -> str:
    phan = tep.relative_to(GOC).with_suffix("").parts
    return ".".join(phan[:-1] if phan[-1] == "__init__" else phan)


@functools.lru_cache(maxsize=None)
def _mo_dun_khai_lop_503() -> tuple[str, ...]:
    """Module trong ``app/`` có ``class X(<lớp họ 503>)`` — dò AST theo TÊN lớp cha, lặp tới điểm bất động (lớp cháu…).

    Chỉ phân tích tệp có chứa tên một lớp của họ: lớp con buộc phải viết tên lớp cha trong nguồn. Không bắt được lớp
    khai qua bí danh (``import … as X``) hay ``type(...)`` — hai ca ấy chỉ được tính nếu module đã nạp (``app.main``)."""
    nguon = {tep: tep.read_bytes() for tep in sorted(APP.rglob("*.py"))}
    ho = {"ServiceUnavailableError"}
    lop_cua: dict[Path, list[ast.ClassDef]] = {}
    while True:
        for tep, raw in nguon.items():
            if tep not in lop_cua and any(ten.encode() in raw for ten in ho):
                cay = ast.parse(raw, filename=str(tep))
                lop_cua[tep] = [n for n in ast.walk(cay) if isinstance(n, ast.ClassDef)]
        moi = {
            lop.name
            for cac_lop in lop_cua.values()
            for lop in cac_lop
            if any(_ten_lop_cha(b) in ho for b in lop.bases)
        } - ho
        if not moi:
            break
        ho |= moi
    return tuple(
        sorted(
            _ten_mo_dun(tep)
            for tep, cac_lop in lop_cua.items()
            if any(_ten_lop_cha(b) in ho for lop in cac_lop for b in lop.bases)
        )
    )


def _ho_503_be() -> set[str]:
    """Mã của MỌI lớp ``ServiceUnavailableError`` (kể cả lớp gốc) khai trong gói ``app`` — không phụ thuộc thứ tự nạp."""
    importlib.import_module("app.main")  # tự nạp, KHÔNG dựa vào tests/conftest.py
    for mo_dun in _mo_dun_khai_lop_503():
        importlib.import_module(mo_dun)
    from app.utils import exceptions as ex

    lop, cho = set(), [ex.ServiceUnavailableError]
    while cho:
        c = cho.pop()
        if c not in lop:
            lop.add(c)
            cho.extend(c.__subclasses__())
    lop = {c for c in lop if c.__module__.partition(".")[0] == "app"}
    assert {c.status_code for c in lop} == {503}, sorted((c.__name__, c.status_code) for c in lop)
    return {c.error_code for c in lop}


def test_moi_ma_ho_503_backend_duoc_phan_loai():
    """Mã của MỌI lớp ``ServiceUnavailableError`` nằm ở ``USER_FACING_UNAVAILABLE_ERROR_CODES``, ở
    ``T6_PUBLISH_STOP_ERROR_CODES`` hoặc ở ``LOAI_TRU_503``. Lớp 503 mới chưa phân loại ⇒ ĐỎ."""
    da_phan_loai = (
        _tap_ma_fe("USER_FACING_UNAVAILABLE_ERROR_CODES")
        | _tap_ma_fe("T6_PUBLISH_STOP_ERROR_CODES")
        | set(LOAI_TRU_503)
    )
    chua = _ho_503_be() - da_phan_loai
    assert not chua, (
        f"Mã họ 503 chưa phân loại: {sorted(chua)} — thêm vào USER_FACING_UNAVAILABLE_ERROR_CODES (error-codes.ts)"
        " hoặc vào LOAI_TRU_503 kèm lý do"
    )


def test_tap_hien_cau_fe_chi_chua_ma_ho_503_backend():
    """``USER_FACING_UNAVAILABLE_ERROR_CODES`` không giữ mã ngoài họ 503 backend (lỗi thời / gõ sai / lớp chưa lên nhánh)."""
    thua = _tap_ma_fe("USER_FACING_UNAVAILABLE_ERROR_CODES") - _ho_503_be()
    assert not thua, f"Mã trong USER_FACING_UNAVAILABLE_ERROR_CODES mà họ 503 backend không có: {sorted(thua)}"


def test_tap_loai_tru_chi_chua_ma_ho_503_backend():
    """``LOAI_TRU_503`` ⊆ mã họ 503 backend: mã loại trừ không còn tồn tại (hoặc không thuộc họ 503) ⇒ ĐỎ."""
    mo_coi = set(LOAI_TRU_503) - _ho_503_be()
    assert not mo_coi, f"Mã trong LOAI_TRU_503 mà họ 503 backend không có: {sorted(mo_coi)} — gỡ khỏi LOAI_TRU_503"


def test_tap_loai_tru_khong_giao_tap_hien_cau():
    """Một mã không thể vừa hiện câu máy chủ vừa bị loại trừ: ``LOAI_TRU_503`` ∩ (tập FE ∪ tập T6) = ∅."""
    hien_cau = _tap_ma_fe("USER_FACING_UNAVAILABLE_ERROR_CODES") | _tap_ma_fe("T6_PUBLISH_STOP_ERROR_CODES")
    giao = set(LOAI_TRU_503) & hien_cau
    assert not giao, f"Mã vừa ở LOAI_TRU_503 vừa ở tập hiện câu của error-codes.ts: {sorted(giao)}"


def test_moi_ma_loai_tru_co_ly_do():
    """Mỗi mã trong ``LOAI_TRU_503`` kèm một lý do không rỗng."""
    thieu = sorted(ma for ma, ly_do in LOAI_TRU_503.items() if not (isinstance(ly_do, str) and ly_do.strip()))
    assert not thieu, f"Mã trong LOAI_TRU_503 thiếu lý do: {thieu}"
