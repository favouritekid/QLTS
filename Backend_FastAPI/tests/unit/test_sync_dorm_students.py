"""Đồng bộ cohort sang hệ KTX — phần logic thuần.

Các nhánh gọi mạng được kiểm ở tầng tích hợp bên repo KTX; ở đây tập trung vào
những chỗ sai âm thầm: quy đổi giới tính, và bộ cột được gửi đi.
"""

import unicodedata
from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest

from app.scripts import sync_dorm_students as sync_module
from app.scripts.sync_dorm_students import (
    DormApi,
    assert_source_env_matches,
    assert_transport_is_encrypted,
    build_student_payload,
    main,
    normalize_gender,
    parse_args,
)

pytestmark = pytest.mark.unit


def _row(**overrides):
    base = dict(
        qlts_profile_id=9001,
        full_name="Nguyễn Văn An",
        source_gender_raw="Nam",
        program_name="Cao đẳng Điều dưỡng",
        academic_year=2026,
        officer_qlts_id=101,
        unit_id=14,
        profile_status="confirmed",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------------------
# Quy đổi giới tính
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Nam", "male"),
        ("nam", "male"),
        ("  NAM  ", "male"),
        ("Male", "male"),
        ("Nữ", "female"),
        ("nữ", "female"),
        ("Nu", "female"),
        ("female", "female"),
    ],
)
def test_normalize_gender_known_values(raw, expected):
    assert normalize_gender(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "Khác", "Other", "x", "1"])
def test_normalize_gender_falls_back_to_unknown(raw):
    """Giá trị lạ PHẢI ra ``unknown``, không được đoán bừa.

    ``unknown`` chặn xếp phòng ở phía KTX — đó là chủ đích. Đoán nhầm giới tính
    rồi xếp vào phòng sai là sự cố với người ở; ``unknown`` chỉ là một việc cần
    người xử lý.
    """
    assert normalize_gender(raw) == "unknown"


def test_normalize_gender_handles_decomposed_unicode():
    """ "Nữ" dạng PHÂN RÃ phải ra ``female``, không rơi xuống ``unknown``.

    Hai chuỗi dưới đây hiện ra giống hệt nhau trên màn hình nhưng khác nhau
    trong Python. Bản phân rã đến từ máy Mac, từ file import, từ một form web
    khác — và nếu nó thành ``unknown`` thì em đó bị chặn xếp phòng vì một lý do
    không ai nhìn ra được khi mở dữ liệu ra xem.
    """
    to_hop_san = "Nữ"
    phan_ra = unicodedata.normalize("NFD", "Nữ")

    assert to_hop_san != phan_ra  # khác nhau thật, không phải giả định
    assert normalize_gender(phan_ra) == "female"
    assert normalize_gender(unicodedata.normalize("NFD", "NỮ")) == "female"


def test_normalize_gender_never_guesses_from_prefix():
    # "Nam" là tiền tố của nhiều chuỗi khác ("Nam sinh", "Namibia"). Khớp theo
    # tiền tố sẽ gán giới tính cho những chuỗi không có nghĩa đó.
    assert normalize_gender("Nam sinh viên") == "unknown"


# ---------------------------------------------------------------------------
# Bộ cột gửi đi
# ---------------------------------------------------------------------------


def test_payload_never_touches_human_decisions():
    """Lượt đồng bộ KHÔNG được ghi đè quyết định của con người.

    Ghi đè ``placement_gender_override`` nghĩa là mỗi lần chạy lại sẽ xoá mất
    phần xử lý tay, và không ai hiểu vì sao nó biến mất.
    """
    payload = build_student_payload(_row(), sync_run_id=7)

    for forbidden in (
        "placement_gender_override",
        "override_reason",
        "overridden_by",
        "overridden_at",
    ):
        assert forbidden not in payload


def test_payload_carries_source_fields():
    payload = build_student_payload(_row(), sync_run_id=7)

    assert payload["qlts_profile_id"] == 9001
    assert payload["normalized_gender"] == "male"
    assert payload["source_gender_raw"] == "Nam"
    assert payload["academic_year"] == 2026
    assert payload["officer_qlts_id"] == 101
    assert payload["last_seen_sync_id"] == 7


def test_payload_marks_present_rows_eligible():
    """Có mặt trong nguồn = còn đủ điều kiện.

    Đây cũng là đường KÍCH HOẠT LẠI: người từng bị hạ cờ mà quay lại danh sách
    sẽ được bật lên, không cần thao tác tay.
    """
    assert build_student_payload(_row(), sync_run_id=1)["source_eligible"] is True


def test_payload_keeps_null_program_name():
    """Hồ sơ chưa chốt ngành vẫn đi qua, ``program_name`` để trống."""
    payload = build_student_payload(_row(program_name=None), sync_run_id=1)

    assert "program_name" in payload
    assert payload["program_name"] is None


def test_payload_carries_synced_at():
    """``synced_at`` PHẢI đi cùng payload.

    PostgREST merge-duplicates chỉ cập nhật những cột được gửi; cột này phía KTX
    chỉ có ``default now()`` của INSERT và không có trigger nào đụng tới. Thiếu
    nó thì mọi hàng đóng băng ở lần đồng bộ đầu tiên, và câu hỏi "danh sách này
    cũ chưa?" nhận về ngày nhìn thấy lần đầu.
    """
    payload = build_student_payload(
        _row(), sync_run_id=7, synced_at="2026-07-28T03:00:00+00:00"
    )

    assert payload["synced_at"] == "2026-07-28T03:00:00+00:00"


def test_payload_synced_at_defaults_to_a_parseable_timestamp():
    payload = build_student_payload(_row(), sync_run_id=7)

    # Phải parse được: một chuỗi Postgres không đọc nổi sẽ làm hỏng CẢ lô ghi.
    assert datetime.fromisoformat(payload["synced_at"]).tzinfo is not None


def test_payload_keeps_raw_gender_even_when_unknown():
    """Giữ nguyên văn giá trị nguồn để người xử lý biết vì sao ra ``unknown``."""
    payload = build_student_payload(_row(source_gender_raw="Khac"), sync_run_id=1)

    assert payload["normalized_gender"] == "unknown"
    assert payload["source_gender_raw"] == "Khac"


# ---------------------------------------------------------------------------
# Tham số dòng lệnh
# ---------------------------------------------------------------------------


def test_academic_year_is_required():
    """Thiếu năm học phải dừng, không được tự đoán."""
    with pytest.raises(SystemExit):
        parse_args([])


def test_dry_run_is_the_default():
    """Không truyền gì = KHÔNG ghi.

    Một công cụ đồng bộ mặc định ghi là công cụ sẽ sửa dữ liệu vì ai đó gõ thiếu
    một chữ.
    """
    args = parse_args(["--academic-year", "2026"])

    assert args.apply is False
    assert args.academic_year == 2026


def test_apply_must_be_explicit():
    args = parse_args(["--academic-year", "2026", "--apply"])

    assert args.apply is True


def test_dry_run_flag_is_accepted():
    """Lệnh trong tài liệu phải chạy được.

    Docstring hướng dẫn gõ ``--dry-run``; nếu argparse không nhận cờ đó thì
    người vận hành copy lệnh từ tài liệu sẽ gặp "unrecognized arguments" và đi
    tìm lỗi ở chỗ khác.
    """
    args = parse_args(["--academic-year", "2026", "--dry-run"])

    assert args.apply is False


@pytest.mark.parametrize("bad", ["0", "-1", "-200"])
def test_batch_size_must_be_positive(bad):
    """``--batch-size`` <= 0 là lỗi VÔ HIỆU HOÁ HÀNG LOẠT, phải chặn ở parser.

    ``range(0, 381, -1)`` và ``range(0, 381, 0)`` đều không sinh vòng lặp nào,
    nên KHÔNG hồ sơ nào được ghi — rồi bước hạ cờ vẫn chạy và coi toàn bộ danh
    sách là "không còn trong nguồn". Đã tái hiện thật: nguồn 381, ghi 0, hạ cờ 7,
    lượt `completed`, thoát 0. Nhìn từ ngoài y hệt một lần chạy thành công.
    """
    with pytest.raises(SystemExit):
        parse_args(["--academic-year", "2026", "--batch-size", bad])


def test_batch_size_positive_is_accepted():
    args = parse_args(["--academic-year", "2026", "--batch-size", "50"])

    assert args.batch_size == 50


def test_apply_and_dry_run_together_is_rejected():
    """Truyền cả hai là mâu thuẫn ý định — phải dừng, không im lặng chọn một bên.

    Ca tệ nhất nếu im lặng: người gõ cả hai tưởng mình đang xem trước.
    """
    with pytest.raises(SystemExit):
        parse_args(["--academic-year", "2026", "--apply", "--dry-run"])


# ---------------------------------------------------------------------------
# Lời gọi gửi đi — kiểm bằng client giả, không đi ra mạng
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, *, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = [] if payload is None else payload
        self.headers = headers or {}

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


class _RecordingClient:
    """httpx client giả: ghi lại lời gọi thay vì đi ra mạng."""

    def __init__(self, response=None, *, post_response=None, post_error=None):
        self.calls = []
        self._response = response if response is not None else _FakeResponse()
        self._post_response = post_response
        self._post_error = post_error

    async def patch(self, url, headers=None, params=None, json=None):
        self.calls.append({"method": "PATCH", "url": url, "json": json})
        return self._response

    async def get(self, url, headers=None, params=None):
        self.calls.append({"method": "GET", "url": url, "params": params})
        return self._response

    async def post(self, url, headers=None, params=None, json=None):
        self.calls.append({"method": "POST", "url": url, "json": json})
        if self._post_error is not None:
            raise self._post_error
        return (
            self._post_response if self._post_response is not None else self._response
        )


def _api_with(client) -> DormApi:
    api = DormApi("https://ktx.test", "khoa-gia")
    api._client = client
    return api


async def test_mark_failed_sends_a_timestamp_postgres_accepts():
    """``completed_at`` phải là mốc ISO, KHÔNG phải chuỗi ``"now()"``.

    PostgREST truyền thẳng chuỗi vào câu UPDATE. Postgres nhận ``now``,
    ``today``, ``epoch``, ``infinity`` nhưng KHÔNG nhận ``now()`` — nó trả 400,
    nhánh đánh dấu thất bại không bao giờ chạy được, lượt treo ``running`` và
    ``uq_sync_run_active_per_year`` khoá cứng năm học đó cho tới khi có người
    sửa tay trong database.
    """
    client = _RecordingClient(_FakeResponse(payload=[{"id": 5}]))

    changed = await _api_with(client).mark_sync_run_failed(
        5, {"source_count": 3, "upserted_count": 0}
    )

    assert changed == 1
    sent = client.calls[0]["json"]["completed_at"]
    assert sent != "now()"
    assert datetime.fromisoformat(sent).tzinfo is not None


async def test_count_students_returns_none_for_non_numeric_range():
    """``Content-Range: */*`` không được làm sập một lần XEM TRƯỚC chỉ-đọc."""
    client = _RecordingClient(_FakeResponse(headers={"content-range": "*/*"}))

    assert await _api_with(client).count_students(2026) is None


async def test_reconcile_returns_the_row_it_already_read():
    """Đối soát phải trả kèm hàng đã đọc, không bắt người gọi query lại.

    Lời gọi thứ hai chạy trong nhánh xử lý lỗi — nơi mạng vốn đang chập chờn.
    Nếu nó ném exception thì một lượt ĐÃ THÀNH CÔNG bị báo thành traceback và
    thoát khác 0, còn người vận hành thì tin là dữ liệu chưa đổi.
    """
    client = _RecordingClient(
        _FakeResponse(
            payload=[{"id": 5, "status": "completed", "deactivated_count": 12}]
        )
    )

    outcome, run = await _api_with(client).reconcile_after_failure(5, 10, 10)

    assert outcome == "finalized"
    assert run["deactivated_count"] == 12
    assert len(client.calls) == 1  # đúng MỘT lần đọc


async def test_open_run_recovers_the_row_it_created_after_a_lost_ack():
    """Mất ACK ở bước MỞ lượt là ca tệ nhất: hàng đã có, client không có id.

    Không nhận lại được thì không có ``run_id`` nào để đối soát, và
    ``uq_sync_run_active_per_year`` từ chối mọi lần chạy sau cho năm đó bằng 409
    cho tới khi có người vào database sửa tay.
    """
    client = _RecordingClient(
        _FakeResponse(payload=[{"id": 88, "status": "running"}]),
        post_error=httpx.ConnectError("mất kết nối"),
    )

    run_id = await _api_with(client).open_sync_run(2026, "abc123")

    assert run_id == 88
    # Tìm lại phải theo ĐÚNG dấu của lần chạy này, không phải "lượt running bất kỳ".
    assert client.calls[1]["params"]["note"] == "eq.client:abc123"


async def test_open_run_recovers_from_an_unreadable_body():
    """2xx nhưng thân không đọc được (proxy cắt, JSON hỏng) — hàng vẫn đã tạo."""
    client = _RecordingClient(
        _FakeResponse(payload=[{"id": 91, "status": "running"}]),
        post_response=_FakeResponse(status_code=201, payload=[]),
    )

    assert await _api_with(client).open_sync_run(2026, "tok") == 91


async def test_open_run_says_plainly_when_nothing_was_created():
    """Không tìm thấy dấu nào = database chưa nhận gì. Nói rõ để người ta chạy lại."""
    client = _RecordingClient(
        _FakeResponse(payload=[]), post_error=httpx.ConnectError("mất kết nối")
    )

    with pytest.raises(RuntimeError) as exc:
        await _api_with(client).open_sync_run(2026, "tok")

    assert "an toàn" in str(exc.value)


def test_open_run_stamps_the_client_token_in_the_insert():
    """Dấu phải nằm NGAY trong câu INSERT, không phải ghi bổ sung sau đó.

    Ghi sau là để lại đúng khoảng trống mà cơ chế này sinh ra để bịt: hàng tạo
    xong, chưa kịp đóng dấu, phản hồi mất — không nhận lại được nữa.
    """
    from app.scripts.sync_dorm_students import _client_note

    assert _client_note("abc") == "client:abc"


# ---------------------------------------------------------------------------
# Đường truyền
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    ["http://ktx.supabase.co", "http://10.0.0.5:8000", "ftp://ktx.supabase.co"],
)
def test_plaintext_destination_is_refused(url):
    """Khoá secret đi trong HAI header và thân request chứa họ tên người học.

    Qua ``http://`` thì cả hai đọc được trên đường truyền — một lần gõ nhầm
    scheme là đủ để rò khoá ghi toàn hệ KTX.
    """
    with pytest.raises(ValueError):
        assert_transport_is_encrypted(url)

    with pytest.raises(ValueError):
        DormApi(url, "khoa-that")


@pytest.mark.parametrize(
    "url",
    ["https://ktx.supabase.co", "http://localhost:54321", "http://127.0.0.1:54321"],
)
def test_https_and_loopback_are_allowed(url):
    """Loopback được miễn: đó là Supabase local, gói tin không rời khỏi máy."""
    assert assert_transport_is_encrypted(url) is None


# ---------------------------------------------------------------------------
# Hàng rào trước khi ghi
# ---------------------------------------------------------------------------


def _set_target_env(monkeypatch, *, app_env="test", source_env="test"):
    monkeypatch.setenv("DORM_SUPABASE_URL", "https://ktx.test")
    monkeypatch.setenv("DORM_SUPABASE_SECRET_KEY", "khoa-gia")
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("DORM_SYNC_SOURCE_ENV", source_env)


def test_source_env_mismatch_is_refused(monkeypatch):
    """Nguồn một môi trường, đích một môi trường khác = dừng.

    Đây là ca nguy hiểm nhất của công cụ: chạy stack DEV với file secret của KTX
    THẬT sẽ ghi đè danh sách thật rồi hạ cờ mọi người không có trong nguồn dev.
    """
    _set_target_env(monkeypatch, app_env="development", source_env="production")

    with pytest.raises(SystemExit) as exc:
        assert_source_env_matches()

    assert exc.value.code == 2


def test_missing_source_env_is_refused(monkeypatch):
    """Thiếu khai báo cũng là dừng.

    Một hàng rào tự đoán giá trị khi thiếu cấu hình thì không phải hàng rào.
    """
    _set_target_env(monkeypatch)
    monkeypatch.delenv("DORM_SYNC_SOURCE_ENV")

    with pytest.raises(SystemExit):
        assert_source_env_matches()


def test_matching_source_env_passes(monkeypatch):
    _set_target_env(monkeypatch, app_env="production", source_env="production")

    assert_source_env_matches() is None


async def test_apply_refuses_an_empty_cohort(monkeypatch):
    """Nguồn RỖNG + ``--apply`` = hạ cờ TOÀN BỘ năm học — phải dừng trước khi ghi.

    Mọi hàng rào phía database đều lọt vì các con số đều bằng 0 và khớp nhau:
    lượt kết thúc ``completed``, thoát 0, nhìn y hệt một lần chạy thành công.
    Cùng kiểu hỏng với ``--batch-size 0``, chỉ khác đường vào (gõ nhầm năm, năm
    chưa mở, vị từ cohort phía QLTS đổi).
    """
    _set_target_env(monkeypatch)
    monkeypatch.setattr(sync_module, "_install_stop_handlers", lambda: None)

    async def _empty_cohort(academic_year):
        return []

    def _no_network(*args, **kwargs):
        raise AssertionError("Không được chạm tới hệ KTX khi nguồn rỗng")

    monkeypatch.setattr(sync_module, "fetch_cohort", _empty_cohort)
    monkeypatch.setattr(sync_module, "DormApi", _no_network)

    assert await main(["--academic-year", "2026", "--apply"]) == 1


async def test_empty_cohort_proceeds_when_opted_in(monkeypatch):
    """ "Năm đó thật sự không còn ai" là ca có thật — nhưng phải gõ ra tường minh."""
    _set_target_env(monkeypatch)
    monkeypatch.setattr(sync_module, "_install_stop_handlers", lambda: None)

    class _ReachedTheApi(RuntimeError):
        pass

    class _FakeApi:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise _ReachedTheApi

        async def __aexit__(self, *exc):
            return False

    async def _empty_cohort(academic_year):
        return []

    monkeypatch.setattr(sync_module, "fetch_cohort", _empty_cohort)
    monkeypatch.setattr(sync_module, "DormApi", _FakeApi)

    with pytest.raises(_ReachedTheApi):
        await main(["--academic-year", "2026", "--apply", "--allow-empty-cohort"])


async def test_interrupt_mid_write_still_closes_the_run(monkeypatch):
    """Ctrl-C giữa chừng vẫn phải ĐÓNG SỔ, không được để lượt treo ``running``.

    ``KeyboardInterrupt`` không phải ``Exception``: bắt hẹp hơn sẽ để nó đi vòng
    qua toàn bộ phần đối soát, và lượt còn ``running`` khiến
    ``uq_sync_run_active_per_year`` từ chối MỌI lần chạy sau cho năm học đó bằng
    409 — một cú Ctrl-C đủ để khoá cứng cả năm cho tới khi có người sửa tay
    trong database.
    """
    _set_target_env(monkeypatch)
    monkeypatch.setattr(sync_module, "_install_stop_handlers", lambda: None)
    da_doi_soat = {}

    class _FakeApi:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def open_sync_run(self, academic_year, client_token):
            return 77

        async def upsert_students(self, rows):
            raise KeyboardInterrupt

        async def reconcile_after_failure(self, run_id, source_count, upserted_count):
            da_doi_soat["run_id"] = run_id
            return "marked_failed", {"id": run_id, "status": "failed"}

    async def _one_row(academic_year):
        return [_row()]

    monkeypatch.setattr(sync_module, "fetch_cohort", _one_row)
    monkeypatch.setattr(sync_module, "DormApi", _FakeApi)

    assert await main(["--academic-year", "2026", "--apply"]) == 1
    assert da_doi_soat["run_id"] == 77


async def test_stop_request_blocks_the_finalizer_when_the_loop_never_ran(monkeypatch):
    """Đã bấm dừng thì KHÔNG được hạ cờ, kể cả khi không có lô nào để chạy.

    Vòng lặp chỉ nhìn cờ dừng ở ĐẦU mỗi lô. Với ``--allow-empty-cohort`` nó chạy
    0 lần, nên nếu không kiểm lại ngay trước bước hạ cờ thì một cú Ctrl-C vẫn
    kết thúc bằng việc vô hiệu hoá TOÀN BỘ năm học. Ca "tín hiệu tới trong lúc
    chạy lô cuối" cũng đi qua đúng khe này.
    """
    _set_target_env(monkeypatch)
    monkeypatch.setattr(sync_module, "_install_stop_handlers", lambda: None)
    monkeypatch.setattr(sync_module, "_stop_requested", True)
    da_doi_soat = {}

    class _FakeApi:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def open_sync_run(self, academic_year, client_token):
            return 91

        async def finalize_sync_run(self, run_id, source_count, upserted_count):
            # ⚠️ KHÔNG raise ở đây: `main` bắt `BaseException`, nên một
            # `AssertionError` sẽ bị nuốt và test xanh dù hạ cờ ĐÃ chạy. Phải
            # ghi nhận rồi khẳng định ở ngoài.
            da_doi_soat["đã_hạ_cờ"] = True
            return 0

        async def reconcile_after_failure(self, run_id, source_count, upserted_count):
            da_doi_soat["run_id"] = run_id
            return "marked_failed", {"id": run_id, "status": "failed"}

    async def _empty_cohort(academic_year):
        return []

    monkeypatch.setattr(sync_module, "fetch_cohort", _empty_cohort)
    monkeypatch.setattr(sync_module, "DormApi", _FakeApi)

    exit_code = await main(
        ["--academic-year", "2026", "--apply", "--allow-empty-cohort"]
    )

    assert "đã_hạ_cờ" not in da_doi_soat
    assert exit_code == 1
    assert da_doi_soat["run_id"] == 91  # vẫn đóng sổ, không bỏ lượt treo `running`


async def test_plaintext_url_stops_before_any_request(monkeypatch):
    """Sai scheme phải dừng ở bước cấu hình, không phải sau khi đã gửi gì đó."""
    _set_target_env(monkeypatch)
    monkeypatch.setenv("DORM_SUPABASE_URL", "http://ktx.supabase.co")
    monkeypatch.setattr(sync_module, "_install_stop_handlers", lambda: None)

    async def _one_row(academic_year):
        return [_row()]

    monkeypatch.setattr(sync_module, "fetch_cohort", _one_row)

    assert await main(["--academic-year", "2026", "--apply"]) == 2


async def test_dry_run_never_needs_the_env_guard(monkeypatch):
    """Xem trước chỉ-đọc không đòi khai báo môi trường.

    Bắt nó khai báo chỉ khiến người ta bỏ qua bước xem trước — và bước xem
    trước chính là thứ chặn được lần ghi sai.
    """
    monkeypatch.setenv("DORM_SUPABASE_URL", "https://ktx.test")
    monkeypatch.setenv("DORM_SUPABASE_SECRET_KEY", "khoa-gia")
    monkeypatch.delenv("DORM_SYNC_SOURCE_ENV", raising=False)

    class _FakeApi:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def count_students(self, academic_year):
            return 0

    async def _empty_cohort(academic_year):
        return []

    monkeypatch.setattr(sync_module, "fetch_cohort", _empty_cohort)
    monkeypatch.setattr(sync_module, "DormApi", _FakeApi)

    assert await main(["--academic-year", "2026"]) == 0
