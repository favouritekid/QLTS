"""MFA: bằng chứng đã xác minh chỉ được TIÊU ĐÚNG MỘT LẦN.

Hai bằng chứng, hai lỗ cùng họ — cả hai đều là đọc-rồi-ghi không nguyên tử, và
cả hai đều FAIL OPEN khi Redis lỗi:

* ``totp_used:{user_id}`` — GET rồi SET (``mfa_service.verify_mfa_code``).
* ``mfa_used:{jti}``      — EXISTS ở đầu, SET ở cuối (``routers/auth.verify_mfa``),
  cửa sổ đua rộng bằng TOÀN BỘ quá trình xác minh.

Tệp này canh HÀNH VI ở tầng service + endpoint trên FakeRedis. Tính nguyên tử
dưới tải đồng thời THẬT nằm ở ``tests/integration/
test_mfa_single_use_atomic_real_redis.py`` — FakeRedis không chứng minh được
điều đó, và tệp này không giả vờ rằng nó chứng minh.

⚠️ Tệp này KHÔNG phải bằng chứng tái hiện: nó import ``KetQuaChiem`` và các
``safe_redis_*`` mới, nên **không collect được trên commit cha**. Bằng chứng
"đỏ trước khi vá" nằm ở ``tests/integration/test_mfa_race_reproducer.py``, tệp
duy nhất chạy được trên cả cây cũ lẫn cây mới. Đừng trích tệp này khi nói
"đỏ trên base".
"""
from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import pytest
from aiobreaker import CircuitBreaker
from fastapi.responses import JSONResponse
from redis.exceptions import ConnectionError as RedisConnectionError

from app import database as db_mod
from app.database import KetQuaChiem
from app.routers import auth as auth_router
from app.services import mfa_service

pytestmark = pytest.mark.asyncio

# Mật khẩu mồi, nhúng trong message của exception Redis — ĐÚNG hình dạng thật:
# redis-py chép endpoint (và do đó cả userinfo của ``REDIS_URL``) vào message
# của ``ConnectionError``. Nên bất kỳ đường log nào chạm tới ``str(exc)`` hoặc
# bật ``exc_info=True`` đều kéo cả credential ra theo.
#
# ⚠️ Bản trước của các canary ném exception với message ``"redis down"`` — vô
# hại — nên chúng chỉ khoá được "không rò JTI", KHÔNG khoá được "không rò
# credential". Đưa ``exc_info=True`` trở lại vẫn xanh.
_MAT_KHAU_MOI = "s3cr3t-canary-khong-duoc-log"
_LOI_CO_CREDENTIAL = (
    f"Error 111 connecting to redis://canary_user:{_MAT_KHAU_MOI}@db.noi.bo:6379/0"
)


@pytest.fixture(autouse=True)
def breaker_rieng_cho_moi_ca(monkeypatch):
    """Mỗi ca một circuit breaker RIÊNG.

    ``db_mod.redis_breaker`` là singleton cấp module với ``fail_max=5``. Tệp này
    cố ý ném lỗi Redis ở nhiều ca, nên dùng chung breaker thì sau năm lần lỗi nó
    chuyển sang OPEN và **mọi ca sau đó trong cùng phiên đều đỏ vì lý do không
    liên quan** — kể cả ca ở tệp khác.

    Đo được khi chưa có fixture này: 10 failed, lan sang cả
    ``test_mfa_race_reproducer.py``. Trạng thái breaker là trạng thái toàn cục;
    ca kiểm nào làm bẩn nó thì phải tự dọn.
    """
    monkeypatch.setattr(
        db_mod, "redis_breaker", CircuitBreaker(fail_max=5, timeout_duration=60)
    )


def _user_totp():
    """User tối thiểu cho nhánh TOTP — nhánh này không chạm DB."""
    return SimpleNamespace(
        id=900_000_000_000 + (uuid.uuid4().int % 10_000_000),
        totp_secret_encrypted="khong-dung-den-vi-decrypt-bi-patch",
        backup_codes_hashed=None,
    )


def _ep_totp_khop(monkeypatch, counter: int):
    """Ép ``verify_totp_with_counter`` khớp ở ĐÚNG một counter cho trước.

    Ta đang kiểm lớp CHỐNG PHÁT LẠI, không kiểm thuật toán TOTP: cố định
    counter là cách duy nhất để ca kiểm tất định (counter thật trôi theo đồng
    hồ tường). Thuật toán TOTP và ``valid_window=1`` không bị đụng tới, và
    đường TOTP thật được đo ở tệp integration Redis thật.
    """
    monkeypatch.setattr(mfa_service, "decrypt_secret", lambda _c: "KHONGDUNGDEN")
    monkeypatch.setattr(
        mfa_service, "verify_totp_with_counter", lambda _s, _c: (True, counter)
    )


class TestTotpTieuMotLan:
    """``totp_used:{uid}`` — so sánh-rồi-ghi phải nguyên tử VÀ đơn điệu."""

    async def test_lan_dau_duoc_chap_nhan_va_ghi_counter(
        self, test_redis_client, clear_redis_keys, monkeypatch
    ):
        user = _user_totp()
        _ep_totp_khop(monkeypatch, 1_000_000)

        assert await mfa_service.verify_mfa_code(None, user, "123456") is True
        assert await test_redis_client.get(f"totp_used:{user.id}") == "1000000"
        assert await test_redis_client.ttl(f"totp_used:{user.id}") > 0, (
            "Khoá chống phát lại không có hạn = khoá vĩnh viễn cho user này."
        )

    async def test_dung_lai_dung_counter_do_bi_tu_choi(
        self, test_redis_client, clear_redis_keys, monkeypatch
    ):
        user = _user_totp()
        _ep_totp_khop(monkeypatch, 1_000_000)

        assert await mfa_service.verify_mfa_code(None, user, "123456") is True
        assert await mfa_service.verify_mfa_code(None, user, "123456") is False, (
            "Cùng một time step TOTP được chấp nhận hai lần."
        )

    async def test_counter_cu_hon_bi_tu_choi(
        self, test_redis_client, clear_redis_keys, monkeypatch
    ):
        """Đơn điệu, không chỉ 'chưa trùng'.

        ``valid_window=1`` chấp nhận cả bước -1. Nếu chỉ chặn trùng khít thì sau
        khi tiêu bước N, kẻ tấn công vẫn dùng lại được bước N-1.
        """
        user = _user_totp()
        _ep_totp_khop(monkeypatch, 1_000_000)
        assert await mfa_service.verify_mfa_code(None, user, "123456") is True

        _ep_totp_khop(monkeypatch, 999_999)
        assert await mfa_service.verify_mfa_code(None, user, "123456") is False, (
            "Một bước thời gian CŨ HƠN vẫn được chấp nhận sau bước mới."
        )
        assert await test_redis_client.get(f"totp_used:{user.id}") == "1000000", (
            "Nhánh từ chối vẫn ghi đè counter — tự xoá dấu vết đã tiêu."
        )

    async def test_counter_moi_hon_duoc_chap_nhan(
        self, test_redis_client, clear_redis_keys, monkeypatch
    ):
        user = _user_totp()
        _ep_totp_khop(monkeypatch, 1_000_000)
        assert await mfa_service.verify_mfa_code(None, user, "123456") is True

        _ep_totp_khop(monkeypatch, 1_000_001)
        assert await mfa_service.verify_mfa_code(None, user, "123456") is True
        assert await test_redis_client.get(f"totp_used:{user.id}") == "1000001"

    @pytest.mark.parametrize("gia_tri", ["-1", "1.5", "khong-phai-so", ""])
    async def test_counter_da_luu_hong_thi_fail_closed(
        self, test_redis_client, clear_redis_keys, monkeypatch, gia_tri
    ):
        """Trạng thái hỏng KHÔNG được tự chuyển thành một lượt xác minh hợp lệ."""
        user = _user_totp()
        key = f"totp_used:{user.id}"
        await test_redis_client.set(key, gia_tri, ex=120)
        _ep_totp_khop(monkeypatch, 1_000_000)

        assert await mfa_service.verify_mfa_code(None, user, "123456") is False, (
            f"Counter đã lưu {gia_tri!r} vẫn cho qua."
        )
        assert await test_redis_client.get(key) == gia_tri, (
            "Nhánh từ chối vẫn sửa giá trị khoá."
        )

    async def test_redis_loi_thi_tu_choi_totp(
        self, clear_redis_keys, monkeypatch
    ):
        """FAIL CLOSED — điểm khác biệt lớn nhất so với bản trước.

        Bản trước: ``safe_redis_get`` nuốt lỗi và trả ``None`` ⇒ vế
        ``if last and …`` falsy ⇒ CHẤP NHẬN. Một lượt Redis chết làm bốc hơi
        im lặng cả lớp chống phát lại.
        """
        user = _user_totp()
        _ep_totp_khop(monkeypatch, 1_000_000)

        class RedisChet:
            async def eval(self, *a, **kw):
                raise ConnectionError("redis down")

        monkeypatch.setattr(db_mod, "redis_client", RedisChet())

        assert await mfa_service.verify_mfa_code(None, user, "123456") is False, (
            "Redis lỗi mà mã TOTP vẫn được chấp nhận — fail OPEN."
        )


class TestParserTotpFailClosed:
    """Parser phải từ chối payload TỰ MÂU THUẪN, không chỉ payload sai KIỂU.

    "Bốn phần tử đều là int" là điều kiện quá yếu: nó cho lọt những payload mà
    *quan hệ* giữa các ô đã hỏng. Nếu script bị thay, bị nâng cấp lệch phiên
    bản, hay Redis trả về thứ ta không lường, tầng Python vẫn phải fail closed
    — đó là lý do tồn tại của lớp kiểm độc lập này.
    """

    _COUNTER = 1_000_000

    @staticmethod
    def _redis_tra(payload):
        class RedisGia:
            async def eval(self, *a, **kw):
                return payload

        return RedisGia()

    @pytest.mark.parametrize(
        "payload, vi_sao",
        [
            (
                [1, _COUNTER - 1, 180, 0],
                "chấp nhận nhưng counter GHI ĐƯỢC khác counter đã xin — lớp chống "
                "phát lại tưởng đã tiêu bước N mà Redis giữ bước khác",
            ),
            (
                [1, _COUNTER, 180, 2],
                "cờ sửa hạn ngoài {0,1} ⇒ payload không do script này sinh ra",
            ),
            (
                [0, _COUNTER - 1, 180, 0],
                "từ chối nhưng counter đã lưu NHỎ HƠN counter đã xin — mâu thuẫn "
                "với chính điều kiện từ chối",
            ),
        ],
    )
    async def test_payload_tu_mau_thuan_bi_tu_choi(
        self, monkeypatch, payload, vi_sao
    ):
        monkeypatch.setattr(db_mod, "redis_client", self._redis_tra(payload))

        kq = await db_mod.safe_redis_consume_totp_counter(
            "totp_used:99", self._COUNTER, 180
        )

        assert kq is None, f"Payload {payload} được chấp nhận, dù {vi_sao}."

    @pytest.mark.parametrize(
        "payload",
        [
            [1, _COUNTER, 180],           # thiếu ô
            [1, _COUNTER, 180, 0, 0],     # thừa ô
            [1, _COUNTER, 180, "0"],      # sai kiểu
            "khong-phai-list",
            None,
        ],
    )
    async def test_payload_sai_hinh_dang_bi_tu_choi(self, monkeypatch, payload):
        monkeypatch.setattr(db_mod, "redis_client", self._redis_tra(payload))

        assert (
            await db_mod.safe_redis_consume_totp_counter(
                "totp_used:99", self._COUNTER, 180
            )
            is None
        )

    async def test_payload_hop_le_van_duoc_chap_nhan(self, monkeypatch):
        """Ca ĐỐI CHỨNG: nếu thiếu nó, mọi kiểm trên đều xanh khi hàm luôn trả None."""
        monkeypatch.setattr(
            db_mod, "redis_client", self._redis_tra([1, self._COUNTER, 180, 0])
        )

        kq = await db_mod.safe_redis_consume_totp_counter(
            "totp_used:99", self._COUNTER, 180
        )

        assert kq is not None and kq.accepted is True
        assert kq.stored_counter == self._COUNTER


class TestHelperChiem:
    """``safe_redis_claim_once`` — ba kết cục, không phải hai."""

    async def test_chiem_lan_dau_thanh_cong_va_co_han(
        self, test_redis_client, clear_redis_keys
    ):
        key = f"mfa_used:utest_{uuid.uuid4().hex}"
        assert await db_mod.safe_redis_claim_once(key, "1", 300) is KetQuaChiem.DA_CHIEM
        assert await test_redis_client.ttl(key) > 0

    async def test_chiem_lan_hai_bao_da_bi_chiem(
        self, test_redis_client, clear_redis_keys
    ):
        key = f"mfa_used:utest_{uuid.uuid4().hex}"
        assert await db_mod.safe_redis_claim_once(key, "1", 300) is KetQuaChiem.DA_CHIEM
        assert (
            await db_mod.safe_redis_claim_once(key, "1", 300)
            is KetQuaChiem.DA_BI_CHIEM
        )

    async def test_redis_loi_thi_khong_chung_minh_duoc(self, monkeypatch):
        class RedisChet:
            async def set(self, *a, **kw):
                raise RedisConnectionError(_LOI_CO_CREDENTIAL)

        monkeypatch.setattr(db_mod, "redis_client", RedisChet())
        assert (
            await db_mod.safe_redis_claim_once("mfa_used:x", "1", 300)
            is KetQuaChiem.KHONG_CHUNG_MINH_DUOC
        )

    async def test_kieu_tra_ve_la_thi_fail_closed(self, monkeypatch):
        """Không diễn giải được ⇒ từ chối, chứ không rơi về nhánh cho đi tiếp."""

        class RedisLa:
            async def set(self, *a, **kw):
                return "OK"  # không phải True/None

        monkeypatch.setattr(db_mod, "redis_client", RedisLa())
        assert (
            await db_mod.safe_redis_claim_once("mfa_used:x", "1", 300)
            is KetQuaChiem.KHONG_CHUNG_MINH_DUOC
        )

    @pytest.mark.parametrize("ttl", [0, -1])
    async def test_ttl_ngoai_mien_thi_fail_closed(self, ttl, monkeypatch):
        """Tham số hỏng KHÔNG được chạm tới Redis."""
        da_goi = {"n": 0}

        class RedisDem:
            async def set(self, *a, **kw):
                da_goi["n"] += 1
                return True

        monkeypatch.setattr(db_mod, "redis_client", RedisDem())
        assert (
            await db_mod.safe_redis_claim_once("mfa_used:x", "1", ttl)
            is KetQuaChiem.KHONG_CHUNG_MINH_DUOC
        )
        assert da_goi["n"] == 0, "Tham số hỏng vẫn gửi lệnh xuống Redis."


class TestKhongLoKhoaVaoLog:
    """Đường LỖI của helper nhạy cảm KHÔNG được mang khoá vào log.

    ``mfa_used:{jti}`` chứa định danh của một bằng chứng MFA còn hiệu lực, và
    nhánh log là nhánh chạy KHI REDIS SỰ CỐ — tức lúc dễ xảy ra nhất, không
    phải một ca hiếm. Ca kiểm nằm cạnh đường lỗi, không ở một tệp guard xa xôi.
    """

    # JTI mồi: đủ đặc biệt để không trùng chuỗi nào khác trong log.
    _JTI_MOI = "canary-jti-khong-duoc-log-9f3a1c"

    # ⚠️ PHẢI phủ CẢ HAI nhánh except. Bản đầu của ca kiểm này chỉ ném
    # ``ConnectionError`` BUILTIN — thứ KHÔNG nằm trong ``REDIS_BREAKER_EXCEPTIONS``
    # (đó là ``redis.exceptions.ConnectionError``) — nên nó luôn rơi vào nhánh
    # ``except Exception`` và để trống hẳn nhánh breaker. Đo được: mutation đưa
    # ``key=key`` trở lại ĐÚNG nhánh breaker vẫn cho 34/34 XANH. Một guard chỉ
    # canh một trong hai nhánh thì nhánh kia muốn rò gì cũng được.
    _LOAI_LOI = [
        pytest.param(RedisConnectionError, id="nhanh-breaker"),
        pytest.param(RuntimeError, id="nhanh-ngoai-du-kien"),
    ]

    @staticmethod
    def _bat_log(monkeypatch):
        """Bắt mọi tham số truyền vào ``log.error``/``log.warning`` của database."""
        ban_ghi: list[str] = []

        def _ghi(*args, **kwargs):
            ban_ghi.append(repr(args) + repr(kwargs))

        monkeypatch.setattr(db_mod.log, "error", _ghi)
        monkeypatch.setattr(db_mod.log, "warning", _ghi)
        return ban_ghi

    @classmethod
    def _kiem_khong_ro(cls, ban_ghi, *chuoi_cam):
        """Ba điều phải đúng cùng lúc, không phải một.

        Chỉ kiểm "JTI không xuất hiện" là chưa đủ: ``exc_info=True`` không kéo
        JTI ra nhưng kéo TRACEBACK và message của exception — nơi redis-py để
        sẵn endpoint kèm ``user:password``.
        """
        assert ban_ghi, (
            "Đường lỗi không ghi log gì — ca kiểm này đang xanh mà không đo gì."
        )
        for dong in ban_ghi:
            assert _MAT_KHAU_MOI not in dong, (
                f"Mật khẩu Redis lọt vào log: {dong!r}. Với REDIS_URL thật, đó là "
                f"credential production nằm nguyên trong log."
            )
            assert "exc_info" not in dong, (
                f"Đường lỗi bật exc_info: {dong!r}. Traceback mang theo message "
                f"của exception, mà message ấy chứa endpoint + credential."
            )
            for xau in chuoi_cam:
                assert xau not in dong, f"Chuỗi cấm {xau!r} lọt vào log: {dong!r}"

    @pytest.mark.parametrize("loai_loi", _LOAI_LOI)
    async def test_claim_loi_redis_khong_lo_jti(self, monkeypatch, loai_loi):
        ban_ghi = self._bat_log(monkeypatch)

        class RedisChet:
            async def set(self, *a, **kw):
                raise loai_loi(_LOI_CO_CREDENTIAL)

        monkeypatch.setattr(db_mod, "redis_client", RedisChet())

        kq = await db_mod.safe_redis_claim_once(
            f"mfa_used:{self._JTI_MOI}", "1", 300, "mfa.token_claim"
        )

        assert kq is KetQuaChiem.KHONG_CHUNG_MINH_DUOC
        self._kiem_khong_ro(ban_ghi, self._JTI_MOI)

    @pytest.mark.parametrize("loai_loi", _LOAI_LOI)
    async def test_precheck_loi_redis_khong_lo_jti(self, monkeypatch, loai_loi):
        """Đi qua ĐÚNG helper precheck sản phẩm, không phải một bản mô phỏng."""
        ban_ghi = self._bat_log(monkeypatch)

        class RedisChet:
            async def exists(self, *a, **kw):
                raise loai_loi(_LOI_CO_CREDENTIAL)

        monkeypatch.setattr(db_mod, "redis_client", RedisChet())

        co = await db_mod.safe_redis_khoa_ton_tai(
            f"mfa_used:{self._JTI_MOI}", "mfa.token_claim"
        )

        assert co is False, "Lỗi Redis phải trả False cho phép kiểm sớm."
        self._kiem_khong_ro(ban_ghi, self._JTI_MOI)

    @pytest.mark.parametrize("loai_loi", _LOAI_LOI)
    async def test_totp_loi_redis_khong_lo_khoa(self, monkeypatch, loai_loi):
        """Helper TOTP cũng vậy — khoá mang ``user_id``, và cùng hai nhánh except."""
        ban_ghi = self._bat_log(monkeypatch)

        class RedisChet:
            async def eval(self, *a, **kw):
                raise loai_loi(_LOI_CO_CREDENTIAL)

        monkeypatch.setattr(db_mod, "redis_client", RedisChet())

        kq = await db_mod.safe_redis_consume_totp_counter(
            f"totp_used:{self._JTI_MOI}", 1_000_000, 180
        )

        assert kq is None
        self._kiem_khong_ro(ban_ghi, self._JTI_MOI)

    async def test_router_dung_helper_khong_lo_khoa(
        self, client, test_user_in_db, clear_redis_keys, monkeypatch
    ):
        """Ca ĐẦU-CUỐI cho đường CLAIM: JTI thật, Redis hỏng ĐÚNG Ở ``SET``.

        Phạm vi hẹp và phải nói đúng phạm vi ấy: ``EXISTS`` ở đây vẫn chạy
        SẠCH, nên ca này KHÔNG nói được gì về đường precheck — nếu router quay
        lại ``safe_redis_exists`` cũ (log nguyên khoá, bật ``exc_info``) thì ca
        này vẫn xanh, vì precheck có lỗi đâu mà log. Đường precheck do
        ``test_router_precheck_loi_khong_lo_khoa`` bên dưới canh.
        """
        ban_ghi = self._bat_log(monkeypatch)
        token = mfa_service.create_mfa_token(
            test_user_in_db["username"], test_user_in_db["id"]
        )
        jti_that = mfa_service.decode_mfa_token(token)["jti"]

        async def _verify_ok(db, user, code):
            return True

        monkeypatch.setattr(mfa_service, "verify_mfa_code", _verify_ok)

        so_lan = {"n": 0}

        async def _fake_complete(user, request, db):
            so_lan["n"] += 1
            return JSONResponse(status_code=200, content={"ok": True})

        monkeypatch.setattr(auth_router, "_complete_login_flow", _fake_complete)

        # ⚠️ Redis phải hỏng ĐÚNG Ở CLAIM, không hỏng từ đầu.
        #
        # Bản trước cho mọi lệnh Redis ném lỗi, nên request chết ngay ở bước
        # ĐẶT CHỖ (`eval`) và trả 503 mà KHÔNG bao giờ tới cổng claim — tức ca
        # kiểm chứng minh nhầm chỗ. Ở đây proxy chuyển tiếp mọi thứ sang
        # FakeRedis thật (precheck sạch, đặt chỗ thành công), chỉ `SET` mới ném.
        that = db_mod.redis_client
        so_lan_set = {"n": 0}

        class HongDungOChoSet:
            def __getattr__(self, ten):
                return getattr(that, ten)

            async def set(self, *a, **kw):
                so_lan_set["n"] += 1
                raise RedisConnectionError(_LOI_CO_CREDENTIAL)

        monkeypatch.setattr(db_mod, "redis_client", HongDungOChoSet())

        res = await client.post(
            "/api/auth/verify-mfa", json={"mfa_token": token, "code": "123456"}
        )

        assert so_lan_set["n"] >= 1, (
            "SET chưa hề được gọi — request chết trước khi tới cổng claim, nên ca "
            "này không chứng minh được gì về đường log của claim."
        )
        assert res.status_code == 503, (
            f"Claim hỏng mà endpoint trả {res.status_code} — phải fail closed."
        )
        assert so_lan["n"] == 0, "Claim hỏng mà vẫn cấp phiên đăng nhập."
        self._kiem_khong_ro(ban_ghi, jti_that)

    async def test_router_precheck_loi_khong_lo_khoa(
        self, client, test_user_in_db, clear_redis_keys, monkeypatch
    ):
        """Ca ĐẦU-CUỐI cho đường PRECHECK: chỉ ``EXISTS`` hỏng, phần còn lại thật.

        Đây là ca khoá việc router KHÔNG được quay lại ``safe_redis_exists``.
        Hai helper có ngữ nghĩa GIỐNG HỆT nhau ở tầng hành vi — lỗi ⇒ ``False``
        ⇒ đi tiếp — nên không phép kiểm hành vi nào phân biệt được chúng. Thứ
        phân biệt là ĐƯỜNG LOG: bản cũ ghi ``key=key`` (tức nguyên
        ``mfa_used:{jti}``) kèm ``exc_info=True`` (tức traceback mang message
        của exception, nơi redis-py để sẵn endpoint + credential).

        Vì thế ca này phải hội đủ:
          * ``EXISTS`` ném lỗi mang mật khẩu mồi — nhánh log mới chạy;
          * ``EVAL`` (đặt chỗ) và ``SET NX`` (claim) chạy THẬT — chứng minh
            request đi tiếp chứ không chết ở precheck, đúng ngữ nghĩa
            "phép kiểm sớm không có thẩm quyền";
          * đăng nhập vẫn hoàn tất — precheck hỏng KHÔNG được chặn người dùng;
          * log không có JTI, không mật khẩu, không ``exc_info``.
        """
        ban_ghi = self._bat_log(monkeypatch)
        token = mfa_service.create_mfa_token(
            test_user_in_db["username"], test_user_in_db["id"]
        )
        jti_that = mfa_service.decode_mfa_token(token)["jti"]

        async def _verify_ok(db, user, code):
            return True

        monkeypatch.setattr(mfa_service, "verify_mfa_code", _verify_ok)

        so_lan = {"n": 0}

        async def _fake_complete(user, request, db):
            so_lan["n"] += 1
            return JSONResponse(status_code=200, content={"ok": True})

        monkeypatch.setattr(auth_router, "_complete_login_flow", _fake_complete)

        that = db_mod.redis_client
        dem = {"exists": 0, "eval": 0, "set": 0}

        class HongDungOChoExists:
            def __getattr__(self, ten):
                return getattr(that, ten)

            async def exists(self, *a, **kw):
                dem["exists"] += 1
                raise RedisConnectionError(_LOI_CO_CREDENTIAL)

            async def eval(self, *a, **kw):
                dem["eval"] += 1
                return await that.eval(*a, **kw)

            async def set(self, *a, **kw):
                dem["set"] += 1
                return await that.set(*a, **kw)

        monkeypatch.setattr(db_mod, "redis_client", HongDungOChoExists())

        res = await client.post(
            "/api/auth/verify-mfa", json={"mfa_token": token, "code": "123456"}
        )

        assert dem["exists"] >= 1, (
            "EXISTS chưa hề được gọi — router không còn đi qua đường precheck, "
            "nên ca này không đo được gì về nó."
        )
        assert dem["eval"] >= 1, "Đặt chỗ không chạy — request chết trước precheck?"
        assert dem["set"] >= 1, (
            "SET NX chưa chạy — precheck hỏng đã CHẶN request. Phép kiểm sớm "
            "không có thẩm quyền thì không được làm hỏng đăng nhập."
        )
        assert res.status_code == 200, (
            f"Precheck hỏng mà endpoint trả {res.status_code} — người dùng hợp lệ "
            "bị chặn vì một phép kiểm không có thẩm quyền."
        )
        assert so_lan["n"] == 1, "Đăng nhập không hoàn tất dù mọi cổng thật đều đạt."
        self._kiem_khong_ro(ban_ghi, jti_that)


class TestMfaTokenTieuMotLan:
    """``mfa_token`` đổi lấy phiên đăng nhập ĐÚNG MỘT LẦN."""

    @staticmethod
    def _gan_verify_thanh_cong(monkeypatch):
        async def _verify_ok(db, user, code):
            # Nhường control để hai request thật sự đan vào nhau, thay vì phụ
            # thuộc vào may rủi của scheduler.
            await asyncio.sleep(0)
            return True

        monkeypatch.setattr(mfa_service, "verify_mfa_code", _verify_ok)

    @staticmethod
    def _dem_completion(monkeypatch, nhat_ky=None):
        so_lan = {"n": 0}

        async def _fake_complete(user, request, db):
            so_lan["n"] += 1
            if nhat_ky is not None:
                nhat_ky.append("complete")
            return JSONResponse(status_code=200, content={"ok": True})

        monkeypatch.setattr(auth_router, "_complete_login_flow", _fake_complete)
        return so_lan

    # Ca TÁI HIỆN race (hai request cùng một mfa_token) nằm ở
    # ``tests/integration/test_mfa_race_reproducer.py`` — nó không import
    # symbol mới nên chạy được cả trên commit cha.

    async def test_chiem_xay_ra_TRUOC_complete_login_flow(
        self, client, test_user_in_db, clear_redis_keys, monkeypatch
    ):
        """Thứ tự nhân quả, không chỉ 'có gọi'.

        Chiếm SAU khi đã cấp phiên thì phiên thứ hai đã ra khỏi cửa rồi — dấu
        vết ghi lúc đó không thu hồi được gì. Ca này bọc hàm THẬT chứ không
        thay nó, nên nó đo đúng đường sản phẩm.
        """
        token = mfa_service.create_mfa_token(
            test_user_in_db["username"], test_user_in_db["id"]
        )
        self._gan_verify_thanh_cong(monkeypatch)

        nhat_ky: list[str] = []
        chiem_that = auth_router.safe_redis_claim_once

        async def _chiem_co_ghi_nhat_ky(*a, **kw):
            nhat_ky.append("claim")
            return await chiem_that(*a, **kw)

        monkeypatch.setattr(auth_router, "safe_redis_claim_once", _chiem_co_ghi_nhat_ky)
        self._dem_completion(monkeypatch, nhat_ky)

        res = await client.post(
            "/api/auth/verify-mfa", json={"mfa_token": token, "code": "123456"}
        )

        assert res.status_code == 200
        assert nhat_ky == ["claim", "complete"], (
            f"Thứ tự thực tế: {nhat_ky}. Chiếm token phải xảy ra TRƯỚC khi cấp phiên."
        )

    async def test_token_thieu_jti_bi_tu_choi_401(
        self, client, test_user_in_db, clear_redis_keys, monkeypatch
    ):
        """Thiếu định danh ⇒ không có gì để đánh dấu ⇒ từ chối.

        Bản trước bọc cả lớp bảo vệ trong ``if mfa_jti:`` nên token không có
        ``jti`` đi thẳng qua mà không hề bị kiểm dùng-lại.
        """
        monkeypatch.setattr(
            mfa_service,
            "decode_mfa_token",
            lambda _t: {
                "sub": test_user_in_db["username"],
                "user_id": test_user_in_db["id"],
                # KHÔNG có "jti"
            },
        )
        self._gan_verify_thanh_cong(monkeypatch)
        so_lan = self._dem_completion(monkeypatch)

        res = await client.post(
            "/api/auth/verify-mfa", json={"mfa_token": "bat-ky", "code": "123456"}
        )

        assert res.status_code == 401
        assert so_lan["n"] == 0, "Token không có jti vẫn hoàn tất đăng nhập."

    @pytest.mark.parametrize("jti_rong", ["", "   "])
    async def test_jti_rong_cung_bi_tu_choi(
        self, client, test_user_in_db, clear_redis_keys, monkeypatch, jti_rong
    ):
        """``""`` là falsy nên bản trước cũng bỏ qua; ``"   "`` thì THẬT SỰ lọt
        qua ``if mfa_jti:`` và tạo khoá ``mfa_used:   `` dùng chung cho mọi
        token rỗng-khoảng-trắng."""
        monkeypatch.setattr(
            mfa_service,
            "decode_mfa_token",
            lambda _t: {
                "sub": test_user_in_db["username"],
                "user_id": test_user_in_db["id"],
                "jti": jti_rong,
            },
        )
        self._gan_verify_thanh_cong(monkeypatch)
        so_lan = self._dem_completion(monkeypatch)

        res = await client.post(
            "/api/auth/verify-mfa", json={"mfa_token": "bat-ky", "code": "123456"}
        )

        assert res.status_code == 401
        assert so_lan["n"] == 0

    async def test_token_da_bi_chiem_tra_401_qua_dung_nhanh_chiem(
        self, client, test_user_in_db, test_redis_client, clear_redis_keys, monkeypatch
    ):
        """Đi qua ĐÚNG nhánh chiếm, không phải nhánh precheck.

        Precheck ``EXISTS`` bị vô hiệu hoá để ca này chứng minh cổng có thẩm
        quyền tự nó chặn được — nếu chỉ để precheck bắt thì ta không biết cổng
        thật có hoạt động hay không.
        """
        token = mfa_service.create_mfa_token(
            test_user_in_db["username"], test_user_in_db["id"]
        )
        payload = mfa_service.decode_mfa_token(token)
        await test_redis_client.set(f"mfa_used:{payload['jti']}", "1", ex=300)

        # ⚠️ PHẢI patch ĐÚNG helper mà router đang gọi, và ĐÚNG chữ ký của nó.
        # Bản trước patch ``safe_redis_exists`` — tên đã không còn được router
        # dùng sau khi precheck chuyển sang ``safe_redis_khoa_ton_tai``. Hệ quả:
        # precheck THẬT chạy, thấy khoá, trả 401 ngay, và ``safe_redis_claim_once``
        # KHÔNG hề chạy. Đo được: gỡ hẳn cổng claim mà ca này vẫn PASS.
        async def _precheck_luon_sach(_key, _nhan_khoa):
            return False

        monkeypatch.setattr(auth_router, "safe_redis_khoa_ton_tai", _precheck_luon_sach)

        # Spy BỌC hàm thật: vừa đếm, vừa để cổng thật quyết định.
        so_lan_chiem = {"n": 0}
        chiem_that = auth_router.safe_redis_claim_once

        async def _chiem_co_dem(*a, **kw):
            so_lan_chiem["n"] += 1
            return await chiem_that(*a, **kw)

        monkeypatch.setattr(auth_router, "safe_redis_claim_once", _chiem_co_dem)
        self._gan_verify_thanh_cong(monkeypatch)
        so_lan = self._dem_completion(monkeypatch)

        res = await client.post(
            "/api/auth/verify-mfa", json={"mfa_token": token, "code": "123456"}
        )

        assert so_lan_chiem["n"] == 1, (
            f"safe_redis_claim_once chạy {so_lan_chiem['n']} lần — ca này phải đi "
            "QUA cổng claim, không được dừng ở precheck. Nếu bằng 0 thì phép kiểm "
            "đang đo nhầm nhánh và gỡ cổng claim nó vẫn xanh."
        )
        assert res.status_code == 401
        assert so_lan["n"] == 0, "Token đã bị chiếm vẫn cấp thêm một phiên."

    async def test_khong_chiem_duoc_thi_503_va_khong_dang_nhap(
        self, client, test_user_in_db, clear_redis_keys, monkeypatch
    ):
        """Redis hỏng ⇒ 503, KHÔNG hoàn tất đăng nhập (fail closed)."""
        token = mfa_service.create_mfa_token(
            test_user_in_db["username"], test_user_in_db["id"]
        )

        async def _chiem_hong(*a, **kw):
            return KetQuaChiem.KHONG_CHUNG_MINH_DUOC

        monkeypatch.setattr(auth_router, "safe_redis_claim_once", _chiem_hong)
        self._gan_verify_thanh_cong(monkeypatch)
        so_lan = self._dem_completion(monkeypatch)

        res = await client.post(
            "/api/auth/verify-mfa", json={"mfa_token": token, "code": "123456"}
        )

        assert res.status_code == 503
        assert so_lan["n"] == 0, (
            "Không chứng minh được token chưa dùng mà vẫn cấp phiên."
        )

    async def test_completion_hong_thi_KHONG_tra_lai_dau_chiem(
        self, client, test_user_in_db, test_redis_client, clear_redis_keys, monkeypatch
    ):
        """Token đã chứng minh MFA thì coi như đã tiêu, kể cả khi phiên hỏng.

        Trả lại dấu chiếm để "bù" nghe có vẻ tử tế, nhưng nó mở lại đúng cửa sổ
        phát lại mà bản vá này đóng: kẻ tấn công chỉ cần làm bước cấp phiên hỏng
        là có token dùng lại được.
        """
        token = mfa_service.create_mfa_token(
            test_user_in_db["username"], test_user_in_db["id"]
        )
        payload = mfa_service.decode_mfa_token(token)
        self._gan_verify_thanh_cong(monkeypatch)

        async def _complete_hong(user, request, db):
            raise RuntimeError("cấp phiên hỏng")

        monkeypatch.setattr(auth_router, "_complete_login_flow", _complete_hong)

        with pytest.raises(RuntimeError):
            await client.post(
                "/api/auth/verify-mfa", json={"mfa_token": token, "code": "123456"}
            )

        assert await test_redis_client.exists(f"mfa_used:{payload['jti']}") == 1, (
            "Dấu chiếm bị gỡ khi cấp phiên hỏng ⇒ token dùng lại được."
        )
