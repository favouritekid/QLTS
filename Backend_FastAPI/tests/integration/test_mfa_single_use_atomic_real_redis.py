"""Tiêu-thụ-một-lần của MFA, đo trên REDIS THẬT.

Cùng lý do tồn tại như ``test_mfa_reservation_real_redis.py``: toàn bộ pytest
còn lại chạy trên FakeRedis (``tests/fixtures/redis.py`` thay
``redis.asyncio.from_url`` TRƯỚC khi app được import). Tính nguyên tử dưới tải
đồng thời là thứ chỉ Redis thật trả lời được — dưới FakeRedis, một bản
đọc-rồi-quyết-ở-client vẫn có thể xanh vì cửa sổ TOCTOU gần như không mở.

Hai bất biến được đo ở đây:

* **TOTP** — một time step đã dùng không được dùng lại (RFC 6238 §5.2). Quyết
  định "counter mới có lớn hơn counter đã tiêu không" phải nằm TRỌN trong một
  script server-side.
* **mfa_token** — một token đã chứng minh MFA chỉ được đổi lấy phiên đăng nhập
  ĐÚNG MỘT LẦN.

An toàn: mỗi ca dùng khoá riêng có UUID/id ngẫu nhiên, xoá trong ``finally``.
Tuyệt đối KHÔNG ``FLUSHDB`` — DB này có thể đang là cache của một stack đang
chạy.

⚠️ Tệp này import ``KetQuaChiem``/``safe_redis_*`` mới nên **không collect được
trên commit cha**. Bằng chứng "đỏ trước khi vá" nằm ở
``test_mfa_race_reproducer.py``.
"""
from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import pytest_asyncio

from app import database as db_mod
from app.database import KetQuaChiem
from tests.fixtures.redis import _original_from_url_async

pytestmark = pytest.mark.asyncio

# Tiền tố riêng của tệp này cho khoá chiếm.
_TIEN_TO_KHOA_THU = "mfa_used:itest_"

# Tập khoá mà CHÍNH tệp này đã sinh ra. Ca dọn dẹp kiểm đúng tập này.
#
# ⚠️ Bản trước quét ``totp_used:9*``. Đó là namespace CHUNG: Redis dev/CI có thể
# đang giữ khoá của người dùng thật có id bắt đầu bằng 9, và ca kiểm sẽ đỏ vì dữ
# liệu KHÔNG do nó tạo ra — một phép kiểm tự nhận trách nhiệm về thứ nó không
# gây ra thì sớm muộn cũng bị tắt đi vì "hay đỏ vớ vẩn".
_KHOA_DA_SINH: set[str] = set()


def _redis_url() -> str:
    """URL Redis thật. CI Tier 2 dựng redis:7-alpine ở localhost:6379."""
    return os.getenv("REDIS_URL") or "redis://localhost:6379/0"


def _thong_bao_an_toan(pha: str, exc: BaseException) -> str:
    """Thông báo lỗi KHÔNG mang credential.

    ``REDIS_URL`` có dạng ``redis://user:password@host/db``; redis-py nhét
    endpoint (và do đó cả userinfo) vào message của exception. In nguyên văn là
    đẩy credential vào log CI, nơi log sống lâu hơn cái mật khẩu.
    """
    return (
        f"Không {pha} được Redis thật ({type(exc).__name__}). "
        "Kiểm biến môi trường REDIS_URL và service redis của cổng CI. "
        "Tiêu-thụ-một-lần của MFA chưa được chứng minh trên Redis thật."
    )


async def _mo_ket_noi(url: str):
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
    client = await _mo_ket_noi(_redis_url())
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def redis_that_gan_vao_app(redis_that, monkeypatch):
    """Trỏ helper SẢN PHẨM vào Redis thật, không chạy bản sao trong ca kiểm."""
    monkeypatch.setattr(db_mod, "redis_client", redis_that)
    return redis_that


def _user_id_moi() -> int:
    """Id ngẫu nhiên — không đụng dữ liệu thật, không đụng ca khác."""
    return 900_000_000_000 + (uuid.uuid4().int % 10_000_000)


def _khoa_totp_moi() -> str:
    """Sinh khoá TOTP và ĐĂNG KÝ nó, để ca dọn dẹp biết chính xác cần kiểm gì."""
    khoa = f"totp_used:{_user_id_moi()}"
    _KHOA_DA_SINH.add(khoa)
    return khoa


def _khoa_chiem_moi() -> str:
    khoa = f"{_TIEN_TO_KHOA_THU}{uuid.uuid4().hex}"
    _KHOA_DA_SINH.add(khoa)
    return khoa


class TestTotpMotLan:
    """Một time step TOTP chỉ được tiêu đúng một lần — RFC 6238 §5.2."""

    # Ca TÁI HIỆN race (hai request cùng một mã TOTP) nằm ở
    # ``test_mfa_race_reproducer.py`` — nó không import symbol mới nên chạy
    # được cả trên commit cha. Ở đây chỉ còn các guard đo helper trực tiếp.

    async def test_muoi_coroutine_qua_nhieu_ket_noi_chi_mot_lan_duoc_chap_nhan(
        self, redis_that_gan_vao_app
    ):
        """Tải đồng thời cao hơn, và đi qua NHIỀU KẾT NỐI thật.

        ``redis.asyncio`` cấp phát mỗi lệnh đang bay một kết nối riêng từ pool,
        nên mười lời gọi song song ở đây thực sự chạy trên nhiều socket khác
        nhau — chứ không phải nối đuôi trên một kết nối, vốn sẽ che mất đúng
        cái nó cần đo.
        """
        redis_that = redis_that_gan_vao_app
        key = _khoa_totp_moi()
        counter = 1_500_000

        try:
            ket_qua = await asyncio.gather(
                *(
                    db_mod.safe_redis_consume_totp_counter(key, counter, 180)
                    for _ in range(10)
                )
            )
            assert all(k is not None for k in ket_qua), (
                "Có lời gọi trả None — helper không chứng minh được kết quả."
            )
            duoc_nhan = [k for k in ket_qua if k.accepted]
            assert len(duoc_nhan) == 1, (
                f"{len(duoc_nhan)}/10 lời gọi cùng tiêu được MỘT counter."
            )
            assert int(await redis_that.get(key)) == counter
            assert await redis_that.ttl(key) > 0
        finally:
            await redis_that.delete(key)

    async def test_counter_cu_hon_bi_tu_choi_tren_redis_that(
        self, redis_that_gan_vao_app
    ):
        redis_that = redis_that_gan_vao_app
        key = _khoa_totp_moi()
        try:
            moi = await db_mod.safe_redis_consume_totp_counter(key, 2_000_000, 180)
            assert moi is not None and moi.accepted is True

            cu = await db_mod.safe_redis_consume_totp_counter(key, 1_999_999, 180)
            assert cu is not None and cu.accepted is False, (
                "Bước thời gian CŨ HƠN vẫn được chấp nhận."
            )
            assert int(await redis_that.get(key)) == 2_000_000, (
                "Nhánh từ chối vẫn ghi đè counter đã tiêu."
            )
        finally:
            await redis_that.delete(key)

    async def test_khoa_khong_han_duoc_sua_thanh_co_han(self, redis_that_gan_vao_app):
        """Khoá không TTL = khoá VĨNH VIỄN, chặn mọi TOTP tương lai của user.

        Từ chối request hiện tại (counter không lớn hơn), NHƯNG phải sửa hạn về
        hữu hạn — hỏng theo chiều ngược lại vẫn là hỏng.
        """
        redis_that = redis_that_gan_vao_app
        key = _khoa_totp_moi()
        try:
            await redis_that.set(key, "3000000")
            assert await redis_that.ttl(key) == -1

            kq = await db_mod.safe_redis_consume_totp_counter(key, 3_000_000, 180)
            assert kq is not None and kq.accepted is False
            assert kq.ttl > 0

            assert await redis_that.ttl(key) > 0, (
                "Khoá chống phát lại không hạn = user bị khoá TOTP vĩnh viễn."
            )
            assert int(await redis_that.get(key)) == 3_000_000
        finally:
            await redis_that.delete(key)

    @pytest.mark.parametrize("gia_tri", ["-1", "1.5", "khong-phai-so"])
    async def test_counter_hong_fail_closed_tren_redis_that(
        self, redis_that_gan_vao_app, gia_tri
    ):
        redis_that = redis_that_gan_vao_app
        key = _khoa_totp_moi()
        try:
            await redis_that.set(key, gia_tri, ex=120)
            ttl_truoc = await redis_that.ttl(key)

            assert (
                await db_mod.safe_redis_consume_totp_counter(key, 4_000_000, 180)
                is None
            ), f"Counter đã lưu {gia_tri!r} được chấp nhận trên Redis thật."

            assert await redis_that.get(key) == gia_tri, (
                "Nhánh từ chối vẫn sửa giá trị khoá."
            )
            ttl_sau = await redis_that.ttl(key)
            assert 0 < ttl_sau <= ttl_truoc, (
                f"Nhánh từ chối vẫn đụng TTL: {ttl_truoc}s → {ttl_sau}s."
            )
        finally:
            await redis_that.delete(key)


class TestChiemMotLan:
    """``mfa_used:{jti}`` — đúng MỘT request chiếm được."""

    async def test_tam_lan_chiem_dong_thoi_chi_mot_lan_thanh_cong(
        self, redis_that_gan_vao_app
    ):
        redis_that = redis_that_gan_vao_app
        key = _khoa_chiem_moi()
        try:
            ket_qua = await asyncio.gather(
                *(db_mod.safe_redis_claim_once(key, "1", 300) for _ in range(8))
            )
            da_chiem = [k for k in ket_qua if k is KetQuaChiem.DA_CHIEM]
            da_bi_chiem = [k for k in ket_qua if k is KetQuaChiem.DA_BI_CHIEM]

            assert len(da_chiem) == 1, (
                f"{len(da_chiem)}/8 request cùng chiếm được MỘT mfa_token. "
                "SET không có NX thì mọi request đều 'thành công'."
            )
            assert len(da_bi_chiem) == 7
            assert await redis_that.ttl(key) > 0, "Dấu chiếm không có hạn."
        finally:
            await redis_that.delete(key)

    async def test_chiem_khong_ghi_de_gia_tri_da_co(self, redis_that_gan_vao_app):
        """NX phải là NX thật: giá trị của người chiếm đầu tiên còn nguyên."""
        redis_that = redis_that_gan_vao_app
        key = _khoa_chiem_moi()
        try:
            assert (
                await db_mod.safe_redis_claim_once(key, "nguoi-dau-tien", 300)
                is KetQuaChiem.DA_CHIEM
            )
            assert (
                await db_mod.safe_redis_claim_once(key, "nguoi-thu-hai", 300)
                is KetQuaChiem.DA_BI_CHIEM
            )
            assert await redis_that.get(key) == "nguoi-dau-tien"
        finally:
            await redis_that.delete(key)


class TestDonDep:
    async def test_khong_de_lai_khoa_thu_nghiem(self, redis_that):
        """Chính tệp này không được để rác lại trên Redis đang chạy.

        Kiểm ĐÚNG tập khoá tệp này đã sinh, không quét namespace chung: quét
        ``totp_used:9*`` sẽ bắt cả khoá của người dùng thật có id bắt đầu bằng
        9 trên một Redis dùng chung, tức ca kiểm đỏ vì dữ liệu không do nó tạo.
        """
        assert _KHOA_DA_SINH, (
            "Không ca nào đăng ký khoá — phép kiểm này đang xanh mà không đo gì. "
            "Nếu các ca trên bị đổi tên/bỏ đi thì phải sửa cả ca dọn dẹp."
        )

        con_lai = []
        for khoa in sorted(_KHOA_DA_SINH):
            if await redis_that.exists(khoa):
                con_lai.append(khoa)

        assert con_lai == [], f"Còn khoá thử nghiệm chưa dọn: {con_lai}"
