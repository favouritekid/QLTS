"""Che bí mật trong mọi thứ được IN RA.

Module này cố ý **không có side effect và không phụ thuộc gì** — không import
``config``, không dựng ``Settings``, không đọc môi trường. Đó là điều kiện để
nó dùng được ở đúng lúc cần nhất: khi ``Settings()`` vừa raise và
``app.config`` KHÔNG import nổi. Nếu hàm che nằm trong ``config.py`` thì ca
hỏng ấy vừa mất cấu hình vừa mất luôn cách in lỗi an toàn, nên thông báo hoặc
là in thô (rò), hoặc là trống rỗng (vô dụng).

Một bản cài đặt duy nhất cho mọi chỗ in: hai bản là hai cơ hội để một bản quên
mất một dạng URL.
"""
from __future__ import annotations

import re

# ``[^\s]*`` THAM LAM là cố ý: mật khẩu chứa ``@`` (đúng ra phải là ``%40``
# nhưng thực tế vẫn gặp) làm một regex dè dặt dừng ở ``@`` ĐẦU và để lọt phần
# đuôi mật khẩu. Tham lam thì ăn tới ``@`` CUỐI trong cùng cụm không-khoảng-
# trắng; nó không vượt qua được dấu cách nên không nuốt nhầm một địa chỉ email
# đứng sau trong cùng câu.
_RE_USERINFO = re.compile(r"(?P<scheme>[A-Za-z][\w+.\-]*://)[^\s]*:[^\s]*@")


def che_userinfo(van_ban: str) -> str:
    """Thay ``scheme://user:pass@`` bằng ``scheme://***:***@``.

    Cố ý KHÔNG cố che mọi thứ trông giống bí mật — chỉ che đúng dạng đã biết là
    mang credential. Che quá tay làm thông báo lỗi vô dụng, và một thông báo vô
    dụng thì người vận hành sẽ đi tìm giá trị thật ở chỗ khác.
    """
    return _RE_USERINFO.sub(lambda m: f"{m.group('scheme')}***:***@", van_ban)


class LoiCauHinh(RuntimeError):
    """Lỗi cấu hình do CHÍNH kho này phát ra.

    Message của nó được viết để KHÔNG mang giá trị cấu hình — chỉ nêu tên biến.

    Sống ở đây (chứ không ở ``config.py``) vì ``mo_ta_loi_an_toan`` cần nhận
    diện được nó ở đúng ca ``config.py`` không import nổi.

    Là lớp con của ``RuntimeError`` để mọi ``except RuntimeError`` và
    ``pytest.raises(RuntimeError, match=...)`` sẵn có vẫn hoạt động.

    Ý nghĩa: "an toàn để in" là một thuộc tính của KIỂU, không phải một phỏng
    đoán theo hình dạng chuỗi. Một exception bất kỳ mang message gì thì không
    ai biết trước; một ``LoiCauHinh`` thì có người viết ra nó và chịu trách
    nhiệm rằng nó chỉ nêu TÊN biến.
    """


# Tên field/chỉ số hợp lệ. Mọi thành phần ``loc`` khác — ví dụ KHOÁ của một
# dict do người dùng đặt — thay bằng ``?``: chính khoá ấy có thể là dữ liệu.
_RE_TEN_TRUONG = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Mô tả CỐ ĐỊNH theo mã lỗi của pydantic. Cố ý không dùng ``msg`` của pydantic:
# với validator tự viết, ``msg`` chính là text của ``ValueError`` mà tác giả
# raise, và tác giả hoàn toàn có thể nhét giá trị vào đó —
# ``raise ValueError(f"gia tri bi mat la {value}")``. Đo được: canary xuất hiện
# nguyên văn trong ``msg`` NGAY CẢ khi đã gọi ``errors(include_input=False)``.
# Mã lỗi thì do pydantic (hoặc tác giả) đặt tên, không sinh ra từ giá trị.
_MO_TA_THEO_MA = {
    "missing": "thiếu giá trị",
    "int_parsing": "không phải số nguyên hợp lệ",
    "float_parsing": "không phải số thực hợp lệ",
    "bool_parsing": "không phải giá trị luận lý hợp lệ",
    "string_too_short": "chuỗi quá ngắn",
    "string_too_long": "chuỗi quá dài",
    "greater_than_equal": "nhỏ hơn giá trị tối thiểu cho phép",
    "less_than_equal": "lớn hơn giá trị tối đa cho phép",
    "value_error": "validator từ chối giá trị",
    "extra_forbidden": "biến không được khai báo",
    "url_parsing": "không phải URL hợp lệ",
}


def _vi_tri_an_toan(vi_tri) -> str:
    if not isinstance(vi_tri, (list, tuple)) or not vi_tri:
        return "?"
    phan = []
    for x in vi_tri:
        if isinstance(x, int) and not isinstance(x, bool):
            phan.append(str(x))
        elif isinstance(x, str) and _RE_TEN_TRUONG.match(x):
            phan.append(x)
        else:
            phan.append("?")
    return ".".join(phan)


def _chi_ten_lop(exc: BaseException) -> str:
    return (
        f"{type(exc).__name__} — không in message vì chưa chứng minh được nó "
        "không mang giá trị cấu hình"
    )


def mo_ta_loi_an_toan(exc: BaseException) -> str:
    """Mô tả một exception mà KHÔNG in giá trị cấu hình.

    Vì sao không dùng ``str(exc)``: ``ValidationError`` của pydantic chèn
    ``input_value=<giá trị người dùng đặt>`` vào message.

    Vì sao cũng không dùng ``msg`` của pydantic: với validator tự viết, ``msg``
    là text của chính ``ValueError`` mà tác giả raise — hoàn toàn có thể mang
    giá trị. Đo được: canary nằm nguyên văn trong ``msg`` kể cả khi đã gọi
    ``errors(include_input=False, include_context=False, include_url=False)``.

    Nên chỉ hai thứ được xuất ra: VỊ TRÍ (tên field, đã lọc) và MÃ LỖI (do
    pydantic/tác giả đặt tên, không sinh từ giá trị). Câu mô tả lấy từ bảng
    CỐ ĐỊNH trong tệp này.

    Ba mức, từ nhiều thông tin nhất tới ít nhất:

    1. ``.errors()`` nhận đủ ba cờ loại trừ và trả cấu trúc đúng → ``loc``+``type``;
    2. là ``LoiCauHinh`` → in message, vì kiểu ấy là lời cam kết rằng message
       chỉ nêu tên biến;
    3. còn lại → CHỈ tên lớp. Không đoán, không in thô.
    """
    lay = getattr(exc, "errors", None)
    if callable(lay):
        try:
            ds = lay(
                include_input=False, include_context=False, include_url=False
            )
        except TypeError:
            # Phiên bản pydantic không nhận các cờ loại trừ. KHÔNG gọi lại
            # ``errors()`` trần: bản không tham số là bản MANG giá trị.
            return _chi_ten_lop(exc)
        except Exception:  # noqa: BLE001 — bộ mô tả lỗi không được tự ném lỗi
            return _chi_ten_lop(exc)

        if isinstance(ds, (list, tuple)) and ds:
            phan = []
            for muc in ds:
                if not isinstance(muc, dict):
                    return _chi_ten_lop(exc)
                ma = muc.get("type")
                ma = ma if isinstance(ma, str) and _RE_TEN_TRUONG.match(ma) else "?"
                mo_ta = _MO_TA_THEO_MA.get(ma)
                vi_tri = _vi_tri_an_toan(muc.get("loc"))
                phan.append(
                    f"{vi_tri}: {mo_ta} [{ma}]" if mo_ta else f"{vi_tri}: [{ma}]"
                )
            return f"{type(exc).__name__}: " + "; ".join(phan)

    if isinstance(exc, LoiCauHinh):
        return f"{type(exc).__name__}: {che_userinfo(str(exc))}"

    return _chi_ten_lop(exc)
