# -*- coding: utf-8 -*-
"""Danh sách cảnh báo đi THẲNG từ SQL helper của Gate 1, không qua tay Python.

🔴 Vì sao đây là một bất biến riêng, đáng có file test riêng:

``dorm_sync_target_snapshot`` phía KTX đã khai đủ vị từ — ``source = 'qlts'``
(loại nhóm nhập tay), ``deleted_at is null``, ``source_eligible``, và
``a.status in ('active', 'cho_duyet')``. Mỗi vế trong đó là một quyết định đã
được cân nhắc và đã có ca đau: thiếu ``source = 'qlts'`` thì 164 hồ sơ nhập tay
bị báo nhầm là "sắp mất cờ"; thiếu ``cho_duyet`` thì một người đang chờ duyệt
chỗ ở biến mất khỏi màn hình cảnh báo dù họ vẫn đang giữ giường.

Dựng lại bất kỳ vế nào trong số đó bằng Python là tạo **hai** định nghĩa cho
cùng một câu hỏi. Chúng khớp hôm nay và lệch vào ngày ai đó sửa một bên — mà
bên lệch sẽ là bên người bấm NHÌN THẤY, không phải bên database dùng để chốt.

Nên quy tắc: ``snapshot_dich.rows`` là NGUỒN DUY NHẤT. QLTS không lọc, không
dựng set, không sắp lại, không tính vị từ. Chỉ được **chiếu xuống** đúng sáu
trường công khai ở tầng router.
"""

import inspect

import pytest
from types import SimpleNamespace

import app.routers.admin_v2_dorm_sync as router_module
from app.services.dorm_sync_config import DormSyncConfig
from app.services.dorm_sync_preview_service import chuan_bi_xem_truoc
from app.services.dorm_sync_service import TargetSnapshot

pytestmark = pytest.mark.unit

_CAU_HINH = DormSyncConfig(
    "https://x.supabase.co", "khoa-gia", "x", "postgres:5432/qlts", "1"
)
_FP = "c" * 32


def _hang_canh_bao(**ghi_de):
    """Một hàng ĐÚNG hình dạng helper trả về — đủ chín trường."""
    base = dict(
        assignment_id=5,
        qlts_profile_id=138,
        full_name="Trần Thị Bình",
        building_id=1,
        building_name="Toà B",
        room_id=30,
        room_code="B305",
        bed_no=13,
        status="active",
    )
    base.update(ghi_de)
    return base


# 🔴 Helper trả CẢ HAI trạng thái chỗ ở. Đây là dữ liệu thật của production:
# `cho_duyet` là đề nghị đang chờ quản lý duyệt, và người đó VẪN đang giữ
# giường — nên họ phải xuất hiện trên màn hình cảnh báo.
#
# ⚠️ Hàng thứ hai CỐ Ý trùng `qlts_profile_id` với hàng đầu — và dữ liệu ấy
# TRÁI ràng buộc bên KTX.
#
# `students.qlts_profile_id` là `not null unique`, và
# `uq_active_assignment_per_student` (unique một phần trên `student_id` với
# `status in ('active','cho_duyet')`) cấm một người giữ hai hàng cùng lúc;
# `chuyen_phong` đóng hàng cũ trước khi mở hàng mới, trong cùng giao dịch. Nên
# một database lành KHÔNG trả về hình dạng này.
#
# Dựng nó ở đây là cố ý, vì bất biến cần canh không phải "trùng có hợp lệ
# không" mà là: QLTS KHÔNG tự chữa dữ liệu của bên kia. Khử trùng theo
# `qlts_profile_id` ở Python là dựng một định nghĩa THỨ HAI cho câu hỏi mà
# helper đã trả lời — và nếu phản hồi có hỏng thật, phép chữa ấy ném đi một
# giường mà không ai biết. Ta chở nguyên, để cái sai lộ ra ở nơi sửa được.
_ROWS_HELPER = (
    _hang_canh_bao(qlts_profile_id=138, assignment_id=5, status="active", bed_no=13),
    _hang_canh_bao(
        qlts_profile_id=138,
        assignment_id=9,
        status="cho_duyet",
        bed_no=4,
        room_code="B307",
    ),
    _hang_canh_bao(
        qlts_profile_id=205, assignment_id=11, status="cho_duyet", bed_no=7,
        room_code="A101",
    ),
    _hang_canh_bao(
        qlts_profile_id=91, assignment_id=2, status="active", bed_no=2,
        room_code="A102",
    ),
)


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


def _api_gia(rows=_ROWS_HELPER, dem=None):
    class _Api:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def fetch_open_academic_years(self):
            return (2026,)

        async def fetch_target_snapshot(self, nam, cohort_ids):
            if dem is not None:
                dem["n"] += 1
            return TargetSnapshot(rows=tuple(rows), fingerprint=_FP)

    return _Api


async def _xem_truoc(rows=_ROWS_HELPER, dem=None):
    async def _cohort(nam, **kw):
        return [_hang_nguon()]

    return await chuan_bi_xem_truoc(
        cau_hinh=_CAU_HINH,
        secret="khoa-ky",
        actor_id=7,
        academic_year=2026,
        now_ts=1_000_000,
        api_factory=_api_gia(rows, dem),
        cohort_loader=_cohort,
    )


# ---------------------------------------------------------------------------
# Service giữ NGUYÊN thứ helper trả về
# ---------------------------------------------------------------------------


async def test_giu_nguyen_SO_HANG_THU_TU_va_ca_hai_trang_thai():
    """🔴 `active` VÀ `cho_duyet` đều phải qua được, giữ nguyên thứ tự.

    ``cho_duyet`` là đề nghị chờ quản lý duyệt — người đó vẫn đang giữ giường.
    Lọc bỏ nó ở phía QLTS nghĩa là người bấm không thấy tên họ, rồi lượt đồng bộ
    hạ cờ một người đang nằm trên giường mà không ai được cảnh báo.

    Thứ tự cũng là của helper: nó khai ``order by sap_1, sap_2`` để dấu vân tay
    ổn định, nên sắp lại ở Python là dựng một thứ tự thứ hai.
    """
    ket_qua = await _xem_truoc()

    assert len(ket_qua.warnings) == 4
    assert [h["qlts_profile_id"] for h in ket_qua.warnings] == [138, 138, 205, 91]
    assert [h["status"] for h in ket_qua.warnings] == [
        "active",
        "cho_duyet",
        "cho_duyet",
        "active",
    ]
    # 🔴 Hai hàng trùng `qlts_profile_id` phải CÙNG QUA, dù hình dạng ấy trái
    # ràng buộc bên KTX. Khử trùng ở Python là tự chữa dữ liệu của bên kia —
    # và nó ném đi một giường mà không để lại dấu vết nào.
    assert [h["bed_no"] for h in ket_qua.warnings[:2]] == [13, 4]


async def test_fingerprint_di_NGUYEN_VAN_khong_tinh_lai():
    """Dấu vân tay do DATABASE tính; QLTS chỉ chở nó đi."""
    ket_qua = await _xem_truoc()

    assert ket_qua.target_fingerprint == _FP


async def test_DUNG_MOT_loi_goi_cho_ca_danh_sach_lan_dau_van_tay():
    """Hai lời gọi HTTP là hai ảnh chụp — người bấm nhìn A, phiếu ký B."""
    dem = {"n": 0}

    await _xem_truoc(dem=dem)

    assert dem["n"] == 1


async def test_helper_tra_RONG_thi_van_di_tiep():
    """"Không ai sắp mất cờ" là trạng thái HỢP LỆ, không phải lỗi."""
    ket_qua = await _xem_truoc(rows=())

    assert ket_qua.warnings == ()
    assert ket_qua.can_apply is True


# ---------------------------------------------------------------------------
# Router chỉ CHIẾU XUỐNG, không lọc
# ---------------------------------------------------------------------------


async def test_router_chieu_xuong_dung_SAU_truong_va_giu_ca_hai_trang_thai(
    monkeypatch,
):
    """Sáu trường công khai; khoá nội bộ của KTX không ra ngoài.

    Nhưng chiếu xuống KHÔNG được kèm lọc: cả ba hàng phải còn, đúng thứ tự, và
    ``cho_duyet`` vẫn ở đó.
    """
    from app.services import dorm_sync_preview_service as service_module

    async def _cohort(nam, **kw):
        return [_hang_nguon()]

    monkeypatch.setattr(service_module, "DormApi", _api_gia())
    monkeypatch.setattr(service_module, "fetch_cohort", _cohort)
    monkeypatch.setattr(
        router_module.DormSyncConfig,
        "from_settings",
        classmethod(lambda cls, settings=None: _CAU_HINH),
    )

    phan_hoi = await router_module.xem_truoc.__wrapped__(
        request=None,
        than=SimpleNamespace(academic_year=2026),
        current_user=SimpleNamespace(id=7),
    )

    assert len(phan_hoi.warnings) == 4
    assert [w.qlts_profile_id for w in phan_hoi.warnings] == [138, 138, 205, 91]
    assert [w.status for w in phan_hoi.warnings] == [
        "active", "cho_duyet", "cho_duyet", "active",
    ]
    assert [w.bed_no for w in phan_hoi.warnings[:2]] == [13, 4]

    # Đúng sáu trường — khoá nội bộ của hệ KTX không ra ngoài.
    truong = set(phan_hoi.warnings[0].model_dump())
    assert truong == {
        "qlts_profile_id",
        "full_name",
        "building_name",
        "room_code",
        "bed_no",
        "status",
    }
    assert "assignment_id" not in truong
    assert "room_id" not in truong
    assert "building_id" not in truong


# ---------------------------------------------------------------------------
# Không dựng lại vị từ ở phía QLTS
# ---------------------------------------------------------------------------


def test_khong_co_vi_tu_nao_duoc_dung_lai_bang_python():
    """🔴 Vị từ thuộc SQL helper Gate 1. Soi mã ba tầng.

    ``source = 'qlts'``, ``deleted_at is null``, ``source_eligible`` và tập
    trạng thái chỗ ở đều nằm trong ``dorm_sync_target_snapshot``. Dựng lại bất
    kỳ vế nào ở Python là tạo hai định nghĩa cho cùng một câu hỏi — chúng khớp
    hôm nay và lệch vào ngày ai đó sửa một bên, mà bên lệch sẽ là bên người bấm
    NHÌN THẤY.

    ⚠️ Bỏ chú thích trước khi soi: chính chúng nhắc những vế này để giải thích
    vì sao KHÔNG dựng lại, và một phép `in` thô sẽ đỏ vì đúng dòng giải thích.
    """
    from app.services import dorm_sync_apply_service, dorm_sync_preview_service

    for mo_dun in (dorm_sync_preview_service, dorm_sync_apply_service, router_module):
        ma = "\n".join(
            d
            for d in inspect.getsource(mo_dun).splitlines()
            if not d.strip().startswith("#")
        )
        for dau_hieu in (
            '"active"',
            "'active'",
            '"cho_duyet"',
            "'cho_duyet'",
            "thu_cong",
            "source_eligible",
            "deleted_at",
        ):
            assert dau_hieu not in ma, (
                f"{mo_dun.__name__} đang dựng lại vị từ của helper: {dau_hieu}"
            )


def test_schema_HTTP_khong_lo_truong_source():
    """Vế loại nhóm nhập tay thuộc SQL helper, không phải hợp đồng HTTP.

    Thêm ``source`` vào schema là mời frontend tự lọc — tức định nghĩa thứ ba
    cho cùng câu hỏi.
    """
    from app.schemas.dorm_sync import DormSyncWarningRow

    assert "source" not in DormSyncWarningRow.model_fields
