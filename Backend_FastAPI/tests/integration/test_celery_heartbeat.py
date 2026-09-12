"""The heartbeat that lets something OUTSIDE Celery notice Celery is dead.

Nothing inside Celery can report its own death: beat schedules, the worker
executes, and both are gone together. This task writes the only signal that
proves both halves ran — and the whole value of that signal comes from four
properties that are easy to break and invisible when broken:

* it must expire (TTL), so a stopped heartbeat becomes ABSENCE rather than a
  value sitting there looking like data;
* it must be stamped at EXECUTION time on the worker, never at schedule time —
  a beat-produced timestamp proves only that beat is alive;
* a Redis failure must PROPAGATE, so the task fails visibly instead of
  reporting success over a value nobody refreshed;
* the beat interval and the monitor's staleness threshold must stay in step.

Each of those has a test here that goes red if the property is removed.
"""
import inspect
import re

import pytest
from redis.exceptions import RedisError

from app.celery_app import celery_app
from app.tasks import heartbeat_tasks as ht
from app.utils import redis_lock as rl

# Không đặt `pytestmark = pytest.mark.asyncio` ở cấp module: pytest.ini đang ở
# `asyncio_mode = auto` nên ca async tự được thu, còn cái mark ấy sẽ dán lên cả
# ca ĐỒNG BỘ trong tệp này và sinh 9 PytestWarning "marked with asyncio but it
# is not an async function".
BEAT_ENTRY = "celery-heartbeat"


def _text(raw):
    return raw.decode() if isinstance(raw, bytes) else raw


class _ClientGhiLai:
    """Bọc client Redis thật: vẫn ghi thật, nhưng ghi lại đối số của `set`.

    Bọc thay vì thay hẳn bằng đồ giả, để ca kiểm vẫn khẳng định được rằng giá
    trị THỰC SỰ tới Redis — một `set` chỉ được spy ghi nhận mà không tới đâu cả
    thì vẫn xanh.
    """

    def __init__(self, that):
        self._that = that
        self.cac_lan_set = []

    async def set(self, *vi_tri, **tu_khoa):
        self.cac_lan_set.append((vi_tri, tu_khoa))
        return await self._that.set(*vi_tri, **tu_khoa)

    def __getattr__(self, ten):
        return getattr(object.__getattribute__(self, "_that"), ten)


@pytest.fixture(autouse=True)
async def _clean():
    client = rl.get_redis_client()
    await client.delete(ht.HEARTBEAT_KEY)
    yield
    await client.delete(ht.HEARTBEAT_KEY)


class TestGiaTriGhiRa:
    async def test_ghi_dung_khoa(self):
        await ht.write_heartbeat()
        client = rl.get_redis_client()
        assert await client.get(ht.HEARTBEAT_KEY) is not None

    async def test_gia_tri_la_epoch_thap_phan_tran(self):
        """The reader is a shell script on a VPS with no ``jq``.

        Anything richer than bare decimal seconds would have to be parsed by
        hand in bash and would fail OPEN on the first format change.
        """
        await ht.write_heartbeat()
        client = rl.get_redis_client()
        value = _text(await client.get(ht.HEARTBEAT_KEY))
        assert re.fullmatch(r"[0-9]+", value), (
            f"gia tri {value!r} khong phai epoch thap phan tran — monitor bash "
            "khong co jq de doc dinh dang khac"
        )
        assert int(value) >= ht.MIN_PLAUSIBLE_EPOCH

    async def test_khoa_mang_TTL(self):
        """Without a TTL a stopped heartbeat leaves its last value in Redis for
        good. Correct only while the reader compares timestamps; a trap the day
        anything treats "key exists" as "alive"."""
        await ht.write_heartbeat()
        client = rl.get_redis_client()
        ttl = await client.ttl(ht.HEARTBEAT_KEY)
        assert ttl > 0, (
            f"ttl={ttl} — -1 nghia la khoa SONG MAI (khong dat EX), -2 nghia la "
            "khoa khong ton tai"
        )
        assert ttl <= ht.HEARTBEAT_TTL_SECONDS

    async def test_TTL_dung_bang_hang_so(self):
        await ht.write_heartbeat()
        client = rl.get_redis_client()
        ttl = await client.ttl(ht.HEARTBEAT_KEY)
        assert ht.HEARTBEAT_TTL_SECONDS - 5 <= ttl <= ht.HEARTBEAT_TTL_SECONDS

    async def test_ghi_qua_client_DUNG_CHUNG_cua_app(self, monkeypatch):
        """Hai hợp đồng KHÁC NHAU, và trộn chúng là cách ca này từng đỏ ở CI.

        * Hợp đồng RUNTIME (ca này): heartbeat phải ghi qua ĐÚNG client dùng
          chung của app, chứ không tự mở một kết nối thứ hai. Một client riêng
          với DB ghim cứng sẽ ghi vào DB mà monitor không đọc, và cả hai phía
          vẫn "chạy được" — không ai thấy gì cho tới lúc cần cảnh báo.
        * Hợp đồng TRIỂN KHAI (không thuộc tệp này): client dùng chung ấy trỏ
          vào Redis DB 1 ở production. Nó được canh độc lập bởi
          `test_monitor_doc_dung_DB_cua_app`, ca đó đọc thẳng `docker-compose.yml`
          nên đúng ở mọi môi trường.

        Bản đầu của ca này khẳng định `settings.REDIS_URL` kết thúc bằng `/1`.
        Đó là khẳng định về MÔI TRƯỜNG CHẠY TEST, không phải về mã: compose cho
        `/1` nên nó xanh ở máy dev, còn runner CI đặt `/0` nên nó đỏ. Chênh lệch
        đo được đúng một ca — Tier 3 cho 406 passed ở máy và 405 passed + 1
        failed ở CI.
        """
        that = rl.get_redis_client()
        theo_doi = _ClientGhiLai(that)
        so_lan_goi_factory = []

        def factory():
            so_lan_goi_factory.append(1)
            return theo_doi

        monkeypatch.setattr(ht, "get_redis_client", factory)
        await ht.write_heartbeat()

        assert len(so_lan_goi_factory) == 1, (
            f"factory duoc goi {len(so_lan_goi_factory)} lan. 0 lan nghia la "
            "write_heartbeat KHONG di qua client dung chung — no da mo mot "
            "ket noi khac, co the tro vao DB ma monitor khong doc."
        )
        assert len(theo_doi.cac_lan_set) == 1, (
            f"client dung chung nhan {len(theo_doi.cac_lan_set)} lan `set`"
        )

        vi_tri, tu_khoa = theo_doi.cac_lan_set[0]
        assert vi_tri[0] == ht.HEARTBEAT_KEY
        assert re.fullmatch(r"[0-9]+", vi_tri[1]), (
            f"gia tri ghi ra khong phai epoch thap phan tran: {vi_tri[1]!r}"
        )
        assert tu_khoa.get("ex") == ht.HEARTBEAT_TTL_SECONDS, (
            f"thieu hoac sai TTL: {tu_khoa!r}"
        )

        # Và giá trị thật sự nằm trong client ĐƯỢC BỌC, không chỉ đi qua spy:
        # nếu chỉ khẳng định trên spy thì một bản ghi đi đâu mất vẫn xanh.
        assert _text(await that.get(ht.HEARTBEAT_KEY)) == vi_tri[1]


class TestThoiDiemLaLucWorkerCHAY:
    async def test_epoch_doc_lai_MOI_LAN_CHAY(self, monkeypatch):
        """The one property that makes this signal mean anything.

        A timestamp captured once — at import, at schedule construction, handed
        in by beat at publish time — proves at most that beat is alive. The
        worker is the half that can die quietly while beat keeps publishing.

        Driven by an advancing fake clock: an implementation that reads the
        clock anywhere other than inside the call writes the SAME value twice.
        """
        gio = iter([1_700_000_000.0, 1_700_000_999.0])
        monkeypatch.setattr(ht, "_now_epoch", lambda: next(gio))
        client = rl.get_redis_client()

        await ht.write_heartbeat()
        lan_1 = _text(await client.get(ht.HEARTBEAT_KEY))
        await ht.write_heartbeat()
        lan_2 = _text(await client.get(ht.HEARTBEAT_KEY))

        assert lan_1 == "1700000000"
        assert lan_2 == "1700000999", (
            f"lan 2 ghi {lan_2!r} — dong ho khong duoc doc trong luc chay, nen "
            "gia tri khong chung minh duoc worker con song"
        )

    async def test_gan_voi_dong_ho_that(self):
        import time

        truoc = int(time.time())
        await ht.write_heartbeat()
        sau = int(time.time())
        client = rl.get_redis_client()
        value = int(_text(await client.get(ht.HEARTBEAT_KEY)))
        assert truoc <= value <= sau

    def test_khong_co_cho_nao_de_tiem_thoi_gian_len_lich(self):
        """Structural, not behavioural: there is deliberately no parameter.

        A ``now=`` / ``scheduled_at=`` argument is precisely the door a
        schedule-time value walks through. Closing the door is stronger than
        testing that nobody currently uses it.
        """
        assert list(inspect.signature(ht.write_heartbeat).parameters) == []

    def test_lich_beat_dat_expires_khong_qua_chu_ky(self):
        """Không có `expires` thì tín hiệu chứng minh SAI thứ nó cần chứng minh.

        Beat chết lúc T. Thông điệp nó đã publish vẫn nằm trong broker. Một
        worker khoẻ rút nó ra lúc T+X và task ghi thời gian THỰC THI, tức
        T+X — một giá trị tươi được sinh ra hoàn toàn SAU khi beat đã chết, và
        monitor đọc thành xanh. Đúng cái lỗ mà "thời gian thực thi" mở ra, và
        `expires` là thứ bịt nó: quá một chu kỳ mà chưa chạy được thì bỏ, không
        tin.

        Trần là ĐÚNG một chu kỳ: lớn hơn thì cửa sổ tin-sai rộng ra.
        """
        entry = celery_app.conf.beat_schedule[BEAT_ENTRY]
        expires = entry.get("options", {}).get("expires")
        assert expires is not None, (
            f"beat entry {BEAT_ENTRY!r} khong dat `expires`: mot thong diep cu "
            "van chay duoc sau khi beat da chet va ghi ra dau thoi gian tuoi"
        )
        assert 0 < expires <= ht.HEARTBEAT_INTERVAL_SECONDS, (
            f"expires={expires} phai nam trong (0, {ht.HEARTBEAT_INTERVAL_SECONDS}]"
        )

    def test_lich_beat_khong_truyen_tham_so_nao(self):
        entry = celery_app.conf.beat_schedule[BEAT_ENTRY]
        assert "args" not in entry and "kwargs" not in entry, (
            f"beat entry {BEAT_ENTRY!r} dang truyen tham so: {entry!r}. Moi "
            "tham so tu beat la mot gia tri sinh ra o THOI DIEM LEN LICH."
        )


class TestLoiRedisPhaiNoiLen:
    async def test_loi_redis_khong_bi_nuot(self, monkeypatch):
        """Swallowing this would mark the task SUCCEEDED while the value goes
        stale — and the monitor would then alert about a Celery outage that is
        really a Redis outage, or keep reading a value nobody refreshes."""
        client = rl.get_redis_client()

        async def no(*a, **k):
            raise RedisError("redis down")

        monkeypatch.setattr(client, "set", no)
        with pytest.raises(RedisError):
            await ht.write_heartbeat()

    async def test_khi_loi_thi_khong_ghi_gi(self, monkeypatch):
        client = rl.get_redis_client()

        async def no(*a, **k):
            raise RedisError("redis down")

        monkeypatch.setattr(client, "set", no)
        with pytest.raises(RedisError):
            await ht.write_heartbeat()
        monkeypatch.undo()
        assert await client.get(ht.HEARTBEAT_KEY) is None

    def test_loi_redis_nam_trong_hop_dong_retry_cua_task(self):
        task = celery_app.tasks[ht.TASK_NAME]
        autoretry = getattr(task, "autoretry_for", ())
        assert autoretry, f"{ht.TASK_NAME} khong khai autoretry_for"
        assert any(issubclass(ht.RETRYABLE_ERROR, k) for k in autoretry), (
            f"RedisError khong nam trong autoretry_for={autoretry!r} — mot blip "
            "Redis se lam task FAILED ngay thay vi thu lai"
        )
        assert task.max_retries and task.max_retries > 0


class TestNoiDayVaoBeat:
    def test_task_dang_ky_dung_ten(self):
        assert ht.TASK_NAME in celery_app.tasks, (
            f"{ht.TASK_NAME} chua dang ky — beat se gui mot ten khong ai nhan, "
            "va worker tra NotRegistered"
        )

    def test_co_trong_lich_beat(self):
        assert BEAT_ENTRY in celery_app.conf.beat_schedule
        assert celery_app.conf.beat_schedule[BEAT_ENTRY]["task"] == ht.TASK_NAME

    def test_di_vao_queue_worker_dang_phuc_vu(self):
        entry = celery_app.conf.beat_schedule[BEAT_ENTRY]
        assert entry.get("options", {}).get("queue") == "default", (
            "queue phai la `default` — worker production dang phuc vu "
            "`celery,default`; mot queue khac nghia la beat gui vao cho khong "
            "ai lang nghe, va heartbeat im lang y NHU khi Celery chet"
        )

    def test_lich_moi_5_phut_KHOP_hang_so_python(self):
        """Three numbers, one chain: interval -> staleness -> TTL.

        Change the cron to ``*/30`` and the 900s threshold turns into a
        permanent false alarm; change it to ``*/1`` and the alarm goes quiet for
        15 minutes longer than anyone expects.
        """
        sched = celery_app.conf.beat_schedule[BEAT_ENTRY]["schedule"]
        minute = getattr(sched, "_orig_minute", None)
        assert minute is not None, (
            f"schedule {sched!r} khong phai crontab — test nay doc `*/N` tu "
            "truong phut"
        )
        khop = re.fullmatch(r"\*/([0-9]+)", str(minute))
        assert khop, f"truong phut {minute!r} khong dang `*/N`"
        assert int(khop.group(1)) * 60 == ht.HEARTBEAT_INTERVAL_SECONDS

    def test_TTL_phai_LON_hon_nguong_cu(self):
        """Ordering, not two independent numbers.

        TTL <= threshold makes the monitor's "stale" branch unreachable dead
        code: the key would always be gone before it could be judged old, so a
        silent worker could only ever look like an absent key.
        """
        assert ht.HEARTBEAT_TTL_SECONDS > 3 * ht.HEARTBEAT_INTERVAL_SECONDS
