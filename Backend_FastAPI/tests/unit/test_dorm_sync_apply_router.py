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
from app.utils.exceptions import ConflictError

pytestmark = pytest.mark.unit

_CAU_HINH = DormSyncConfig(
    "https://x.supabase.co", "khoa-gia", "x", "postgres:5432/qlts", "1"
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


async def test_commit_A_hong_thi_CHUA_cham_sang_KTX(monkeypatch):
    """Bất biến khi commit A hỏng: chưa gọi một mutation nào sang hệ kia."""
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
        ket_qua=KetQuaGhi(ket_cuc=KetCuc.COMPLETED, ktx_run_id=42),
    )

    with pytest.raises(RuntimeError):
        await _goi(_Db(nhat_ky, commit_a_hong=True))

    assert "execute" not in nhat_ky
    assert nhat_ky == ["prepare", "commit_A_HONG"]


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
        ),
    )

    with pytest.raises(ConflictError):
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
