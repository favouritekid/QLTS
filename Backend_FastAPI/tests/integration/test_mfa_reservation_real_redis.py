"""Máy trạng thái đặt chỗ MFA, chạy trên REDIS THẬT.

Vì sao tệp này tồn tại: toàn bộ pytest còn lại chạy trên FakeRedis —
``tests/fixtures/redis.py`` thay ``redis.asyncio.from_url`` TRƯỚC khi app được
import. ``lupa`` chỉ là trình thực thi Lua cho fakeredis, nó **không** phải bằng
chứng rằng script chạy đúng trên Redis thật: ngữ nghĩa ``INCR`` trên giá
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


def _thong_bao_an_toan(pha: str, exc: BaseException) -> str:
    """Thông báo lỗi KHÔNG mang bí mật.

    ``REDIS_URL`` có dạng ``redis://user:password@host/db``. In nguyên văn URL
    — hoặc in ``repr`` của exception, vì redis-py nhét endpoint (và do đó cả
    userinfo) vào message — là đẩy credential vào log CI, nơi ai đọc được job
    cũng đọc được, và log thì còn lại lâu hơn cái mật khẩu.

    Chỉ giữ ba thứ đủ để sửa lỗi: PHA thất bại, TÊN LỚP exception, và chỗ cần
    kiểm. Không endpoint, không message của exception, không query string.
    """
    return (
        f"Không {pha} được Redis thật ({type(exc).__name__}). "
        "Kiểm biến môi trường REDIS_URL và service redis của cổng CI. "
        "Máy trạng thái đặt chỗ chưa được chứng minh trên Redis thật."
    )


async def _mo_ket_noi(url: str):
    """Dựng + kiểm client Redis thật, hoặc ĐỎ với thông báo không rò bí mật.

    Tách khỏi fixture để ca hồi quy chống rò credential gọi được ĐÚNG đường lỗi
    này, chứ không chỉ kiểm hàm dựng thông báo.
    """
    try:
        client = _original_from_url_async(url, decode_responses=True)
    except Exception as exc:  # pragma: no cover - lỗi cấu hình
        pytest.fail(_thong_bao_an_toan("dựng client", exc))

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
        pytest.fail(_thong_bao_an_toan("kết nối", exc))

    assert info.get("redis_version"), (
        "INFO không trả redis_version — đây không phải server thật"
    )
    return client


@pytest_asyncio.fixture
async def redis_that():
    """Kết nối Redis THẬT, dựng bằng callable gốc (trước khi bị patch).

    Ba phép kiểm trước khi trả về, để ca kiểm không âm thầm chạy trên FakeRedis:
    lớp không thuộc gói fakeredis, ``PING`` tới được, và ``INFO`` trả về thông
    tin server thật.
    """
    client = await _mo_ket_noi(_redis_url())
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


# Chuỗi mồi. Nó xuất hiện ở CẢ URL lẫn message của exception, đúng hai nguồn
# mà đường lỗi từng chép nguyên văn vào log.
_MOI = "s3cr3t-canary-khong-duoc-log"


class TestKhongRoCredential:
    """Đường LỖI không được rò credential vào log CI.

    ``REDIS_URL`` mang ``user:password``. Một lượt CI hỏng là một lượt in
    secret ra chỗ ai đọc được job cũng đọc được — và log sống lâu hơn mật khẩu.
    Ca kiểm nằm ở đây, cạnh đường lỗi, chứ không phải ở một tệp guard xa xôi.
    """

    async def test_ham_dung_thong_bao_khong_mang_bi_mat(self):
        exc = ConnectionError(
            f"Error 111 connecting to redis://admin:{_MOI}@db.noi.bo:6379/0"
        )
        thong_bao = _thong_bao_an_toan("kết nối", exc)

        for xau in (_MOI, "admin", "db.noi.bo", "redis://"):
            assert xau not in thong_bao, (
                f"Thông báo lỗi chứa {xau!r} — lấy từ message của exception."
            )
        # Vẫn phải đủ dùng để sửa lỗi.
        assert "ConnectionError" in thong_bao
        assert "REDIS_URL" in thong_bao

    async def test_duong_loi_that_khong_ro_credential(self):
        """Đi qua ĐÚNG ``_mo_ket_noi``, không phải một bản mô phỏng.

        Port 1 trên loopback không có ai nghe ⇒ kết nối bị từ chối ngay, nên ca
        này nhanh và tất định.
        """
        url = f"redis://canary_user:{_MOI}@127.0.0.1:1/0?token={_MOI}"

        with pytest.raises(BaseException) as thong_tin:
            await _mo_ket_noi(url)

        thong_bao = str(thong_tin.value)
        for xau in (_MOI, "canary_user", "127.0.0.1", "token=", "@"):
            assert xau not in thong_bao, (
                f"Thông báo lỗi chứa {xau!r}. Với REDIS_URL thật, đó là "
                f"credential nằm nguyên trong log CI. Thông báo: {thong_bao!r}"
            )
        assert "REDIS_URL" in thong_bao


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
