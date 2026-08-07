# -*- coding: utf-8 -*-
"""Ba pha của bước GHI: chuẩn bị, thực thi, đóng sổ.

🔴 Bất biến trung tâm: **một phiếu chạy đúng một lần, và chỉ chạy khi trạng
thái hai đầu vẫn đúng thứ người bấm đã nhìn.**

Thứ tự trong ``prepare_apply`` LÀ hàng rào — tra sổ TRƯỚC khi đọc nguồn. Các ca
dưới đây ghi lại DÃY lời gọi chứ không kiểm sự hiện diện: kiểm hiện diện thì
đảo thứ tự vẫn xanh, mà đảo thứ tự đúng là lỗi cần chặn.
"""

import uuid

import pytest
from types import SimpleNamespace

from app.services.dorm_sync_apply_service import (
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
from app.utils.exceptions import DormSyncTokenError

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


def _so_cai(status="running", **ghi_de):
    base = dict(
        id=11,
        operation_id=uuid.uuid4(),
        actor_id=7,
        academic_year=2026,
        snapshot_hash="s" * 64,
        snapshot_version=1,
        status=status,
        ktx_run_id=None,
        result=None,
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
    monkeypatch.setattr(m, "log_audit", _audit)

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
        so_cai_co_san=_so_cai(status=status, operation_id=claims.operation_id),
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
    hang_thang = _so_cai(status="running", operation_id=claims.operation_id)
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
    monkeypatch.setattr(m, "log_audit", _audit)

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
        await db.flush()
        return so_cai

    async def _audit(db, entity, eid, action, **kw):
        da_goi.append(("audit", action))
        return None

    monkeypatch.setattr(m, "cap_nhat_ket_qua", _cap_nhat)
    monkeypatch.setattr(m, "log_audit", _audit)

    db = _DbGia()
    so_cai = _so_cai()

    await record_result(
        db,
        so_cai,
        actor_id=7,
        status="completed",
        ket_qua=KetQuaGhi(ktx_run_id=42, upserted=2, blocked=0, deactivated=3),
    )

    assert db.da_commit == 0, "service KHÔNG được commit"
    assert db.da_flush >= 1
    assert da_goi == [("cap_nhat", "completed"), ("audit", "dorm_sync_completed")]
    assert so_cai.result["ktx_run_id"] == 42
    assert so_cai.result["deactivated"] == 3
