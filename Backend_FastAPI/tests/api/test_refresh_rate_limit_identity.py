"""Xô rate-limit của ``/auth/refresh`` phải tách theo CHỦ THỂ, không theo IP.

Bối cảnh (audit prod 2026-07-30): cả trường ra Internet qua một IP NAT, mà
``/auth/refresh`` bị giới hạn 20/giờ theo IP — tức một quota CHUNG cho toàn bộ
nhân sự. 32% request refresh (86/270 trong 24h) bị chặn, và mỗi lần chặn là một
officer bị đá ra giữa lúc nhập liệu.

Hai lớp kiểm, vì mỗi lớp một mình đều xanh oan được:

* **Wiring** — endpoint THẬT (``app.routers.auth.refresh_access_token``) phải
  thực sự được đăng ký với đúng ``key_func`` và đúng ``limit_provider``. Không
  có lớp này thì mọi test hành vi bên dưới chỉ đang chứng minh hai hàm rời hoạt
  động đúng, trong khi endpoint vẫn chạy hạn mức IP cũ.
* **Hành vi qua ASGI** — hai xô thật sự tách nhau và hai hạn mức thật sự khác
  nhau. Không có lớp này thì wiring đúng nhưng logic khoá có thể vẫn gộp mọi
  người vào một xô.
"""
from __future__ import annotations

import time

import jwt
import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.core import rate_limits as rl
from app.core.rate_limits import get_refresh_identity_key, refresh_limit

REFRESH_ROUTE = "app.routers.auth.refresh_access_token"


def _make_refresh_token(
    sub: str = "officer01",
    jti: str = "jti-1",
    token_type: str = "refresh",
    expires_in: int = 3600,
    secret: str | None = None,
) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": sub,
            "jti": jti,
            "type": token_type,
            "exp": now + expires_in,
            "iat": now,
        },
        secret if secret is not None else settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )


class _FakeRequest:
    """Đủ mặt cho ``get_refresh_identity_key``: cookies + client IP."""

    def __init__(self, cookies: dict[str, str], ip: str = "203.0.113.7"):
        self.cookies = cookies
        self.headers = {"X-Real-IP": ip}
        self.client = type("C", (), {"host": ip})()
        self.state = type("S", (), {})()


# ---------------------------------------------------------------------------
# Lớp 1 — WIRING trên endpoint thật
# ---------------------------------------------------------------------------


def test_real_refresh_endpoint_is_registered_with_identity_key_and_dynamic_limit():
    """``refresh_access_token`` thật dùng ĐÚNG cặp key_func + limit_provider.

    slowapi xếp một limit dạng callable vào ``_dynamic_route_limits`` (khác
    ``_route_limits`` của limit tĩnh), nên chỉ riêng việc endpoint có mặt ở đây
    đã chứng minh nó không còn dùng hằng ``AUTH_REFRESH_TOKEN`` như trước.
    """
    import app.routers.auth  # noqa: F401 — import để decorator kịp đăng ký

    dynamic = rl.limiter._dynamic_route_limits
    assert REFRESH_ROUTE in dynamic, (
        f"{REFRESH_ROUTE} không nằm trong _dynamic_route_limits — endpoint vẫn "
        f"đang dùng hạn mức TĨNH (theo IP) chứ không phải refresh_limit"
    )

    groups = dynamic[REFRESH_ROUTE]
    assert len(groups) == 1, f"kỳ vọng đúng một LimitGroup, có {len(groups)}"
    group = groups[0]

    assert group.key_function is get_refresh_identity_key, (
        "key_func của endpoint không phải get_refresh_identity_key → xô vẫn "
        "chia theo IP"
    )
    # Tên đã bị name-mangle trong LimitGroup; đọc thẳng vì đây chính là thứ
    # quyết định hạn mức nào được áp.
    provider = getattr(group, "_LimitGroup__limit_provider")
    assert provider is refresh_limit, (
        "limit_provider của endpoint không phải refresh_limit → hai hạn mức "
        "không bao giờ được phân biệt"
    )


def test_limit_provider_and_key_func_match_slowapi_calling_convention():
    """slowapi nhận diện hai hàm này QUA TÊN THAM SỐ.

    ``slowapi/wrappers.py:86`` kiểm ``"key" in signature(limit_provider)`` để
    quyết định gọi ``limit_provider(key_func(request))`` hay ``limit_provider()``;
    và ngay sau đó ``assert "request" in signature(key_function)``. Đổi tên tham
    số là hỏng lúc chạy chứ không phải lúc import, nên khoá lại ở đây.
    """
    import inspect

    assert list(inspect.signature(refresh_limit).parameters) == ["key"]
    assert "request" in inspect.signature(get_refresh_identity_key).parameters


# ---------------------------------------------------------------------------
# Lớp 2 — hành vi của khoá
# ---------------------------------------------------------------------------


def test_identity_key_uses_subject_when_token_proves_it():
    key = get_refresh_identity_key(
        _FakeRequest({"refresh_token": _make_refresh_token(sub="officer01")})
    )
    assert key == "refresh:user:officer01"


def test_two_users_behind_one_ip_do_not_share_a_bucket():
    """Đây chính là ca prod: cùng IP NAT, khác người."""
    ip = "203.0.113.7"
    a = get_refresh_identity_key(
        _FakeRequest({"refresh_token": _make_refresh_token(sub="officer01")}, ip)
    )
    b = get_refresh_identity_key(
        _FakeRequest({"refresh_token": _make_refresh_token(sub="officer02")}, ip)
    )
    assert a != b, "hai người dùng sau cùng một IP vẫn bị gộp chung xô"


@pytest.mark.parametrize(
    "cookies, reason",
    [
        ({}, "không có cookie refresh_token"),
        ({"refresh_token": "khong-phai-jwt"}, "cookie không phải JWT"),
        (
            {"refresh_token": _make_refresh_token(token_type="access")},
            "token type=access, không phải refresh",
        ),
        (
            {"refresh_token": _make_refresh_token(expires_in=-60)},
            "token đã hết hạn",
        ),
        (
            {"refresh_token": _make_refresh_token(secret="khoa-sai-hoan-toan")},
            "chữ ký sai — nếu lọt thì ai cũng tự đúc được sub",
        ),
        ({"refresh_token": _make_refresh_token(sub="")}, "sub rỗng"),
        ({"refresh_token": _make_refresh_token(jti="")}, "jti rỗng"),
    ],
)
def test_identity_key_falls_back_to_ip_when_identity_not_proven(cookies, reason):
    """Fail-safe theo hướng SIẾT: không chứng minh được thì chịu hạn mức chặt."""
    key = get_refresh_identity_key(_FakeRequest(cookies, ip="198.51.100.9"))
    assert key == "refresh:ip:198.51.100.9", f"phải về khoá IP khi {reason}"


def _per_hour(value: str) -> int:
    amount, _, unit = value.partition("/")
    assert unit == "hour", f"kỳ vọng hạn mức theo giờ, gặp {value!r}"
    return int(amount)


def _production_limit(attr_name: str) -> str:
    """Giá trị hằng ở chế độ KHÔNG phải test, đọc qua AST.

    Ở ``APP_ENV=test`` cả hai hằng đều bị nâng lên ``10000/hour`` để test khác
    không vướng rate limit — nên so sánh chúng lúc chạy test là so hai giá trị
    bằng nhau, vô nghĩa. Con số thật nằm ở nhánh ``if settings.APP_ENV != "test"``
    của biểu thức, và đó mới là thứ chạy ở prod.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(rl))
    cls = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "RateLimits"
    )
    for node in cls.body:
        if not isinstance(node, ast.Assign):
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id != attr_name:
            continue
        value = node.value
        # `"20/hour" if settings.APP_ENV != "test" else "10000/hour"`
        return ast.literal_eval(value.body if isinstance(value, ast.IfExp) else value)
    raise AssertionError(f"RateLimits.{attr_name} không tồn tại")


def test_refresh_limit_picks_the_right_constant_for_each_key(monkeypatch):
    """``refresh_limit`` chỉ CHỌN giữa hai hằng, không tự giữ con số nào.

    Monkeypatch hai hằng rồi kiểm hàm trả đúng giá trị vừa đặt: nếu ai đó chép
    cứng ``"20/hour"``/``"120/hour"`` vào thân hàm, test này đỏ ngay — đó chính
    là kiểu trùng lặp làm hai nơi lệch nhau sau một lần sửa.
    """
    monkeypatch.setattr(rl.RateLimits, "AUTH_REFRESH_TOKEN", "7/hour", raising=False)
    monkeypatch.setattr(
        rl.RateLimits, "AUTH_REFRESH_TOKEN_IDENTIFIED", "99/hour", raising=False
    )

    assert refresh_limit("refresh:user:officer01") == "99/hour"
    assert refresh_limit("refresh:ip:203.0.113.7") == "7/hour"
    # Khoá lạ (không thuộc hai tiền tố) phải chịu nhánh chặt.
    assert refresh_limit("dieu-gi-do-la") == "7/hour"


def test_production_identified_limit_is_looser_than_ip_limit():
    """Ở PROD, nhánh chứng minh được danh tính phải rộng hơn nhánh IP.

    Nếu không thì việc tách khoá chẳng giải quyết được gì: người dùng hợp lệ
    vẫn bị chặn y như cũ, chỉ khác là bị chặn trong một xô riêng.
    """
    ip_limit = _production_limit("AUTH_REFRESH_TOKEN")
    identified_limit = _production_limit("AUTH_REFRESH_TOKEN_IDENTIFIED")

    assert ip_limit != identified_limit
    assert _per_hour(identified_limit) > _per_hour(ip_limit), (
        f"hạn mức có danh tính ({identified_limit}) không rộng hơn hạn mức IP "
        f"({ip_limit})"
    )


# ---------------------------------------------------------------------------
# Lớp 3 — 429 THẬT qua ASGI, hai xô, hai hạn mức
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_asgi_identified_and_anonymous_buckets_are_independent(monkeypatch):
    """Đo qua request thật: hết xô IP không kéo theo người dùng có danh tính.

    Hai hằng bị hạ xuống mức nhỏ để không phải bắn 20/120 request. ``refresh_limit``
    đọc ``RateLimits`` LÚC GỌI nên monkeypatch thuộc tính lớp là đủ — và chính
    điều đó cũng là một phép kiểm: nếu ai đó chép cứng con số vào thân hàm, test
    này đỏ.
    """
    monkeypatch.setattr(rl.settings, "APP_ENV", "development", raising=False)
    monkeypatch.setattr(rl.RateLimits, "AUTH_REFRESH_TOKEN", "1/hour", raising=False)
    monkeypatch.setattr(
        rl.RateLimits, "AUTH_REFRESH_TOKEN_IDENTIFIED", "3/hour", raising=False
    )

    app = FastAPI()
    assert rl.configure_rate_limiting(app) is True

    @app.post("/api/auth/refresh")
    @rl.limiter.limit(refresh_limit, key_func=get_refresh_identity_key)
    async def fake_refresh(request: Request):  # noqa: ARG001 — slowapi cần tham số
        return {"ok": True}

    ip = "192.0.2.55"  # IP riêng để không đụng state của test khác
    headers = {"X-Real-IP": ip}
    token = _make_refresh_token(sub="officer-asgi", jti="jti-asgi")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://ratelimit.test") as c:
        # Nhánh IP: hạn mức 1/giờ → request thứ hai bị chặn.
        assert (await c.post("/api/auth/refresh", headers=headers)).status_code == 200
        blocked = await c.post("/api/auth/refresh", headers=headers)
        assert blocked.status_code == 429, blocked.text

        # CÙNG IP đó, nhưng có refresh token hợp lệ → xô khác, hạn mức 3/giờ.
        auth_headers = {**headers, "Cookie": f"refresh_token={token}"}
        for i in range(3):
            ok = await c.post("/api/auth/refresh", headers=auth_headers)
            assert ok.status_code == 200, f"request {i + 1} có danh tính: {ok.text}"

        # …và nhánh có danh tính cũng có trần riêng của nó.
        over = await c.post("/api/auth/refresh", headers=auth_headers)
        assert over.status_code == 429, over.text
