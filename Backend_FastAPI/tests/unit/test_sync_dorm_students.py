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
        degree_level="Cao đẳng",
        academic_year=2026,
        officer_qlts_id=101,
        unit_id=14,
        profile_status="confirmed",
        contact_phone="0912345678",
        contact_phone2=None,
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


def test_payload_carries_degree_level():
    """Trình độ đi CÙNG tên ngành, không tách.

    Cùng một tên ngành tồn tại ở hai bậc, nên thiếu cột này thì phía KTX gộp
    hai chương trình khác nhau thành một dòng thống kê — và dòng đó trông hoàn
    toàn bình thường.
    """
    payload = build_student_payload(
        _row(program_name="Công nghệ ô tô", degree_level="Trung cấp"), sync_run_id=1
    )

    assert payload["program_name"] == "Công nghệ ô tô"
    assert payload["degree_level"] == "Trung cấp"


def test_payload_keeps_null_degree_level():
    """Ngành thiếu trình độ vẫn đi qua, ô để trống chứ không đoán."""
    payload = build_student_payload(_row(degree_level=None), sync_run_id=1)

    assert "degree_level" in payload
    assert payload["degree_level"] is None


def test_payload_survives_a_row_without_the_degree_level_column():
    """Hàng nguồn THIẾU HẲN thuộc tính vẫn gửi được, giá trị NULL.

    ⚠️ Ca này có thật: chạy bản script mới trên một nhánh backend chưa có cột
    thì ``row`` không có thuộc tính đó. Nổ ở đây là nổ GIỮA một lượt ghi đã mở
    — trạng thái tệ hơn nhiều so với một cột để trống.
    """
    row = _row()
    del row.degree_level

    payload = build_student_payload(row, sync_run_id=1)

    assert payload["degree_level"] is None


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


def test_phone_longer_than_the_column_is_dropped_not_truncated():
    """Số vượt trần thì BỎ, không cắt.

    Cột đích có ``check (length <= 20)`` nên một giá trị bẩn làm PostgREST trả
    400 và hỏng CẢ LÔ 200 hàng, không phải một hàng. Còn cắt thì dựng ra một số
    khác gọi được — tức người liên hệ sai, và không ai biết.
    """
    from app.scripts.sync_dorm_students import chuan_hoa_so

    assert chuan_hoa_so("0912345678") == "0912345678"
    assert chuan_hoa_so("  0912345678  ") == "0912345678"
    assert chuan_hoa_so("0" * 20) == "0" * 20  # đúng trần vẫn qua
    assert chuan_hoa_so("0" * 21) is None
    assert chuan_hoa_so("   ") is None
    assert chuan_hoa_so("") is None
    assert chuan_hoa_so(None) is None


def test_payload_carries_both_contact_numbers():
    payload = build_student_payload(
        _row(contact_phone="0912345678", contact_phone2="0987654321"), sync_run_id=1
    )

    assert payload["contact_phone"] == "0912345678"
    assert payload["contact_phone2"] == "0987654321"


def test_payload_drops_a_duplicate_second_number():
    """Hai ô hiện cùng một số thì ô thứ hai không nói thêm gì.

    Tệ hơn: nó khiến người gọi thử lại đúng số vừa không nghe máy.
    """
    payload = build_student_payload(
        _row(contact_phone="0912345678", contact_phone2="  0912345678 "),
        sync_run_id=1,
    )

    assert payload["contact_phone"] == "0912345678"
    assert payload["contact_phone2"] is None


def test_payload_keeps_contact_keys_even_when_empty():
    """Thiếu số vẫn phải GỬI khoá với giá trị ``None``.

    PostgREST merge-duplicates chỉ cập nhật cột được gửi. Bỏ khoá đi thì một số
    cũ đã sai ở hệ KTX sẽ nằm lại mãi, dù bên QLTS đã xoá.
    """
    payload = build_student_payload(_row(contact_phone=None), sync_run_id=1)

    assert "contact_phone" in payload
    assert "contact_phone2" in payload
    assert payload["contact_phone"] is None


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
        self.calls.append(
            {"method": "GET", "url": url, "params": params, "headers": headers}
        )
        return self._response

    async def post(self, url, headers=None, params=None, json=None):
        self.calls.append(
            {"method": "POST", "url": url, "json": json, "headers": headers}
        )
        if self._post_error is not None:
            raise self._post_error
        return (
            self._post_response if self._post_response is not None else self._response
        )


class _ClientLocTheoParams(_RecordingClient):
    """Fake LỌC theo ``params`` thật, thay vì trả sẵn kết quả đã mô phỏng.

    ⚠️ Đây là khác biệt giữa một test chứng minh được điều gì và một test
    không. ``_RecordingClient`` trả cùng một ``_FakeResponse`` bất kể params,
    nên khi test dựng sẵn ``payload=[]`` kèm chú thích "server đã lọc status",
    chính nó đã mô phỏng luôn cái đang cần chứng minh: bỏ hẳn
    ``status=eq.running`` khỏi client thì fake vẫn trả rỗng, và test vẫn xanh.

    Fake này giữ một tập hàng và tự áp bộ lọc, nên câu hỏi "client có gửi đúng
    bộ lọc không" mới có chỗ để trả lời sai.
    """

    def __init__(self, hang, *, post_response=None, post_error=None):
        super().__init__(post_response=post_response, post_error=post_error)
        self._hang = hang

    async def get(self, url, headers=None, params=None):
        self.calls.append(
            {"method": "GET", "url": url, "params": params, "headers": headers}
        )
        khop = [h for h in self._hang if self._khop(h, params or {})]
        return _FakeResponse(payload=khop)

    @staticmethod
    def _khop(hang, params) -> bool:
        for khoa, gia in params.items():
            # Không phải bộ lọc — chúng chỉ định hình dạng phản hồi.
            if khoa in {"select", "limit", "order", "offset"}:
                continue
            if not isinstance(gia, str):
                continue
            if gia.startswith("eq."):
                if str(hang.get(khoa)) != gia[3:]:
                    return False
            elif gia == "is.null":
                if hang.get(khoa) is not None:
                    return False
        return True


def _api_with(client) -> DormApi:
    # Loopback: các test dưới đây không đi ra mạng (client là đồ giả), và
    # loopback được miễn CẢ hàng rào đường truyền lẫn hàng rào project ref —
    # Supabase local không có ref. Dùng một hostname bịa như `ktx.test` sẽ vướng
    # hàng rào đích, và vướng vì đúng lý do nó tồn tại.
    api = DormApi("http://127.0.0.1:54321", "khoa-gia")
    api._client = client
    return api


async def test_mark_failed_goes_through_the_rpc_without_source_count():
    """Đóng sổ lượt hỏng đi qua RPC, và KHÔNG gửi ``source_count``.

    Contract mới ràng ``failed ⇒ source_count IS NULL`` ở tầng database. Một
    PATCH mang theo con số đó sẽ vướng CHECK, và khi ấy MỌI lỗi sau lúc mở lượt
    đều để lại một lượt treo ``running`` — thứ khoá cứng năm học bằng
    ``uq_sync_run_active_per_year``. Đây là chế độ hỏng tệ hơn hẳn cái nó thay.
    """
    client = _RecordingClient(
        _FakeResponse(payload=[{"id": 5, "status": "failed", "upserted_count": 7}])
    )

    run = await _api_with(client).mark_sync_run_failed(5)

    assert run["status"] == "failed"
    goi = client.calls[0]
    assert goi["url"].endswith("/rpc/fail_sync_run")
    assert goi["json"] == {"p_run_id": 5}


async def test_reconcile_trusts_the_status_the_rpc_returns():
    """Lượt vừa `completed` xong giữa chừng KHÔNG được ghi thành thất bại.

    RPC có nhánh trả nguyên hàng mà không đổi gì. Nếu người gọi chỉ nhìn việc
    lời gọi không ném, một lượt đã hạ cờ xong sẽ bị ghi sổ là "đã đánh dấu thất
    bại" — đúng ở ca dễ xảy ra nhất, mất ACK sau khi commit.
    """

    class _DoiTrangThai(_RecordingClient):
        async def get(self, url, headers=None, params=None):
            self.calls.append({"method": "GET", "url": url, "params": params})
            return _FakeResponse(payload=[{"id": 9, "status": "running"}])

        async def post(self, url, headers=None, params=None, json=None):
            self.calls.append({"method": "POST", "url": url, "json": json})
            return _FakeResponse(payload=[{"id": 9, "status": "completed"}])

    outcome, run = await _api_with(_DoiTrangThai()).reconcile_after_failure(9)

    assert outcome == "finalized"
    assert run["status"] == "completed"


@pytest.mark.parametrize(
    "body",
    [
        [],  # mảng rỗng
        [{"upserted": 1, "blocked": 0}, {"upserted": 2, "blocked": 0}],  # hai hàng
        [{"upserted": "3", "blocked": 0}],  # chuỗi số
        [{"upserted": True, "blocked": 0}],  # bool là lớp con của int
        [{"upserted": 2.9, "blocked": 0}],  # số thực bị cắt
        [{"upserted": -1, "blocked": 0}],  # âm
        [{"upserted": 1}],  # thiếu khoá
        ["không phải object"],
        {"upserted": 1, "blocked": 0},  # không phải mảng
    ],
)
def test_batch_counts_are_read_fail_closed(body):
    """Số liệu lô đọc sai kiểu là DỪNG, không đoán.

    Hai con số này quyết định phép kiểm ``raw = source + blocked`` ở bước hạ
    cờ. ``int(...)`` trần nhận cả ``True``, chuỗi ``"3"`` và ``2.9`` — cả ba
    đều nghĩa là hai đầu đang hiểu nhau khác đi, và nhận bừa ở đây là hạ cờ
    theo một con số sai.
    """
    from app.scripts.sync_dorm_students import _doc_so_lieu_lo

    with pytest.raises(RuntimeError):
        _doc_so_lieu_lo(body)


def test_batch_counts_accept_the_valid_shape():
    from app.scripts.sync_dorm_students import _doc_so_lieu_lo

    assert _doc_so_lieu_lo([{"upserted": 198, "blocked": 2}]) == (198, 2)


def test_close_response_accepts_the_shape_postgrest_really_returns():
    """`returns public.sync_runs` là composite SCALAR → PostgREST trả OBJECT ĐƠN.

    Đo trên PostgREST thật. Bản trước đòi mảng đúng một phần tử, nên MỌI lần
    đóng sổ thành công đều ném ngay rồi rơi xuống nhánh xử lý lỗi — vẫn ra kết
    quả đúng nhờ lần đối soát thứ hai, nhưng đường chính hỏng hoàn toàn và
    không có gì nói ra điều đó.

    Mảng một phần tử vẫn nhận, phòng khi ai đó đổi sang `returns setof` hoặc
    bật `Accept: application/vnd.pgrst.object`.
    """
    from app.scripts.sync_dorm_students import _doc_hang_sync_run

    doi_tuong = {"id": 9, "status": "failed", "upserted_count": 3}
    assert _doc_hang_sync_run(doi_tuong, 9) == doi_tuong
    assert _doc_hang_sync_run([doi_tuong], 9) == doi_tuong


@pytest.mark.parametrize(
    "body",
    [
        {"id": 999, "status": "failed"},  # hàng của lượt KHÁC
        {"id": 9, "status": "running"},  # chưa đóng mà nhận là đã đóng
        [{"id": 9, "status": "failed"}, {"id": 10, "status": "failed"}],  # hai hàng
        {"status": "failed"},  # thiếu id
        {"id": True, "status": "failed"},  # bool không phải id
        {},
        [],
        "không phải object",
    ],
)
def test_close_response_is_read_fail_closed(body):
    """Phản hồi đóng sổ phải mang ĐÚNG lượt và ĐÚNG trạng thái đã đóng.

    Nhận bừa một hàng của lượt khác thì kết luận "lượt này đã đóng" nói về một
    lượt không phải nó, còn lượt thật vẫn treo ``running`` và khoá năm học.
    Nhận một hàng còn ``running`` làm bằng chứng đã đóng sổ là tự tuyên bố xong
    việc chưa làm.
    """
    from app.scripts.sync_dorm_students import _doc_hang_sync_run

    with pytest.raises(RuntimeError):
        _doc_hang_sync_run(body, 9)


@pytest.mark.parametrize(
    "trang_thai_lan_hai,mong_doi",
    [
        # POST đã tới nơi và commit, chỉ phản hồi không về.
        ("failed", "marked_failed"),
        # Lượt đã HOÀN TẤT trước đó — mất ACK sau khi hạ cờ xong. Báo thất bại
        # ở đây là ghi sai sổ theo chiều ngược hẳn: dữ liệu ĐÃ đổi.
        ("completed", "finalized"),
        # POST chưa tới database. Lượt vẫn khoá năm học, và người vận hành cần
        # biết điều đó thay vì tin là đã đóng sổ.
        ("running", "unknown"),
    ],
)
async def test_reconcile_probes_again_when_closing_is_ambiguous(
    trang_thai_lan_hai, mong_doi
):
    """Mất ACK ở BƯỚC ĐÓNG SỔ cũng phải đối soát lại, và phân loại đúng cả ba.

    Mất kết nối, 408, 5xx — cả ba đều có thể xảy ra SAU khi database đã commit.
    Trả "không xác định" ngay là bỏ mất chính cơ chế đối soát mà bước MỞ lượt đã
    có. Ba trạng thái đọc được ở lần hai dẫn tới ba kết luận khác nhau, và hai
    trong số đó là báo thành công / báo thất bại ngược hẳn nhau.
    """

    class _MatAckKhiDong(_RecordingClient):
        def __init__(self):
            super().__init__()
            self.lan_get = 0

        async def get(self, url, headers=None, params=None):
            self.lan_get += 1
            self.calls.append({"method": "GET", "url": url, "params": params})
            trang_thai = "running" if self.lan_get == 1 else trang_thai_lan_hai
            return _FakeResponse(payload=[{"id": 9, "status": trang_thai}])

        async def post(self, url, headers=None, params=None, json=None):
            self.calls.append({"method": "POST", "url": url, "json": json})
            raise httpx.ConnectError("mất kết nối")

    client = _MatAckKhiDong()
    outcome, _ = await _api_with(client).reconcile_after_failure(9)

    assert outcome == mong_doi
    # Đúng ba lời gọi: đọc → thử đóng → đọc lại. Thiếu lời gọi cuối là quay về
    # đúng lỗi vừa vá.
    assert [c["method"] for c in client.calls] == ["GET", "POST", "GET"]


async def test_get_sync_run_returns_none_for_a_strange_body():
    """``[{}]`` không được ném ``KeyError`` giữa nhánh xử lý lỗi.

    Mọi lời gọi ở nhánh đó chạy vì có gì đó đã hỏng sẵn; ném thêm một exception
    lạ ở đây là biến một lượt cần đối soát thành traceback.
    """
    than_la = [
        [{}],
        [],
        [{"id": 999, "status": "failed"}],  # hàng của lượt khác
        ["lạ"],
        {"id": 9},  # không phải mảng
        [{"id": 9, "status": "dang_nghi"}],  # trạng thái ngoài state machine
        # Hai hàng MÂU THUẪN. Lọc là `id=eq.<run_id>` trên khoá chính nên điều
        # này không thể xảy ra khi mọi thứ bình thường — và chính vì thế, lấy
        # `rows[0]` ở đây là bỏ qua đúng lúc phải dừng. Đã tái hiện: nhánh phục
        # hồi nhận hàng đầu và tuyên bố lượt đã xong.
        [{"id": 9, "status": "completed"}, {"id": 9, "status": "running"}],
    ]
    for than in than_la:
        client = _RecordingClient(_FakeResponse(payload=than))
        assert await _api_with(client).get_sync_run(9) is None


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

    outcome, run = await _api_with(client).reconcile_after_failure(5)

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

    run_id = await _api_with(client).open_sync_run(2026, "abc123", raw_count=1)

    assert run_id == 88
    # Tìm lại phải theo ĐÚNG dấu của lần chạy này, không phải "lượt running bất kỳ".
    assert client.calls[1]["params"]["note"] == "eq.client:abc123"


async def test_open_run_recovers_from_an_unreadable_body():
    """2xx nhưng thân không đọc được (proxy cắt, JSON hỏng) — hàng vẫn đã tạo."""
    client = _RecordingClient(
        _FakeResponse(payload=[{"id": 91, "status": "running"}]),
        post_response=_FakeResponse(status_code=201, payload=[]),
    )

    assert await _api_with(client).open_sync_run(2026, "tok", raw_count=1) == 91


async def test_open_run_says_plainly_when_nothing_was_created():
    """Không tìm thấy dấu nào = database chưa nhận gì. Nói rõ để người ta chạy lại."""
    client = _RecordingClient(
        _FakeResponse(payload=[]), post_error=httpx.ConnectError("mất kết nối")
    )

    with pytest.raises(RuntimeError) as exc:
        await _api_with(client).open_sync_run(2026, "tok", raw_count=1)

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

    assert await _api_with(client).open_sync_run(2026, "tok", raw_count=1) == 77
    assert [c["method"] for c in client.calls] == ["POST", "GET"]


@pytest.mark.parametrize("ma_loi", [400, 401, 403])
async def test_open_run_trusts_definitive_client_errors(ma_loi):
    """400/401/403 là câu trả lời DỨT KHOÁT — không có hàng nào để đối soát."""
    client = _RecordingClient(
        _FakeResponse(payload=[]),
        post_response=_FakeResponse(status_code=ma_loi, payload=[]),
    )

    with pytest.raises(RuntimeError):
        await _api_with(client).open_sync_run(2026, "tok", raw_count=1)

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
        await _api_with(client).open_sync_run(2026, "tok", raw_count=1)

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

    assert await _api_with(client).open_sync_run(2026, "tok", raw_count=1) == 55


async def test_open_run_refuses_a_conflict_it_does_not_own():
    """409 mà không mang dấu mình = lượt của tiến trình khác. Không được đụng."""
    client = _RecordingClient(
        _FakeResponse(payload=[]),
        post_response=_FakeResponse(status_code=409, payload=[]),
    )

    with pytest.raises(RuntimeError) as exc:
        await _api_with(client).open_sync_run(2026, "tok", raw_count=1)

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

    ⚠️ Fake ở đây LỌC theo params thật. Bản trước dựng sẵn ``payload=[]`` kèm
    chú thích "server đã lọc status" — tức nó tự mô phỏng luôn điều cần chứng
    minh, và gỡ hẳn ``status=eq.running`` khỏi client cũng không làm nó đỏ.
    """
    client = _ClientLocTheoParams(
        [
            # Hàng LỊCH SỬ: đúng dấu, đúng năm, nhưng đã `failed`. Chỉ bộ lọc
            # `status=eq.running` mới loại nó ra.
            {
                "id": 41,
                "academic_year": 2026,
                "note": "client:tok",
                "status": "failed",
            }
        ],
        post_response=_FakeResponse(status_code=502, payload=[]),
    )

    with pytest.raises(RuntimeError) as exc:
        await _api_with(client).open_sync_run(2026, "tok", raw_count=1)

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
        await _api_with(client).open_sync_run(2026, "tok", raw_count=1)

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


async def test_open_run_stamps_the_client_token_in_the_insert():
    """Dấu phải nằm NGAY trong câu INSERT, không phải ghi bổ sung sau đó.

    Ghi sau là để lại đúng khoảng trống mà cơ chế này sinh ra để bịt: hàng tạo
    xong, chưa kịp đóng dấu, phản hồi mất — không nhận lại được nữa.

    ⚠️ Bản trước chỉ assert ``_client_note("abc") == "client:abc"``, tức nó
    kiểm một hàm thuần và KHÔNG chạm tới câu INSERT. Gỡ hẳn ``note`` khỏi
    payload thì nó vẫn xanh — đúng thứ nó khai là đang canh.
    """
    client = _RecordingClient(
        post_response=_FakeResponse(status_code=201, payload=[{"id": 7}])
    )

    assert await _api_with(client).open_sync_run(2026, "abc", raw_count=5) == 7

    insert = client.calls[0]
    assert insert["method"] == "POST"
    assert insert["url"].endswith("/sync_runs")
    assert insert["json"]["note"] == "client:abc"
    # `raw_count` cũng phải nằm ngay trong INSERT: một lượt hỏng giữa chừng vẫn
    # phải trả lời được "nguồn có bao nhiêu".
    assert insert["json"]["raw_count"] == 5


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

    # ⚠️ KHÔNG đặt assert bên trong `pytest.raises`: dòng phía trên đã ném, nên
    # mọi câu sau nó trong cùng block KHÔNG BAO GIỜ CHẠY và test xanh mà chẳng
    # kiểm gì. Dựng object rỗng rồi gọi `__init__` tường minh để còn cầm được
    # tham chiếu mà soi sau khi exception đã bay ra.
    api = object.__new__(DormApi)

    with pytest.raises(ValueError):
        DormApi.__init__(api, "https://sai-project.supabase.co", "khoa-that")

    assert not hasattr(api, "_headers")
    assert not hasattr(api, "_base")


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


def test_database_name_comparison_is_case_sensitive(monkeypatch):
    """``QLTS`` và ``qlts`` là HAI database khác nhau.

    PostgreSQL cho phép ``CREATE DATABASE "QLTS"`` tồn tại song song với
    ``qlts`` trong cùng cluster. Hạ tên về chữ thường khiến cả ba lớp hàng rào
    cho qua trong khi đang đọc đúng cái database khác — tức hàng rào im lặng
    hỏng ở chính ca nó sinh ra để chặn.
    """
    _set_target_env(monkeypatch, source_db="postgres:5432/QLTS")
    _patch_database_url(monkeypatch, "postgresql+asyncpg://u:p@postgres:5432/qlts")

    with pytest.raises(SystemExit) as exc:
        assert_source_database_matches()

    assert exc.value.code == 2


def test_hostname_comparison_stays_case_insensitive(monkeypatch):
    """Ngược lại, hostname KHÔNG phân biệt hoa/thường theo DNS.

    Siết cả hostname sẽ chặn oan một cấu hình hoàn toàn hợp lệ.
    """
    _set_target_env(monkeypatch, source_db="POSTGRES:5432/qlts")
    _patch_database_url(monkeypatch, "postgresql+asyncpg://u:p@postgres:5432/qlts")

    assert assert_source_database_matches() is None


async def test_live_source_name_comparison_is_case_sensitive(monkeypatch):
    """Lớp hỏi thẳng database cũng phải phân biệt hoa/thường."""
    from app.scripts.sync_dorm_students import assert_live_source_matches

    _set_target_env(monkeypatch, source_db="postgres:5432/QLTS")

    with pytest.raises(SystemExit) as exc:
        await assert_live_source_matches(_FakeSession(dbname="qlts"))

    assert exc.value.code == 2


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

        async def open_sync_run(
            self, academic_year, client_token, raw_count, *, la_lan_chay_lai=False
        ):
            return 77

        async def upsert_students(self, run_id, rows):
            raise KeyboardInterrupt

        async def finalize_sync_run(self, run_id, source_count, upserted_count):
            # ⚠️ KHÔNG raise ở đây: `main` bắt `BaseException`, nên một
            # `AssertionError` sẽ bị nuốt và test xanh dù hạ cờ ĐÃ chạy. Ghi
            # nhận rồi khẳng định ở ngoài — cùng lý do với ca dừng bên dưới.
            da_doi_soat["đã_hạ_cờ"] = True
            return 0

        async def reconcile_after_failure(self, run_id):
            da_doi_soat["run_id"] = run_id
            return "marked_failed", {"id": run_id, "status": "failed"}

    async def _one_row(academic_year, **kwargs):
        return [_row()]

    monkeypatch.setattr(sync_module, "fetch_cohort", _one_row)
    monkeypatch.setattr(sync_module, "DormApi", _FakeApi)

    assert await main(["--academic-year", "2026", "--apply"]) == 1
    assert da_doi_soat["run_id"] == 77
    # Bất biến CHÍNH của ca này: Ctrl-C giữa lúc ghi thì TUYỆT ĐỐI không được
    # hạ cờ. Trước đây `_FakeApi` không có `finalize_sync_run`, nên nếu code
    # hồi quy và gọi nó thì `AttributeError` bị `except BaseException` nuốt —
    # test vẫn xanh trong khi bất biến đã vỡ.
    assert "đã_hạ_cờ" not in da_doi_soat


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

        async def open_sync_run(
            self, academic_year, client_token, raw_count, *, la_lan_chay_lai=False
        ):
            return 91

        async def finalize_sync_run(self, run_id, source_count, upserted_count):
            # ⚠️ KHÔNG raise ở đây: `main` bắt `BaseException`, nên một
            # `AssertionError` sẽ bị nuốt và test xanh dù hạ cờ ĐÃ chạy. Phải
            # ghi nhận rồi khẳng định ở ngoài.
            da_doi_soat["đã_hạ_cờ"] = True
            return 0

        async def reconcile_after_failure(self, run_id):
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


class _ApiGhiNhan:
    """API giả ghi lại số liệu đưa vào bước đóng sổ."""

    def __init__(self, so_bi_chan=0):
        self._so_bi_chan = so_bi_chan
        self.finalize_args = None
        self.lo_da_gui = []

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def open_sync_run(
        self, academic_year, client_token, raw_count, *, la_lan_chay_lai=False
    ):
        self.raw_count = raw_count
        # Ghi lại để test resume quan sát được: `main` phải truyền True đúng khi
        # người vận hành tự đưa `--client-token`.
        self.la_lan_chay_lai = la_lan_chay_lai
        return 42

    async def upsert_students(self, run_id, rows):
        self.lo_da_gui.append(rows)
        # Chặn ở lô ĐẦU cho tới hết hạn mức, phần còn lại ghi bình thường.
        chan = min(self._so_bi_chan, len(rows))
        self._so_bi_chan -= chan
        return len(rows) - chan, chan

    async def finalize_sync_run(self, run_id, source_count, upserted_count):
        self.finalize_args = (source_count, upserted_count)
        return 0


async def test_finalize_receives_effective_not_raw(monkeypatch):
    """Có hàng bị chặn thì ``source_count`` phải là EFFECTIVE, không phải nguồn.

    Truyền số nguồn vào đây khi có dù chỉ một hàng bị chặn sẽ làm guard "chưa
    ghi hết nguồn" phía database từ chối hạ cờ — và thông điệp lúc đó nói về
    một sự cố không có thật, nên người vận hành sẽ đi tìm lỗi ở chỗ khác.
    """
    _set_target_env(monkeypatch)
    monkeypatch.setattr(sync_module, "_install_stop_handlers", lambda: None)
    api = _ApiGhiNhan(so_bi_chan=1)

    async def _ba_hang(academic_year, **kwargs):
        return [_row(qlts_profile_id=i) for i in (1, 2, 3)]

    monkeypatch.setattr(sync_module, "fetch_cohort", _ba_hang)
    monkeypatch.setattr(sync_module, "DormApi", api)

    assert await main(["--academic-year", "2026", "--apply"]) == 0

    # raw = 3, blocked = 1 → effective = 2, và hai tham số phải BẰNG NHAU.
    assert api.raw_count == 3
    assert api.finalize_args == (2, 2)


async def test_batch_mismatch_stops_before_the_destructive_step(monkeypatch):
    """RPC bỏ sót hàng trong im lặng thì DỪNG, không đi tiếp tới bước hạ cờ."""
    _set_target_env(monkeypatch)
    monkeypatch.setattr(sync_module, "_install_stop_handlers", lambda: None)

    class _ApiThieu(_ApiGhiNhan):
        async def upsert_students(self, run_id, rows):
            # Báo ghi ít hơn số gửi, và KHÔNG khai phần thiếu là bị chặn.
            return len(rows) - 1, 0

        async def reconcile_after_failure(self, run_id):
            return "marked_failed", {"id": run_id, "status": "failed"}

    api = _ApiThieu()

    async def _hai_hang(academic_year, **kwargs):
        return [_row(qlts_profile_id=i) for i in (1, 2)]

    monkeypatch.setattr(sync_module, "fetch_cohort", _hai_hang)
    monkeypatch.setattr(sync_module, "DormApi", api)

    assert await main(["--academic-year", "2026", "--apply"]) == 1
    assert api.finalize_args is None  # chưa từng tới bước hạ cờ


async def test_raw_count_is_stamped_when_the_run_opens(monkeypatch):
    """``raw_count`` ghi lúc MỞ lượt, không đợi lúc đóng.

    Để trống tới bước cuối nghĩa là đúng những lượt cần đối soát nhất — lượt
    hỏng giữa chừng — lại là những lượt không có con số đó.
    """
    _set_target_env(monkeypatch)
    monkeypatch.setattr(sync_module, "_install_stop_handlers", lambda: None)
    api = _ApiGhiNhan()

    async def _bon_hang(academic_year, **kwargs):
        return [_row(qlts_profile_id=i) for i in range(4)]

    monkeypatch.setattr(sync_module, "fetch_cohort", _bon_hang)
    monkeypatch.setattr(sync_module, "DormApi", api)

    await main(["--academic-year", "2026", "--apply"])

    assert api.raw_count == 4


async def test_preview_counts_follow_the_contract(monkeypatch, capsys):
    """Ba con số liên hệ ở bước XEM TRƯỚC phải nói đúng điều chúng nhận.

    Hai ca dễ sai và đã sai một lần:

    * "Không có số" phải nghĩa là KHÔNG CÓ SỐ NÀO. Chỉ đếm ô chính sẽ báo nhầm
      những em chỉ khai số phụ là không liên hệ được, trong khi họ gọi được.
    * "Số bị bỏ vì quá dài" đếm SỐ, không phải HỒ SƠ, và phải phủ cả hai ô.
      Nó cũng không được tính lây sang ô phụ bị bỏ vì TRÙNG số chính — đó là
      dữ liệu bình thường.
    """
    _set_target_env(monkeypatch)

    dai = "0" * 21
    rows = [
        # Không có số nào — đúng một hồ sơ.
        _row(qlts_profile_id=1, contact_phone=None, contact_phone2=None),
        # Chỉ có số phụ: KHÔNG được tính là "không có số".
        _row(qlts_profile_id=2, contact_phone=None, contact_phone2="0900000002"),
        # Trùng nhau: ô phụ bị bỏ, nhưng KHÔNG phải vì quá dài.
        _row(
            qlts_profile_id=3, contact_phone="0900000003", contact_phone2="0900000003"
        ),
        # Hai số quá dài trên cùng một hồ sơ = HAI số bị bỏ.
        _row(qlts_profile_id=4, contact_phone=dai, contact_phone2=dai),
    ]

    async def _cohort(academic_year, **kwargs):
        return rows

    class _FakeApi:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def count_students(self, academic_year):
            return 0

    monkeypatch.setattr(sync_module, "fetch_cohort", _cohort)
    monkeypatch.setattr(sync_module, "DormApi", _FakeApi)

    assert await main(["--academic-year", "2026"]) == 0

    man_hinh = capsys.readouterr().out

    # HAI hồ sơ không liên hệ được: hồ sơ 1 (không khai số nào) và hồ sơ 4 (khai
    # hai số nhưng cả hai vượt trần nên bị bỏ). Con số này trả lời "bao nhiêu em
    # KHÔNG GỌI ĐƯỢC", nên một hồ sơ có dữ liệu mà dữ liệu không dùng được thì
    # vẫn thuộc về nó — đó cũng là lý do "số bị bỏ vì quá dài" đứng riêng, để
    # người vận hành biết trong hai em đó có một em sửa được bên QLTS.
    assert "Không có số liên hệ  : 2" in man_hinh
    assert "Có số phụ            : 1" in man_hinh
    # ĐẾM SỐ, không đếm hồ sơ: hồ sơ 4 đóng góp hai. Và ô phụ của hồ sơ 3 bị bỏ
    # vì TRÙNG số chính — không được tính lây vào đây.
    assert "Số bị bỏ vì quá dài  : 2" in man_hinh


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


# ---------------------------------------------------------------------------
# Bốn thay đổi của `693b9cda` — trước đây chỉ parser có test
# ---------------------------------------------------------------------------


def test_bearer_header_only_for_jwt_keys():
    """``Authorization: Bearer`` CHỈ gửi khi khoá là JWT.

    Khoá thế hệ mới ``sb_secret_...`` không phải JWT, và đặt nó ở vị trí Bearer
    là dùng sai contract của header đó. Đo được: Supabase local vẫn trả 200 khi
    gửi cả hai, nên đây KHÔNG phải lỗi đang hỏng — nó dựa vào việc máy chủ bỏ
    qua một header sai. Ngày máy chủ siết lại, lượt đồng bộ chết bằng 401 ở
    đúng thao tác ghi dữ liệu thật.
    """
    moi = DormApi("http://127.0.0.1:54321", "sb_secret_ABCdef")
    assert "Authorization" not in moi._headers
    assert moi._headers["apikey"] == "sb_secret_ABCdef"

    # Khoá legacy `service_role` là JWT thật (mở đầu `eyJ`) — vẫn phải gửi.
    cu = DormApi("http://127.0.0.1:54321", "eyJhbGciOiJIUzI1NiJ9.x.y")
    assert cu._headers["Authorization"] == "Bearer eyJhbGciOiJIUzI1NiJ9.x.y"


async def test_count_students_excludes_tombstoned_rows():
    """Phép đếm đối soát phải BỎ hồ sơ đã gỡ.

    Khoá secret đi vòng qua RLS, nên policy che tombstone không áp cho lời gọi
    này. Không lọc thì con số "đang có ở hệ KTX" cao hơn danh sách cán bộ thật
    sự nhìn thấy — mà đó đúng là con số dùng để quyết định trước khi ghi.
    """
    client = _RecordingClient(_FakeResponse(headers={"content-range": "0-0/7"}))

    assert await _api_with(client).count_students(2026) == 7

    params = client.calls[0]["params"]
    assert params["deleted_at"] == "is.null"
    assert params["academic_year"] == "eq.2026"


async def test_finalize_succeeds_on_the_main_path_without_reconciling():
    """Đóng sổ thành công đi ĐƯỜNG CHÍNH, không rơi vào nhánh xử lý lỗi.

    Đây là ca mà bản trước `693b9cda` hỏng hoàn toàn mà không ai thấy:
    ``finalize_sync_run`` khai ``returns public.sync_runs`` (composite SCALAR)
    nên PostgREST trả OBJECT ĐƠN, còn parser thì đòi mảng — nên MỌI lần đóng sổ
    thành công đều ném tại parser rồi được lần đối soát thứ hai cứu. Kết quả
    cuối vẫn đúng, nên bề mặt sạch trơn.

    Test này khoá hai điều cùng lúc: trả đúng số, VÀ chỉ tốn đúng một lời gọi.
    Bỏ vế thứ hai thì nó xanh cả khi đường chính lại hỏng.
    """
    client = _RecordingClient(
        _FakeResponse(payload={"id": 9, "status": "completed", "deactivated_count": 3})
    )

    assert await _api_with(client).finalize_sync_run(9, 5, 5) == 3

    assert len(client.calls) == 1
    assert client.calls[0]["url"].endswith("/rpc/finalize_sync_run")
    assert client.calls[0]["json"] == {
        "p_run_id": 9,
        "p_source_count": 5,
        "p_upserted_count": 5,
    }


# ---------------------------------------------------------------------------
# 1E — mã lỗi map phía client, và nhánh chạy lại
# ---------------------------------------------------------------------------


async def test_error_maps_the_code_and_never_echoes_the_server_message():
    """Lỗi in MÃ và thông điệp cố định phía client, KHÔNG in ``message``.

    PostgREST trả nguyên văn thông điệp của Postgres, mà thông điệp đó mang
    theo giá trị hàng. Một dòng lỗi như thế đi thẳng ra stderr — nơi CI, cron
    và container thu gom y như log.
    """
    client = _RecordingClient(
        _FakeResponse(
            status_code=400,
            payload={
                "code": "P0136",
                "message": "Chua ghi het nguon cho Nguyen Van An 0912345678",
                "details": "hang gay loi: 0912345678",
            },
        )
    )

    with pytest.raises(RuntimeError) as exc:
        await _api_with(client).finalize_sync_run(9, 5, 4)

    loi = str(exc.value)
    assert "[P0136]" in loi
    assert "Chưa ghi hết phần đáng ghi" in loi
    # Không một mảnh nào của thân phản hồi được nhắc lại.
    assert "Nguyen Van An" not in loi
    assert "0912345678" not in loi
    assert "hang gay loi" not in loi


async def test_unknown_error_code_is_shown_but_not_invented():
    """Mã lạ vẫn in ra mã — nó là thứ duy nhất để tra log, và không chứa PII."""
    client = _RecordingClient(
        _FakeResponse(
            status_code=400,
            payload={"code": "22P02", "message": "invalid input syntax: 1.5"},
        )
    )

    with pytest.raises(RuntimeError) as exc:
        await _api_with(client).count_students(2026)

    loi = str(exc.value)
    assert "[22P02]" in loi
    assert "chưa được map" in loi
    assert "invalid input syntax" not in loi


async def test_malformed_error_body_does_not_break_the_error_path():
    """Thân lỗi không phải JSON thì vẫn ném lỗi tử tế, không nổ tại parser."""

    class _ThanHong(_FakeResponse):
        def json(self):
            raise ValueError("không phải JSON")

    client = _RecordingClient(_ThanHong(status_code=500))

    with pytest.raises(RuntimeError) as exc:
        await _api_with(client).count_students(2026)

    assert "HTTP 500" in str(exc.value)


class _ClientTheoUrl:
    """Client giả ĐỊNH TUYẾN THEO URL — nhánh chạy lại đụng ba endpoint.

    Trả cùng một phản hồi cho mọi URL (như ``_RecordingClient``) sẽ làm test
    resume xanh giả: lời gọi đóng sổ và lời gọi mở lượt không phân biệt được.
    """

    def __init__(self, *, run_dang_chay, post_sync_runs=None):
        self.calls = []
        self._run_dang_chay = run_dang_chay
        self._post_sync_runs = post_sync_runs

    async def get(self, url, headers=None, params=None):
        self.calls.append({"method": "GET", "url": url, "params": params})
        return _FakeResponse(payload=self._run_dang_chay)

    async def post(self, url, headers=None, params=None, json=None):
        self.calls.append({"method": "POST", "url": url, "json": json})
        if url.endswith("/rpc/fail_sync_run"):
            return _FakeResponse(payload={"id": json["p_run_id"], "status": "failed"})
        if url.endswith("/sync_runs"):
            if self._post_sync_runs is not None:
                return self._post_sync_runs
            return _FakeResponse(status_code=409)
        raise AssertionError(f"URL không mong đợi: {url}")

    def urls(self):
        return [c["url"].rsplit("/rest/v1", 1)[-1] for c in self.calls]


async def test_manual_token_closes_the_old_run_and_opens_a_new_one():
    """``--client-token`` TRUYỀN TAY: đóng sổ lượt cũ rồi mở lượt MỚI.

    Nhận lại lượt cũ là trộn hai lần chạy vào một sổ. Hàng đã ghi ở lần trước
    vẫn mang ``last_seen_sync_id`` của lượt đó, nên hoặc guard đếm lại từ chối
    hạ cờ (P0138) và lượt treo ``running`` khoá cứng năm học, hoặc — tệ hơn —
    nó KHÔNG nổ và ``blocked_count`` cộng dồn qua cả hai lần, cho ra một quyển
    sổ khép kín mà sai.
    """
    client = _ClientTheoUrl(run_dang_chay=[{"id": 11, "status": "running"}])
    api = _api_with(client)

    # POST /sync_runs: lần đầu 409 (lượt cũ còn sống), lần sau mở được lượt mới.
    dem = {"n": 0}
    post_goc = client.post

    async def _post(url, headers=None, params=None, json=None):
        if url.endswith("/sync_runs"):
            dem["n"] += 1
            client.calls.append({"method": "POST", "url": url, "json": json})
            if dem["n"] == 1:
                return _FakeResponse(status_code=409)
            return _FakeResponse(status_code=201, payload=[{"id": 12}])
        return await post_goc(url, headers=headers, params=params, json=json)

    client.post = _post

    run_id = await api.open_sync_run(2026, "tay", raw_count=5, la_lan_chay_lai=True)

    assert run_id == 12, "phải là lượt MỚI, không phải lượt cũ 11"
    assert "/rpc/fail_sync_run" in client.urls(), "lượt cũ phải được đóng sổ"
    # Đóng ĐÚNG lượt cũ, không phải lượt nào khác.
    dong = [c for c in client.calls if c["url"].endswith("/rpc/fail_sync_run")]
    assert dong[0]["json"] == {"p_run_id": 11}


async def test_generated_token_reuses_the_recovered_run():
    """Token TỰ SINH: nhận lại lượt cũ, KHÔNG đóng sổ nó.

    Dấu tự sinh chỉ tồn tại trong tiến trình này, nên một hàng mang dấu đó
    nghĩa là chính lời gọi mở lượt vừa rồi đã tới database rồi mất phản hồi —
    chưa ghi học viên nào. Đóng sổ nó rồi mở lượt mới là bỏ đi đúng cơ chế phục
    hồi mà cái dấu sinh ra để phục vụ.
    """
    client = _ClientTheoUrl(run_dang_chay=[{"id": 11, "status": "running"}])

    run_id = await _api_with(client).open_sync_run(
        2026, "tu-sinh", raw_count=5, la_lan_chay_lai=False
    )

    assert run_id == 11
    assert "/rpc/fail_sync_run" not in client.urls()


async def test_main_flags_a_manual_token_as_a_rerun(monkeypatch):
    """``main`` phải phân biệt token truyền tay với token tự sinh."""
    _set_target_env(monkeypatch)
    monkeypatch.setattr(sync_module, "_install_stop_handlers", lambda: None)

    async def _mot_hang(academic_year, **kwargs):
        return [_row(qlts_profile_id=1)]

    monkeypatch.setattr(sync_module, "fetch_cohort", _mot_hang)

    tu_sinh = _ApiGhiNhan()
    monkeypatch.setattr(sync_module, "DormApi", tu_sinh)
    assert await main(["--academic-year", "2026", "--apply"]) == 0
    assert tu_sinh.la_lan_chay_lai is False

    truyen_tay = _ApiGhiNhan()
    monkeypatch.setattr(sync_module, "DormApi", truyen_tay)
    assert (
        await main(["--academic-year", "2026", "--apply", "--client-token", "abc123"])
        == 0
    )
    assert truyen_tay.la_lan_chay_lai is True


# ---------------------------------------------------------------------------
# 1F — ba vá nhỏ
# ---------------------------------------------------------------------------


def test_batch_size_ceiling_matches_the_rpc():
    """``--batch-size`` khoá trong 1..500, cùng trần với RPC.

    RPC từ chối lô > 500 (P0111). CLI không chặn thì ``--batch-size 501`` MỞ
    LƯỢT trước rồi mới hỏng ở lô đầu — để lại một lượt phải đóng sổ vì một con
    số gõ sai.
    """
    hop_le = parse_args(["--academic-year", "2026", "--batch-size", "500"])
    assert hop_le.batch_size == 500

    with pytest.raises(SystemExit):
        parse_args(["--academic-year", "2026", "--batch-size", "501"])

    with pytest.raises(SystemExit):
        parse_args(["--academic-year", "2026", "--batch-size", "0"])


async def test_missing_content_range_is_unknown_not_empty():
    """Thiếu hẳn header đếm = KHÔNG BIẾT, không phải "hệ KTX rỗng".

    Mặc định cũ ``"*/0"`` biến đúng ca này thành con số 0, và người vận hành
    đọc số 0 ở bước xem trước sẽ kết luận ngược hẳn với thực tế.
    """
    client = _RecordingClient(_FakeResponse(headers={}))

    assert await _api_with(client).count_students(2026) is None


async def test_finalize_reconciles_a_gateway_5xx_instead_of_declaring_failure():
    """502 ở bước hạ cờ thì ĐỐI SOÁT, không kết luận là database từ chối.

    408/5xx thường đến từ gateway đứng TRƯỚC database, nên transaction có thể
    đã commit xong rồi phản hồi mới hỏng. Đây LÀ bước hạ cờ: coi 502 là câu trả
    lời dứt khoát sẽ ghi ``failed`` cho một lượt đã đổi ``source_eligible`` của
    cả cohort — và ``open_sync_run`` cách đó hai mươi dòng đã lập luận ngược lại.
    """

    class _GatewayHongRoiDoiSoat:
        def __init__(self):
            self.calls = []

        async def post(self, url, headers=None, params=None, json=None):
            self.calls.append({"method": "POST", "url": url})
            return _FakeResponse(status_code=502)

        async def get(self, url, headers=None, params=None):
            self.calls.append({"method": "GET", "url": url})
            return _FakeResponse(
                payload=[{"id": 9, "status": "completed", "deactivated_count": 4}]
            )

    client = _GatewayHongRoiDoiSoat()

    assert await _api_with(client).finalize_sync_run(9, 5, 5) == 4

    # Đã hỏi lại thay vì ném thẳng.
    assert any(c["method"] == "GET" for c in client.calls)
