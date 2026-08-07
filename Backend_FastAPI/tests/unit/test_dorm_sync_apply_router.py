# -*- coding: utf-8 -*-
"""Router ``POST /apply``: trình tự hai transaction và các nhánh kết cục.

🔴 Bất biến trung tâm: **COMMIT A phải xong TRƯỚC khi có mutation nào sang hệ
ký túc xá.** Đảo lại thì một lượt đã ghi thật bên kia có thể không để lại dấu
nào trong sổ cái — và lần bấm sau sẽ chạy lại nó.

Các ca dưới đây ghi lại DÃY sự kiện chứ không kiểm sự hiện diện: kiểm hiện diện
thì đảo thứ tự vẫn xanh, mà đảo thứ tự đúng là lỗi cần chặn.
"""

import uuid

import pytest
from types import SimpleNamespace

import app.routers.admin_v2_dorm_sync as router_module
from app.services.dorm_sync_apply_service import (
    KetCuc,
    KetQuaChuanBi,
    KetQuaGhi,
    TrangThaiChuanBi,
)
from app.services.dorm_sync_config import DormSyncConfig
from app.services.dorm_sync_service import OpenSyncRunResult, TargetSnapshot
from app.services.dorm_sync_snapshot import (
    build_source_snapshot,
    hash_source_snapshot,
    phat_hanh_token,
)
from app.utils.exceptions import DormSyncOperationBlockedError

pytestmark = pytest.mark.unit

_CAU_HINH = DormSyncConfig(
    "https://x.supabase.co", "khoa-gia", "x", "postgres:5432/qlts", "1"
)
_FP = "c" * 32


def _hang_nguon(**ghi_de):
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


_ROWS = [_hang_nguon(), _hang_nguon(qlts_profile_id=9002)]


def _phieu_that():
    """Phiếu ký THẬT, khớp `_ROWS` — để `prepare_apply` bản thật chạy được.

    ⚠️ Ký bằng CHÍNH `settings.SECRET_KEY` và mốc thời gian THẬT: router dùng
    hai giá trị đó, nên một phiếu ký bằng khoá test sẽ chết ở bước xác thực chữ
    ký và ca này không kiểm được thứ nó khai là đang kiểm.
    """
    import time

    from app.config import settings

    return phat_hanh_token(
        secret=settings.SECRET_KEY,
        actor_id=7,
        academic_year=2026,
        source_hash=hash_source_snapshot(build_source_snapshot(_ROWS)),
        target_fingerprint=_FP,
        now_ts=int(time.time()),
    )


class _Db:
    """Session giả ghi lại thứ tự commit/rollback."""

    def __init__(self, nhat_ky, *, commit_b_hong=False, commit_a_hong=False):
        self.nhat_ky = nhat_ky
        self.so_commit = 0
        self.commit_b_hong = commit_b_hong
        self.commit_a_hong = commit_a_hong

    async def commit(self):
        self.so_commit += 1
        nhan = "commit_A" if self.so_commit == 1 else "commit_B"
        if self.so_commit == 1 and self.commit_a_hong:
            self.nhat_ky.append("commit_A_HONG")
            raise RuntimeError("commit A hỏng")
        if self.so_commit == 2 and self.commit_b_hong:
            self.nhat_ky.append("commit_B_HONG")
            raise RuntimeError("commit B hỏng")
        self.nhat_ky.append(nhan)

    async def rollback(self):
        self.nhat_ky.append("rollback")


def _so_cai(status="running", **ghi_de):
    base = dict(
        id=11,
        operation_id=uuid.uuid4(),
        actor_id=7,
        academic_year=2026,
        snapshot_hash="s" * 64,
        snapshot_version=1,
        status=status,
        ktx_run_id=42 if status == "completed" else None,
        result=(
            {
                "status": "completed",
                "ktx_run_id": 42,
                "upserted": 5,
                "blocked": 1,
                "deactivated": 2,
            }
            if status == "completed"
            else None
        ),
    )
    base.update(ghi_de)
    return SimpleNamespace(**base)


def _claims(op_id=None):
    return SimpleNamespace(
        operation_id=op_id or uuid.uuid4(), academic_year=2026
    )


def _gan(
    monkeypatch,
    nhat_ky,
    *,
    chuan_bi,
    ket_qua=None,
    record_hong=False,
):
    async def _prepare(db, **kw):
        nhat_ky.append("prepare")
        return chuan_bi

    async def _execute(**kw):
        nhat_ky.append("execute")
        return ket_qua

    async def _record(db, so_cai, **kw):
        nhat_ky.append("record")
        if record_hong:
            raise RuntimeError("ghi sổ hỏng")
        return so_cai

    monkeypatch.setattr(router_module, "prepare_apply", _prepare)
    monkeypatch.setattr(router_module, "execute_apply", _execute)
    monkeypatch.setattr(router_module, "record_result", _record)
    monkeypatch.setattr(
        router_module.DormSyncConfig,
        "from_settings",
        classmethod(lambda cls, settings=None: _CAU_HINH),
    )


async def _goi(db):
    return await router_module.ghi_dong_bo.__wrapped__(
        request=None,
        than=SimpleNamespace(preview_token="phieu"),
        db=db,
        current_user=SimpleNamespace(id=7),
    )


# ---------------------------------------------------------------------------
# Trình tự hai transaction
# ---------------------------------------------------------------------------


async def test_trinh_tu_prepare_commitA_execute_record_commitB(monkeypatch):
    """🔴 COMMIT A xong TRƯỚC khi chạm sang hệ ký túc xá.

    Đảo lại thì một lượt đã ghi thật bên kia có thể không để lại dấu nào trong
    sổ cái, và lần bấm sau chạy lại nó — mỗi lượt hạ cờ đủ-điều-kiện của cả một
    cohort.

    ``execute`` nằm GIỮA hai commit, tức ngoài mọi transaction QLTS: nó mất vài
    chục giây, và giữ transaction suốt thời gian đó là khoá sổ cái trong lúc
    chờ mạng.
    """
    nhat_ky = []
    so_cai = _so_cai()
    _gan(
        monkeypatch,
        nhat_ky,
        chuan_bi=KetQuaChuanBi(
            trang_thai=TrangThaiChuanBi.SAN_SANG,
            so_cai=so_cai,
            claims=_claims(so_cai.operation_id),
            rows=[object()],
        ),
        ket_qua=KetQuaGhi(
            ket_cuc=KetCuc.COMPLETED,
            ktx_run_id=42,
            upserted=5,
            blocked=1,
            deactivated=2,
        ),
    )

    phan_hoi = await _goi(_Db(nhat_ky))

    assert nhat_ky == [
        "prepare",
        "commit_A",
        "execute",
        "record",
        "commit_B",
    ]
    assert phan_hoi.outcome == "completed"
    assert phan_hoi.ledger_saved is True
    assert phan_hoi.deactivated == 2


# 🔴 Bốn endpoint MUTATION của hệ ký túc xá.
#
# Ca commit-A phải chứng minh KHÔNG endpoint nào trong số này được gọi. Kiểm
# `"execute" not in nhat_ky` là chưa đủ: ai đó dời một mutation vào
# `prepare_apply` thì ca đó vẫn xanh, mà bất biến thì đã vỡ.
_MUTATION_KTX = (
    "POST /sync_runs",
    "POST /rpc/upsert_students_batch",
    "POST /rpc/finalize_sync_run",
    "POST /rpc/fail_sync_run",
)


class _ApiGhiEndpoint:
    """Ghi lại TỪNG method + endpoint đã gọi sang hệ ký túc xá."""

    def __init__(self, nhat_ky):
        self.nhat_ky = nhat_ky

    def __call__(self, *a, **kw):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def fetch_open_academic_years(self):
        self.nhat_ky.append("GET /dorm_academic_years")
        return (2026,)

    async def fetch_target_snapshot(self, nam, cohort_ids):
        # RPC nhưng CHỈ ĐỌC — `prepare_apply` bắt buộc gọi nó để đối chiếu dấu
        # vân tay, nên nó KHÔNG nằm trong danh sách mutation.
        self.nhat_ky.append("POST /rpc/dorm_sync_target_snapshot")
        return TargetSnapshot(rows=(), fingerprint=_FP)

    async def open_sync_run(self, nam, token, raw_count, *, la_lan_chay_lai=False):
        self.nhat_ky.append("POST /sync_runs")
        return OpenSyncRunResult(42)

    async def upsert_students(self, run_id, rows):
        self.nhat_ky.append("POST /rpc/upsert_students_batch")
        return len(rows), 0

    async def finalize_sync_run(self, run_id, **kw):
        self.nhat_ky.append("POST /rpc/finalize_sync_run")
        return 2

    async def reconcile_after_failure(self, run_id):
        self.nhat_ky.append("POST /rpc/fail_sync_run")
        return "marked_failed", {"id": run_id, "status": "failed"}


def _gan_that(monkeypatch, nhat_ky, *, hang_da_co=None):
    """Nối RUỘT THẬT của cả ba pha, chỉ giả tầng adapter.

    ⚠️ Cả `prepare_apply` lẫn `execute_apply` đều chạy bản thật, và cả hai dùng
    CHUNG một `DormApi` giả biết ghi endpoint. Nhờ vậy, dời một mutation từ
    `execute_apply` sang `prepare_apply` KHÔNG giấu được nó khỏi ca kiểm.
    """
    import app.services.dorm_sync_apply_service as service_module

    api = _ApiGhiEndpoint(nhat_ky)
    hang_moi = _so_cai()

    async def _lay(db, op_id):
        return hang_da_co

    async def _chen(db, **kw):
        return hang_moi

    async def _cohort(nam, **kw):
        return _ROWS

    async def _activity(db, **kw):
        return None

    monkeypatch.setattr(service_module, "DormApi", api)
    monkeypatch.setattr(service_module, "fetch_cohort", _cohort)
    monkeypatch.setattr(service_module, "lay_theo_operation_id", _lay)
    monkeypatch.setattr(service_module, "chen_neu_chua_co", _chen)
    monkeypatch.setattr(service_module, "log_activity", _activity)
    monkeypatch.setattr(service_module, "cap_nhat_ket_qua", _cap_nhat_gia)
    monkeypatch.setattr(
        router_module.DormSyncConfig,
        "from_settings",
        classmethod(lambda cls, settings=None: _CAU_HINH),
    )
    return hang_moi


async def _cap_nhat_gia(db, so_cai, **kw):
    so_cai.status = kw["status"]
    so_cai.ktx_run_id = kw.get("ktx_run_id")
    so_cai.result = kw.get("result")
    return so_cai


async def test_commit_A_hong_thi_KHONG_endpoint_MUTATION_nao_duoc_goi(monkeypatch):
    """🔴 Ghi lại TỪNG method + endpoint, không chỉ đếm lời gọi service.

    Bất biến khi commit A hỏng không phải "hàm execute chưa chạy" mà là "chưa
    một mutation nào tới hệ ký túc xá". Hai điều đó khác nhau: ai đó dời
    `open_sync_run` vào `prepare_apply` thì vế thứ nhất vẫn đúng trong khi vế
    thứ hai đã vỡ — và bên kia còn lại một lượt `running` khoá cứng năm học,
    cho một request mà sổ cái QLTS vừa rollback sạch.

    ⚠️ Ca này chạy RUỘT THẬT của cả `prepare_apply` lẫn `execute_apply`; chỉ
    tầng adapter là giả, và nó dùng CHUNG một đối tượng ghi endpoint.
    """
    nhat_ky_http = []
    _gan_that(monkeypatch, nhat_ky_http)

    token, _ = _phieu_that()
    db = _Db([], commit_a_hong=True)

    with pytest.raises(RuntimeError):
        await router_module.ghi_dong_bo.__wrapped__(
            request=None,
            than=SimpleNamespace(preview_token=token),
            db=db,
            current_user=SimpleNamespace(id=7),
        )

    da_goi = set(nhat_ky_http)
    for endpoint in _MUTATION_KTX:
        assert endpoint not in da_goi, f"đã gọi {endpoint} trước khi commit A xong"

    # Vế ĐẢO: bước chuẩn bị VẪN phải đọc đích — nếu không, ca trên xanh chỉ vì
    # chẳng có lời gọi nào cả.
    assert "POST /rpc/dorm_sync_target_snapshot" in da_goi


async def test_duong_thanh_cong_co_goi_du_ba_mutation(monkeypatch):
    """Vế ĐẢO của ca trên: khi commit A xong, ba mutation phải chạy thật.

    Không có nó thì một bản vá bỏ hẳn `execute_apply` vẫn cho ca commit-A xanh.
    """
    nhat_ky_http = []
    _gan_that(monkeypatch, nhat_ky_http)

    token, _ = _phieu_that()
    await router_module.ghi_dong_bo.__wrapped__(
        request=None,
        than=SimpleNamespace(preview_token=token),
        db=_Db([]),
        current_user=SimpleNamespace(id=7),
    )

    da_goi = set(nhat_ky_http)
    assert "POST /sync_runs" in da_goi
    assert "POST /rpc/upsert_students_batch" in da_goi
    assert "POST /rpc/finalize_sync_run" in da_goi


# ---------------------------------------------------------------------------
# Các nhánh không chạm KTX
# ---------------------------------------------------------------------------


async def test_DA_XONG_tra_ket_qua_cu_va_KHONG_goi_KTX(monkeypatch):
    """Idempotent: cùng phiếu, cùng kết quả — không chạy lại."""
    nhat_ky = []
    so_cai = _so_cai(status="completed")
    _gan(
        monkeypatch,
        nhat_ky,
        chuan_bi=KetQuaChuanBi(
            trang_thai=TrangThaiChuanBi.DA_XONG,
            so_cai=so_cai,
            claims=_claims(so_cai.operation_id),
            thong_diep="đã chạy xong trước đó",
        ),
    )

    phan_hoi = await _goi(_Db(nhat_ky))

    assert nhat_ky == ["prepare"], "đã chạm KTX cho một lượt đã xong"
    assert phan_hoi.outcome == "completed"
    assert phan_hoi.ktx_run_id == 42
    assert (phan_hoi.upserted, phan_hoi.blocked, phan_hoi.deactivated) == (5, 1, 2)


async def test_KHONG_CHAY_LAI_tra_409_va_KHONG_goi_KTX(monkeypatch):
    """409, không 400: người gửi không sai gì — họ tới sau một lượt còn dở."""
    nhat_ky = []
    so_cai = _so_cai(status="running")
    _gan(
        monkeypatch,
        nhat_ky,
        chuan_bi=KetQuaChuanBi(
            trang_thai=TrangThaiChuanBi.KHONG_CHAY_LAI,
            so_cai=so_cai,
            claims=_claims(so_cai.operation_id),
            thong_diep="Lượt đồng bộ này đang chạy.",
            loi_chan=DormSyncOperationBlockedError(
                "Lượt đồng bộ này đang chạy.",
                operation_status="running",
                next_action="wait",
            ),
        ),
    )

    with pytest.raises(DormSyncOperationBlockedError):
        await _goi(_Db(nhat_ky))

    assert nhat_ky == ["prepare"]


# ---------------------------------------------------------------------------
# Commit B hỏng sau khi KTX đã đổi
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("record_hong", [True, False])
async def test_ghi_so_hong_sau_COMPLETED_van_tra_thanh_cong_kem_canh_bao(
    monkeypatch, record_hong
):
    """🔴 Hệ ký túc xá ĐÃ đổi rồi.

    Ném 500 ở đây là nói với người bấm rằng việc chưa xảy ra — rồi họ bấm lại,
    và lượt thứ hai chạy chồng lên. Trả thành công kèm cảnh báo: việc đã xong,
    chỉ sổ sách là thiếu, và mã lượt đủ để đối soát tay.

    Hai đường hỏng đều phải cho cùng kết luận: `record_result` ném, hoặc chính
    ``COMMIT B`` ném.
    """
    nhat_ky = []
    so_cai = _so_cai()
    _gan(
        monkeypatch,
        nhat_ky,
        chuan_bi=KetQuaChuanBi(
            trang_thai=TrangThaiChuanBi.SAN_SANG,
            so_cai=so_cai,
            claims=_claims(so_cai.operation_id),
            rows=[object()],
        ),
        ket_qua=KetQuaGhi(
            ket_cuc=KetCuc.COMPLETED, ktx_run_id=42, upserted=5, deactivated=2
        ),
        record_hong=record_hong,
    )

    phan_hoi = await _goi(_Db(nhat_ky, commit_b_hong=not record_hong))

    assert phan_hoi.outcome == "completed"
    assert phan_hoi.ledger_saved is False
    assert phan_hoi.ktx_run_id == 42
    assert "sổ đối soát" in phan_hoi.message
    assert "rollback" in nhat_ky


# ---------------------------------------------------------------------------
# Kết cục hỏng — thông điệp nói việc phải làm, không lộ chi tiết
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ket_cuc, phai_co",
    [
        (KetCuc.FAILED, "Bấm Xem trước lại"),
        (KetCuc.OUTCOME_UNKNOWN, "ĐỪNG bấm lại"),
    ],
)
async def test_ket_cuc_hong_khong_lo_chuoi_loi_noi_bo(monkeypatch, ket_cuc, phai_co):
    """``ly_do`` là chuỗi exception phía client — nó mang được request-id,
    hostname, và bất cứ thứ gì thư viện HTTP nhét vào."""
    nhat_ky = []
    so_cai = _so_cai()
    BI_MAT = "RuntimeError: connect to 10.0.0.5:5432 failed, request-id abc123"
    _gan(
        monkeypatch,
        nhat_ky,
        chuan_bi=KetQuaChuanBi(
            trang_thai=TrangThaiChuanBi.SAN_SANG,
            so_cai=so_cai,
            claims=_claims(so_cai.operation_id),
            rows=[object()],
        ),
        ket_qua=KetQuaGhi(ket_cuc=ket_cuc, ktx_run_id=42, ly_do=BI_MAT),
    )

    phan_hoi = await _goi(_Db(nhat_ky))

    assert phan_hoi.outcome == str(ket_cuc)
    assert phai_co in phan_hoi.message
    assert "10.0.0.5" not in phan_hoi.message
    assert "abc123" not in phan_hoi.message
    # Mã lượt vẫn có để đối soát tay.
    assert phan_hoi.ktx_run_id == 42


# ---------------------------------------------------------------------------
# Ranh giới router
# ---------------------------------------------------------------------------


def test_router_re_nhanh_theo_KIEU_khong_doc_trang_thai_tho():
    """Router không được đọc ``so_cai.status`` hay parse chuỗi exception.

    Máy trạng thái sống ở service; một bản sao ở router sẽ lệch ngay lần sửa
    đầu, và lúc đó hai tầng nói hai chuyện khác nhau về cùng một lượt.
    """
    import inspect

    ma = inspect.getsource(router_module.ghi_dong_bo.__wrapped__)
    # ⚠️ Bỏ chú thích và docstring trước khi soi.
    #
    # Chính những dòng ấy NHẮC `so_cai.status` để giải thích vì sao KHÔNG đọc
    # nó — một phép `in` thô sẽ đỏ vì đúng dòng giải thích, và người sửa sau sẽ
    # gỡ lời giải thích thay vì giữ ràng buộc.
    ma_thuc = "\n".join(
        d for d in ma.splitlines() if not d.strip().startswith("#")
    )
    than = ma_thuc.split('"""')
    ma_thuc = than[0] + "".join(than[2:]) if len(than) > 2 else ma_thuc

    assert "TrangThaiChuanBi.DA_XONG" in ma_thuc
    assert "TrangThaiChuanBi.KHONG_CHAY_LAI" in ma_thuc
    # Máy trạng thái sống ở service; router không được dựng bản sao.
    assert "so_cai.status" not in ma_thuc
    assert "str(exc)" not in ma_thuc
    assert "ket_qua.ly_do" not in ma_thuc
    assert "== 'completed'" not in ma_thuc and '== "completed"' not in ma_thuc


def test_endpoint_apply_that_su_bi_limiter_boc():
    """`@router.post` NGOÀI, `@limiter.limit` TRONG — soi hàm ĐÃ ĐĂNG KÝ.

    Đảo thứ tự thì route giữ hàm thô và endpoint chạy không giới hạn, trong khi
    ``lay_boi_canh``/``ghi_dong_bo`` ở cấp module vẫn có ``__wrapped__``.
    """
    tuyen = [
        r
        for r in router_module.router.routes
        if getattr(r, "path", "") == "/api/v2/admin/dorm-sync/apply"
    ]
    assert len(tuyen) == 1
    assert tuyen[0].endpoint is router_module.ghi_dong_bo
    assert hasattr(tuyen[0].endpoint, "__wrapped__")


async def test_rollback_cung_hong_van_tra_thanh_cong(monkeypatch):
    """🔴 ``rollback`` hỏng vì CÙNG lý do đã làm ``commit`` hỏng.

    Mất kết nối làm cả hai cùng ném. Để cái thứ hai bay ra ngoài là đánh mất
    đúng bảo đảm vừa dựng: endpoint thoát 500 cho một lượt mà hệ ký túc xá đã
    hoàn tất, rồi người bấm thử lại và lượt thứ hai chạy chồng lên.
    """
    nhat_ky = []
    so_cai = _so_cai()

    class _DbRollbackHong(_Db):
        async def rollback(self):
            self.nhat_ky.append("rollback_HONG")
            raise RuntimeError("rollback connection lost")

    _gan(
        monkeypatch,
        nhat_ky,
        chuan_bi=KetQuaChuanBi(
            trang_thai=TrangThaiChuanBi.SAN_SANG,
            so_cai=so_cai,
            claims=_claims(so_cai.operation_id),
            rows=[object()],
        ),
        ket_qua=KetQuaGhi(
            ket_cuc=KetCuc.COMPLETED, ktx_run_id=42, upserted=5, deactivated=2
        ),
    )

    phan_hoi = await _goi(_DbRollbackHong(nhat_ky, commit_b_hong=True))

    assert phan_hoi.outcome == "completed"
    assert phan_hoi.ledger_saved is False
    assert phan_hoi.ktx_run_id == 42
    assert "rollback_HONG" in nhat_ky


async def test_HUY_o_transaction_B_van_tra_thanh_cong(monkeypatch):
    """``CancelledError`` KHÔNG phải ``Exception``.

    Một lần huỷ rơi vào đúng lúc ghi sổ sẽ xoá sạch bảo đảm "KTX xong vẫn trả
    200" nếu nhánh bắt chỉ khai ``Exception``.
    """
    import asyncio

    nhat_ky = []
    so_cai = _so_cai()

    class _DbHuy(_Db):
        async def commit(self):
            self.so_commit += 1
            if self.so_commit == 1:
                self.nhat_ky.append("commit_A")
                return
            self.nhat_ky.append("commit_B_HUY")
            raise asyncio.CancelledError()

    _gan(
        monkeypatch,
        nhat_ky,
        chuan_bi=KetQuaChuanBi(
            trang_thai=TrangThaiChuanBi.SAN_SANG,
            so_cai=so_cai,
            claims=_claims(so_cai.operation_id),
            rows=[object()],
        ),
        ket_qua=KetQuaGhi(
            ket_cuc=KetCuc.COMPLETED, ktx_run_id=42, upserted=5, deactivated=2
        ),
    )

    phan_hoi = await _goi(_DbHuy(nhat_ky))

    assert phan_hoi.outcome == "completed"
    assert phan_hoi.ledger_saved is False


async def test_thong_diep_FAILED_khong_noi_KTX_khong_doi(monkeypatch):
    """🔴 Điều duy nhất chắc chắn là KHÔNG ai bị hạ cờ.

    Các lô ``upsert`` gửi đi TRƯỚC lúc hỏng vẫn nằm bên kia — chúng là dữ liệu
    thật, không bị rút lại. Nói "hệ ký túc xá không thay đổi" là để người vận
    hành bỏ qua một khác biệt có thật giữa hai hệ.
    """
    nhat_ky = []
    so_cai = _so_cai()
    _gan(
        monkeypatch,
        nhat_ky,
        chuan_bi=KetQuaChuanBi(
            trang_thai=TrangThaiChuanBi.SAN_SANG,
            so_cai=so_cai,
            claims=_claims(so_cai.operation_id),
            rows=[object()],
        ),
        ket_qua=KetQuaGhi(ket_cuc=KetCuc.FAILED, ktx_run_id=42),
    )

    phan_hoi = await _goi(_Db(nhat_ky))

    thong_diep = phan_hoi.message
    assert "không thay đổi" not in thong_diep
    assert "KHÔNG ai bị hạ cờ" in thong_diep
    assert "vẫn còn" in thong_diep


# ---------------------------------------------------------------------------
# Hợp đồng MÁY ĐỌC ĐƯỢC cho ba trạng thái chặn
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "trang_thai_so, hanh_dong",
    [
        ("running", "wait"),
        ("failed", "preview_again"),
        ("outcome_unknown", "manual_reconcile"),
    ],
)
async def test_ba_trang_thai_chan_cho_ba_payload_KHAC_NHAU(
    monkeypatch, trang_thai_so, hanh_dong
):
    """🔴 Đi qua ĐÚNG handler thật; frontend chỉ đọc được thứ ra tới đây.

    Ba trạng thái đòi ba hành động TRÁI NGƯỢC nhau:

    * ``running``         → chờ, tuyệt đối không bấm lại;
    * ``failed``          → bấm Xem trước lại;
    * ``outcome_unknown`` → KHÔNG chạy lại, đối soát tay.

    Bản trước nén cả ba thành ``ConflictError``: cùng 409, cùng ``error_code``,
    chỉ khác câu tiếng Việt — mà ``error-handler.ts`` cố ý CHE ``detail`` của
    mã ``CONFLICT``. Frontend khi đó không còn gì để rẽ nhánh, và ca đắt nhất
    (``outcome_unknown``) sẽ được mời "thử lại".
    """
    import json

    from app.middleware.exception_handlers import base_app_exception_handler
    from app.services.dorm_sync_apply_service import _xet_so_cai_cu

    so_cai = _so_cai(status=trang_thai_so)
    claims = _claims(so_cai.operation_id)
    so_cai.snapshot_hash = claims_snapshot_hash = so_cai.snapshot_hash
    claims = SimpleNamespace(
        operation_id=so_cai.operation_id,
        academic_year=so_cai.academic_year,
        snapshot_hash=claims_snapshot_hash,
        snapshot_version=so_cai.snapshot_version,
    )

    ket_qua = _xet_so_cai_cu(so_cai, claims, so_cai.actor_id)
    assert ket_qua.trang_thai is TrangThaiChuanBi.KHONG_CHAY_LAI

    yeu_cau = SimpleNamespace(
        url=SimpleNamespace(path="/api/v2/admin/dorm-sync/apply"), method="POST"
    )
    # ⚠️ `await` thẳng. Ca này CHẠY TRONG một event loop rồi (pytest-asyncio),
    # nên `run_until_complete` sẽ ném "Cannot run the event loop while another
    # loop is running".
    phan_hoi = await base_app_exception_handler(yeu_cau, ket_qua.loi_chan)
    than = json.loads(phan_hoi.body.decode())

    assert phan_hoi.status_code == 409
    assert than["error_code"] == "DORM_SYNC_OPERATION_BLOCKED"
    assert than["operation_status"] == trang_thai_so
    assert than["next_action"] == hanh_dong


async def test_payload_chan_KHONG_ro_du_lieu_noi_bo(monkeypatch):
    """Chỉ hai chuỗi hằng ra ngoài — không mã lượt, không tên người, không lý do.

    ``operator_detail`` và ``context`` ở lại log; ``public_payload`` là trường
    tách riêng, mặc định rỗng, người ném lỗi phải chủ động điền.
    """
    import json

    from app.middleware.exception_handlers import base_app_exception_handler

    loi = DormSyncOperationBlockedError(
        "Lượt #4127 của Nguyễn Văn An treo ở sync_run 88 trên 10.0.0.5",
        operation_status="outcome_unknown",
        next_action="manual_reconcile",
    )

    yeu_cau = SimpleNamespace(
        url=SimpleNamespace(path="/api/v2/admin/dorm-sync/apply"), method="POST"
    )
    phan_hoi = await base_app_exception_handler(yeu_cau, loi)
    than = phan_hoi.body.decode()

    assert "4127" not in than
    assert "Nguyễn Văn An" not in than
    assert "10.0.0.5" not in than
    assert set(json.loads(than)) == {
        "operation_status",
        "next_action",
        "detail",
        "error_code",
    }
    # Người vận hành vẫn có bản đầy đủ.
    assert "4127" in loi.operator_detail


def test_hanh_dong_do_SERVICE_quyet_dinh_khong_phai_router():
    """Router không được đọc ``so_cai.status`` rồi tự ánh xạ.

    Một bản sao của máy trạng thái ở tầng router sẽ lệch ngay lần sửa đầu, và
    lúc đó hai tầng nói hai chuyện khác nhau về cùng một lượt.
    """
    import inspect

    from app.services.dorm_sync_apply_service import HanhDongTiepTheo

    ma = "\n".join(
        d
        for d in inspect.getsource(router_module.ghi_dong_bo.__wrapped__).splitlines()
        if not d.strip().startswith("#")
    )

    assert "chuan_bi.loi_chan" in ma
    # ⚠️ Tìm chuỗi TRONG NGOẶC KÉP, không tìm chuỗi trần: `"wait"` là chuỗi con
    # của chính từ `await` nằm khắp file, nên phép `in` thô luôn đỏ và ca này sẽ
    # bị gỡ vì tưởng nó viết sai.
    for hanh_dong in HanhDongTiepTheo:
        for dang in (f'"{hanh_dong}"', f"'{hanh_dong}'"):
            assert dang not in ma, f"router tự ánh xạ hành động: {hanh_dong}"
    assert "DormSyncOperationBlockedError(" not in ma
