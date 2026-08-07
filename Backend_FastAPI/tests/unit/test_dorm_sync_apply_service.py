# -*- coding: utf-8 -*-
"""Ba pha của bước GHI: chuẩn bị, thực thi, đóng sổ.

🔴 Bất biến trung tâm: **một phiếu chạy đúng một lần, và chỉ chạy khi trạng
thái hai đầu vẫn đúng thứ người bấm đã nhìn.**

Thứ tự trong ``prepare_apply`` LÀ hàng rào — tra sổ TRƯỚC khi đọc nguồn. Các ca
dưới đây ghi lại DÃY lời gọi chứ không kiểm sự hiện diện: kiểm hiện diện thì
đảo thứ tự vẫn xanh, mà đảo thứ tự đúng là lỗi cần chặn.
"""


import asyncio

import pytest
from types import SimpleNamespace

from app.services.dorm_sync_apply_service import (
    KetCuc,
    KetQuaGhi,
    TrangThaiChuanBi,
    execute_apply,
    prepare_apply,
    record_result,
)
from app.services.dorm_sync_config import DormSyncConfig
from app.services.dorm_sync_service import OpenSyncRunResult, TargetSnapshot
from app.services.dorm_sync_snapshot import (
    build_source_snapshot,
    hash_source_snapshot,
    phat_hanh_token,
)
from app.utils.exceptions import (
    BusinessRuleViolation,
    DormSyncOpenAbsentError,
    DormSyncOpenNotCreatedError,
    DormSyncOpenUnknownError,
    DormSyncTokenError,
)

pytestmark = pytest.mark.unit

_KHOA = "khoa-ky-test"
_CAU_HINH = DormSyncConfig(
    "https://x.supabase.co", "khoa-gia", "x", "postgres:5432/qlts_production", "76188"
)
_FP = "c" * 32


def _row(**ghi_de):
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
    base.update(ghi_de)
    return SimpleNamespace(**base)


_ROWS = [_row(), _row(qlts_profile_id=9002)]


def _phieu(rows=None, *, actor_id=7, fingerprint=_FP):
    return phat_hanh_token(
        secret=_KHOA,
        actor_id=actor_id,
        academic_year=2026,
        source_hash=hash_source_snapshot(build_source_snapshot(rows or _ROWS)),
        target_fingerprint=fingerprint,
        now_ts=1_000_000,
    )


class _DbGia:
    """Session giả — chỉ cần ghi nhận `flush`/`commit` và giữ vài object."""

    def __init__(self):
        self.da_commit = 0
        self.da_flush = 0
        self.da_them = []

    def add(self, obj):
        self.da_them.append(obj)

    async def flush(self):
        self.da_flush += 1

    async def commit(self):
        self.da_commit += 1

    async def execute(self, *a, **kw):  # pragma: no cover - không dùng ở đây
        raise AssertionError("ca này không được chạm truy vấn thật")


def _so_cai(status="running", claims=None, **ghi_de):
    """Hàng sổ cái KHỚP phiếu mặc định.

    ⚠️ Hàng lệch phiếu có ca riêng bên dưới; mặc định phải khớp, nếu không mọi
    ca khác đều dừng ở hàng rào ràng-sổ-với-phiếu và không kiểm được thứ chúng
    khai là đang kiểm.
    """
    if claims is None:
        _, claims = _phieu()
    base = dict(
        id=11,
        operation_id=claims.operation_id,
        actor_id=7,
        academic_year=claims.academic_year,
        snapshot_hash=claims.snapshot_hash,
        snapshot_version=claims.snapshot_version,
        status=status,
        # Hàng `completed` mặc định là hàng HỢP LỆ; ca kiểm hàng hỏng dựng
        # riêng bên dưới.
        ktx_run_id=42 if status == "completed" else None,
        result=(
            {
                "status": "completed",
                "ktx_run_id": 42,
                "upserted": 2,
                "blocked": 0,
                "deactivated": 3,
            }
            if status == "completed"
            else None
        ),
    )
    base.update(ghi_de)
    return SimpleNamespace(**base)


def _api_gia(thu_tu=None, fingerprint=_FP):
    class _Api:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def fetch_target_snapshot(self, nam, cohort_ids):
            if thu_tu is not None:
                thu_tu.append("snapshot_dich")
            return TargetSnapshot(rows=(), fingerprint=fingerprint)

    return _Api


async def _chuan_bi(
    monkeypatch,
    *,
    token,
    so_cai_co_san=None,
    chen_tra_ve="moi",
    thu_tu=None,
    rows=None,
    actor_id=7,
    fingerprint=_FP,
):
    """Chạy ``prepare_apply`` với sổ cái và cohort giả."""
    import app.services.dorm_sync_apply_service as m

    hang_moi = _so_cai()

    async def _lay(db, op_id):
        if thu_tu is not None:
            thu_tu.append("tra_so")
        return so_cai_co_san

    async def _chen(db, **kw):
        if thu_tu is not None:
            thu_tu.append("mo_so")
        if chen_tra_ve == "moi":
            return hang_moi
        return None

    async def _cohort(nam, **kw):
        if thu_tu is not None:
            thu_tu.append("doc_nguon")
        # Hàng rào định danh nguồn phải được BẬT ở bước ghi.
        assert kw.get("verify_source") is True
        assert kw.get("expected_source_db") == _CAU_HINH.source_db
        return rows if rows is not None else _ROWS

    async def _audit(*a, **kw):
        if thu_tu is not None:
            thu_tu.append("audit")
        return None

    monkeypatch.setattr(m, "lay_theo_operation_id", _lay)
    monkeypatch.setattr(m, "chen_neu_chua_co", _chen)
    monkeypatch.setattr(m, "log_activity", _audit)

    return await prepare_apply(
        _DbGia(),
        token=token,
        secret=_KHOA,
        actor_id=actor_id,
        cau_hinh=_CAU_HINH,
        now_ts=1_000_100,
        api_factory=_api_gia(thu_tu, fingerprint),
        cohort_loader=_cohort,
    )


# ---------------------------------------------------------------------------
# Thứ tự hàng rào
# ---------------------------------------------------------------------------


async def test_thu_tu_chuan_bi(monkeypatch):
    """Giải phiếu → tra sổ → đọc nguồn → hỏi đích → mở sổ → ghi nhật ký."""
    token, _ = _phieu()
    thu_tu = []

    ket_qua = await _chuan_bi(monkeypatch, token=token, thu_tu=thu_tu)

    assert ket_qua.trang_thai is TrangThaiChuanBi.SAN_SANG
    assert thu_tu == [
        "tra_so",
        "doc_nguon",
        "snapshot_dich",
        "mo_so",
        "audit",
    ]


@pytest.mark.parametrize(
    "status, mong_doi",
    [
        ("completed", TrangThaiChuanBi.DA_XONG),
        ("running", TrangThaiChuanBi.KHONG_CHAY_LAI),
        ("failed", TrangThaiChuanBi.KHONG_CHAY_LAI),
        ("outcome_unknown", TrangThaiChuanBi.KHONG_CHAY_LAI),
    ],
)
async def test_so_cai_da_co_thi_KHONG_cham_nguon_hay_KTX(
    monkeypatch, status, mong_doi
):
    """🔴 Cả BỐN trạng thái đều dừng ngay sau khi tra sổ.

    ``completed`` trả lại kết quả cũ. Ba trạng thái còn lại khác nhau, nhưng
    chung một điều: ta không biết hệ ký túc xá đang ở đâu. Tự chạy lại là ghi
    chồng lên một lượt có thể đang ghi dở — mà mỗi lượt hạ cờ đủ-điều-kiện của
    cả một cohort.

    ⚠️ Vế "không chạm" mới là vế quan trọng: một bản vá đọc nguồn rồi mới xét
    trạng thái vẫn trả đúng kết luận, và ca chỉ kiểm `trang_thai` sẽ xanh.
    """
    token, claims = _phieu()
    thu_tu = []

    ket_qua = await _chuan_bi(
        monkeypatch,
        token=token,
        so_cai_co_san=_so_cai(status=status, claims=claims),
        thu_tu=thu_tu,
    )

    assert ket_qua.trang_thai is mong_doi
    assert thu_tu == ["tra_so"], "đã chạm nguồn/KTX cho một lượt đã có trong sổ"
    assert ket_qua.rows is None
    assert ket_qua.thong_diep


async def test_ben_THUA_cuoc_dua_di_qua_CUNG_may_trang_thai(monkeypatch):
    """🔴 ``ON CONFLICT DO NOTHING`` trả ``None`` — KHÔNG ``IntegrityError``.

    Bên thua đọc lại hàng của bên thắng rồi đi qua CHÍNH máy trạng thái ở
    trên. Một nhánh riêng cho bên thua là một bản sao của cùng logic, và nó sẽ
    lệch đúng vào ngày ai đó sửa một bên.
    """
    import app.services.dorm_sync_apply_service as m

    token, claims = _phieu()
    hang_thang = _so_cai(status="running", claims=claims)
    lan_tra = {"n": 0}

    async def _lay(db, op_id):
        lan_tra["n"] += 1
        # Lần đầu: chưa có. Lần hai (sau khi thua): đọc được hàng bên thắng.
        return None if lan_tra["n"] == 1 else hang_thang

    async def _chen(db, **kw):
        return None  # thua

    async def _cohort(nam, **kw):
        return _ROWS

    async def _audit(*a, **kw):
        raise AssertionError("bên thua không được ghi nhật ký 'requested'")

    monkeypatch.setattr(m, "lay_theo_operation_id", _lay)
    monkeypatch.setattr(m, "chen_neu_chua_co", _chen)
    monkeypatch.setattr(m, "log_activity", _audit)

    ket_qua = await prepare_apply(
        _DbGia(),
        token=token,
        secret=_KHOA,
        actor_id=7,
        cau_hinh=_CAU_HINH,
        now_ts=1_000_100,
        api_factory=_api_gia(),
        cohort_loader=_cohort,
    )

    assert ket_qua.trang_thai is TrangThaiChuanBi.KHONG_CHAY_LAI
    assert ket_qua.so_cai is hang_thang
    assert lan_tra["n"] == 2


# ---------------------------------------------------------------------------
# Hai đầu phải đúng thứ đã ký
# ---------------------------------------------------------------------------


async def test_nguon_doi_sau_khi_ky_thi_TU_CHOI(monkeypatch):
    token, _ = _phieu(rows=_ROWS)
    thu_tu = []

    with pytest.raises(DormSyncTokenError):
        await _chuan_bi(
            monkeypatch,
            token=token,
            thu_tu=thu_tu,
            rows=[_row(contact_phone="0987654321"), _row(qlts_profile_id=9002)],
        )

    # Dừng TRƯỚC khi hỏi đích và trước khi mở sổ.
    assert thu_tu == ["tra_so", "doc_nguon"]


async def test_dich_doi_sau_khi_ky_thi_TU_CHOI(monkeypatch):
    """Chốt thật nằm trong ``finalize_sync_run`` (P0192); đây là lớp thu hẹp.

    Hỏng ở đây thì chưa mở lượt nào; hỏng ở đó thì phải đi đóng sổ một lượt dở.
    """
    token, _ = _phieu()
    thu_tu = []

    with pytest.raises(DormSyncTokenError):
        await _chuan_bi(
            monkeypatch, token=token, thu_tu=thu_tu, fingerprint="d" * 32
        )

    assert thu_tu == ["tra_so", "doc_nguon", "snapshot_dich"]
    assert "mo_so" not in thu_tu


async def test_phieu_cua_nguoi_KHAC_thi_tu_choi_truoc_moi_thu(monkeypatch):
    token, _ = _phieu(actor_id=7)
    thu_tu = []

    with pytest.raises(DormSyncTokenError):
        await _chuan_bi(monkeypatch, token=token, thu_tu=thu_tu, actor_id=8)

    assert thu_tu == [], "chưa được tra sổ khi phiếu chưa hợp lệ"


# ---------------------------------------------------------------------------
# execute_apply
# ---------------------------------------------------------------------------


class _ApiGhi:
    def __init__(self, *, so_bi_chan=0):
        self.calls = []
        self._so_bi_chan = so_bi_chan
        self.finalize_kwargs = None
        self.so_lan_chup = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def fetch_target_snapshot(self, nam, ids):
        self.so_lan_chup += 1
        return TargetSnapshot(rows=(), fingerprint="KHAC" + "0" * 28)

    async def open_sync_run(self, nam, token, raw_count, *, la_lan_chay_lai=False):
        self.calls.append(("open", raw_count))
        return OpenSyncRunResult(42)

    async def upsert_students(self, run_id, rows):
        self.calls.append(("upsert", len(rows)))
        chan = min(self._so_bi_chan, len(rows))
        self._so_bi_chan -= chan
        return len(rows) - chan, chan

    async def finalize_sync_run(self, run_id, **kw):
        self.calls.append(("finalize", run_id))
        self.finalize_kwargs = kw
        return 3

    async def reconcile_after_failure(self, run_id):
        self.calls.append(("reconcile", run_id))
        raise AssertionError("đường thành công không được đối soát")


async def test_execute_dung_fingerprint_DA_KY_va_khong_chup_lai():
    """🔴 Chụp lại trước khi đóng sổ = chốt so một giá trị với chính nó.

    Nó luôn khớp: vẫn xanh, vẫn tốn một lời gọi, và không chặn được gì. API giả
    ở đây cố tình trả một fingerprint KHÁC nếu bị hỏi lại, nên một bản vá chụp
    lại sẽ gửi giá trị sai xuống finalize và ca này đỏ.
    """
    _, claims = _phieu()
    api = _ApiGhi()

    ket_qua = await execute_apply(
        cau_hinh=_CAU_HINH, claims=claims, rows=_ROWS, api=api
    )

    assert api.so_lan_chup == 0, "đã chụp lại ảnh đích trước khi đóng sổ"
    assert api.finalize_kwargs["expected_target_fingerprint"] == _FP
    assert ket_qua.ket_cuc is KetCuc.COMPLETED
    assert ket_qua.ktx_run_id == 42
    assert ket_qua.upserted == 2
    assert ket_qua.deactivated == 3


async def test_execute_gui_EFFECTIVE_total_khong_phai_so_hang_nguon():
    """``source_count`` = nguồn − bị chặn.

    Truyền ``len(rows)`` khi có dù một hàng bị chặn sẽ làm guard "chưa ghi hết
    nguồn" phía database từ chối hạ cờ, và thông điệp lúc đó nói về một sự cố
    không có thật.
    """
    _, claims = _phieu()
    api = _ApiGhi(so_bi_chan=1)

    ket_qua = await execute_apply(
        cau_hinh=_CAU_HINH, claims=claims, rows=_ROWS, api=api
    )

    assert ket_qua.blocked == 1
    assert api.finalize_kwargs["source_count"] == 1
    assert api.finalize_kwargs["upserted_count"] == 1


async def test_execute_dung_operation_id_lam_dau_luot():
    """Dấu lượt phải truy ngược được về sổ cái, không phải một uuid tuỳ ý."""
    _, claims = _phieu()

    class _Bat(_ApiGhi):
        async def open_sync_run(self, nam, token, raw_count, *, la_lan_chay_lai=False):
            self.dau = token
            return OpenSyncRunResult(42)

    api = _Bat()
    await execute_apply(cau_hinh=_CAU_HINH, claims=claims, rows=_ROWS, api=api)

    assert api.dau == str(claims.operation_id)


def test_execute_KHONG_nhan_session_database():
    """🔴 Ràng buộc, không phải thiếu sót.

    Lượt này mất vài chục giây; ôm một transaction suốt thời gian đó là giữ
    khoá trên sổ cái trong lúc chờ mạng, và mọi request khác đụng cùng hàng sẽ
    xếp hàng sau một cuộc gọi HTTP.
    """
    import inspect

    tham_so = inspect.signature(execute_apply).parameters

    assert "db" not in tham_so
    assert not any("session" in t.lower() for t in tham_so)


# ---------------------------------------------------------------------------
# record_result
# ---------------------------------------------------------------------------


async def test_record_result_chi_flush_KHONG_commit(monkeypatch):
    """``commit`` ở service sẽ chốt sổ độc lập với phần còn lại của request.

    Router mất khả năng gộp hai việc vào một transaction — thứ mà bước 12 dựa
    vào để sổ cái và nhật ký không bao giờ nói hai chuyện khác nhau.
    """
    import app.services.dorm_sync_apply_service as m

    da_goi = []

    async def _cap_nhat(db, so_cai, **kw):
        da_goi.append(("cap_nhat", kw["status"]))
        so_cai.status = kw["status"]
        so_cai.result = kw.get("result")
        # 🔴 Giữ lại giá trị đi vào CỘT sổ cái, tách khỏi giá trị trong JSON.
        # Không giữ riêng thì hai nguồn lệch nhau vẫn xanh — đã đo: kiểm ngược
        # cộng 57 vào cột mà cả bộ vẫn 26/26.
        so_cai.ktx_run_id = kw.get("ktx_run_id")
        await db.flush()
        return so_cai

    async def _activity(db, *, action, **kw):
        da_goi.append(("activity", action))
        # MỘT nguồn cho `ktx_run_id`: nhật ký và sổ cái phải nói cùng con số.
        da_goi.append(("run_id_trong_nhat_ky", kw["changes"]["ktx_run_id"]))
        return None

    monkeypatch.setattr(m, "cap_nhat_ket_qua", _cap_nhat)
    monkeypatch.setattr(m, "log_activity", _activity)

    db = _DbGia()
    so_cai = _so_cai()

    await record_result(
        db,
        so_cai,
        actor_id=7,
        ket_qua=KetQuaGhi(
            ket_cuc=KetCuc.COMPLETED,
            ktx_run_id=42,
            upserted=2,
            blocked=0,
            deactivated=3,
        ),
    )

    assert db.da_commit == 0, "service KHÔNG được commit"
    assert db.da_flush >= 1
    assert da_goi == [
        ("cap_nhat", "completed"),
        ("activity", "dorm_sync_apply_completed"),
        ("run_id_trong_nhat_ky", 42),
    ]
    assert so_cai.result["ktx_run_id"] == 42
    assert so_cai.result["deactivated"] == 3
    # 🔴 CỘT sổ cái, JSON kết quả và nhật ký phải nói CÙNG một con số.
    #
    # Ba chỗ ghi cùng một sự thật; chúng chỉ khớp vì cả ba lấy từ một
    # `KetQuaGhi`. Ngày ai đó thêm một tham số thứ hai, chúng lệch — và sổ cái
    # sẽ trỏ tới một lượt KTX không phải lượt vừa chạy.
    assert so_cai.ktx_run_id == 42, "cột sổ cái lệch khỏi kết quả thật"
    assert so_cai.ktx_run_id == so_cai.result["ktx_run_id"]


# ---------------------------------------------------------------------------
# Máy trạng thái LỖI — ba kết cục, phân biệt bằng ĐỐI SOÁT
# ---------------------------------------------------------------------------


class _ApiHong:
    """Mở lượt xong rồi hỏng ở ``upsert``; đối soát trả kết quả khai sẵn."""

    def __init__(self, outcome, hang=None, *, no_o_buoc="upsert"):
        self.outcome = outcome
        self.hang = hang
        self.no_o_buoc = no_o_buoc
        self.so_lan_doi_soat = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def open_sync_run(self, nam, token, raw_count, *, la_lan_chay_lai=False):
        if self.no_o_buoc == "open":
            raise DormSyncOpenAbsentError("đã đối soát: database chưa nhận gì")
        if self.no_o_buoc == "open_unknown":
            raise DormSyncOpenUnknownError("không đối soát được là đã mở hay chưa")
        return OpenSyncRunResult(42)

    async def upsert_students(self, run_id, rows):
        if self.no_o_buoc == "upsert":
            raise RuntimeError("mất kết nối giữa chừng")
        return len(rows), 0

    async def finalize_sync_run(self, run_id, **kw):
        if self.no_o_buoc == "finalize":
            raise RuntimeError("[P0192] chỗ ở đã đổi")
        return 3

    async def reconcile_after_failure(self, run_id):
        self.so_lan_doi_soat += 1
        if self.outcome == "no":
            raise RuntimeError("chính lời gọi đối soát cũng hỏng")
        return self.outcome, self.hang


@pytest.mark.parametrize(
    "outcome, hang, ket_cuc",
    [
        ("finalized", {"id": 42, "status": "completed", "deactivated_count": 5}, KetCuc.COMPLETED),
        ("marked_failed", {"status": "failed"}, KetCuc.FAILED),
        ("unknown", None, KetCuc.OUTCOME_UNKNOWN),
        ("no", None, KetCuc.OUTCOME_UNKNOWN),
    ],
)
async def test_hong_giua_chung_thi_DOI_SOAT_roi_moi_ket_luan(outcome, hang, ket_cuc):
    """🔴 Ba kết cục, phân biệt bằng cách HỎI LẠI hệ KTX.

    Lỗi phía client KHÔNG đồng nghĩa với "database chưa làm gì":

    * ``finalized`` — đã hoàn tất, chỉ phản hồi không về tới nơi. Báo thất bại
      ở ca này là ghi sai sổ sách;
    * ``marked_failed`` — lượt bên kia đã đóng sổ, một phiếu mới chạy được;
    * ``unknown`` — KHÔNG biết. Gộp vào ``failed`` là nói dối rằng bên kia đã
      sạch, rồi lượt sau ghi chồng lên một lượt có thể đang sống.

    Ca cuối (``"no"``) là ca chính lời gọi đối soát cũng hỏng — vẫn phải là
    ``OUTCOME_UNKNOWN``, không được rơi thành exception.
    """
    _, claims = _phieu()
    api = _ApiHong(outcome, hang)

    ket_qua = await execute_apply(
        cau_hinh=_CAU_HINH, claims=claims, rows=_ROWS, api=api
    )

    assert ket_qua.ket_cuc is ket_cuc
    assert api.so_lan_doi_soat == 1, "phải đối soát ĐÚNG một lần"
    assert ket_qua.ktx_run_id == 42, "kết cục nào cũng phải truy được về lượt KTX"
    if ket_cuc is KetCuc.COMPLETED:
        assert ket_qua.deactivated == 5


async def test_hong_NGAY_LUC_MO_thi_khong_doi_soat():
    """Chưa mở được lượt nào ⇒ chưa có gì bên kia để đối soát.

    Đây là ca DUY NHẤT kết luận được mà không hỏi lại.
    """
    _, claims = _phieu()
    api = _ApiHong("finalized", None, no_o_buoc="open")

    ket_qua = await execute_apply(
        cau_hinh=_CAU_HINH, claims=claims, rows=_ROWS, api=api
    )

    assert ket_qua.ket_cuc is KetCuc.FAILED
    assert ket_qua.ktx_run_id is None
    assert api.so_lan_doi_soat == 0


async def test_execute_KHONG_bao_gio_nem():
    """Đẩy exception ra ngoài buộc router tự viết nghiệp vụ đối soát.

    Mà đối soát là việc duy nhất phân biệt được ba kết cục, và ba kết cục ấy
    dẫn tới ba trạng thái sổ cái khác nhau.
    """
    _, claims = _phieu()

    for buoc in ("open", "upsert", "finalize"):
        api = _ApiHong("unknown", None, no_o_buoc=buoc)
        ket_qua = await execute_apply(
            cau_hinh=_CAU_HINH, claims=claims, rows=_ROWS, api=api
        )
        assert isinstance(ket_qua, KetQuaGhi), buoc


# ---------------------------------------------------------------------------
# Tổ hợp bất khả thi
# ---------------------------------------------------------------------------


def test_completed_KHONG_co_run_id_thi_tu_choi_ngay_luc_dung():
    """Một hàng `completed` rỗng sẽ được lần bấm sau trả về như "đã xong"."""
    with pytest.raises(ValueError):
        KetQuaGhi(ket_cuc=KetCuc.COMPLETED, ktx_run_id=None)


def test_luot_hong_ma_khai_so_ha_co_thi_tu_choi():
    """Ghi vào sổ một việc chưa chắc đã xảy ra."""
    for ket_cuc in (KetCuc.FAILED, KetCuc.OUTCOME_UNKNOWN):
        with pytest.raises(ValueError):
            KetQuaGhi(ket_cuc=ket_cuc, ktx_run_id=42, deactivated=3)


def test_record_result_chi_nhan_MOT_nguon_cho_run_id():
    """🔴 Không có tham số thứ hai để lệch.

    Bản trước nhận rời ``status`` + ``ktx_run_id`` + ``ket_qua`` và không kiểm
    quan hệ giữa chúng — đo được: sổ ghi ``ktx_run_id=99`` trong khi JSON kết
    quả ghi ``42``.
    """
    import inspect

    tham_so = set(inspect.signature(record_result).parameters)

    assert "ktx_run_id" not in tham_so
    assert "status" not in tham_so
    assert "ly_do" not in tham_so
    assert "ket_qua" in tham_so


# ---------------------------------------------------------------------------
# Hàng đã có trong sổ phải DÙNG ĐƯỢC
# ---------------------------------------------------------------------------


async def test_hang_completed_HONG_thi_khong_tra_ve_nhu_da_xong(monkeypatch):
    """Sổ ghi `completed` mà thiếu `ktx_run_id`/`result` là sổ đã hỏng từ trước.

    Trả nó về như "đã xong" là đóng dấu xác nhận lên đúng cái hỏng đó, và người
    vận hành mất luôn đường lần ra lượt bên kia.
    """
    from app.utils.exceptions import BusinessRuleViolation

    token, claims = _phieu()
    hong = _so_cai(status="completed", claims=claims)
    hong.ktx_run_id = None
    hong.result = None

    with pytest.raises(BusinessRuleViolation):
        await _chuan_bi(monkeypatch, token=token, so_cai_co_san=hong)


async def test_trang_thai_LA_thi_fail_closed(monkeypatch):
    """CHECK constraint chỉ cho bốn giá trị; tới đây nghĩa là nó đã bị gỡ.

    Rơi vào một nhánh mặc định "cho chạy" ở đúng chỗ này là chạy một lượt hạ cờ
    trên một trạng thái không ai định nghĩa.
    """
    from app.utils.exceptions import BusinessRuleViolation

    token, claims = _phieu()

    with pytest.raises(BusinessRuleViolation):
        await _chuan_bi(
            monkeypatch,
            token=token,
            so_cai_co_san=_so_cai(status="dang_cho", claims=claims),
        )


def test_dung_dung_he_nhat_ky_da_duyet():
    """Contract: ``activity_service.log_activity``, không phải ``log_audit``.

    Hai hệ khác nhau: một ghi việc NGƯỜI làm, một ghi việc TRƯỜNG dữ liệu đổi.
    Lượt đồng bộ là thao tác của người vận hành và phải nằm cùng chỗ với mọi
    thao tác khác của họ — nếu không thì màn hình nhật ký hoạt động im lặng bỏ
    sót đúng thao tác nguy hiểm nhất trong hệ.
    """
    import inspect

    import app.services.dorm_sync_apply_service as m

    ma = inspect.getsource(m)

    assert "from app.services.activity_service import log_activity" in ma
    # ⚠️ Soi LỜI GỌI và IMPORT, không soi chuỗi trần: chú thích trong file có
    # nhắc `log_audit` để giải thích vì sao KHÔNG dùng nó, và một phép `in`
    # thô sẽ đỏ vì đúng dòng giải thích ấy.
    assert "log_audit(" not in ma
    assert "audit_service" not in ma.replace(
        "`audit_service.log_audit`", ""
    ).replace("audit_service.log_audit", "")
    assert 'action="dorm_sync_apply_requested"' in ma
    assert 'action=f"dorm_sync_apply_{ket_qua.ket_cuc}"' in ma


# ---------------------------------------------------------------------------
# Bốn khoảng hở đo được ở vòng review trước
# ---------------------------------------------------------------------------


async def test_MAT_ACK_luc_mo_luot_phai_la_outcome_unknown():
    """🔴 "Chưa có run_id" KHÔNG đồng nghĩa "chưa mở được lượt".

    ``open_sync_run`` phân biệt hai ca bằng KIỂU:

    * ``DormSyncOpenAbsentError`` — đã đối soát, biết chắc bên kia sạch;
    * ``DormSyncOpenUnknownError`` — POST mất ACK VÀ lần GET đối soát cũng hỏng.
      Một hàng ``running`` CÓ THỂ đang nằm bên kia và khoá cứng năm học đó.

    Bản trước gộp cả hai thành ``failed``. Ghi ``failed`` cho ca thứ hai là nói
    dối rằng bên kia đã sạch — rồi lượt sau mở lượt thứ hai chồng lên, và
    ``uq_sync_run_active_per_year`` từ chối mọi lần chạy cho tới khi có người
    vào database sửa tay.
    """
    _, claims = _phieu()
    api = _ApiHong("unknown", None, no_o_buoc="open_unknown")

    ket_qua = await execute_apply(
        cau_hinh=_CAU_HINH, claims=claims, rows=_ROWS, api=api
    )

    assert ket_qua.ket_cuc is KetCuc.OUTCOME_UNKNOWN
    assert ket_qua.ktx_run_id is None
    assert api.so_lan_doi_soat == 0, "chưa có run_id thì không đối soát được gì"


class _ApiDongHong(_ApiHong):
    """Chạy trót lọt, nhưng việc ĐÓNG client hỏng."""

    def __init__(self):
        super().__init__("finalized", None, no_o_buoc="khong")
        self.da_finalize = False

    async def finalize_sync_run(self, run_id, **kw):
        self.da_finalize = True
        return 3

    async def __aexit__(self, *exc):
        raise RuntimeError("close failed after finalize")


async def test_loi_DONG_client_khong_xoa_ket_qua_completed():
    """🔴 ``try`` phải bao TRỌN vòng đời context manager.

    Bản trước đặt ``try`` bên trong ``async with``, nên lỗi ở
    ``__aenter__``/``__aexit__`` đi vòng qua toàn bộ hàng rào. Ca tệ nhất:
    ``finalize`` đã thành công — hệ KTX đã đổi thật — rồi việc đóng socket
    hỏng, và người gọi không nhận được ``KetQuaGhi`` nào để đóng sổ. Sổ cái ở
    lại ``running`` cho một lượt đã xong.
    """
    _, claims = _phieu()
    api = _ApiDongHong()

    ket_qua = await execute_apply(
        cau_hinh=_CAU_HINH, claims=claims, rows=_ROWS, api=api
    )

    assert api.da_finalize is True
    assert ket_qua.ket_cuc is KetCuc.COMPLETED
    assert ket_qua.deactivated == 3


async def test_loi_MO_client_van_tra_KetQuaGhi():
    """Vế còn lại của cùng vòng đời: ``__aenter__`` hỏng ⇒ FAILED, không ném.

    🔴 ``DormApi.__aenter__`` chỉ dựng ``httpx.AsyncClient`` — chưa gửi byte
    nào sang hệ KTX. Hỏng ở đây là CHẮC CHẮN chưa tạo lượt nào.

    Bản trước để nó bay thẳng ra. Sau khi commit A đã ghi ``running``, router
    không nhận được ``KetQuaGhi`` nào, sổ cái nằm lại ``running``, và mọi lần
    bấm sau với cùng phiếu bị chặn vĩnh viễn.
    """

    class _MoHong:
        async def __aenter__(self):
            raise RuntimeError("không mở nổi kết nối")

        async def __aexit__(self, *exc):
            return False

    _, claims = _phieu()

    ket_qua = await execute_apply(
        cau_hinh=_CAU_HINH, claims=claims, rows=_ROWS, api=_MoHong()
    )

    assert ket_qua.ket_cuc is KetCuc.FAILED
    assert ket_qua.ktx_run_id is None


@pytest.mark.parametrize(
    "hang, vi_sao",
    [
        (None, "không có hàng nào"),
        ({"id": 42, "status": "completed"}, "thiếu deactivated_count"),
        ({"id": 99, "status": "completed", "deactivated_count": 5}, "hàng của lượt KHÁC"),
        ({"id": 42, "status": "running", "deactivated_count": 5}, "chưa đóng sổ"),
        ({"id": 42, "status": "completed", "deactivated_count": "5"}, "số liệu là chuỗi"),
        ({"id": 42, "status": "completed", "deactivated_count": True}, "bool"),
        ({"id": 42, "status": "completed", "deactivated_count": -1}, "số âm"),
    ],
)
async def test_hang_finalized_KHONG_doc_duoc_thi_outcome_unknown(hang, vi_sao):
    """🔴 KHÔNG ép về 0.

    Bản trước dùng ``int((hang or {}).get(...) or 0)``, nên một phản hồi thiếu
    trường — hoặc mang hàng của lượt KHÁC — vẫn được ghi ``completed`` với
    ``deactivated=0``. Con số đó đi vào sổ đối soát và vào màn hình; bịa ra 0 là
    khai "không ai bị hạ cờ" cho một lượt mà ta không hề đọc được kết quả.
    """
    _, claims = _phieu()
    api = _ApiHong("finalized", hang)

    ket_qua = await execute_apply(
        cau_hinh=_CAU_HINH, claims=claims, rows=_ROWS, api=api
    )

    assert ket_qua.ket_cuc is KetCuc.OUTCOME_UNKNOWN, vi_sao
    assert ket_qua.ktx_run_id == 42


@pytest.mark.parametrize(
    "ghi_de, vi_sao",
    [
        ({"actor_id": 8}, "người bấm khác"),
        ({"academic_year": 2025}, "năm học khác"),
        ({"snapshot_hash": "z" * 64}, "dấu băm ảnh chụp khác"),
        ({"snapshot_version": 99}, "phiên bản ảnh chụp khác"),
    ],
)
async def test_so_cai_LECH_phieu_thi_tu_choi(monkeypatch, ghi_de, vi_sao):
    """🔴 ``operation_id`` khớp là CHƯA ĐỦ — nó khớp vì ta tra sổ bằng chính nó.

    Những thứ còn lại mới nói hàng ấy có thật sự là lượt của phiếu này không.
    Lệch nghĩa là hoặc khoá ký bị dùng ở nơi khác, hoặc sổ cái bị sửa tay — và
    trả ``DA_XONG`` cho một hàng lệch là nói với người bấm rằng việc của họ đã
    xong, trong khi thứ đã chạy là một việc khác.
    """
    token, claims = _phieu()
    hang = _so_cai(status="completed", claims=claims)
    for k, v in ghi_de.items():
        setattr(hang, k, v)

    with pytest.raises(BusinessRuleViolation):
        await _chuan_bi(monkeypatch, token=token, so_cai_co_san=hang)


async def test_so_cai_completed_LECH_run_id_giua_cot_va_JSON(monkeypatch):
    """Hai chỗ ghi cùng một sự thật; lệch nghĩa là một trong hai đã bị sửa.

    Người vận hành dùng ``ktx_run_id`` để lần ra lượt bên kia — trỏ họ tới sai
    lượt còn tệ hơn không trỏ gì.
    """
    token, claims = _phieu()
    hang = _so_cai(status="completed", claims=claims)
    hang.ktx_run_id = 42
    hang.result = {"status": "completed", "ktx_run_id": 99}

    with pytest.raises(BusinessRuleViolation):
        await _chuan_bi(monkeypatch, token=token, so_cai_co_san=hang)


def test_KHONG_nuot_KeyboardInterrupt_va_SystemExit():
    """``BaseException`` nuốt cả yêu cầu dừng tiến trình.

    Ctrl-C giữa một lượt đồng bộ phải dừng tiến trình, không được biến thành
    "một lượt vẫn chạy tiếp rồi trả kết quả".
    """
    import inspect

    import app.services.dorm_sync_apply_service as m

    ma = inspect.getsource(m.execute_apply)

    assert "except BaseException" not in ma
    assert "except asyncio.CancelledError" in ma
    assert "except Exception as loi" in ma


# ---------------------------------------------------------------------------
# Vòng ba — vòng đời client, phân loại dứt khoát, cached result
# ---------------------------------------------------------------------------


async def test_loi_DUNG_client_van_tra_KetQuaGhi():
    """Constructor `DormApi` chạy hai guard và có thể ném — chưa gửi HTTP nào."""

    def _dung_hong(*a, **kw):
        raise ValueError("project ref không khớp")

    _, claims = _phieu()

    ket_qua = await execute_apply(
        cau_hinh=_CAU_HINH, claims=claims, rows=_ROWS, api_factory=_dung_hong
    )

    assert ket_qua.ket_cuc is KetCuc.FAILED
    assert ket_qua.ktx_run_id is None


class _ApiHuyLucDong(_ApiHong):
    """Chạy trót lọt, rồi bị HUỶ đúng lúc đóng client."""

    def __init__(self):
        super().__init__("finalized", None, no_o_buoc="khong")

    async def finalize_sync_run(self, run_id, **kw):
        return 3

    async def __aexit__(self, *exc):
        raise asyncio.CancelledError()


async def test_HUY_luc_dong_client_khong_xoa_ket_qua_completed():
    """🔴 ``CancelledError`` KHÔNG phải ``Exception``.

    Bản trước chỉ bắt ``Exception`` ở chỗ đóng client, nên một lần huỷ rơi đúng
    vào lúc đóng socket — SAU khi ``finalize`` đã thành công — xoá sạch kết quả
    ``completed`` vừa tính xong. Hệ KTX đã đổi thật mà sổ cái nằm lại
    ``running``.
    """
    _, claims = _phieu()

    ket_qua = await execute_apply(
        cau_hinh=_CAU_HINH, claims=claims, rows=_ROWS, api=_ApiHuyLucDong()
    )

    assert ket_qua.ket_cuc is KetCuc.COMPLETED
    assert ket_qua.deactivated == 3


async def test_tu_choi_DUT_KHOAT_cua_database_la_FAILED_khong_phai_unknown():
    """🔴 401/403/400: database đã trả lời dứt khoát và KHÔNG tạo lượt.

    Ghi ``outcome_unknown`` cho ca này là bắt người vận hành đi đối soát một
    lượt chưa từng tồn tại — và chặn mọi phiếu mới cho tới khi họ làm xong.
    """
    _, claims = _phieu()

    class _TuChoi(_ApiHong):
        def __init__(self):
            super().__init__("unknown", None, no_o_buoc="open_not_created")

        async def open_sync_run(self, nam, token, raw_count, *, la_lan_chay_lai=False):
            raise DormSyncOpenNotCreatedError(
                "Mở lượt đồng bộ thất bại (HTTP 401, request-id x)."
            )

    api = _TuChoi()
    ket_qua = await execute_apply(
        cau_hinh=_CAU_HINH, claims=claims, rows=_ROWS, api=api
    )

    assert ket_qua.ket_cuc is KetCuc.FAILED
    assert api.so_lan_doi_soat == 0


def test_ca_absent_van_la_mot_DormSyncOpenNotCreatedError():
    """Ba đường vào khác nhau, cùng một sự thật ⇒ cùng một kiểu.

    Người gọi chỉ hỏi ``isinstance``; thêm một nhánh chắc chắn về sau mà quên
    cập nhật danh sách kiểu là cách bản trước để 401 rơi thành
    ``outcome_unknown``.
    """
    assert issubclass(DormSyncOpenAbsentError, DormSyncOpenNotCreatedError)
    assert not issubclass(DormSyncOpenUnknownError, DormSyncOpenNotCreatedError)


@pytest.mark.parametrize(
    "ket_qua_luu, vi_sao",
    [
        ([1, 2, 3], "JSONB là list, không phải object"),
        ("xong", "JSONB là chuỗi"),
        (42, "JSONB là số"),
        ({"ktx_run_id": 42, "upserted": 2, "blocked": 0, "deactivated": 3},
         "thiếu `status`"),
        ({"status": "failed", "ktx_run_id": 42, "upserted": 2, "blocked": 0,
          "deactivated": 3}, "`status` không phải completed"),
        ({"status": "completed", "ktx_run_id": 42, "blocked": 0, "deactivated": 3},
         "thiếu `upserted`"),
        ({"status": "completed", "ktx_run_id": 42, "upserted": "2", "blocked": 0,
          "deactivated": 3}, "`upserted` là chuỗi"),
        ({"status": "completed", "ktx_run_id": 42, "upserted": True, "blocked": 0,
          "deactivated": 3}, "`upserted` là bool"),
        ({"status": "completed", "ktx_run_id": 42, "upserted": -1, "blocked": 0,
          "deactivated": 3}, "`upserted` âm"),
    ],
)
async def test_cached_result_HONG_thi_fail_closed(monkeypatch, ket_qua_luu, vi_sao):
    """🔴 ``result`` là JSONB — nó nhận được cả list, cả số, cả object thiếu trường.

    Bản trước gọi thẳng ``so_cai.result.get(...)`` và một giá trị list làm nổ
    ``AttributeError`` ra khỏi service: người bấm nhận 500 trần cho một sự cố có
    tên rất rõ là "sổ sách hỏng".

    Con số ở đây đi thẳng vào màn hình "đã đồng bộ xong" và vào sổ đối soát.
    """
    token, claims = _phieu()
    hang = _so_cai(status="completed", claims=claims)
    hang.result = ket_qua_luu

    with pytest.raises(BusinessRuleViolation):
        await _chuan_bi(monkeypatch, token=token, so_cai_co_san=hang)


def test_execute_apply_KHONG_bao_gio_ne_khoi_KetQuaGhi():
    """Soi mã: mọi đường ra của hàm phải là `return KetQuaGhi` hoặc `return ket_qua`.

    Ca hành vi ở trên phủ từng đường một; ca này khoá lại vế "không có đường
    nào khác" — một `raise` mới thêm vào sau này sẽ lọt qua mọi ca kia.
    """
    import inspect

    import app.services.dorm_sync_apply_service as m

    ma = inspect.getsource(m.execute_apply)

    # Chỉ được `raise` bên trong khối `try` của thân chính (BusinessRuleViolation
    # khi lô lệch) — nó nằm trong tầm bắt. Ngoài ra không có `raise` nào khác.
    assert ma.count("raise ") == 1, "có đường ném mới chưa được bọc"
    assert "except asyncio.CancelledError" in ma
    assert "except (Exception, asyncio.CancelledError)" in ma
