"""Hàng rào chi phí bcrypt ở đường MFA — bốn bất biến mà việc ĐẾM bcrypt không thấy.

``test_mfa_backup_code_cost.py`` đếm *số phép* bcrypt. Tệp này đo bốn thứ khác,
mỗi thứ tương ứng một cách hỏng đã có thật hoặc suýt có:

  1. Chi phí bcrypt chạy NGOÀI event loop — heartbeat vẫn đập trong lúc băm.
     (Bản cũ băm ngay trong coroutine ⇒ 14,1s đóng băng toàn bộ tiến trình.)
  2. Số bcrypt ĐỒNG THỜI bị trần tài nguyên chặn. Đẩy sang thread mà không có
     trần thì đổi một kiểu tự sát lấy một kiểu khác: N request ⇒ N thread băm.
  3. Đặt chỗ Redis xảy ra TRƯỚC bcrypt và FAIL CLOSED — Redis chết thì trả 503
     mà KHÔNG tiêu một phép bcrypt nào.
  4. Hai request cùng một backup code: ĐÚNG MỘT thành công (khoá hàng thật).

Mỗi ca chỉ vi phạm MỘT bất biến, để khi đỏ thì biết đỏ vì gì.

Ca 1 mang sẵn **đối chứng nhân quả**: cùng một harness đếm nhịp, chạy trên bản
ĐỒNG BỘ của chính hàm ấy phải cho ~0 nhịp. Không có đối chứng này thì "đếm được
nhiều nhịp" chỉ chứng minh harness biết đếm, chưa chứng minh nó biết phát hiện
tắc nghẽn.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid

import pyotp
import pytest
from sqlalchemy import select

from app import models
from app.config import settings
from app.database import AsyncSessionLocal
from app.security import get_password_hash
from app.services import mfa_service

pytestmark = pytest.mark.asyncio

PWD = "TestPassword123!"


@pytest.fixture
def bat_writer_v2(monkeypatch):
    """Bật pha B. Các ca dưới nói về ĐƯỜNG v2 (selector), không về việc
    pha nào đang bật ở production — mặc định sản phẩm vẫn là pha A."""
    monkeypatch.setattr(settings, "MFA_BACKUP_CODE_V2_WRITER_ENABLED", True)


# Ngưỡng nhịp: harness đập mỗi 5ms. Một cửa sổ 0,3s "sạch" cho ~60 nhịp; đòi 5
# nhịp là biên 12 lần, đủ rộng cho runner CI chậm mà vẫn tách hẳn khỏi ca tắc
# (đo được 0–1 nhịp). Không nới thêm: nới nữa là guard hết nhìn thấy hồi quy.
NHIP_TOI_THIEU = 5
NHIP_TOI_DA_KHI_TAC = 1
CUA_SO_TOI_THIEU_S = 0.30


# --------------------------------------------------------------------------- #
# Harness đếm nhịp event loop
# --------------------------------------------------------------------------- #
async def _dem_nhip(than, *, tick_s: float = 0.005):
    """Chạy ``than()`` trong khi một task nền đập nhịp mỗi ``tick_s``.

    Trả về ``(ket_qua, so_nhip, thoi_gian)``. ``than`` là coroutine function.
    Nếu thân chặn event loop, task nền không được lên lịch ⇒ so_nhip ≈ 0.
    """
    nhip = 0
    dung = False

    async def _dap():
        nonlocal nhip
        while not dung:
            await asyncio.sleep(tick_s)
            nhip += 1

    task = asyncio.create_task(_dap())
    await asyncio.sleep(0.02)          # cho task nền vào nhịp trước khi đo
    moc = nhip
    t0 = time.perf_counter()
    try:
        ket_qua = await than()
    finally:
        thoi_gian = time.perf_counter() - t0
        dung = True
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    return ket_qua, nhip - moc, thoi_gian


class TestKhongChanEventLoop:
    """1. Băm bcrypt không được đóng băng event loop."""

    async def test_sinh_ma_khong_chan_heartbeat(self):
        async def than():
            return await mfa_service.agenerate_backup_codes(count=8)

        (plaintext, entries), nhip, giay = await _dem_nhip(than)

        assert len(plaintext) == 8 and len(entries) == 8
        assert giay >= CUA_SO_TOI_THIEU_S, (
            f"Cửa sổ đo quá ngắn ({giay:.3f}s) để kết luận gì về nhịp — "
            "bcrypt hình như không thật sự chạy."
        )
        assert nhip >= NHIP_TOI_THIEU, (
            f"Sinh 8 backup code chặn event loop: chỉ {nhip} nhịp trong "
            f"{giay:.2f}s. Chi phí bcrypt phải chạy ngoài loop."
        )

    async def test_xac_minh_khong_chan_heartbeat(self):
        codes, entries = mfa_service.generate_backup_codes(count=8)
        kho = json.dumps(entries)

        async def than():
            return await mfa_service.averify_backup_code(codes[0], kho)

        (khop, _), nhip, giay = await _dem_nhip(than)

        assert khop is True
        assert nhip >= NHIP_TOI_THIEU, (
            f"Xác minh backup code chặn event loop: {nhip} nhịp trong {giay:.2f}s."
        )

    async def test_doi_chung_ban_dong_bo_that_su_lam_tac_nhip(self):
        """Đối chứng nhân quả: cùng harness, thân ĐỒNG BỘ phải cho ~0 nhịp.

        Ca này KHÔNG kiểm mã sản phẩm — nó kiểm chính phép đo ở hai ca trên.
        Nếu ca này cũng đếm được nhiều nhịp thì harness mù, và hai ca kia xanh
        vô nghĩa.
        """
        async def than_dong_bo():
            # Gọi thẳng bản đồng bộ NGAY TRONG coroutine: đúng cách bản cũ làm.
            return mfa_service.generate_backup_codes(count=8)

        (plaintext, _), nhip, giay = await _dem_nhip(than_dong_bo)

        assert len(plaintext) == 8
        assert giay >= CUA_SO_TOI_THIEU_S, (
            f"Thân đồng bộ chạy quá nhanh ({giay:.3f}s) để làm đối chứng."
        )
        assert nhip <= NHIP_TOI_DA_KHI_TAC, (
            f"Harness KHÔNG phát hiện được tắc nghẽn: {nhip} nhịp trong "
            f"{giay:.2f}s dù thân chạy đồng bộ. Hai ca heartbeat kia vô nghĩa."
        )


# --------------------------------------------------------------------------- #
# Trần tài nguyên
# --------------------------------------------------------------------------- #
class _TheoDoiDongThoi:
    """Bọc CryptContext, ghi lại số phép bcrypt chạy CÙNG LÚC."""

    def __init__(self, that):
        self._that = that
        self._lock = threading.Lock()
        self.dang_chay = 0
        self.dinh = 0

    def _vao(self):
        with self._lock:
            self.dang_chay += 1
            if self.dang_chay > self.dinh:
                self.dinh = self.dang_chay

    def _ra(self):
        with self._lock:
            self.dang_chay -= 1

    def hash(self, code):
        self._vao()
        try:
            return self._that.hash(code)
        finally:
            self._ra()

    def verify(self, code, hashed):
        self._vao()
        try:
            return self._that.verify(code, hashed)
        finally:
            self._ra()


class TestTranTaiNguyenBcrypt:
    """2. Đẩy bcrypt sang thread mà không có trần = đổi kiểu tự sát."""

    async def test_so_bcrypt_dong_thoi_khong_vuot_tran(
        self, monkeypatch, bat_writer_v2
    ):
        codes, entries = mfa_service.generate_backup_codes(count=4)
        kho = json.dumps(entries)

        that = mfa_service._backup_context()
        theo_doi = _TheoDoiDongThoi(that)
        monkeypatch.setattr(mfa_service, "_backup_context", lambda: theo_doi)

        tran = mfa_service._max_bcrypt_workers()
        # 12 request đồng thời, mỗi cái trúng selector ⇒ mỗi cái đúng 1 bcrypt.
        ket_qua = await asyncio.gather(
            *(mfa_service.averify_backup_code(codes[i % 4], kho) for i in range(12))
        )

        assert all(khop for khop, _ in ket_qua)
        assert theo_doi.dinh >= 1, "Không phép bcrypt nào chạy — ca này đo hụt."
        assert theo_doi.dinh <= tran, (
            f"{theo_doi.dinh} phép bcrypt chạy cùng lúc, vượt trần {tran}. "
            "12 request đồng thời sẽ bung thread băm không giới hạn."
        )

    async def test_executor_co_tran_khai_bao(self):
        executor = mfa_service._get_bcrypt_executor()
        assert executor._max_workers == mfa_service._max_bcrypt_workers()
        # Gọi lại phải trả ĐÚNG một executor — mỗi lần một pool mới thì trần
        # per-pool vô nghĩa, tổng thread vẫn bung theo số request.
        assert mfa_service._get_bcrypt_executor() is executor


# --------------------------------------------------------------------------- #
# Đặt chỗ Redis: TRƯỚC bcrypt, và fail closed
# --------------------------------------------------------------------------- #
class _DemBcrypt:
    def __init__(self, that):
        self._that = that
        self.tong = 0

    def hash(self, code):
        self.tong += 1
        return self._that.hash(code)

    def verify(self, code, hashed):
        self.tong += 1
        return self._that.verify(code, hashed)


async def _seed_user_mfa(so_ma: int = 3):
    """Tạo user đã bật MFA, KHÔNG đi qua API (tránh 4 lần băm mật khẩu rounds=15).

    Trả về ``(user_id, username, secret, codes)``.
    """
    username = f"mfa_dos_{uuid.uuid4().hex[:10]}"
    secret = pyotp.random_base32()
    codes, entries = mfa_service.generate_backup_codes(count=so_ma)
    async with AsyncSessionLocal() as s:
        u = models.User(
            username=username,
            email=f"{username}@test.local",
            password_hash=get_password_hash(PWD),
            role="user",
            status="active",
            mfa_enabled=True,
            totp_secret_encrypted=mfa_service.encrypt_secret(secret),
            backup_codes_hashed=json.dumps(entries),
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u.id, username, secret, codes


class TestDatChoTruocBcryptVaFailClosed:
    """3. Redis chết ⇒ 503 và KHÔNG tiêu bcrypt."""

    async def test_redis_incr_hong_tra_503_va_khong_bcrypt(
        self, client, test_redis_client, monkeypatch
    ):
        from httpx import ASGITransport, AsyncClient

        from app.main import fastapi_app
        from app.routers import auth as auth_router

        user_id, username, _secret, codes = await _seed_user_mfa(so_ma=3)
        mfa_token = mfa_service.create_mfa_token(username, user_id)

        dem = _DemBcrypt(mfa_service._backup_context())
        dem_legacy = _DemBcrypt(mfa_service._pwd_context)
        monkeypatch.setattr(mfa_service, "_backup_context", lambda: dem)
        monkeypatch.setattr(mfa_service, "_pwd_context", dem_legacy)

        async def _dat_cho_hong(*a, **kw):
            return None

        monkeypatch.setattr(
            auth_router, "safe_redis_reserve_attempt", _dat_cho_hong
        )

        # Mã HỢP LỆ, đúng hình dạng backup: nếu đặt chỗ nằm SAU xác minh thì
        # bcrypt đã chạy và ca này bắt được.
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            res = await c.post(
                "/api/auth/verify-mfa",
                json={"mfa_token": mfa_token, "code": codes[0]},
            )

        assert res.status_code == 503, (
            f"Redis đặt chỗ hỏng mà vẫn cho đi tiếp (HTTP {res.status_code}). "
            "Đường brute-force OTP không được fail open."
        )
        assert res.headers.get("Retry-After") == "60"
        tong = dem.tong + dem_legacy.tong
        assert tong == 0, (
            f"{tong} phép bcrypt đã chạy trước khi đặt chỗ được xác nhận — "
            "thứ tự sai, kẻ tấn công vẫn đốt được CPU khi Redis chết."
        )

        # Và mã vẫn còn nguyên: 503 không được tiêu thụ backup code.
        async with AsyncSessionLocal() as s:
            u = await s.get(models.User, user_id)
            assert len(json.loads(u.backup_codes_hashed)) == 3

    async def test_dat_cho_chan_dung_nguong_khi_redis_song(
        self, client, test_redis_client
    ):
        """Đặt chỗ atomic vẫn giữ đúng trần MFA_MAX_ATTEMPTS lần thử."""
        from httpx import ASGITransport, AsyncClient

        from app.config import settings
        from app.main import fastapi_app

        user_id, username, _secret, _codes = await _seed_user_mfa(so_ma=2)
        mfa_token = mfa_service.create_mfa_token(username, user_id)

        ma_sai = "000000"          # hình dạng TOTP ⇒ 0 bcrypt mỗi lần thử
        for _ in range(settings.MFA_MAX_ATTEMPTS):
            async with AsyncClient(
                transport=ASGITransport(app=fastapi_app), base_url="http://test"
            ) as c:
                res = await c.post(
                    "/api/auth/verify-mfa",
                    json={"mfa_token": mfa_token, "code": ma_sai},
                )
            assert res.status_code == 401

        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            res = await c.post(
                "/api/auth/verify-mfa",
                json={"mfa_token": mfa_token, "code": ma_sai},
            )
        assert res.status_code == 429
        assert res.headers.get("Retry-After")

        dem = await test_redis_client.get(f"mfa_attempts:{username}")
        assert int(dem) == settings.MFA_MAX_ATTEMPTS, (
            "Bộ đếm phải DỪNG ở trần. Khẳng định cũ (max+1) khoá đúng hành vi "
            "sai: mỗi request bị chặn lại cộng thêm một, nên kẻ tấn công vừa "
            "đẩy bộ đếm lên vô hạn vừa gia hạn khoá của nạn nhân."
        )


# --------------------------------------------------------------------------- #
# Đồng thời cùng một backup code
# --------------------------------------------------------------------------- #
class TestDongThoiCungMotMa:
    """4. Hai request cùng một mã: đúng một thành công."""

    async def test_hai_phien_cung_ma_chi_mot_thanh_cong(
        self, setup_test_database, bat_writer_v2
    ):
        user_id, _username, _secret, codes = await _seed_user_mfa(so_ma=3)
        ma = codes[0]

        # BARRIER là phần bắt buộc, không phải trang trí. Không có nó, hai phiên
        # có thể chạy NỐI TIẾP: phiên hai nạp user SAU khi phiên một đã commit,
        # nên identity map của nó vốn đã mới và lỗi đọc-dữ-liệu-cũ không bao giờ
        # lộ ra. Đo được: bản không barrier PASS ngay cả khi guard bị gỡ.
        # Barrier ép cả hai nạp xong MỚI cho đi tiếp — đúng cửa sổ đua thật.
        cong = asyncio.Barrier(2)

        async def _thu():
            async with AsyncSessionLocal() as s:
                u = (
                    await s.execute(
                        select(models.User).where(models.User.id == user_id)
                    )
                ).scalar_one()
                await cong.wait()      # cả hai đã nạp user vào identity map
                ok = await mfa_service.verify_mfa_code(s, u, ma)
                await s.commit()
                return ok

        ket_qua = await asyncio.gather(_thu(), _thu(), return_exceptions=True)

        loi = [r for r in ket_qua if isinstance(r, BaseException)]
        assert not loi, f"Đường khoá hàng ném lỗi: {loi!r}"
        assert sum(1 for r in ket_qua if r is True) == 1, (
            f"Hai request cùng một backup code cho kết quả {ket_qua!r}. "
            "Mã dùng một lần mà dùng được hai lần = lost update."
        )

        async with AsyncSessionLocal() as s:
            u = await s.get(models.User, user_id)
            con_lai = json.loads(u.backup_codes_hashed)
        assert len(con_lai) == 2, (
            f"Còn {len(con_lai)} mã, đúng ra phải còn 2 — mã bị tiêu thụ sai số lần."
        )
        khop, _ = mfa_service.verify_backup_code(ma, json.dumps(con_lai))
        assert khop is False, "Mã đã dùng vẫn còn trong kho."


# --------------------------------------------------------------------------- #
# Regenerate
# --------------------------------------------------------------------------- #
class TestRegenerateSinhV2:
    """Cấp lại backup code phải sinh v2 và vô hiệu toàn bộ mã cũ."""

    async def test_regenerate_sinh_v2_va_vo_hieu_ma_cu(
        self, setup_test_database, bat_writer_v2
    ):
        user_id, _username, _secret, ma_cu = await _seed_user_mfa(so_ma=3)

        async with AsyncSessionLocal() as s:
            u = await s.get(models.User, user_id)
            ma_moi, callback = await mfa_service.regenerate_backup_codes(s, u, PWD)
            await s.commit()

        assert callback is None
        assert len(ma_moi) == 8

        async with AsyncSessionLocal() as s:
            u = await s.get(models.User, user_id)
            kho = u.backup_codes_hashed
        muc = json.loads(kho)
        assert len(muc) == 8
        assert all(m.get("v") == 2 for m in muc), "Regenerate còn sinh mục legacy."
        assert all("sel" in m and "vfy" in m for m in muc)

        # Semantics đã xác định: mã CŨ chết, mã MỚI sống.
        for ma in ma_cu:
            khop, _ = mfa_service.verify_backup_code(ma, kho)
            assert khop is False, "Mã cũ vẫn dùng được sau khi cấp lại."
        khop, con_lai = mfa_service.verify_backup_code(ma_moi[0], kho)
        assert khop is True
        assert len(json.loads(con_lai)) == 7


# --------------------------------------------------------------------------- #
# Đặt chỗ NGUYÊN TỬ + KHÔNG kéo dài hình phạt
# --------------------------------------------------------------------------- #
class _RedisEvalGia:
    """Proxy: mọi thứ đi qua client thật, riêng ``eval`` bị ép hỏng.

    Dùng để kiểm nhánh fail-closed. ``loi`` ném ngoại lệ; ``ket_qua`` trả về một
    payload sai (thiếu phần tử, sai kiểu, hoặc TTL không dương).
    """

    def __init__(self, that, ket_qua=None, loi=None):
        self._that = that
        self._ket_qua = ket_qua
        self._loi = loi

    def __getattr__(self, ten):
        return getattr(self._that, ten)

    async def eval(self, *a, **kw):
        if self._loi is not None:
            raise self._loi
        return self._ket_qua


class _GhiLenhRedis:
    """Proxy ghi lại TÊN các lệnh Redis đã phát trong một thao tác."""

    _LENH = (
        "get", "set", "setex", "incr", "decr", "expire", "ttl", "persist",
        "delete", "eval", "evalsha", "pipeline", "watch", "multi", "execute",
    )

    def __init__(self, that):
        self._that = that
        self.lenh = []

    def __getattr__(self, ten):
        thuoc = getattr(self._that, ten)
        if ten in self._LENH:
            def _bao(*a, **kw):
                self.lenh.append(ten)
                return thuoc(*a, **kw)
            return _bao
        return thuoc


class TestDatChoNguyenTu:
    """Đặt chỗ phải là MỘT thao tác server-side, và phải chứng minh được hạn."""

    async def test_helper_tra_allowed_count_ttl(self, test_redis_client):
        from app.database import safe_redis_reserve_attempt

        key = f"mfa_attempts:tt_{uuid.uuid4().hex[:8]}"
        dau = await safe_redis_reserve_attempt(key, 300, 5)
        assert dau is not None
        assert dau.allowed is True
        assert dau.count == 1
        assert dau.ttl > 0, "Đặt chỗ không có hạn = khoá vĩnh viễn."

        sau = await safe_redis_reserve_attempt(key, 300, 5)
        assert sau.allowed is True and sau.count == 2 and sau.ttl > 0

    async def test_dat_cho_chi_dung_MOT_lenh_server_side(
        self, test_redis_client, monkeypatch
    ):
        """Bất biến CẤU TRÚC, không phải hành vi.

        Ca đồng thời ở dưới KHÔNG phân biệt được nguyên tử với không nguyên tử:
        dưới fakeredis trong một event loop, cửa sổ giữa GET và INCR gần như
        không mở ra, nên bản đọc-rồi-quyết-ở-client vẫn xanh (đã đo). Bất biến
        thật sự là "quyết định nằm TRONG Redis", và nó đo được trực tiếp: đúng
        MỘT lệnh, và lệnh đó là script.
        """
        from app import database as db_mod

        ghi = _GhiLenhRedis(db_mod.redis_client)
        monkeypatch.setattr(db_mod, "redis_client", ghi)

        key = f"mfa_attempts:tt_{uuid.uuid4().hex[:8]}"
        kq = await db_mod.safe_redis_reserve_attempt(key, 300, 5)

        assert kq is not None and kq.allowed is True
        assert ghi.lenh == ["eval"], (
            "Đặt chỗ phải là MỘT thao tác server-side. Nhiều lệnh nghĩa là "
            "quyết định được lấy ở phía client giữa các round-trip — đúng cửa "
            f"sổ TOCTOU mà script sinh ra để đóng. Đã phát: {ghi.lenh}"
        )

    async def test_eval_nem_loi_thi_tra_None(self, test_redis_client, monkeypatch):
        from redis.exceptions import ConnectionError as RedisConnErr

        from app import database as db_mod

        monkeypatch.setattr(
            db_mod,
            "redis_client",
            _RedisEvalGia(db_mod.redis_client, loi=RedisConnErr("mat ket noi")),
        )
        key = f"mfa_attempts:tt_{uuid.uuid4().hex[:8]}"
        assert await db_mod.safe_redis_reserve_attempt(key, 300, 5) is None

    @pytest.mark.parametrize(
        "payload",
        [
            None,
            [],
            [1, 2],
            [1, 1, 0, 0],          # TTL = 0: không chứng minh được hạn
            [1, 1, -1, 0],         # TTL = -1: khoá vĩnh viễn
            [-1, 0, 0, 0],         # bộ đếm hỏng, không parse được
            ["x", "y", "z", "w"],  # sai kiểu
        ],
    )
    async def test_payload_sai_thi_tra_None(
        self, test_redis_client, monkeypatch, payload
    ):
        """Fail closed cho MỌI ca không chứng minh được đặt chỗ + hạn dương."""
        from app import database as db_mod

        monkeypatch.setattr(
            db_mod, "redis_client", _RedisEvalGia(db_mod.redis_client, ket_qua=payload)
        )
        key = f"mfa_attempts:tt_{uuid.uuid4().hex[:8]}"
        assert await db_mod.safe_redis_reserve_attempt(key, 300, 5) is None

    async def test_eval_hong_thi_route_tra_503_va_0_bcrypt(
        self, client, test_redis_client, monkeypatch
    ):
        from httpx import ASGITransport, AsyncClient
        from redis.exceptions import ConnectionError as RedisConnErr

        from app import database as db_mod
        from app.main import fastapi_app

        user_id, username, _secret, codes = await _seed_user_mfa(so_ma=3)
        mfa_token = mfa_service.create_mfa_token(username, user_id)

        dem = _DemBcrypt(mfa_service._backup_context())
        dem_legacy = _DemBcrypt(mfa_service._pwd_context)
        monkeypatch.setattr(mfa_service, "_backup_context", lambda: dem)
        monkeypatch.setattr(mfa_service, "_pwd_context", dem_legacy)
        monkeypatch.setattr(
            db_mod,
            "redis_client",
            _RedisEvalGia(db_mod.redis_client, loi=RedisConnErr("mat ket noi")),
        )

        # Mã HỢP LỆ, đúng hình dạng backup: nếu đặt chỗ nằm SAU xác minh thì
        # bcrypt đã chạy và ca này bắt được.
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            res = await c.post(
                "/api/auth/verify-mfa",
                json={"mfa_token": mfa_token, "code": codes[0]},
            )

        assert res.status_code == 503, (
            f"Đặt chỗ hỏng mà vẫn cho đi tiếp (HTTP {res.status_code})."
        )
        assert res.headers.get("Retry-After") == "60"
        tong = dem.tong + dem_legacy.tong
        assert tong == 0, f"{tong} phép bcrypt chạy dù chưa đặt chỗ được."

        async with AsyncSessionLocal() as s:
            u = await s.get(models.User, user_id)
            assert len(json.loads(u.backup_codes_hashed)) == 3


class TestKhongKeoDaiKhoaMFA:
    """Một request ĐÃ BỊ CHẶN không được gia hạn hình phạt của chính nó.

    Bản trước luôn chạy INCR + EXPIRE kể cả khi đã chạm trần. Hệ quả đo được:
    bộ đếm bò lên mãi và TTL bị kéo về TRỌN cửa sổ sau mỗi lần gõ. Kẻ tấn công
    chỉ cần gửi một request trước khi TTL hết là giữ được tài khoản nạn nhân ở
    trạng thái khoá MFA VÔ THỜI HẠN — đổi một lỗ hổng CPU lấy một lỗ hổng
    availability nhắm đúng một người.
    """

    async def test_request_bi_chan_khong_gia_han_ttl(
        self, client, test_redis_client, monkeypatch
    ):
        from httpx import ASGITransport, AsyncClient

        from app.config import settings
        from app.main import fastapi_app

        user_id, username, _secret, codes = await _seed_user_mfa(so_ma=3)
        mfa_token = mfa_service.create_mfa_token(username, user_id)
        key = f"mfa_attempts:{username}"
        toi_da = settings.MFA_MAX_ATTEMPTS

        # Trạng thái xuất phát: đã chạm trần, còn 30 giây nữa là hết khoá.
        await test_redis_client.set(key, str(toi_da), ex=30)
        ttl_truoc = await test_redis_client.ttl(key)
        assert ttl_truoc > 0

        dem = _DemBcrypt(mfa_service._backup_context())
        dem_legacy = _DemBcrypt(mfa_service._pwd_context)
        monkeypatch.setattr(mfa_service, "_backup_context", lambda: dem)
        monkeypatch.setattr(mfa_service, "_pwd_context", dem_legacy)

        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            res = await c.post(
                "/api/auth/verify-mfa",
                json={"mfa_token": mfa_token, "code": codes[0]},
            )

        assert res.status_code == 429
        assert res.headers.get("Retry-After")

        ttl_sau = await test_redis_client.ttl(key)

        assert 0 < ttl_sau <= ttl_truoc, (
            f"Request đã bị chặn kéo dài hình phạt: TTL {ttl_truoc}s → {ttl_sau}s. "
            "Gửi một request trước mỗi lần hết hạn là khoá nạn nhân vĩnh viễn."
        )
        assert dem.tong + dem_legacy.tong == 0, "Request bị chặn vẫn tiêu bcrypt."

    async def test_request_bi_chan_khong_tang_bo_dem(
        self, client, test_redis_client
    ):
        """Bất biến RIÊNG: bộ đếm dừng ở trần.

        Tách khỏi ca TTL ở trên vì hai bất biến hỏng độc lập nhau — gộp lại thì
        một ca đỏ không nói được nó đỏ vì cái nào.
        """
        from httpx import ASGITransport, AsyncClient

        from app.config import settings
        from app.main import fastapi_app

        user_id, username, _secret, codes = await _seed_user_mfa(so_ma=3)
        mfa_token = mfa_service.create_mfa_token(username, user_id)
        key = f"mfa_attempts:{username}"
        toi_da = settings.MFA_MAX_ATTEMPTS

        await test_redis_client.set(key, str(toi_da), ex=120)

        for _ in range(3):
            async with AsyncClient(
                transport=ASGITransport(app=fastapi_app), base_url="http://test"
            ) as c:
                res = await c.post(
                    "/api/auth/verify-mfa",
                    json={"mfa_token": mfa_token, "code": codes[0]},
                )
            assert res.status_code == 429

        dem_sau = int(await test_redis_client.get(key))
        assert dem_sau == toi_da, (
            f"Ba request bị chặn đẩy bộ đếm {toi_da} → {dem_sau}. Bộ đếm bò lên "
            "vô hạn theo số lần kẻ tấn công gõ."
        )

    async def test_dong_thoi_vuot_tran_chi_max_lan_duoc_verify(
        self, client, test_redis_client
    ):
        """Từ key MỚI, gửi nhiều hơn trần: đúng `max` lần được verify."""
        from httpx import ASGITransport, AsyncClient

        from app.config import settings
        from app.main import fastapi_app

        user_id, username, _secret, _codes = await _seed_user_mfa(so_ma=2)
        mfa_token = mfa_service.create_mfa_token(username, user_id)
        key = f"mfa_attempts:{username}"
        toi_da = settings.MFA_MAX_ATTEMPTS
        du = 3

        async def _thu():
            async with AsyncClient(
                transport=ASGITransport(app=fastapi_app), base_url="http://test"
            ) as c:
                r = await c.post(
                    "/api/auth/verify-mfa",
                    json={"mfa_token": mfa_token, "code": "000000"},
                )
                return r.status_code

        ma_tt = await asyncio.gather(*(_thu() for _ in range(toi_da + du)))

        assert ma_tt.count(401) == toi_da, (
            f"{ma_tt.count(401)} request tới được bước xác minh, đúng ra là "
            f"{toi_da}. Đặt chỗ không nguyên tử thì hai request cùng đọc một "
            f"giá trị rồi cùng lọt. Mã trạng thái: {ma_tt}"
        )
        assert ma_tt.count(429) == du, ma_tt

        dem_cuoi = int(await test_redis_client.get(key))
        assert dem_cuoi == toi_da, (
            f"Bộ đếm cuối {dem_cuoi}, đúng ra dừng ở {toi_da} — phần bị chặn "
            "không được cộng thêm."
        )
        assert await test_redis_client.ttl(key) > 0

    async def test_khoa_khong_han_duoc_sua_thanh_co_han(
        self, client, test_redis_client, monkeypatch
    ):
        """count >= max mà TTL = -1: chặn, nhưng phải sửa thành có hạn.

        Không sửa thì đó là khoá VĨNH VIỄN — hỏng theo chiều ngược lại nhưng
        vẫn là hỏng, và không ai gỡ được nếu không vào Redis bằng tay.
        """
        from httpx import ASGITransport, AsyncClient

        from app.config import settings
        from app.main import fastapi_app

        user_id, username, _secret, codes = await _seed_user_mfa(so_ma=3)
        mfa_token = mfa_service.create_mfa_token(username, user_id)
        key = f"mfa_attempts:{username}"

        await test_redis_client.set(key, str(settings.MFA_MAX_ATTEMPTS))
        assert await test_redis_client.ttl(key) == -1, "ca kiểm phải bắt đầu từ TTL -1"

        dem = _DemBcrypt(mfa_service._backup_context())
        monkeypatch.setattr(mfa_service, "_backup_context", lambda: dem)

        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://test"
        ) as c:
            res = await c.post(
                "/api/auth/verify-mfa",
                json={"mfa_token": mfa_token, "code": codes[0]},
            )

        assert res.status_code == 429
        ttl_sau = await test_redis_client.ttl(key)
        assert ttl_sau > 0, (
            "Bộ đếm chạm trần mà không có hạn thì khoá là VĨNH VIỄN; "
            f"TTL sau khi xử lý vẫn là {ttl_sau}."
        )
        assert int(await test_redis_client.get(key)) == settings.MFA_MAX_ATTEMPTS
        assert dem.tong == 0
