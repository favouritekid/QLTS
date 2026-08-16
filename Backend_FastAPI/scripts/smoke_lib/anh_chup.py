"""Chụp ảnh trạng thái các bảng được theo dõi, để sổ hành động so TRƯỚC/SAU.

`registry.bat_dau_action()` đòi một `AnhChup = {bảng: {id: vân tay hàng}}` khai
TRƯỚC khi thao tác, và `ket_thuc_action()` so nó với ảnh chụp SAU. Cho tới nay
không có ai dựng được ảnh chụp ấy: `van_tay_hang()` chỉ băm một dict do người
gọi tự truyền, nên hai hàm kia chỉ có caller trong unit test. Tệp này lấp đúng
khoảng trống đó.

Vì sao SQL trả JSON thay vì `-At -F '|'`
-----------------------------------------
Giá trị thật có thể chứa `|` (ghi chú, tên người, lý do từ chối). Tách theo dấu
phân cách là mời một hàng làm lệch cả ảnh chụp mà không ai thấy. `to_jsonb` để
chính PostgreSQL lo phần thoát ký tự, phía Python chỉ `json.loads`.

Vì sao suy ra cột lúc chạy thay vì khai bảng cột bằng tay
----------------------------------------------------------
Một bảng cột viết tay sẽ lệch khỏi lược đồ đúng lúc không ai để ý — đã có bốn
lần trong dự án này. Ảnh chụp chỉ được so TRƯỚC với SAU **trong cùng một action**
(cách nhau vài giây), nên cột suy ra lúc chạy là ổn định trong phạm vi đang cần,
và tự đúng khi lược đồ đổi.

Vì sao loại `updated_at`
-------------------------
Nó đổi ở MỌI lần ghi, kể cả lần ghi không liên quan tới điều ca đang khẳng định.
Giữ nó lại thì mọi hàng bị chạm đều hiện ra là "đã đổi", và một tín hiệu luôn
bật thì không còn là tín hiệu — đúng cảnh báo trong docstring của
`registry.van_tay_hang`. Các cột thời gian KHÁC (`verified_at`, `rejected_at`,
`completed_at`…) thì GIỮ: chúng đổi vì nghiệp vụ đổi, đó là thứ cần bắt.
"""

from __future__ import annotations

import json
from typing import Callable, Dict, Iterable, List, Sequence

from . import baseline, registry

# Cột bị loại khỏi vân tay hàng. Cố ý chỉ có MỘT tên: mỗi cột thêm vào đây là
# một loại thay đổi mà sổ hành động sẽ không còn nhìn thấy.
COT_BO_QUA = ("updated_at",)


class LoiAnhChup(RuntimeError):
    pass


def cau_lenh_anh_chup(bang: str) -> str:
    """SQL trả về một dòng JSON: `[{"id": "...", "v": {...}}, ...]`.

    `to_jsonb(t) - 'updated_at'` bỏ cột biến động ngay trong PostgreSQL, nên
    phía Python không phải biết tên cột của bảng nào cả.
    """
    baseline.kiem_ten_bang(bang)
    bo = " - ".join(f"'{c}'" for c in COT_BO_QUA)
    loai = f" - {bo}" if COT_BO_QUA else ""
    return (
        "SELECT COALESCE(json_agg(json_build_object("
        f"'id', t.id::text, 'v', to_jsonb(t){loai}) ORDER BY t.id), '[]'::json)::text "
        f"FROM {bang} t;"
    )


def phan_tich(bang: str, dau_ra: str) -> Dict[str, str]:
    """Đọc kết quả JSON thành `{id: vân tay hàng}` — fail-closed.

    Đầu ra rỗng KHÔNG được hiểu là "bảng rỗng": một lệnh psql hỏng cũng cho
    stdout rỗng, và khi ấy ảnh chụp sẽ nói dối rằng mọi hàng đã biến mất.
    PostgreSQL luôn trả ít nhất `[]` cho truy vấn này.
    """
    tho = dau_ra.strip()
    if not tho:
        raise LoiAnhChup(
            f"bảng {bang!r}: psql không trả gì. Rỗng không phải quan sát — "
            "lệnh hỏng và bảng rỗng cho cùng một stdout."
        )
    try:
        hang = json.loads(tho)
    except json.JSONDecodeError as e:
        raise LoiAnhChup(f"bảng {bang!r}: đầu ra không phải JSON: {e}")
    if not isinstance(hang, list):
        raise LoiAnhChup(f"bảng {bang!r}: JSON không phải mảng")

    ket: Dict[str, str] = {}
    for i, h in enumerate(hang):
        if not isinstance(h, dict) or "id" not in h or "v" not in h:
            raise LoiAnhChup(f"bảng {bang!r}: phần tử {i} sai dạng: {h!r}")
        ma = str(h["id"])
        if ma in ket:
            raise LoiAnhChup(f"bảng {bang!r}: id trùng {ma!r} — ảnh chụp không tin được")
        ket[ma] = registry.van_tay_hang(h["v"])
    return ket


def chup(
    bang: Sequence[str],
    chay_sql: Callable[[str], str],
) -> registry.AnhChup:
    """Chụp ảnh nhiều bảng. `chay_sql(sql) -> stdout`.

    Bảng phải nằm trong `registry.BANG_THEO_DOI`: sổ hành động chỉ so được những
    bảng nó theo dõi, và một bảng ngoài danh sách sẽ lặng lẽ không bao giờ được
    đối chiếu.
    """
    ten: List[str] = [str(b) for b in bang]
    if not ten:
        raise LoiAnhChup("không có bảng nào để chụp — ảnh chụp rỗng không phải quan sát")
    la = [b for b in ten if b not in registry.BANG_THEO_DOI]
    if la:
        raise LoiAnhChup(f"bảng ngoài BANG_THEO_DOI: {la}")
    trung = [b for b in set(ten) if ten.count(b) > 1]
    if trung:
        raise LoiAnhChup(f"bảng khai trùng: {sorted(trung)}")

    return {b: phan_tich(b, chay_sql(cau_lenh_anh_chup(b))) for b in sorted(ten)}


def doc_cap(gia_tri: Iterable[str], *, ten_co: str) -> Dict[str, List[str]]:
    """Đọc các cặp `bảng=a,b,c` từ dòng lệnh thành `{bảng: [id...]}`."""
    ket: Dict[str, List[str]] = {}
    for g in gia_tri:
        if "=" not in g:
            raise LoiAnhChup(f"{ten_co} sai dạng {g!r}, cần `bảng=id[,id...]`")
        bang, _, phan = g.partition("=")
        bang = bang.strip()
        if bang not in registry.BANG_THEO_DOI:
            raise LoiAnhChup(f"{ten_co}: bảng {bang!r} ngoài BANG_THEO_DOI")
        ids = [x.strip() for x in phan.split(",") if x.strip()]
        if not ids:
            raise LoiAnhChup(f"{ten_co}: {g!r} không khai id nào")
        ket.setdefault(bang, []).extend(ids)
    return ket


def doc_so_luong(gia_tri: Iterable[str], *, ten_co: str) -> Dict[str, int]:
    """Đọc các cặp `bảng=N` — dùng khi server sinh id, ta chỉ biết SỐ LƯỢNG."""
    ket: Dict[str, int] = {}
    for g in gia_tri:
        if "=" not in g:
            raise LoiAnhChup(f"{ten_co} sai dạng {g!r}, cần `bảng=N`")
        bang, _, phan = g.partition("=")
        bang = bang.strip()
        if bang not in registry.BANG_THEO_DOI:
            raise LoiAnhChup(f"{ten_co}: bảng {bang!r} ngoài BANG_THEO_DOI")
        try:
            n = int(phan.strip())
        except ValueError:
            raise LoiAnhChup(f"{ten_co}: {g!r} — số lượng phải là số nguyên")
        if n < 0:
            raise LoiAnhChup(f"{ten_co}: {g!r} — số lượng âm")
        if bang in ket:
            raise LoiAnhChup(f"{ten_co}: bảng {bang!r} khai hai lần")
        ket[bang] = n
    return ket
