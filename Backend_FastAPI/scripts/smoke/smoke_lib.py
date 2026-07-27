"""Tiện ích dùng chung cho các bước smoke — gọi API THẬT qua HTTP.

⚠️ CÔNG CỤ PHÁ HOẠI DỮ LIỆU. Bộ script này đặt lại mật khẩu tài khoản, sửa
thẳng bảng học phí và cấu hình ngành. Chỉ chạy trên môi trường dùng-một-lần.

Ba chốt chặn bắt buộc, KHÔNG có giá trị mặc định nào:
  * ``SMOKE_ALLOW_DESTRUCTIVE=1`` — người chạy phải nói rõ mình chấp nhận.
  * ``SMOKE_BASE`` — địa chỉ API. Không đoán ``backend:8000``: đoán sai địa chỉ
    là bắn thẳng vào hệ thống thật.
  * ``SMOKE_PASSWORD`` — mật khẩu gieo cho tài khoản smoke. Hằng số trong mã
    nguồn nghĩa là mật khẩu admin công khai trên mọi DB từng chạy script.

Thêm một lớp nữa: từ chối chạy khi môi trường hoặc chuỗi kết nối trông giống
production/staging, kể cả khi ba biến trên đã đặt đúng.
"""
import asyncio
import json
import os
import re
from decimal import Decimal

import httpx

# Dấu hiệu môi trường THẬT — chặn cứng, không cho cờ nào ghi đè.
_DAU_HIEU_THAT = ("production", "prod", "staging", "qlts_production")


def _chan_moi_truong_that() -> None:
    """Từ chối chạy nếu đây không phải môi trường dùng-một-lần.

    Kiểm cả ``APP_ENV`` lẫn chuỗi kết nối DB: một stack dev trỏ nhầm sang DB
    prod vẫn có ``APP_ENV=development``, nên chỉ nhìn APP_ENV là chưa đủ.
    """
    if os.environ.get("SMOKE_ALLOW_DESTRUCTIVE") != "1":
        raise SystemExit(
            "CHẶN: bộ smoke sửa dữ liệu (đặt lại mật khẩu, ghi đè học phí).\n"
            "Đặt SMOKE_ALLOW_DESTRUCTIVE=1 nếu DB này là bản dùng-một-lần."
        )

    app_env = (os.environ.get("APP_ENV") or "").lower()
    if app_env in _DAU_HIEU_THAT:
        raise SystemExit(f"CHẶN: APP_ENV={app_env!r} — không chạy smoke ở đây.")

    dsn = (os.environ.get("DATABASE_URL") or "").lower()
    # Che mật khẩu trước khi in ra log.
    dsn_an = re.sub(r"://[^:]+:[^@]+@", "://***:***@", dsn)
    for dau in _DAU_HIEU_THAT:
        if dau in dsn:
            raise SystemExit(
                f"CHẶN: DATABASE_URL chứa {dau!r} ({dsn_an}) — trông như hệ "
                "thống thật. Smoke sẽ ghi đè học phí và mật khẩu."
            )


def _bat_buoc(ten: str, goi_y: str) -> str:
    gia_tri = os.environ.get(ten)
    if not gia_tri:
        raise SystemExit(f"CHẶN: thiếu biến môi trường {ten}. {goi_y}")
    return gia_tri


_chan_moi_truong_that()

BASE = _bat_buoc(
    "SMOKE_BASE",
    "Ví dụ: SMOKE_BASE=http://backend:8000 (địa chỉ API của stack smoke).",
)
PW = _bat_buoc(
    "SMOKE_PASSWORD",
    "Mật khẩu gieo cho tài khoản smoke — đặt một chuỗi dùng-một-lần.",
)

_KQ = []


def ghi(muc: str, ten: str, dat: bool, chi_tiet: str = ""):
    _KQ.append({"muc": muc, "ten": ten, "pass": bool(dat), "chi_tiet": chi_tiet})
    dau = "PASS" if dat else "FAIL"
    print(f"[{dau}] {muc} — {ten}" + (f" :: {chi_tiet}" if chi_tiet else ""))
    return dat


def tong_ket(nhan: str):
    tot = sum(1 for k in _KQ if k["pass"])
    print(f"\n===== {nhan}: {tot}/{len(_KQ)} PASS =====")
    for k in _KQ:
        if not k["pass"]:
            print(f"  FAIL: {k['muc']} — {k['ten']} :: {k['chi_tiet']}")
    print("SMOKE_RESULT_JSON " + json.dumps(
        {"nhan": nhan, "tong": len(_KQ), "pass": tot,
         "fail": [k for k in _KQ if not k["pass"]]}, ensure_ascii=False))
    return tot == len(_KQ)


async def xoa_gioi_han_dang_nhap():
    """Xoá bộ đếm rate-limit + lockout trong Redis.

    Endpoint login giới hạn 5 lần/khoảng — đúng về bảo mật, nhưng kịch bản smoke
    cần đăng nhập 7 vai liên tiếp. Xoá bộ đếm là thao tác của môi trường kiểm
    thử, KHÔNG phải nới lỏng ứng dụng.
    """
    import redis.asyncio as aioredis

    for db in (0, 1, 2, 3):
        try:
            r = aioredis.from_url(f"redis://redis:6379/{db}")
            keys = []
            async for k in r.scan_iter(match="*LIMITER*"):
                keys.append(k)
            async for k in r.scan_iter(match="*lockout*"):
                keys.append(k)
            async for k in r.scan_iter(match="*login_attempt*"):
                keys.append(k)
            if keys:
                await r.delete(*keys)
            await r.aclose()
        except Exception:
            pass


async def tao_client(username: str) -> httpx.AsyncClient:
    """Client ĐÃ đăng nhập cho một vai — mỗi vai một cookie jar riêng.

    Token nằm trong cookie httpOnly (không có trong body), và mutation cần
    CSRF double-submit qua header ``X-CSRF-Token``.
    """
    c = httpx.AsyncClient(timeout=90, follow_redirects=False)
    # Endpoint dùng OAuth2PasswordRequestForm ⇒ form-data, KHÔNG phải JSON.
    for lan in range(6):
        r = await c.post(f"{BASE}/api/auth/login",
                         data={"username": username, "password": PW})
        if r.status_code != 429:
            break
        await xoa_gioi_han_dang_nhap()
        await asyncio.sleep(1 + lan)
    r.raise_for_status()
    csrf = c.cookies.get("csrf_token") or c.cookies.get("csrftoken")
    if csrf:
        c.headers["X-CSRF-Token"] = csrf
    me = await c.get(f"{BASE}/api/users/me")
    assert me.status_code == 200, f"login {username} nhưng /users/me = {me.status_code}"
    return c


def duong_dan_ids() -> str:
    """Nơi seed ghi và các kịch bản đọc id đã gieo.

    Suy từ gốc dự án (thư mục cha của ``scripts/``) chứ KHÔNG hằng số ``/app``:
    cùng một đường dẫn dù chạy trong container hay ngoài host. Cho phép đổi
    bằng ``SMOKE_IDS_PATH`` khi chạy song song nhiều stack.
    """
    rieng = os.environ.get("SMOKE_IDS_PATH")
    if rieng:
        return rieng
    goc = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(goc, "smoke_ids.json")


def ghi_ids(du_lieu: dict) -> str:
    """Ghi NGUYÊN TỬ: tạo file tạm cùng thư mục rồi ``os.replace``.

    Nếu ghi thẳng mà tiến trình chết giữa chừng, kịch bản sau đọc phải JSON cụt
    và chết vì lý do vô nghĩa. ``os.replace`` là thao tác nguyên tử trên cùng
    hệ thống tệp nên người đọc chỉ thấy bản cũ hoặc bản mới, không thấy bản dở.
    """
    dich = duong_dan_ids()
    tam = f"{dich}.tmp"
    with open(tam, "w", encoding="utf-8") as f:
        json.dump(du_lieu, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tam, dich)
    return dich


def doc_ids() -> dict:
    """Đọc id đã gieo, báo lỗi CÓ HƯỚNG DẪN khi chưa chạy seed."""
    dich = duong_dan_ids()
    try:
        with open(dich, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise SystemExit(
            f"CHẶN: chưa thấy {dich}. Chạy smoke_seed.py trước — nó gieo dữ liệu "
            "và ghi file này cho các kịch bản sau."
        )
    except json.JSONDecodeError as e:
        raise SystemExit(f"CHẶN: {dich} hỏng ({e}). Chạy lại smoke_seed.py.")


async def xoa_tran_gui_lai_link(profile_id: int) -> None:
    """Xoá bộ đếm "3 link / 24h" của MỘT hồ sơ trong Redis.

    Trần này nằm ở Redis (``admission:confirm:resend:<id>``), KHÔNG ở bảng token
    — nên không thể né bằng cách chọn hồ sơ khác trong SQL. Lần chạy smoke trước
    để lại bộ đếm, làm lần sau bị chặn và báo lỗi oan cho code. Xoá bộ đếm là
    thao tác của môi trường kiểm thử, giống ``xoa_gioi_han_dang_nhap`` —
    KHÔNG nới lỏng ứng dụng.
    """
    import redis.asyncio as aioredis

    for db in (0, 1, 2, 3):
        try:
            r = aioredis.from_url(f"redis://redis:6379/{db}")
            await r.delete(f"admission:confirm:resend:{profile_id}")
            await r.aclose()
        except Exception:
            pass


def tien(x) -> Decimal:
    return Decimal(str(x))


def chay(main) -> None:
    """Chạy một kịch bản smoke và ĐỔI kết quả thành mã thoát tiến trình.

    ``asyncio.run(main())`` trần luôn thoát 0 kể cả khi có mục FAIL — người gọi
    (và CI) không có cách nào biết, nên smoke xanh giả. Mọi kịch bản phải đi qua
    đây, và ``main()`` phải ``return tong_ket(NHAN)``.
    """
    ket_qua = asyncio.run(main())
    if ket_qua is None:
        raise SystemExit(
            "LỖI KỊCH BẢN: main() không trả về gì. Phải `return tong_ket(NHAN)` "
            "để mã thoát phản ánh đúng kết quả."
        )
    raise SystemExit(0 if ket_qua else 1)
