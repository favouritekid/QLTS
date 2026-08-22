# tests/middleware/test_admission_freeze.py
"""T0-2 admission freeze middleware coverage.

Stub app dựng ĐỘNG theo ``FROZEN_PREFIXES`` (10 tiền tố, 11 router tuyển sinh)
nên không trôi khi danh sách dài ra. Stub giữ các ca này không cần DB/Casbin/Redis
và cho phép phủ kín ma trận method × tiền tố × trạng thái đóng băng.

Bản trước viết cứng "4 router / 3 prefix verified at HEAD 2c57e5d6" — đúng ở thời
điểm ấy, rồi các router ``/api/v2/`` ra đời và không ai rà lại. Đó chính là cách
39 đường ghi thoát khỏi cần gạt ở CẢ hai tầng.

The middleware reads ``settings.ADMISSION_FROZEN`` directly per request, so we
toggle the singleton and rely on the existing module import.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import settings as app_settings
from app.middleware.admission_freeze import (
    ADMISSION_ROUTER_MODULES,
    ADMISSION_WRITE_ROUTES,
    FROZEN_METHODS,
    FROZEN_PREFIXES,
    NON_ADMISSION_ROUTER_MODULES,
    AdmissionFreezeMiddleware,
)


def _make_stub_app() -> FastAPI:
    """App cô lập, route dựng THEO ``FROZEN_PREFIXES`` nên không trôi.

    Bản trước viết cứng ba tiền tố; khi ``FROZEN_PREFIXES`` dài ra thì các ca
    parametrize trên nó lại đánh vào route không tồn tại và 404 — xanh/đỏ vì lý
    do sai. Dựng động thì thêm tiền tố là stub tự có.
    """
    app = FastAPI()
    app.add_middleware(AdmissionFreezeMiddleware)

    methods = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]

    def _tao(scope: str):
        async def _xu_ly(rest: str = ""):
            return {"ok": True, "scope": scope, "rest": rest}

        return _xu_ly

    for prefix in FROZEN_PREFIXES:
        app.add_api_route(
            f"{prefix}/{{rest:path}}", _tao(prefix), methods=methods
        )

    app.add_api_route("/api/leads/{rest:path}", _tao("leads"), methods=methods)

    @app.get("/health")
    async def health_stub():
        return {"ok": True}

    # Khớp theo ĐOẠN path: hai đường dưới startswith một tiền tố nhưng KHÔNG
    # nằm dưới nó. Giữ cả bản v1 lẫn v2 — cùng một lỗi qua nhánh anh em.
    for gia in ("/api/admissionsfoo", "/api/v2/admin/roundsfoo"):
        app.add_api_route(gia, _tao("lookalike"), methods=methods)

    return app


@pytest.fixture
def stub_app() -> FastAPI:
    return _make_stub_app()


@pytest.fixture
async def client(stub_app: FastAPI):
    async with AsyncClient(
        transport=ASGITransport(app=stub_app),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.fixture
def freeze_off():
    original = app_settings.ADMISSION_FROZEN
    app_settings.ADMISSION_FROZEN = False
    try:
        yield
    finally:
        app_settings.ADMISSION_FROZEN = original


@pytest.fixture
def freeze_on():
    original = app_settings.ADMISSION_FROZEN
    app_settings.ADMISSION_FROZEN = True
    try:
        yield
    finally:
        app_settings.ADMISSION_FROZEN = original


# ---------------------------------------------------------------------------
# Contract sanity (data shape only — NOT a drift catch).
# ---------------------------------------------------------------------------


def test_freeze_constants_have_expected_shape():
    assert isinstance(FROZEN_PREFIXES, tuple)
    assert len(FROZEN_PREFIXES) >= 1
    assert all(p.startswith("/api/") for p in FROZEN_PREFIXES)
    assert FROZEN_METHODS == frozenset({"POST", "PUT", "PATCH", "DELETE"})


# ---------------------------------------------------------------------------
# Cổng chống trôi THẬT — đối chiếu theo cặp (method, path), không theo chuỗi.
#
# Bản trước quét ``"admission" in path`` nên vừa BÁO THỪA (các route GET như
# reports/catalog/export) vừa BỎ SÓT đường ghi không mang chữ đó
# (``/api/v2/admin/rounds/...``, ``/api/v2/admin/priority-config/...``).
# Bốn phép kiểm dưới đây buộc ba khai báo độc lập trong ``admission_freeze.py``
# phải khớp nhau, và mỗi phép chỉ vi phạm MỘT bất biến.
# ---------------------------------------------------------------------------

_METHOD_GHI = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _bang_route_that():
    """(method, path, module) của mọi route trên app thật.

    Import ``fastapi_app`` chạy ``include_router(...)`` cho toàn bộ router;
    lifespan KHÔNG chạy khi import nên đây vẫn là test đơn vị (không DB/Redis).
    """
    from app.main import fastapi_app

    ra = []
    for route in fastapi_app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None)
        if not isinstance(path, str) or not methods:
            continue
        mod = getattr(getattr(route, "endpoint", None), "__module__", "") or ""
        for m in methods:
            ra.append((m, path, mod))
    return ra


def _duoi_tien_to(path: str) -> bool:
    return any(path == fp or path.startswith(fp + "/") for fp in FROZEN_PREFIXES)


def test_bang_route_that_doc_duoc():
    """Chốt chặn cho ba ca dưới: nếu không đọc nổi bảng route thì chúng xanh giả."""
    bang = _bang_route_that()
    assert len(bang) > 300, (
        "Quet bang route chi thay %d muc — main.py ngung dang ky router, hoac "
        "phep quet hong. Dieu tra truoc khi tin ba ca sau." % len(bang)
    )


def test_moi_route_ghi_deu_XAC_DINH_DUOC_module():
    """Chốt chặn TRƯỚC phân loại: không route ghi nào được thiếu ``__module__``.

    Ba ca phân loại đều lọc ``and mod``, nên một endpoint không cung cấp
    ``__module__`` (functools.partial, endpoint dựng động, class-based view gắn
    thẳng) sẽ thành ``""`` rồi biến mất khỏi cả hai tập — thế giới "đóng" lại hở
    đúng chỗ không ai nhìn. Ca này bắt nó trước.
    """
    khuyet = sorted(
        (m, p) for m, p, mod in _bang_route_that() if m in _METHOD_GHI and not mod
    )
    assert not khuyet, (
        "Route GHI khong xac dinh duoc module: %s. Phan loai admission/"
        "non-admission dua tren module, nen metadata rong lam route bien mat "
        "khoi moi phep kiem." % khuyet
    )


def test_MOI_module_co_route_ghi_deu_da_duoc_phan_loai():
    """THẾ GIỚI ĐÓNG — không có module nào được ở ngoài cả hai tập.

    Đây là ca then chốt. Ba ca còn lại đều đi từ tập tuyển sinh hoặc từ tiền tố,
    nên một router MỚI ở tiền tố MỚI (``admissions_v3`` → ``/api/v3/admissions``)
    lọt qua tất cả: không thuộc ``ADMISSION_ROUTER_MODULES`` nên ca "router
    thoát" bỏ qua nó; không nằm dưới tiền tố nào nên ca "danh mục" và ca "hút
    nhầm" cũng bỏ qua. Bốn ca xanh — đúng hình dạng đã sinh ra sự cố v2.

    Ca này buộc người thêm router phải QUYẾT ĐỊNH, thay vì im lặng bỏ sót.
    """
    co_ghi = {
        mod for m, _, mod in _bang_route_that() if m in _METHOD_GHI and mod
    }
    chua_phan_loai = sorted(
        co_ghi - ADMISSION_ROUTER_MODULES - NON_ADMISSION_ROUTER_MODULES
    )
    assert not chua_phan_loai, (
        "Module co route GHI nhung CHUA duoc phan loai: %s.\n"
        "Khai bao no trong ADMISSION_ROUTER_MODULES (neu thuoc mien tuyen sinh, "
        "kem tien to tuong ung trong FROZEN_PREFIXES + khoi `location ~` cua "
        "nginx) hoac trong NON_ADMISSION_ROUTER_MODULES."
        % chua_phan_loai
    )


def test_hai_tap_module_khong_giao_nhau():
    """Chiều ngược: một module nằm ở CẢ HAI tập thì "đúng một" mất nghĩa."""
    giao = sorted(ADMISSION_ROUTER_MODULES & NON_ADMISSION_ROUTER_MODULES)
    assert not giao, "Module nam o CA HAI tap: %s" % giao


def test_khong_khai_thua_module_khong_con_ton_tai():
    """Khai báo thừa cũng phải đỏ — nếu không, hai tập trôi dần thành vô nghĩa.

    Một module đã bị xoá mà vẫn nằm trong tập sẽ che mất việc route của nó đã
    chuyển đi đâu.
    """
    co_ghi = {mod for m, _, mod in _bang_route_that() if m in _METHOD_GHI and mod}
    thua = sorted(
        (ADMISSION_ROUTER_MODULES | NON_ADMISSION_ROUTER_MODULES) - co_ghi
    )
    assert not thua, (
        "Module duoc khai bao nhung khong con route GHI nao: %s. "
        "Go khoi tap tuong ung." % thua
    )


def test_danh_muc_khop_dung_bang_route_that():
    """``ADMISSION_WRITE_ROUTES`` == mọi đường GHI nằm dưới ``FROZEN_PREFIXES``.

    Thêm/xoá một route ghi dưới tiền tố đã đóng băng ⇒ ĐỎ, để danh mục luôn là
    bản đã có người rà chứ không phải bản tự trôi.
    """
    that = {
        (m, p)
        for m, p, _ in _bang_route_that()
        if m in _METHOD_GHI and _duoi_tien_to(p)
    }
    khai = set(ADMISSION_WRITE_ROUTES)
    thieu = sorted(that - khai)
    thua = sorted(khai - that)
    assert not thieu and not thua, (
        "ADMISSION_WRITE_ROUTES lech bang route that.\n"
        "  co that ma thieu trong danh muc: %s\n"
        "  co trong danh muc ma khong con: %s" % (thieu, thua)
    )


def test_moi_duong_ghi_cua_router_tuyen_sinh_deu_bi_dong_bang():
    """Hồi quy của chính lỗ hổng này: router tuyển sinh mới ở tiền tố mới.

    Đo trên main@0c3031d7 TRƯỚC bản vá: 39 đường ghi ``/api/v2/`` thuộc 6 router
    tuyển sinh không nằm dưới tiền tố nào. Phép kiểm đi từ MODULE SỞ HỮU nên nó
    không phụ thuộc việc path có chứa chữ "admission" hay không.
    """
    ho = sorted(
        (m, p)
        for m, p, mod in _bang_route_that()
        if m in _METHOD_GHI and mod in ADMISSION_ROUTER_MODULES and not _duoi_tien_to(p)
    )
    assert not ho, (
        "Duong GHI cua router tuyen sinh THOAT khoi dong bang: %s. "
        "Bo sung tien to vao FROZEN_PREFIXES (va dong bo khoi `location ~` trong "
        "nginx/templates/default.conf.template)." % ho
    )


def test_khong_hut_nham_route_ngoai_mien_tuyen_sinh():
    """Chiều ngược: tiền tố không được khoá nhầm API quản trị khác.

    Chặn cả ``/api/v2/admin`` sẽ tiện hơn nhiều nhưng khoá luôn casbin,
    system-config, vn-school, vn-locality — không thuộc tuyển sinh.
    """
    la = sorted(
        (m, p, mod)
        for m, p, mod in _bang_route_that()
        if m in _METHOD_GHI and _duoi_tien_to(p) and mod not in ADMISSION_ROUTER_MODULES
    )
    assert not la, (
        "Tien to dong bang hut nham duong ghi NGOAI mien tuyen sinh: %s. "
        "Thu hep FROZEN_PREFIXES, hoac neu that su thuoc tuyen sinh thi khai bao "
        "module do trong ADMISSION_ROUTER_MODULES." % la
    )


def test_nginx_template_dung_cung_tap_tien_to():
    """Hai tầng phải nói cùng một danh sách — sinh lại chuỗi, không nhìn bằng mắt.

    Lỗ hổng v2 hở ở CẢ HAI lớp cùng lúc vì mỗi lớp giữ bản sao riêng. Ca này
    dựng lại đúng dòng ``location ~`` từ ``FROZEN_PREFIXES`` rồi đòi template
    chứa nguyên văn nó.
    """
    goc = Path(__file__).resolve().parents[3]
    tep = goc / "nginx" / "templates" / "default.conf.template"
    assert tep.is_file(), "khong thay %s" % tep
    noi_dung = tep.read_text(encoding="utf-8")

    tien_to = "/api/"
    assert all(p.startswith(tien_to) for p in FROZEN_PREFIXES)
    alt = "|".join(p[len(tien_to):] for p in FROZEN_PREFIXES)
    mong = "location ~ ^/api/(" + alt + ")(/.*)?$ {"
    assert mong in noi_dung, (
        "Khoi freeze cua nginx khong khop FROZEN_PREFIXES.\n  can co: %s" % mong
    )


def test_chi_co_MOT_khoi_freeze_trong_nginx():
    """Đúng MỘT khối ``location`` mang phép kiểm freeze.

    nginx chọn duy nhất một ``location`` regex khớp đầu tiên, nên khối thứ hai
    cùng phủ sẽ chết lặng — vẫn `nginx -t` sạch, vẫn reload rc=0, mà nửa số
    đường không đóng. Đếm ``set $freeze_check`` chứ không đếm số lần nhắc tên
    biến: tên biến còn xuất hiện trong chú thích và trong thân 503.
    """
    goc = Path(__file__).resolve().parents[3]
    noi_dung = (goc / "nginx" / "templates" / "default.conf.template").read_text(
        encoding="utf-8"
    )
    n = noi_dung.count("set $freeze_check")
    assert n == 1, "Mong dung 1 khoi freeze trong nginx, thay %d." % n


# ---------------------------------------------------------------------------
# ADMISSION_FROZEN=False  →  every method passes through the freeze gate.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prefix", FROZEN_PREFIXES)
@pytest.mark.parametrize("method", sorted(FROZEN_METHODS))
@pytest.mark.asyncio
async def test_writes_pass_through_when_unfrozen(client, freeze_off, prefix, method):
    response = await client.request(method, f"{prefix}/anything")
    assert response.status_code == 200, (
        f"unfrozen {method} {prefix}/anything should pass through, "
        f"got {response.status_code} {response.text!r}"
    )


# ---------------------------------------------------------------------------
# ADMISSION_FROZEN=True  →  chặn ghi trên MỌI tiền tố trong FROZEN_PREFIXES.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prefix", FROZEN_PREFIXES)
@pytest.mark.parametrize("method", sorted(FROZEN_METHODS))
@pytest.mark.asyncio
async def test_writes_blocked_when_frozen(client, freeze_on, prefix, method):
    response = await client.request(method, f"{prefix}/anything")
    assert response.status_code == 503, (
        f"frozen {method} {prefix}/anything should return 503, "
        f"got {response.status_code} {response.text!r}"
    )
    body = response.json()
    assert body["code"] == "ADMISSION_FROZEN"
    assert body["frozen_prefix"] == prefix
    assert "frozen for maintenance" in body["detail"]


@pytest.mark.parametrize("prefix", FROZEN_PREFIXES)
@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
@pytest.mark.asyncio
async def test_reads_allowed_when_frozen(client, freeze_on, prefix, method):
    response = await client.request(method, f"{prefix}/anything")
    assert response.status_code == 200, (
        f"frozen {method} {prefix}/anything must be allowed, "
        f"got {response.status_code} {response.text!r}"
    )


# ---------------------------------------------------------------------------
# Frozen window leaves non-admission traffic untouched.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", sorted(FROZEN_METHODS))
@pytest.mark.asyncio
async def test_non_admission_writes_unaffected(client, freeze_on, method):
    response = await client.request(method, "/api/leads/123")
    assert response.status_code == 200
    assert response.json()["scope"] == "leads"


@pytest.mark.asyncio
async def test_health_endpoint_still_reachable(client, freeze_on):
    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.parametrize("gia", ["/api/admissionsfoo", "/api/v2/admin/roundsfoo"])
@pytest.mark.parametrize("method", sorted(FROZEN_METHODS))
@pytest.mark.asyncio
async def test_path_segment_match_rejects_lookalike(client, freeze_on, method, gia):
    # startswith một tiền tố nhưng khác ĐOẠN cuối ⇒ không được chặn.
    response = await client.request(method, gia)
    assert response.status_code == 200, (
        f"frozen {method} {gia} must NOT match any FROZEN_PREFIX, "
        f"got {response.status_code} {response.text!r}"
    )


# ---------------------------------------------------------------------------
# Bare prefix (no trailing slash) is also covered.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prefix", FROZEN_PREFIXES)
@pytest.mark.asyncio
async def test_bare_prefix_post_blocked(client, freeze_on, prefix):
    # FastAPI route is `/{prefix}/{rest:path}` so a bare prefix returns 404
    # under the stub, but that 404 must come from the router AFTER the
    # freeze gate decides — frozen state should produce a 503 first.
    response = await client.post(prefix)
    assert response.status_code == 503
    body = response.json()
    assert body["frozen_prefix"] == prefix
