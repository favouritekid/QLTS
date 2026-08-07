# -*- coding: utf-8 -*-
"""Vỏ dòng lệnh của lượt đồng bộ: tham số, mã thoát, tín hiệu dừng, điều phối.

Lõi đã chuyển sang ``app/services/dorm_sync_service.py`` và được canh ở
``test_dorm_sync_service.py``. File này canh phần CÒN LẠI — thứ người vận hành
thực sự chạm vào khi ứng dụng sập.

🔴 Vì sao vẫn canh đủ vỏ CLI thay vì bỏ bớt cho gọn: đây là đường thoát vận hành
duy nhất khi app không lên. Hợp đồng của nó — mã thoát, cờ bắt buộc, dừng sạch
sau lô hiện tại — phải được kiểm y như lõi.
"""

import os

import pytest
from types import SimpleNamespace

from app.scripts import sync_dorm_students as sync_module
from app.services import dorm_sync_service as service_module
from app.utils.exceptions import DormSyncConfigError, DormSyncGuardError
from app.scripts.sync_dorm_students import main, parse_args
from app.services.dorm_sync_service import (
    DormSyncNotice,
    LoaiThongBao,
    OpenSyncRunResult,
    TargetSnapshot,
)


pytestmark = pytest.mark.unit

# Lõi nay nhận cấu hình TƯỜNG MINH thay vì tự đọc os.environ — nó chạy trong web
# worker, nơi cấu hình tới từ Settings chứ không từ shell. Ba helper dưới đây
# đóng đúng vai adapter mà vỏ CLI làm thật, nên các ca vẫn dựng bối cảnh bằng
# monkeypatch.setenv như cũ.
def _khai_nguon():
    return os.environ.get("DORM_SYNC_SOURCE_DB", "")


def _khai_system_id():
    return os.environ.get("DORM_SYNC_SOURCE_SYSTEM_ID", "")


def _khai_ref():
    return os.environ.get("DORM_SYNC_TARGET_PROJECT_REF", "")

_DEV_DB_URL = "postgresql+asyncpg://qlts:mat-khau@postgres:5432/qlts"

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


# ── Helper dựng phản hồi giả, copy từ test lõi ─────────────────────────
# Vỏ CLI phải chạy được trọn một lượt mà không chạm mạng, nên nó cần cùng bộ
# fake. Copy thay vì import chéo giữa hai file test: một file test import file
# test khác là thứ sẽ gãy im lặng khi ai đó sắp lại thứ tự.

_FP_GIA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _snapshot_gia(rows=()):
    """Ảnh chụp rỗng dùng cho các fake không quan tâm tới cảnh báo chỗ ở."""
    return TargetSnapshot(rows=tuple(rows), fingerprint=_FP_GIA)


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

    async def fetch_target_snapshot(self, academic_year, cohort_ids):
        self.cohort_ids_da_chup = list(cohort_ids)
        return _snapshot_gia()

    async def open_sync_run(
        self, academic_year, client_token, raw_count, *, la_lan_chay_lai=False
    ):
        self.raw_count = raw_count
        # Ghi lại để test resume quan sát được: `main` phải truyền True đúng khi
        # người vận hành tự đưa `--client-token`.
        self.la_lan_chay_lai = la_lan_chay_lai
        return OpenSyncRunResult(42)

    async def upsert_students(self, run_id, rows):
        self.lo_da_gui.append(rows)
        # Chặn ở lô ĐẦU cho tới hết hạn mức, phần còn lại ghi bình thường.
        chan = min(self._so_bi_chan, len(rows))
        self._so_bi_chan -= chan
        return len(rows) - chan, chan

    async def finalize_sync_run(
        self, run_id, source_count, upserted_count, expected_target_fingerprint
    ):
        self.finalize_args = (source_count, upserted_count)
        self.fingerprint_da_nhan = expected_target_fingerprint
        return 0


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

        async def fetch_target_snapshot(self, academic_year, cohort_ids):
            self.cohort_ids_da_chup = list(cohort_ids)
            return _snapshot_gia()

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

        async def fetch_target_snapshot(self, academic_year, cohort_ids):
            self.cohort_ids_da_chup = list(cohort_ids)
            return _snapshot_gia()

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


@pytest.mark.asyncio
async def test_main_also_stops_in_preview_mode(monkeypatch):
    """Xem trước cũng phải đỏ.

    Nếu script và repository lệch phiên bản, bản xem trước in ra những con số
    KHÔNG phải thứ ``--apply`` sẽ ghi. Người vận hành duyệt một thứ rồi chạy
    một thứ khác — và bước xem trước, vốn là hàng rào cuối trước khi ghi, trở
    thành thứ tạo ra sự yên tâm sai.
    """
    thieu = _row()
    del thieu.degree_level

    async def fake_fetch(academic_year, *, verify_source=False, **kw):
        return [thieu]

    class ApiKhongDuocDung:
        def __init__(self, *a, **kw):
            raise AssertionError("main() đã dựng DormApi ở chế độ xem trước")

    monkeypatch.setenv("DORM_SUPABASE_URL", "https://abc.supabase.co")
    monkeypatch.setenv("DORM_SUPABASE_SECRET_KEY", "sb_secret_x")
    monkeypatch.setenv("DORM_SYNC_TARGET_PROJECT_REF", "abc")
    monkeypatch.setattr(sync_module, "fetch_cohort", fake_fetch)
    monkeypatch.setattr(sync_module, "DormApi", ApiKhongDuocDung)

    assert await main(["--academic-year", "2026"]) == 2


@pytest.mark.asyncio
async def test_main_goes_on_when_the_cohort_is_complete(monkeypatch):
    """Chốt chặn ĐẢO: cohort đủ trường thì cổng KHÔNG chặn.

    Không có ca này thì một cổng viết quá tay — chặn mọi lượt — vẫn xanh, và ta
    chỉ phát hiện lúc chạy thật.
    """

    async def fake_fetch(academic_year, *, verify_source=False, **kw):
        return [_row(), _row(qlts_profile_id=9002, degree_level=None)]

    # 🔴 KHÔNG thay `DormApi` bằng đồ giả.
    #
    # Ca này là ca "xem trước chạy trót lọt" — tức chính là ca phải chứng minh
    # rằng bộ ba biến ĐÍCH đủ để đi hết đường. Thay cả lớp `DormApi` thì
    # `assert_target_project_matches` không chạy lần nào, và một cấu hình thiếu
    # `DORM_SYNC_TARGET_PROJECT_REF` vẫn cho ca này xanh trong khi lệnh thật
    # chết ở đúng dòng đó. Đã xảy ra một lần.
    #
    # Nên chỉ giả TẦNG VẬN CHUYỂN: `httpx.AsyncClient` mà `__aenter__` dựng.
    # Hàng rào đích, hàng rào đường truyền và thứ tự dựng headers đều chạy thật.
    class _TransportGia:
        def __init__(self, **kw):
            self.calls = []
            self.payloads = []

        async def aclose(self):
            return None

        async def get(self, url, headers=None, params=None):
            self.calls.append(url)
            return SimpleNamespace(
                status_code=200,
                is_success=True,
                headers={"content-range": "0-0/0"},
                json=lambda: [],
            )

        async def post(self, url, headers=None, params=None, json=None):
            self.calls.append(url)
            self.payloads.append(json)
            return SimpleNamespace(
                status_code=200,
                is_success=True,
                headers={},
                json=lambda: {"rows": [], "fingerprint": _FP_GIA},
            )

    transport = _TransportGia()
    monkeypatch.setattr(
        service_module.httpx, "AsyncClient", lambda **kw: transport
    )

    monkeypatch.setenv("DORM_SUPABASE_URL", "https://abc.supabase.co")
    monkeypatch.setenv("DORM_SUPABASE_SECRET_KEY", "sb_secret_x")
    monkeypatch.setenv("DORM_SYNC_TARGET_PROJECT_REF", "abc")
    # Xem trước KHÔNG đòi hai biến nguồn — bắt khai chỉ khiến người ta bỏ qua
    # bước xem trước, mà xem trước mới là thứ chặn được lần ghi sai.
    monkeypatch.delenv("DORM_SYNC_SOURCE_DB", raising=False)
    monkeypatch.delenv("DORM_SYNC_SOURCE_SYSTEM_ID", raising=False)
    monkeypatch.setattr(sync_module, "fetch_cohort", fake_fetch)

    assert await main(["--academic-year", "2026"]) == 0
    # Đi thật tới đích: một lời gọi đếm học viên đã được phát ra, và nó đi tới
    # ĐÚNG project khai trong biến môi trường.
    # Đếm học viên + ảnh chụp chỗ ở = hai lời gọi, cả hai tới ĐÚNG project.
    assert len(transport.calls) == 2, "cohort hợp lệ phải đi tiếp tới bước xem trước"
    assert all(
        u.startswith("https://abc.supabase.co/rest/v1/") for u in transport.calls
    )
    # 🔴 Xem trước PHẢI gọi đúng RPC mà bước ghi sẽ chốt bằng — một wrapper
    # khác, hay một truy vấn tự dựng, là cho người bấm duyệt một trạng thái
    # rồi chốt bằng một trạng thái khác.
    assert transport.calls[1].endswith("/rpc/dorm_sync_target_snapshot")
    assert transport.payloads[0]["p_academic_year"] == 2026
    assert transport.payloads[0]["p_cohort_ids"] == [9001, 9002]


def test_every_notice_kind_has_a_line_on_screen():
    """🔴 Bảng định dạng phải phủ ĐỦ ``LoaiThongBao``.

    Thiếu một mục thì loại cảnh báo ấy biến mất khỏi màn hình trong im lặng —
    và đây là những dòng nói cho người vận hành biết lượt trước còn sống hay đã
    đóng sổ, tức thứ quyết định họ có đi sửa tay database hay không.

    ⚠️ So bằng TẬP, không đếm. Đếm thì đổi tên một khoá thành chuỗi gõ sai vẫn
    ra cùng con số.
    """
    assert set(sync_module._MAU_THONG_BAO) == set(LoaiThongBao)


def test_each_notice_prints_its_own_line(capsys):
    """Ba loại, ba câu khác nhau — mỗi tình huống đòi một quyết định khác."""
    sync_module._in_thong_bao_phuc_hoi(
        [
            DormSyncNotice(loai=LoaiThongBao.LUOT_CU_DANG_CHAY, run_id=11, dau="client:x"),
            DormSyncNotice(loai=LoaiThongBao.LUOT_CU_DA_HOAN_TAT, run_id=11),
            DormSyncNotice(loai=LoaiThongBao.LUOT_CU_DA_DONG_SO, run_id=11),
        ]
    )

    man_hinh = capsys.readouterr().out
    assert "đang chạy mang dấu 'client:x'" in man_hinh
    assert "hoá ra đã HOÀN TẤT" in man_hinh
    assert "Đã đóng sổ lượt #11" in man_hinh


async def test_apply_carries_the_previewed_fingerprint_into_the_finalizer(monkeypatch):
    """🔴 Dấu vân tay đi từ ảnh chụp TRƯỚC vòng ghi thẳng tới bước đóng sổ.

    Chốt chống đua chỉ có nghĩa nếu con số mang đi so là trạng thái người bấm
    ĐÃ NHÌN. Chụp lại sau vòng ghi thì nó luôn khớp, chốt thành phép so một giá
    trị với chính nó: vẫn xanh, vẫn tốn một lời gọi, và không chặn được gì.

    Ca này khoá cả hai vế: đúng MỘT lần chụp, và chuỗi tới finalizer là chuỗi
    của lần chụp đó.
    """
    _set_target_env(monkeypatch)
    monkeypatch.setattr(sync_module, "_install_stop_handlers", lambda: None)

    FP_XEM_TRUOC = "c" * 32
    ghi_nhan = {"so_lan_chup": 0}

    class _Api:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def fetch_target_snapshot(self, academic_year, cohort_ids):
            ghi_nhan["so_lan_chup"] += 1
            # Lần chụp THỨ HAI (nếu có) trả một giá trị khác — nên một bản vá
            # chụp lại trước khi đóng sổ sẽ lộ ra ở khẳng định cuối.
            if ghi_nhan["so_lan_chup"] == 1:
                return TargetSnapshot(rows=(), fingerprint=FP_XEM_TRUOC)
            return TargetSnapshot(rows=(), fingerprint="d" * 32)

        async def open_sync_run(
            self, academic_year, client_token, raw_count, *, la_lan_chay_lai=False
        ):
            return OpenSyncRunResult(51)

        async def upsert_students(self, run_id, rows):
            return len(rows), 0

        async def finalize_sync_run(
            self, run_id, source_count, upserted_count, expected_target_fingerprint
        ):
            ghi_nhan["fingerprint"] = expected_target_fingerprint
            return 0

    async def _hai_hang(academic_year, **kwargs):
        return [_row(), _row(qlts_profile_id=9002)]

    monkeypatch.setattr(sync_module, "fetch_cohort", _hai_hang)
    monkeypatch.setattr(sync_module, "DormApi", _Api)

    assert await main(["--academic-year", "2026", "--apply"]) == 0

    assert ghi_nhan["so_lan_chup"] == 1, "chụp nhiều lần thì chốt so với chính nó"
    assert ghi_nhan["fingerprint"] == FP_XEM_TRUOC


async def test_a_changed_fingerprint_keeps_the_batches_but_never_lowers_the_flag(
    monkeypatch,
):
    """🔴 Chỗ ở đổi giữa chừng: dữ liệu đã ghi VẪN CÒN, nhưng KHÔNG hạ cờ.

    Đây là hình dạng đúng của một lượt bị chốt chặn. Hai vế đều quan trọng:

    * các lô đã gửi không bị rút lại — chúng là dữ liệu thật và lượt sau sẽ
      dùng lại; huỷ chúng chỉ tạo thêm việc;
    * KHÔNG có ai bị hạ cờ, và lượt được đóng sổ ``failed`` chứ không treo
      ``running`` khoá cứng năm học.
    """
    _set_target_env(monkeypatch)
    monkeypatch.setattr(sync_module, "_install_stop_handlers", lambda: None)

    ghi_nhan = {"lo_da_gui": 0, "da_ha_co": False, "outcome": None}

    class _Api:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def fetch_target_snapshot(self, academic_year, cohort_ids):
            return TargetSnapshot(rows=(), fingerprint="c" * 32)

        async def open_sync_run(
            self, academic_year, client_token, raw_count, *, la_lan_chay_lai=False
        ):
            return OpenSyncRunResult(52)

        async def upsert_students(self, run_id, rows):
            ghi_nhan["lo_da_gui"] += 1
            return len(rows), 0

        async def finalize_sync_run(
            self, run_id, source_count, upserted_count, expected_target_fingerprint
        ):
            # Đúng thứ database trả khi có người nhận giường giữa chừng.
            raise RuntimeError(
                "Kết thúc lượt đồng bộ thất bại (HTTP 500, request-id x). "
                "[P0192] Chỗ ở phía ký túc xá ĐÃ ĐỔI sau khi xem trước."
            )

        async def reconcile_after_failure(self, run_id):
            ghi_nhan["outcome"] = "marked_failed"
            return "marked_failed", {"id": run_id, "status": "failed"}

    async def _hai_hang(academic_year, **kwargs):
        return [_row(), _row(qlts_profile_id=9002)]

    monkeypatch.setattr(sync_module, "fetch_cohort", _hai_hang)
    monkeypatch.setattr(sync_module, "DormApi", _Api)

    assert await main(["--academic-year", "2026", "--apply"]) == 1
    assert ghi_nhan["lo_da_gui"] == 1, "các lô đã ghi phải còn nguyên, không rút lại"
    assert ghi_nhan["da_ha_co"] is False
    assert ghi_nhan["outcome"] == "marked_failed", "lượt phải được đóng sổ, không treo"


async def test_dry_run_reads_the_snapshot_but_opens_no_run(monkeypatch, capsys):
    """Xem trước CHỈ ĐỌC: có ảnh chụp cảnh báo, tuyệt đối không mở lượt.

    Mở một ``sync_run`` ở chế độ xem trước là để lại một hàng ``running`` khoá
    cứng năm học ở hệ KTX — cho một lệnh mà cả tên lẫn tài liệu đều hứa là
    không ghi gì.
    """
    _set_target_env(monkeypatch)

    class _Api:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def count_students(self, academic_year):
            return 0

        async def fetch_target_snapshot(self, academic_year, cohort_ids):
            return TargetSnapshot(
                rows=(
                    {
                        "assignment_id": 5,
                        "qlts_profile_id": 138,
                        "full_name": "Trần Thị Bình",
                        "building_id": 1,
                        "building_name": "Toà B",
                        "room_id": 30,
                        "room_code": "B305",
                        "bed_no": 13,
                        "status": "active",
                    },
                ),
                fingerprint="e" * 32,
            )

        async def open_sync_run(self, *a, **kw):
            raise AssertionError("xem trước đã MỞ LƯỢT — nó phải chỉ đọc")

        async def upsert_students(self, *a, **kw):
            raise AssertionError("xem trước đã GHI")

        async def finalize_sync_run(self, *a, **kw):
            raise AssertionError("xem trước đã HẠ CỜ")

    async def _mot_hang(academic_year, **kwargs):
        return [_row()]

    monkeypatch.setattr(sync_module, "fetch_cohort", _mot_hang)
    monkeypatch.setattr(sync_module, "DormApi", _Api)

    assert await main(["--academic-year", "2026"]) == 0

    man_hinh = capsys.readouterr().out
    assert "SẮP MẤT CỜ MÀ VẪN ĐANG GIỮ GIƯỜNG" in man_hinh
    # Người bấm phải đọc được ĐỦ để nhận ra danh sách có gì sai: là ai, ở đâu.
    assert "Trần Thị Bình" in man_hinh
    assert "B305" in man_hinh
    assert "giường 13" in man_hinh


async def test_missing_target_ref_stops_before_reading_the_cohort(monkeypatch):
    """🔴 Thiếu ``DORM_SYNC_TARGET_PROJECT_REF`` phải dừng ở DÒNG ĐẦU.

    Đây là ca hai tầng từng nói hai điều khác nhau về cùng một biến: adapter
    cấu hình miễn nó cho bước xem trước, còn ``DormApi`` thì đòi. Hậu quả không
    phải "một thông điệp lỗi xấu" mà là THỨ TỰ: lệnh chạy trót lọt qua cả
    ``fetch_cohort`` — mở transaction, đọc trọn danh sách người học khỏi
    database production — rồi mới chết vì một biến môi trường lẽ ra kiểm được
    trước khi chạm vào bất cứ thứ gì.

    Ca này khoá đúng thứ tự đó lại: cổng phải đứng TRƯỚC ``fetch_cohort``.

    ⚠️ Nới tập bắt buộc của bước xem trước từ ba biến về hai sẽ làm ĐÚNG ca này
    đỏ (``fetch_cohort`` bị gọi), không phải một ca nào khác.
    """
    monkeypatch.setenv("DORM_SUPABASE_URL", "https://abc.supabase.co")
    monkeypatch.setenv("DORM_SUPABASE_SECRET_KEY", "sb_secret_x")
    monkeypatch.delenv("DORM_SYNC_TARGET_PROJECT_REF", raising=False)

    da_doc_cohort = []

    async def _cohort_khong_duoc_doc(academic_year, **kwargs):
        da_doc_cohort.append(academic_year)
        return []

    class ApiKhongDuocDung:
        def __init__(self, *a, **kw):
            raise AssertionError("đã dựng DormApi dù thiếu biến đích")

    monkeypatch.setattr(sync_module, "fetch_cohort", _cohort_khong_duoc_doc)
    monkeypatch.setattr(sync_module, "DormApi", ApiKhongDuocDung)

    ma = await main(["--academic-year", "2026"])

    assert ma == 2, "cấu hình thiếu là mã thoát 2, không phải 0 hay 1"
    assert da_doc_cohort == [], (
        "đã đọc cohort khỏi database TRƯỚC khi biết gói tin sẽ đi tới đâu"
    )


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

        async def fetch_target_snapshot(self, academic_year, cohort_ids):
            self.cohort_ids_da_chup = list(cohort_ids)
            return _snapshot_gia()

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

        async def fetch_target_snapshot(self, academic_year, cohort_ids):
            self.cohort_ids_da_chup = list(cohort_ids)
            return _snapshot_gia()

        async def open_sync_run(
            self, academic_year, client_token, raw_count, *, la_lan_chay_lai=False
        ):
            return OpenSyncRunResult(77)

        async def upsert_students(self, run_id, rows):
            raise KeyboardInterrupt

        async def finalize_sync_run(
        self, run_id, source_count, upserted_count, expected_target_fingerprint
    ):
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

        async def fetch_target_snapshot(self, academic_year, cohort_ids):
            self.cohort_ids_da_chup = list(cohort_ids)
            return _snapshot_gia()

        async def open_sync_run(
            self, academic_year, client_token, raw_count, *, la_lan_chay_lai=False
        ):
            return OpenSyncRunResult(91)

        async def finalize_sync_run(
        self, run_id, source_count, upserted_count, expected_target_fingerprint
    ):
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


@pytest.mark.asyncio
async def test_main_stops_before_touching_the_dorm_api_when_a_row_is_incomplete(
    monkeypatch,
):
    """🔴 Không chỉ kiểm hàm — kiểm CHỖ NỐI, và kiểm THỨ TỰ.

    ``assert_payload_contract`` có test riêng, nhưng chúng gọi thẳng vào hàm.
    Xoá lời gọi ở ``main``, hoặc dời nó xuống SAU ``open_sync_run``, thì mọi
    test đó vẫn xanh — và cái giá của việc dời là một lượt ``running`` bỏ dở
    giữa chừng, đúng trạng thái mà cổng này sinh ra để tránh.

    Nên phép kiểm ở đây không phải "có ném lỗi không" mà là "đã chạm tới hệ KTX
    chưa": ``DormApi`` phải CHƯA TỪNG được dựng.
    """
    thieu = _row()
    del thieu.degree_level

    async def fake_fetch(academic_year, *, verify_source=False, **kw):
        return [_row(), thieu]

    da_dung_api = []

    class ApiKhongDuocDung:
        def __init__(self, *a, **kw):
            da_dung_api.append(True)
            raise AssertionError(
                "main() đã dựng DormApi TRƯỚC khi kiểm hợp đồng — "
                "một lượt đồng bộ có thể đã được mở."
            )

    monkeypatch.setenv("DORM_SUPABASE_URL", "https://abc.supabase.co")
    monkeypatch.setenv("DORM_SUPABASE_SECRET_KEY", "sb_secret_x")
    monkeypatch.setattr(sync_module, "fetch_cohort", fake_fetch)
    monkeypatch.setattr(sync_module, "DormApi", ApiKhongDuocDung)
    # Hai hàng rào nguồn không thuộc phạm vi ca này; để nguyên sẽ đỏ vì thiếu
    # cấu hình chứ không vì thứ đang được kiểm.
    monkeypatch.setattr(sync_module, "assert_source_database_matches", lambda: None)
    monkeypatch.setattr(sync_module, "_install_stop_handlers", lambda: None)

    ma = await main(["--academic-year", "2026", "--apply"])

    assert ma == 2
    assert da_dung_api == [], "DormApi KHÔNG được dựng khi hợp đồng payload sai"


# ── Vỏ CLI dịch domain exception thành mã thoát ────────────────────────────
#
# 🔴 Lõi nay NÉM thay vì sys.exit — service chạy trong web worker, và sys.exit ở
# đó giết luôn request của người khác. Nhưng người vận hành không được thấy khác
# biệt nào: vẫn phải là mã thoát 2. Hai ca dưới đây là chỗ duy nhất canh phép
# dịch ấy; gỡ khối `except` trong main() thì cả hai đỏ.


async def test_cli_doi_loi_cau_hinh_thanh_ma_thoat_2(monkeypatch, capsys):
    def _thieu(ten):
        raise DormSyncConfigError("Thiếu biến môi trường %s" % ten)

    monkeypatch.setattr(
        sync_module.DormSyncConfig, "from_environment",
        classmethod(lambda cls, *a, **k: _thieu("DORM_SUPABASE_URL")),
    )

    ma = await main(["--academic-year", "2026", "--dry-run"])

    assert ma == 2
    # Lý do phải ra stderr, không nuốt im lặng: người vận hành đọc dòng này rồi
    # đặt biến, chứ không đi dò từng cái.
    assert "Thiếu biến môi trường" in capsys.readouterr().err


async def test_cli_doi_loi_hang_rao_nguon_thanh_ma_thoat_2(monkeypatch, capsys):
    def _lech(*a):
        raise DormSyncGuardError("Từ chối ghi: cluster nguồn lệch khai báo")

    monkeypatch.setattr(
        sync_module.DormSyncConfig, "from_environment",
        classmethod(lambda cls, *a, **k: sync_module.DormSyncConfig(
            "https://ktx.supabase.co", "khoa", "ktx", "postgres:5432/db", "1")),
    )
    monkeypatch.setattr(sync_module, "assert_source_database_matches", _lech)
    monkeypatch.setattr(sync_module, "_install_stop_handlers", lambda: None)

    ma = await main(["--academic-year", "2026", "--apply"])

    assert ma == 2
    assert "Từ chối ghi" in capsys.readouterr().err


def test_cli_va_service_dung_CHUNG_mot_DormApi():
    """🔴 Vế chứng minh DI CHUYỂN chứ không sao chép.

    Nếu ai đó "sửa nhanh" bằng cách chép lại DormApi vào vỏ CLI, ca này đỏ ngay —
    và đó đúng là kiểu sửa sẽ làm hai hệ nói hai danh sách khác nhau mà không có
    gì nổ ra.
    """
    assert sync_module.DormApi is service_module.DormApi
    assert sync_module.fetch_cohort is service_module.fetch_cohort
    assert (
        sync_module.assert_live_source_matches
        is service_module.assert_live_source_matches
    )
