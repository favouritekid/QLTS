"""Máy trạng thái đặt chỗ MFA, chạy trên REDIS THẬT.

Vì sao tệp này tồn tại: toàn bộ pytest còn lại chạy trên FakeRedis —
``tests/fixtures/redis.py`` thay ``redis.asyncio.from_url`` TRƯỚC khi app được
import. ``lupa`` chỉ là trình thực thi Lua cho fakeredis, nó **không** phải bằng
chứng rằng script chạy đúng trên Redis production: ngữ nghĩa ``INCR`` trên giá
trị lạ, kiểu trả về của ``EVAL``, tính nguyên tử dưới tải đồng thời thật — cả
ba đều là thứ chỉ Redis thật trả lời được.

Ở đây khách hàng Redis được dựng bằng callable GỐC đã lưu trước lúc patch, nên
nó là kết nối thật tới server thật. Nếu server không tới được thì ca kiểm ĐỎ —
không skip, không fail-open. "Không đo được" không phải là "đạt".

An toàn: mỗi ca dùng khoá riêng có UUID, xoá trong ``finally``. Tuyệt đối
KHÔNG ``FLUSHDB`` — DB này có thể đang là cache của một stack đang chạy.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio

from app import database as db_mod
from tests.fixtures.redis import _original_from_url_async

pytestmark = pytest.mark.asyncio

TOI_DA = 5
CUA_SO = 300


def _redis_url() -> str:
    """URL Redis thật. CI Tier 2 dựng redis:7-alpine ở localhost:6379."""
    return os.getenv("REDIS_URL") or "redis://localhost:6379/0"


@pytest_asyncio.fixture
async def redis_that():
    """Kết nối Redis THẬT, dựng bằng callable gốc (trước khi bị patch).

    Ba phép kiểm trước khi trả về, để ca kiểm không âm thầm chạy trên FakeRedis:
    lớp không thuộc gói fakeredis, ``PING`` tới được, và ``INFO`` trả về thông
    tin server thật.
    """
    url = _redis_url()
    try:
        client = _original_from_url_async(url, decode_responses=True)
    except Exception as exc:  # pragma: no cover - lỗi cấu hình
        pytest.fail(f"Không dựng được client Redis thật từ {url!r}: {exc!r}")

    mo_dun = type(client).__module__ or ""
    assert "fakeredis" not in mo_dun, (
        f"Client là {mo_dun}.{type(client).__name__} — đây vẫn là FakeRedis. "
        "Tệp này mất toàn bộ ý nghĩa nếu chạy trên bản giả."
    )

    try:
        assert await client.ping() is True
        info = await client.info("server")
    except Exception as exc:
        await client.aclose()
        # KHÔNG skip: không đo được thì phải đỏ.
        pytest.fail(
            f"Không kết nối được Redis thật tại {url!r}: {exc!r}. "
            "Máy trạng thái đặt chỗ chưa được chứng minh trên Redis production."
        )

    assert info.get("redis_version"), (
        "INFO không trả redis_version — đây không phải server thật"
    )
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def dat_cho_that(redis_that, monkeypatch):
    """Trỏ helper SẢN PHẨM vào Redis thật.

    Gọi thẳng ``db_mod.safe_redis_reserve_attempt`` — không chạy một bản sao
    script trong ca kiểm, vì bản sao chỉ chứng minh chính nó.
    """
    monkeypatch.setattr(db_mod, "redis_client", redis_that)
    return db_mod.safe_redis_reserve_attempt


def _khoa_moi() -> str:
    return f"mfa_attempts:itest_{uuid.uuid4().hex}"


class TestRedisThat:
    async def test_khoa_moi_cho_qua_va_co_han(self, redis_that, dat_cho_that):
        key = _khoa_moi()
        try:
            kq = await dat_cho_that(key, CUA_SO, TOI_DA)
            assert kq is not None
            assert kq.allowed is True
            assert kq.count == 1
            assert 0 < kq.ttl <= CUA_SO
            assert await redis_that.ttl(key) > 0
        finally:
            await redis_that.delete(key)

    async def test_dong_thoi_dung_max_lan_duoc_cho_qua(self, redis_that, dat_cho_that):
        """Tính NGUYÊN TỬ, đo trên server thật.

        Đây là phép đo mà FakeRedis không làm được: dưới fakeredis, bản
        đọc-rồi-quyết-ở-client vẫn xanh vì cửa sổ TOCTOU gần như không mở.
        """
        key = _khoa_moi()
        du = 4
        try:
            ket = await asyncio.gather(
                *(dat_cho_that(key, CUA_SO, TOI_DA) for _ in range(TOI_DA + du))
            )
            assert all(k is not None for k in ket)
            cho_qua = [k for k in ket if k.allowed]
            bi_chan = [k for k in ket if not k.allowed]

            assert len(cho_qua) == TOI_DA, (
                f"{len(cho_qua)} lượt được cho qua, đúng ra {TOI_DA}. "
                "Đặt chỗ không nguyên tử thì nhiều request cùng đọc một giá trị."
            )
            assert len(bi_chan) == du
            assert sorted(k.count for k in cho_qua) == list(range(1, TOI_DA + 1))
            assert all(k.count == TOI_DA for k in bi_chan)

            assert int(await redis_that.get(key)) == TOI_DA
            assert await redis_that.ttl(key) > 0
        finally:
            await redis_that.delete(key)

    async def test_bi_chan_khong_tang_count_khong_gia_han_ttl(
        self, redis_that, dat_cho_that
    ):
        key = _khoa_moi()
        try:
            await redis_that.set(key, str(TOI_DA), ex=30)
            ttl_truoc = await redis_that.ttl(key)

            kq = await dat_cho_that(key, CUA_SO, TOI_DA)
            assert kq is not None and kq.allowed is False
            assert kq.count == TOI_DA

            assert int(await redis_that.get(key)) == TOI_DA, (
                "Request bị chặn vẫn tăng bộ đếm trên Redis thật."
            )
            ttl_sau = await redis_that.ttl(key)
            assert 0 < ttl_sau <= ttl_truoc, (
                f"Request bị chặn kéo dài hình phạt: {ttl_truoc}s → {ttl_sau}s."
            )
        finally:
            await redis_that.delete(key)

    async def test_khoa_khong_han_duoc_sua_thanh_co_han(
        self, redis_that, dat_cho_that
    ):
        key = _khoa_moi()
        try:
            await redis_that.set(key, str(TOI_DA))
            assert await redis_that.ttl(key) == -1

            kq = await dat_cho_that(key, CUA_SO, TOI_DA)
            assert kq is not None and kq.allowed is False
            assert kq.ttl > 0

            assert await redis_that.ttl(key) > 0, (
                "Bộ đếm chạm trần mà không có hạn = khoá VĨNH VIỄN."
            )
            assert int(await redis_that.get(key)) == TOI_DA
        finally:
            await redis_that.delete(key)

    @pytest.mark.parametrize("gia_tri", ["0", "-1", "1.5", "khong-phai-so"])
    async def test_bo_dem_ngoai_mien_fail_closed(
        self, redis_that, dat_cho_that, gia_tri
    ):
        """Trạng thái hỏng KHÔNG được tự chuyển thành một lượt hợp lệ.

        ``"-1"`` là ca đắt nhất: bản trước để nó rơi xuống ``INCR`` thành ``0``
        rồi trả ``allowed``. Trên Redis thật, ``INCR`` một giá trị như ``"1.5"``
        còn ném lỗi — nhưng ca kiểm này đòi hỏi mạnh hơn: KHÔNG được chạm vào
        khoá ngay từ đầu.
        """
        key = _khoa_moi()
        try:
            await redis_that.set(key, gia_tri, ex=120)
            ttl_truoc = await redis_that.ttl(key)

            assert await dat_cho_that(key, CUA_SO, TOI_DA) is None, (
                f"Bộ đếm {gia_tri!r} được chấp nhận trên Redis thật."
            )
            assert await redis_that.get(key) == gia_tri, (
                "Nhánh từ chối vẫn sửa giá trị khoá."
            )
            ttl_sau = await redis_that.ttl(key)
            assert 0 < ttl_sau <= ttl_truoc, (
                f"Nhánh từ chối vẫn đụng TTL: {ttl_truoc}s → {ttl_sau}s."
            )
        finally:
            await redis_that.delete(key)

    async def test_khong_de_lai_khoa_thu_nghiem(self, redis_that):
        """Chính tệp này không được để rác lại trên Redis đang chạy."""
        con_lai = [k async for k in redis_that.scan_iter("mfa_attempts:itest_*")]
        assert con_lai == [], f"Còn khoá thử nghiệm chưa dọn: {con_lai}"
