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
    assert_source_database_matches,
    assert_transport_is_encrypted,
    build_student_payload,
    database_identity_from_url,
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


def test_client_token_is_optional_and_passthrough():
    """Truyền lại dấu cũ là đường phục hồi một lần chạy đứt giữa chừng."""
    assert parse_args(["--academic-year", "2026"]).client_token is None
    assert (
        parse_args(["--academic-year", "2026", "--client-token", "abc"]).client_token
        == "abc"
    )


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
    # Loopback: các test dưới đây không đi ra mạng (client là đồ giả), và
    # loopback được miễn CẢ hàng rào đường truyền lẫn hàng rào project ref —
    # Supabase local không có ref. Dùng một hostname bịa như `ktx.test` sẽ vướng
    # hàng rào đích, và vướng vì đúng lý do nó tồn tại.
    api = DormApi("http://127.0.0.1:54321", "khoa-gia")
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


@pytest.mark.parametrize("ma_loi", [500, 502, 503, 504, 408])
async def test_open_run_reconciles_ambiguous_gateway_replies(ma_loi):
    """5xx/408 KHÔNG phải câu trả lời dứt khoát của database.

    Gateway đứng TRƯỚC database: INSERT có thể đã commit xong rồi phản hồi mới
    hỏng trên đường về. Ném thẳng ở những mã này là bỏ lại đúng hàng ``running``
    đang khoá năm học mà cơ chế dấu sinh ra để nhận lại.
    """
    client = _RecordingClient(
        _FakeResponse(payload=[{"id": 77, "status": "running"}]),
        post_response=_FakeResponse(status_code=ma_loi, payload=[]),
    )

    assert await _api_with(client).open_sync_run(2026, "tok") == 77
    assert [c["method"] for c in client.calls] == ["POST", "GET"]


@pytest.mark.parametrize("ma_loi", [400, 401, 403])
async def test_open_run_trusts_definitive_client_errors(ma_loi):
    """400/401/403 là câu trả lời DỨT KHOÁT — không có hàng nào để đối soát."""
    client = _RecordingClient(
        _FakeResponse(payload=[]),
        post_response=_FakeResponse(status_code=ma_loi, payload=[]),
    )

    with pytest.raises(RuntimeError):
        await _api_with(client).open_sync_run(2026, "tok")

    assert [c["method"] for c in client.calls] == ["POST"]


async def test_open_run_never_claims_safety_when_the_probe_also_failed():
    """Mất mạng CẢ HAI CHIỀU thì tuyệt đối không được nói "chạy lại an toàn".

    POST mất ACK rồi GET đối soát cũng hỏng = ta KHÔNG BIẾT hàng đã được tạo hay
    chưa. Tuyên bố an toàn ở đây là kiểu sai tệ hơn im lặng: người vận hành chạy
    lại, gặp 409, và không hiểu vì sao.
    """
    client = _RecordingClient(
        post_error=httpx.ConnectError("mất kết nối"),
        response=_FakeResponse(status_code=503, payload=[]),
    )

    with pytest.raises(RuntimeError) as exc:
        await _api_with(client).open_sync_run(2026, "tok")

    thong_diep = str(exc.value)
    assert "an toàn" not in thong_diep
    assert "CÓ THỂ" in thong_diep
    assert "client:tok" in thong_diep  # cầm đi tra database được
    assert "--client-token tok" in thong_diep


async def test_open_run_reuses_its_own_running_row_on_conflict():
    """409 mang DẤU của chính mình = lượt cũ của lần chạy này, dùng tiếp.

    Đây là đường phục hồi khi chạy lại với `--client-token` của một lần đứt
    giữa chừng — không cần ai vào database sửa tay.
    """
    client = _RecordingClient(
        _FakeResponse(payload=[{"id": 55, "status": "running"}]),
        post_response=_FakeResponse(status_code=409, payload=[]),
    )

    assert await _api_with(client).open_sync_run(2026, "tok") == 55


async def test_open_run_refuses_a_conflict_it_does_not_own():
    """409 mà không mang dấu mình = lượt của tiến trình khác. Không được đụng."""
    client = _RecordingClient(
        _FakeResponse(payload=[]),
        post_response=_FakeResponse(status_code=409, payload=[]),
    )

    with pytest.raises(RuntimeError) as exc:
        await _api_with(client).open_sync_run(2026, "tok")

    assert "KHÔNG mang dấu của lần chạy này" in str(exc.value)


@pytest.mark.parametrize(
    "response,mong_doi",
    [
        (_FakeResponse(payload=[{"id": 1, "status": "running"}]), "found"),
        (_FakeResponse(payload=[]), "absent"),
        (_FakeResponse(status_code=500, payload=[]), "unknown"),
        (_FakeResponse(payload={"message": "không phải danh sách"}), "unknown"),
        # Hàng đã đóng KHÔNG phải lượt vừa mở — xem test lọc status bên dưới.
        (_FakeResponse(payload=[{"id": 41, "status": "failed"}]), "unknown"),
        (_FakeResponse(payload=[{"id": 41, "status": "completed"}]), "unknown"),
        # Thân lạ phải ra `unknown`, không được ném KeyError giữa nhánh phục hồi.
        (_FakeResponse(payload=[{}]), "unknown"),
        (_FakeResponse(payload=["không phải hàng"]), "unknown"),
        (_FakeResponse(payload=[{"id": None, "status": "running"}]), "unknown"),
        (_FakeResponse(payload=[{"id": True, "status": "running"}]), "unknown"),
    ],
)
async def test_find_run_by_token_distinguishes_absent_from_unknown(response, mong_doi):
    """BA kết quả, không phải hai.

    Gộp "đọc được, không có hàng nào" với "không đọc được" là gốc của lời tuyên
    bố an toàn sai ở nhánh trên.
    """
    outcome, _ = await _api_with(_RecordingClient(response)).find_run_by_token(
        2026, "tok"
    )

    assert outcome == mong_doi


async def test_find_run_by_token_asks_only_for_running_rows():
    """``note`` KHÔNG unique — chỉ lượt ĐANG CHẠY mới được ràng một-mỗi-năm.

    Chạy lại với cùng ``--client-token`` sau một lượt đã ``failed`` để lại hàng
    lịch sử mang đúng dấu đó. Không lọc thì lời gọi này nhận nhầm hàng cũ, còn
    hàng ``running`` vừa tạo bị bỏ lại và tiếp tục khoá năm học.
    """
    client = _RecordingClient(_FakeResponse(payload=[]))

    await _api_with(client).find_run_by_token(2026, "tok")

    assert client.calls[0]["params"]["status"] == "eq.running"


async def test_open_run_does_not_recover_a_historical_failed_row():
    """Ca đã tái hiện: POST commit hàng running mới rồi trả 502.

    Nếu lookup nhặt hàng ``failed`` cũ cùng dấu, script chạy tiếp với id sai và
    bỏ lại hàng running thật — năm học vẫn bị khoá, mà nhật ký thì báo đã phục
    hồi xong.
    """
    client = _RecordingClient(
        # Server đã lọc status nên trả rỗng; hàng failed id 41 không lọt qua.
        _FakeResponse(payload=[]),
        post_response=_FakeResponse(status_code=502, payload=[]),
    )

    with pytest.raises(RuntimeError) as exc:
        await _api_with(client).open_sync_run(2026, "tok")

    assert "chạy lại là an toàn" in str(exc.value)


async def test_open_run_reports_unknown_when_the_conflict_probe_fails():
    """409 + không đọc được ≠ "lượt của người khác".

    Khẳng định nhầm sẽ đẩy người vận hành đi đánh dấu failed một lượt có thể là
    của chính họ — và lượt đó đang ghi dở.
    """
    client = _RecordingClient(
        _FakeResponse(status_code=503, payload=[]),
        post_response=_FakeResponse(status_code=409, payload=[]),
    )

    with pytest.raises(RuntimeError) as exc:
        await _api_with(client).open_sync_run(2026, "tok")

    thong_diep = str(exc.value)
    assert "KHÔNG mang dấu" not in thong_diep
    assert "KHÔNG đối soát được" in thong_diep
    assert "--client-token tok" in thong_diep


async def test_find_run_by_token_reports_unknown_on_transport_error():
    class _DeadClient(_RecordingClient):
        async def get(self, url, headers=None, params=None):
            raise httpx.ReadTimeout("hết giờ")

    outcome, run = await _api_with(_DeadClient()).find_run_by_token(2026, "tok")

    assert (outcome, run) == ("unknown", None)


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
# Hàng rào ĐÍCH — project nào nhận dữ liệu
# ---------------------------------------------------------------------------


def test_target_project_ref_must_match_the_host(monkeypatch):
    """Sai MỘT ký tự trong ref là dừng.

    Hàng rào nguồn bảo vệ việc đọc đúng database. Nhưng đích thì trước đây chỉ
    kiểm scheme https, nên một cặp URL + secret key hợp lệ của project KHÁC vẫn
    nhận trọn cohort và báo thành công.
    """
    from app.scripts.sync_dorm_students import assert_target_project_matches

    monkeypatch.setenv("DORM_SYNC_TARGET_PROJECT_REF", "wkrwceedapisacgyujtg")

    assert (
        assert_target_project_matches("https://wkrwceedapisacgyujtg.supabase.co")
        is None
    )

    with pytest.raises(ValueError) as exc:
        # Thiếu đúng một ký tự cuối.
        assert_target_project_matches("https://wkrwceedapisacgyujt.supabase.co")

    assert "wkrwceedapisacgyujtg" in str(exc.value)


def test_target_guard_refuses_a_custom_domain_it_cannot_verify(monkeypatch):
    """Domain lạ KHÔNG được suy ra ref — phải khai allowlist riêng."""
    from app.scripts.sync_dorm_students import assert_target_project_matches

    monkeypatch.setenv("DORM_SYNC_TARGET_PROJECT_REF", "ktx")

    with pytest.raises(ValueError):
        assert_target_project_matches("https://ktx.truong-cd.edu.vn")


def test_target_guard_skips_loopback(monkeypatch):
    """Supabase local không có project ref, và gói tin không rời khỏi máy."""
    from app.scripts.sync_dorm_students import assert_target_project_matches

    monkeypatch.delenv("DORM_SYNC_TARGET_PROJECT_REF", raising=False)

    assert assert_target_project_matches("http://127.0.0.1:54321") is None


def test_target_guard_requires_the_declaration(monkeypatch):
    """Thiếu khai báo là dừng — không đoán project từ URL."""
    from app.scripts.sync_dorm_students import assert_target_project_matches

    monkeypatch.delenv("DORM_SYNC_TARGET_PROJECT_REF", raising=False)

    with pytest.raises(SystemExit):
        assert_target_project_matches("https://ktx.supabase.co")


def test_secret_key_never_leaves_the_process_when_the_target_is_wrong(monkeypatch):
    """Kiểm NGƯỢC: đích sai thì khoá secret chưa vào bất kỳ cấu trúc nào.

    Thứ tự trong ``DormApi.__init__`` là có chủ đích — đường truyền, rồi đích,
    rồi mới tới headers. Nếu ai đó đảo lại, headers mang khoá đã được dựng xong
    trước khi biết nó đi tới đâu, và ca này bắt được điều đó.
    """
    monkeypatch.setenv("DORM_SYNC_TARGET_PROJECT_REF", "dung-project")

    with pytest.raises(ValueError):
        api = DormApi("https://sai-project.supabase.co", "khoa-that")
        assert not hasattr(api, "_headers")


async def test_wrong_target_stops_before_any_request(monkeypatch):
    """Đi hết ``main``: ref sai → thoát 2, không request nào được gửi."""
    _set_target_env(monkeypatch, target_ref="dung-project")
    monkeypatch.setenv("DORM_SUPABASE_URL", "https://sai-project.supabase.co")
    monkeypatch.setattr(sync_module, "_install_stop_handlers", lambda: None)

    async def _one_row(academic_year, **kwargs):
        return [_row()]

    monkeypatch.setattr(sync_module, "fetch_cohort", _one_row)

    assert await main(["--academic-year", "2026", "--apply"]) == 2


# ---------------------------------------------------------------------------
# Hàng rào trước khi ghi
# ---------------------------------------------------------------------------


_DEV_DB_URL = "postgresql+asyncpg://qlts:mat-khau@postgres:5432/qlts"
_PROD_DB_IDENTITY = "postgres:5432/qlts_production"


def _set_target_env(
    monkeypatch,
    *,
    source_db="postgres:5432/qlts",
    system_id="7000000000000000001",
    target_ref="ktx",
):
    monkeypatch.setenv("DORM_SUPABASE_URL", f"https://{target_ref}.supabase.co")
    monkeypatch.setenv("DORM_SUPABASE_SECRET_KEY", "khoa-gia")
    monkeypatch.setenv("DORM_SYNC_SOURCE_DB", source_db)
    monkeypatch.setenv("DORM_SYNC_SOURCE_SYSTEM_ID", system_id)
    monkeypatch.setenv("DORM_SYNC_TARGET_PROJECT_REF", target_ref)
    # Mặc định cho nguồn KHỚP khai báo, để các test về nhánh khác không phải
    # quan tâm tới hàng rào. Test nào cần ca lệch thì gọi `_patch_database_url`
    # sau lời gọi này để ghi đè.
    _patch_database_url(monkeypatch, f"postgresql+asyncpg://u:p@{source_db}")


def _patch_database_url(monkeypatch, url=_DEV_DB_URL):
    from app.config import settings

    monkeypatch.setattr(settings, "DATABASE_URL", url, raising=False)


@pytest.mark.parametrize(
    "url,mong_doi",
    [
        (_DEV_DB_URL, "postgres:5432/qlts"),
        # Không có cổng => mặc định 5432, không phải chuỗi rỗng.
        (
            "postgresql+asyncpg://u:p@db.internal/qlts_production",
            "db.internal:5432/qlts_production",
        ),
        # Mật khẩu chứa ký tự mã hoá URL và có query string: hai chỗ mọi parser
        # viết tay đều sai, mà sai ở đây nghĩa là hàng rào so nhầm.
        (
            "postgresql+asyncpg://u:p%40ss%3Aword@postgres:6543/qlts?ssl=require",
            "postgres:6543/qlts",
        ),
    ],
)
def test_database_identity_survives_real_url_shapes(url, mong_doi):
    assert database_identity_from_url(url) == mong_doi


def test_source_database_mismatch_is_refused(monkeypatch):
    """Đọc database này mà đích khai database khác = dừng.

    Đây là ca nguy hiểm nhất của công cụ: chạy stack DEV với file secret của KTX
    THẬT sẽ ghi đè danh sách thật rồi hạ cờ mọi người không có trong nguồn dev —
    và lượt đó vẫn kết thúc ``completed``, thoát 0.
    """
    _set_target_env(monkeypatch, source_db=_PROD_DB_IDENTITY)
    _patch_database_url(monkeypatch)  # thực tế đang đọc dev

    with pytest.raises(SystemExit) as exc:
        assert_source_database_matches()

    assert exc.value.code == 2


@pytest.mark.parametrize("thieu", ["DORM_SYNC_SOURCE_DB", "DORM_SYNC_SOURCE_SYSTEM_ID"])
def test_missing_source_declaration_is_refused(monkeypatch, thieu):
    """Thiếu khai báo nào cũng là dừng.

    ``SYSTEM_ID`` chỉ dùng ở lớp ba (hỏi thẳng database), nhưng phải đòi ngay từ
    đây: cho chạy tiếp khi thiếu nó nghĩa là lớp mạnh nhất im lặng không chạy,
    và không có gì trên màn hình nói điều đó.
    """
    _set_target_env(monkeypatch)
    _patch_database_url(monkeypatch)
    monkeypatch.delenv(thieu)

    with pytest.raises(SystemExit):
        assert_source_database_matches()


def test_matching_source_database_passes(monkeypatch):
    _set_target_env(monkeypatch, source_db="postgres:5432/qlts")
    _patch_database_url(monkeypatch)

    assert assert_source_database_matches() is None


class _FakeSession:
    """Session giả trả lời hai câu hỏi định danh, hoặc ném ở câu thứ hai."""

    def __init__(
        self, *, dbname="qlts", system_id="7000000000000000001", no_catalog=False
    ):
        self._dbname = dbname
        self._system_id = system_id
        self._no_catalog = no_catalog
        self.executed = []

    async def execute(self, stmt):
        sql = str(stmt)
        self.executed.append(sql)

        class _Result:
            def __init__(self, value):
                self._value = value

            def scalar(self):
                return self._value

            def all(self):
                return []

        if "current_database" in sql:
            return _Result(self._dbname)
        if "pg_control_system" in sql:
            if self._no_catalog:
                raise RuntimeError("permission denied for function pg_control_system")
            return _Result(self._system_id)
        return _Result(None)


async def test_live_source_accepts_the_declared_cluster(monkeypatch):
    from app.scripts.sync_dorm_students import assert_live_source_matches

    _set_target_env(monkeypatch, source_db="postgres:5432/qlts")

    assert await assert_live_source_matches(_FakeSession()) is None


async def test_live_source_refuses_a_different_database_name(monkeypatch):
    """Tên trong URL có thể bị pooler viết lại — hỏi thẳng mới biết thật."""
    from app.scripts.sync_dorm_students import assert_live_source_matches

    _set_target_env(monkeypatch, source_db=_PROD_DB_IDENTITY)

    with pytest.raises(SystemExit) as exc:
        await assert_live_source_matches(_FakeSession(dbname="qlts"))

    assert exc.value.code == 2


async def test_live_source_refuses_a_clone_with_the_same_name(monkeypatch):
    """Ca mà hai lớp đầu KHÔNG bắt được: bản sao mang đúng tên database.

    Recipe kéo prod về dev giữ nguyên tên, nên ``current_database()`` khớp.
    ``system_identifier`` sinh lúc ``initdb`` và không đổi qua restore logic —
    đây là thứ duy nhất phân biệt được hệ thật với bản sao của nó.
    """
    from app.scripts.sync_dorm_students import assert_live_source_matches

    _set_target_env(
        monkeypatch, source_db="postgres:5432/qlts", system_id="7000000000000000001"
    )

    with pytest.raises(SystemExit) as exc:
        await assert_live_source_matches(
            _FakeSession(dbname="qlts", system_id="7999999999999999999")
        )

    assert exc.value.code == 2


async def test_live_source_stops_when_the_cluster_id_cannot_be_read(monkeypatch):
    """Không đọc được ``system_identifier`` là DỪNG, không phải bỏ qua.

    Một hàng rào tự tắt khi gặp trở ngại thì không phải hàng rào — và ca "thiếu
    quyền đọc catalog" trùng đúng với ca "đây không phải cluster ta nghĩ".
    """
    from app.scripts.sync_dorm_students import assert_live_source_matches

    _set_target_env(monkeypatch, source_db="postgres:5432/qlts")

    with pytest.raises(SystemExit) as exc:
        await assert_live_source_matches(_FakeSession(no_catalog=True))

    assert exc.value.code == 2


async def test_dry_run_does_not_verify_the_live_source(monkeypatch):
    """Xem trước chỉ-đọc KHÔNG chạm hai lớp hỏi database.

    Bắt một lần xem trước phải khai đủ cấu hình nguồn chỉ khiến người ta bỏ qua
    bước xem trước — mà đó chính là bước chặn được lần ghi sai.
    """
    session = _FakeSession()
    goi = []

    async def _theo_doi(s):
        goi.append(s)

    monkeypatch.setattr(sync_module, "assert_live_source_matches", _theo_doi)

    class _CM:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(sync_module, "AsyncSessionLocal", lambda: _CM())
    monkeypatch.setattr(
        sync_module, "select_paid_hk1_cohort", lambda year: "SELECT-GIA"
    )

    await sync_module.fetch_cohort(2026, verify_source=False)
    assert goi == []

    await sync_module.fetch_cohort(2026, verify_source=True)
    assert len(goi) == 1


async def test_read_only_transaction_is_opened_before_reading(monkeypatch):
    """``SET TRANSACTION READ ONLY`` chống lưng cho tuyên bố "MỘT CHIỀU, CHỈ ĐỌC".

    Không có nó thì một lỗi lập trình làm lọt câu ghi sẽ sửa thẳng dữ liệu tuyển
    sinh, và không lớp nào phía dưới chặn lại.
    """
    session = _FakeSession()

    class _CM:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(sync_module, "AsyncSessionLocal", lambda: _CM())
    monkeypatch.setattr(
        sync_module, "select_paid_hk1_cohort", lambda year: "SELECT-GIA"
    )

    await sync_module.fetch_cohort(2026)

    assert "SET TRANSACTION READ ONLY" in session.executed[0]


def test_source_guard_compares_database_not_app_env(monkeypatch):
    """Kiểm NGƯỢC: ``APP_ENV`` không còn ảnh hưởng gì tới hàng rào.

    Bản trước so ``APP_ENV`` với một nhãn khai trong file secret — mà chính file
    secret đó được nạp bằng ``--env-from-file`` nên nó mang được luôn
    ``APP_ENV``. Hàng rào khi ấy so hai giá trị đến từ cùng một file.

    Ca dưới đây dựng đúng cái bẫy đó: nhãn nói 'production' ở cả hai đầu, nhưng
    database thật là dev. Hàng rào cũ cho qua; hàng rào mới phải chặn.
    """
    _set_target_env(monkeypatch, source_db=_PROD_DB_IDENTITY)
    _patch_database_url(monkeypatch)  # dev
    monkeypatch.setenv("APP_ENV", "production")

    with pytest.raises(SystemExit):
        assert_source_database_matches()

    # Và chiều ngược lại: database khớp thì ``APP_ENV`` lệch cũng không chặn,
    # vì nhãn không phải thứ quyết định script đọc dữ liệu ở đâu.
    _set_target_env(monkeypatch, source_db="postgres:5432/qlts")
    monkeypatch.setenv("APP_ENV", "development")

    assert assert_source_database_matches() is None


async def test_apply_refuses_an_empty_cohort(monkeypatch):
    """Nguồn RỖNG + ``--apply`` = hạ cờ TOÀN BỘ năm học — phải dừng trước khi ghi.

    Mọi hàng rào phía database đều lọt vì các con số đều bằng 0 và khớp nhau:
    lượt kết thúc ``completed``, thoát 0, nhìn y hệt một lần chạy thành công.
    Cùng kiểu hỏng với ``--batch-size 0``, chỉ khác đường vào (gõ nhầm năm, năm
    chưa mở, vị từ cohort phía QLTS đổi).
    """
    _set_target_env(monkeypatch)
    monkeypatch.setattr(sync_module, "_install_stop_handlers", lambda: None)

    async def _empty_cohort(academic_year, **kwargs):
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

    async def _empty_cohort(academic_year, **kwargs):
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

    async def _one_row(academic_year, **kwargs):
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

    async def _empty_cohort(academic_year, **kwargs):
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

    async def _one_row(academic_year, **kwargs):
        return [_row()]

    monkeypatch.setattr(sync_module, "fetch_cohort", _one_row)

    assert await main(["--academic-year", "2026", "--apply"]) == 2


async def test_dry_run_never_needs_the_source_declaration(monkeypatch):
    """Xem trước chỉ-đọc không đòi khai báo cấu hình nguồn.

    Bắt nó khai báo chỉ khiến người ta bỏ qua bước xem trước — và bước xem
    trước chính là thứ chặn được lần ghi sai.
    """
    monkeypatch.setenv("DORM_SUPABASE_URL", "https://ktx.supabase.co")
    monkeypatch.setenv("DORM_SUPABASE_SECRET_KEY", "khoa-gia")
    monkeypatch.setenv("DORM_SYNC_TARGET_PROJECT_REF", "ktx")
    monkeypatch.delenv("DORM_SYNC_SOURCE_DB", raising=False)
    monkeypatch.delenv("DORM_SYNC_SOURCE_SYSTEM_ID", raising=False)

    class _FakeApi:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def count_students(self, academic_year):
            return 0

    async def _empty_cohort(academic_year, **kwargs):
        return []

    monkeypatch.setattr(sync_module, "fetch_cohort", _empty_cohort)
    monkeypatch.setattr(sync_module, "DormApi", _FakeApi)

    assert await main(["--academic-year", "2026"]) == 0
