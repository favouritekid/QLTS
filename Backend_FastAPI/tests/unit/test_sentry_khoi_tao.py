# -*- coding: utf-8 -*-
"""F223 (Codex lần 6) — Sentry: MỘT nơi khởi tạo (``app/core/sentry_init.py``) và sự kiện gửi đi
KHÔNG mang dữ liệu cá nhân.

Đo bằng sentry-sdk THẬT (bản ghim), transport GIẢ bắt mọi envelope, KHÔNG mạng: mọi lời gọi socket
bị chặn + đếm (phải 0). Ứng dụng FastAPI NHỎ dựng SAU khi khởi tạo (như ``main.py``: route gắn sau
``init`` ⇒ tích hợp FastAPI / Starlette của SDK thật sự bọc route). Mỗi ca đặt mã giả (sinh lúc
chạy) vào ĐÚNG MỘT nguồn — thân JSON, biến cục bộ, chuỗi truy vấn, chữ ngoại lệ, log INFO, log
ERROR, header Referer, cookie, token trong đường dẫn — rồi kiểm (a) SDK có bắt sự kiện (ca không
rỗng), (b) mã giả KHÔNG có trong byte của BẤT KỲ envelope nào. Mỗi tuỳ chọn chặn của
``khoi_tao_sentry`` có đúng một ca đỏ khi gỡ nó (đột biến: báo cáo E4 §5).

Nối dây: ``main.py`` thật sự gọi hàm chủ sở hữu (tiến trình con import ``app.main`` với DSN giả rồi
đọc tuỳ chọn của client) và không chỗ nào khác trong ``app/`` gọi ``sentry_sdk.init``.
Sau mỗi ca: client đóng, mọi scope về client không ghi (trạng thái toàn cục được dọn).
"""
import ast
import json
import logging
import os
import random
import secrets
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
import sentry_sdk
from fastapi import FastAPI
from sentry_sdk.transport import Transport

from app.core import sentry_init
from app.core.sentry_init import khoi_tao_sentry, loc_su_kien
from tests.fixtures.hoi_dong_seed import ma_gia

pytestmark = pytest.mark.unit

GOC = Path(__file__).resolve().parents[2]  # Backend_FastAPI
DSN_GIA = "https://gia@sentry.invalid/1"


class _BatGiu(Transport):
    """Transport giả: giữ mọi envelope trong bộ nhớ, không gửi gì."""

    def __init__(self, options=None):
        super().__init__(options)
        self.envelope = []

    def capture_envelope(self, envelope):
        self.envelope.append(envelope)

    def flush(self, timeout, callback=None):
        return None

    def kill(self):
        return None


def _ba_scope():
    return (
        sentry_sdk.get_global_scope(),
        sentry_sdk.get_isolation_scope(),
        sentry_sdk.get_current_scope(),
    )


def _don_sentry():
    sentry_sdk.get_client().close()
    for s in _ba_scope():
        s.set_client(None)
        s.clear_breadcrumbs()


def _dung_app(ma, token):
    """Ứng dụng nhỏ — dựng SAU khi khởi tạo Sentry. Mỗi route đặt ``ma`` / ``token`` vào đúng một
    nguồn."""
    app = FastAPI()
    log = logging.getLogger("app.gia_sentry_e4")

    @app.post("/gia/than")
    async def than(payload: dict):
        raise RuntimeError("loi gia")

    @app.get("/gia/cuc-bo")
    async def cuc_bo():
        bien_cuc_bo = "".join(ma)  # chỉ có trong biến cục bộ của khung route
        raise RuntimeError("loi gia %d" % len(bien_cuc_bo))

    @app.get("/gia/loi")
    async def loi():
        raise RuntimeError("loi gia")

    @app.get("/gia/thong-diep")
    async def thong_diep():
        raise RuntimeError("loi gia ma " + ma)

    @app.get("/gia/log-info")
    async def log_info():
        log.info("gia ma %s", ma)
        raise RuntimeError("loi gia")

    @app.get("/gia/log-error")
    async def log_error():
        log.error("gia ma %s", ma)
        return {"ok": True}

    @app.get("/api/admissions/confirm/{token}")
    async def xac_nhan(token: str):
        raise RuntimeError("loi gia")

    return app


@pytest.fixture
def mang_bi_chan(monkeypatch):
    dem = {"n": 0}

    def chan(*a, **k):
        dem["n"] += 1
        raise OSError("mạng bị chặn trong test Sentry")

    monkeypatch.setattr(socket.socket, "connect", chan)
    monkeypatch.setattr(socket.socket, "connect_ex", chan)
    monkeypatch.setattr(socket, "create_connection", chan)
    monkeypatch.setattr(socket, "getaddrinfo", chan)
    return dem


@pytest.fixture
def sg(mang_bi_chan):
    """Sentry khởi tạo QUA ``khoi_tao_sentry`` (giao dịch lấy mẫu 100% cho tất định) + transport
    giả + ứng dụng nhỏ. Dọn trạng thái Sentry toàn cục sau ca."""
    for s in _ba_scope():
        s.clear_breadcrumbs()
    bg = _BatGiu()
    ma = ma_gia(random.randrange(10**6))
    token = "tokgia" + secrets.token_hex(8)
    try:
        assert khoi_tao_sentry(DSN_GIA, "test", 1.0, transport=bg) is True
        yield {
            "bg": bg,
            "ma": ma,
            "token": token,
            "app": _dung_app(ma, token),
            "mang": mang_bi_chan,
        }
    finally:
        _don_sentry()
    assert not sentry_sdk.get_client().is_active()


async def _gui(sg, method, url, **kw):
    for s in _ba_scope():
        s.clear_breadcrumbs()
    tr = httpx.ASGITransport(app=sg["app"], raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=tr, base_url="http://gia.invalid") as c:
        r = await c.request(method, url, **kw)
    sentry_sdk.flush()
    loi, gd, tho = [], [], b""
    for env in sg["bg"].envelope:
        tho += env.serialize()
        for it in env.items:
            if it.type == "event":
                loi.append(json.loads(it.get_bytes()))
            elif it.type == "transaction":
                gd.append(json.loads(it.get_bytes()))
    assert sg["mang"]["n"] == 0, "SDK đã thử gọi mạng"
    return r, loi, gd, tho


def _khong_co(sg, tho, khoa="ma"):
    return sg[khoa].encode() not in tho


# ═══════════════════════════════ không DSN ⇒ không khởi tạo ═══════════════════════════════
def test_dsn_rong_thi_khong_khoi_tao():
    assert khoi_tao_sentry("", "test", 1.0) is False
    assert not sentry_sdk.get_client().is_active()


# ═══════════════════════════════ mỗi nguồn dữ liệu một ca ═══════════════════════════════════
async def test_than_json_khong_vao_su_kien(sg):
    # max_request_body_size="never" — SDK không đọc thân.
    r, loi, _gd, tho = await _gui(
        sg, "POST", "/gia/than", json={"ma_ho_so": [sg["ma"]]}
    )
    assert r.status_code == 500 and len(loi) == 1
    assert (
        loi[0]["request"]["method"] == "POST"
    )  # có thông tin request, chỉ không có thân
    assert _khong_co(sg, tho), "thân JSON (mã giả) có trong envelope"


async def test_bien_cuc_bo_khong_vao_su_kien(sg):
    # include_local_variables=False — khung ngăn xếp không kèm biến.
    r, loi, _gd, tho = await _gui(sg, "GET", "/gia/cuc-bo")
    assert r.status_code == 500 and len(loi) == 1
    khung = loi[0]["exception"]["values"][-1]["stacktrace"]["frames"]
    assert khung and not any("vars" in k for k in khung)
    assert _khong_co(sg, tho), "biến cục bộ (mã giả) có trong envelope"


async def test_chuoi_truy_van_khong_vao_su_kien(sg):
    # loc_su_kien bỏ query_string (SDK luôn thu — _asgi_common._get_request_data).
    r, loi, gd, tho = await _gui(sg, "GET", "/gia/loi?ma=" + sg["ma"])
    assert r.status_code == 500 and len(loi) == 1 and len(gd) == 1
    assert "query_string" not in loi[0]["request"]
    assert _khong_co(sg, tho), "chuỗi truy vấn (mã giả) có trong envelope"


async def test_chu_ngoai_le_chi_con_loai(sg):
    # loc_su_kien: chữ của ngoại lệ ⇒ chỉ loại + mã số (loai_loi_an_toan).
    r, loi, _gd, tho = await _gui(sg, "GET", "/gia/thong-diep")
    assert r.status_code == 500 and len(loi) == 1
    assert loi[0]["exception"]["values"][-1]["type"] == "RuntimeError"
    assert _khong_co(sg, tho), "chữ của ngoại lệ (mã giả) có trong envelope"


async def test_log_info_khong_thanh_breadcrumb(sg):
    # max_breadcrumbs=0 — bộ che log KHÔNG che chuỗi số trơn (khoảng trống có chủ ý của log máy
    # chủ) ⇒ breadcrumb từ log là đường lộ (đo E4) ⇒ không breadcrumb nào.
    r, loi, _gd, tho = await _gui(sg, "GET", "/gia/log-info")
    assert r.status_code == 500 and len(loi) == 1
    assert not (loi[0].get("breadcrumbs") or {}).get("values")
    assert _khong_co(sg, tho), "breadcrumb từ log (mã giả) có trong envelope"


async def test_log_error_khong_thanh_su_kien(sg):
    # LoggingIntegration(event_level=None) — log ERROR không thành sự kiện.
    r, loi, gd, tho = await _gui(sg, "GET", "/gia/log-error")
    assert r.status_code == 200 and len(gd) == 1  # SDK đang chạy (có giao dịch)
    assert loi == []
    assert _khong_co(sg, tho), "log ERROR (mã giả) có trong envelope"


async def test_header_referer_khong_vao_su_kien(sg):
    # loc_su_kien: chỉ giữ header thuộc TIEU_DE_GIU.
    r, loi, _gd, tho = await _gui(
        sg,
        "GET",
        "/gia/loi",
        headers={"referer": "https://gia.invalid/?ma=" + sg["ma"]},
    )
    assert r.status_code == 500 and len(loi) == 1
    assert set(loi[0]["request"]["headers"]) <= sentry_init.TIEU_DE_GIU
    assert _khong_co(sg, tho), "header Referer (mã giả) có trong envelope"


async def test_cookie_khong_vao_su_kien(sg):
    # send_default_pii=False — SDK không thu cookie.
    r, loi, _gd, tho = await _gui(
        sg, "GET", "/gia/loi", headers={"cookie": "gia=" + sg["ma"]}
    )
    assert r.status_code == 500 and len(loi) == 1
    assert "cookies" not in loi[0]["request"]
    assert _khong_co(sg, tho), "cookie (mã giả) có trong envelope"


async def test_token_trong_duong_dan_bi_che(sg):
    # loc_su_kien: url qua bộ che log (tiền tố đường dẫn mang token — TOKEN_PATH_PREFIXES).
    r, loi, _gd, tho = await _gui(sg, "GET", "/api/admissions/confirm/" + sg["token"])
    assert r.status_code == 500 and len(loi) == 1
    assert "<redacted>" in loi[0]["request"]["url"]
    assert _khong_co(sg, tho, "token"), "token trong đường dẫn có trong envelope"


async def test_token_trong_ten_giao_dich_khi_khong_khop_route_bi_che(sg):
    # Đường không khớp route ⇒ SDK đặt TÊN giao dịch = đường dẫn thô ⇒ loc_su_kien che cả tên.
    r, loi, gd, tho = await _gui(sg, "GET", "/confirm/" + sg["token"])
    assert r.status_code == 404 and loi == [] and len(gd) == 1
    assert _khong_co(
        sg, tho, "token"
    ), "token trong tên giao dịch / url có trong envelope"


def test_bo_loc_hong_thi_bo_su_kien():
    class _Hong(dict):
        def items(self):
            raise RuntimeError("hỏng")

    assert loc_su_kien({"request": {"headers": _Hong(a=1)}}, {}) is None


# ═══════════════════════════════ nối dây: main.py ⇒ hàm chủ sở hữu ═══════════════════════════
def test_moi_noi_goi_sentry_init_chi_o_chu_so_huu():
    goi = []
    for p in sorted((GOC / "app").rglob("*.py")):
        cay = ast.parse(p.read_text(encoding="utf-8"))
        for n in ast.walk(cay):
            if isinstance(n, ast.ImportFrom) and n.module == "sentry_sdk":
                assert "init" not in {a.name for a in n.names}, p
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "init"
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "sentry_sdk"
            ):
                goi.append(p.relative_to(GOC).as_posix())
    assert goi == ["app/core/sentry_init.py"]
    main = ast.parse((GOC / "app" / "main.py").read_text(encoding="utf-8"))
    assert any(
        isinstance(n, ast.Expr)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
        and n.value.func.id == "khoi_tao_sentry"
        for n in main.body
    ), "main.py không gọi khoi_tao_sentry ở cấp module"


_DOC_TUY_CHON = r"""
import json
import socket

MANG = []


def _chan(*a, **k):
    MANG.append(1)
    raise OSError("mạng bị chặn")


socket.socket.connect = socket.socket.connect_ex = _chan
socket.create_connection = socket.getaddrinfo = _chan
import app.main  # noqa: F401 — khởi tạo Sentry ở cấp module như khi chạy thật
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

c = sentry_sdk.get_client()
o = c.options
li = c.get_integration(LoggingIntegration)
ten = lambda f: None if f is None else "%s.%s" % (f.__module__, f.__qualname__)
print("TUY_CHON=" + json.dumps({
    "active": c.is_active(),
    "send_default_pii": o["send_default_pii"],
    "max_request_body_size": o["max_request_body_size"],
    "include_local_variables": o["include_local_variables"],
    "max_breadcrumbs": o["max_breadcrumbs"],
    "before_send": ten(o["before_send"]),
    "before_send_transaction": ten(o["before_send_transaction"]),
    "log_thanh_su_kien": li is not None and li._handler is not None,
    "goi_mang": len(MANG),
}))
"""


def test_main_khoi_tao_sentry_qua_ham_chu_so_huu():
    env = dict(os.environ, SENTRY_DSN=DSN_GIA, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run(
        [sys.executable, "-c", _DOC_TUY_CHON],
        cwd=str(GOC),
        env=env,
        capture_output=True,
        text=True,
        timeout=50,
    )
    dong = [x for x in r.stdout.splitlines() if x.startswith("TUY_CHON=")]
    assert r.returncode == 0 and len(dong) == 1, (r.returncode, r.stderr[-800:])
    assert json.loads(dong[0][len("TUY_CHON=") :]) == {
        "active": True,
        "send_default_pii": False,
        "max_request_body_size": "never",
        "include_local_variables": False,
        "max_breadcrumbs": 0,
        "before_send": "app.core.sentry_init.loc_su_kien",
        "before_send_transaction": "app.core.sentry_init.loc_su_kien",
        "log_thanh_su_kien": False,
        "goi_mang": 0,
    }
