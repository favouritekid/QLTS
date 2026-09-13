# -*- coding: utf-8 -*-
"""Hợp đồng trạng thái KHỞI TẠO cho lead mới (P1/B2).

Vì sao tệp này tồn tại: trên MỌI cơ sở dữ liệu dựng mới bằng
``alembic upgrade head``, ``POST /api/leads/import`` trả 400
``"System configuration error: Initial lead status not found."``.
Nguyên nhân đo được: ``StatusHelper.get_initial_status`` tra theo CỘT
``legacy_status == 'new' AND is_final == False``, mà seed thật để
``legacy_status`` NULL ở 20/21 hàng — **0 hàng** thoả. Cột đó là *override* cho
``derive_lead_status``, chưa bao giờ là định danh.

Bốn nhóm khẳng định, mỗi nhóm canh một thứ khác nhau:

1. **Định danh** — chọn theo ``code``, và chọn ĐÚNG hàng đó ngay cả khi có hàng
   khác trông "giống initial" hơn (cùng stage, có ``legacy_status='new'``).
2. **Điều kiện hợp lệ** — hàng được chọn phải non-final, non-universal, có
   stage. Mỗi điều kiện một ca riêng để biết ca đỏ vì gì.
3. **Thiếu cấu hình** — fail-closed bằng ``InitialLeadStatusNotConfigured``
   (503), KHÔNG trả ``None`` để người gọi ghi lead nửa vời rồi trả 201.
4. **Một nguồn chuẩn** — ``fsm_engine`` (Rule #11) và ``StatusHelper`` dùng
   CHUNG một hằng; ``lead.status`` của đường nhập theo lô tính bằng CHÍNH
   ``derive_lead_status`` của đường tạo-một-lead.
"""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.status_mapping import (
    INITIAL_CONSULTATION_STATUS_CODE,
    create_status_info_from_model,
    derive_lead_status,
)
from app.services.status_helper import StatusHelper
from app.utils.exceptions import InitialLeadStatusNotConfigured

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest_asyncio.fixture
async def canonical_only(db: AsyncSession, seeded_dependencies: dict):
    """Gỡ mã chuẩn khỏi mọi hàng để từng ca tự dựng đúng hoàn cảnh của nó.

    Không dùng chung một hàng seed sẵn: mỗi ca dưới đây cần một hàng mang MỘT
    khiếm khuyết duy nhất, và sửa tại chỗ một hàng dùng chung là cách nhanh nhất
    để hai ca ảnh hưởng nhau.
    """
    await db.execute(
        text("UPDATE consultation_status SET code = NULL WHERE code = :c"),
        {"c": INITIAL_CONSULTATION_STATUS_CODE},
    )
    await db.flush()
    return seeded_dependencies


async def _stage(db: AsyncSession, sid: str) -> str:
    db.add(models.PipelineStage(id=sid, name=f"Stage {sid}", order=77))
    await db.flush()
    return sid


async def _status(db: AsyncSession, **kw) -> models.ConsultationStatus:
    kw.setdefault("color_code", "#123456")
    kw.setdefault("name", kw["id"])
    st = models.ConsultationStatus(**kw)
    db.add(st)
    await db.flush()
    return st


# =============================================================================
# 1. ĐỊNH DANH
# =============================================================================


async def test_chon_theo_code_khong_theo_legacy_status(db, canonical_only):
    """Hàng ĐÚNG mang ``code`` nhưng ``legacy_status`` NULL — y như prod.

    Ca này là phép thử trực tiếp của lỗi gốc: một hàng mồi nhử mang
    ``legacy_status='new'`` + ``is_final=False`` (tức thoả TRỌN VẸN tiêu chí
    cũ) và đứng TRƯỚC theo thứ tự id, nên truy vấn cũ
    ``WHERE legacy_status='new' ... ORDER BY id LIMIT 1`` sẽ chọn nó.
    """
    await _stage(db, "ISC_STG")
    await _status(
        db, id="ISC_AAA_MOI_NHU", stage_id="ISC_STG",
        legacy_status="new", is_final=False, phase="consultation",
    )
    await _status(
        db, id="ISC_ZZZ_THAT", code=INITIAL_CONSULTATION_STATUS_CODE,
        stage_id="ISC_STG", is_final=False, phase="consultation",
    )

    got = await StatusHelper.get_initial_status(db)

    assert got.id == "ISC_ZZZ_THAT", (
        "get_initial_status phải chọn theo code, không theo legacy_status "
        f"và không theo thứ tự id — đang trả {got.id!r}"
    )
    assert got.legacy_status is None, (
        "hàng chuẩn trên CSDL thật có legacy_status NULL; ca này mất ý nghĩa "
        "nếu fixture lỡ đóng dấu cột đó"
    )


async def test_get_initial_status_id_tra_dung_id_cua_hang_chuan(db, canonical_only):
    """``get_initial_status_id`` không được có đường chọn riêng."""
    await _stage(db, "ISC_STG2")
    await _status(
        db, id="ISC_CANON2", code=INITIAL_CONSULTATION_STATUS_CODE,
        stage_id="ISC_STG2", is_final=False, phase="consultation",
    )

    assert await StatusHelper.get_initial_status_id(db) == "ISC_CANON2"


# =============================================================================
# 2. ĐIỀU KIỆN HỢP LỆ — mỗi ca một khiếm khuyết
# =============================================================================


async def test_hang_chuan_is_final_bi_tu_choi(db, canonical_only):
    """``is_final=True`` ⇒ lead chết ngay lúc sinh ra. Phải 503, không im lặng dùng."""
    await _stage(db, "ISC_STG_F")
    await _status(
        db, id="ISC_FINAL", code=INITIAL_CONSULTATION_STATUS_CODE,
        stage_id="ISC_STG_F", is_final=True, is_universal=False,
        phase="consultation",
    )

    with pytest.raises(InitialLeadStatusNotConfigured) as e:
        await StatusHelper.get_initial_status(db)
    assert "is_final" in str(e.value.context["problems"])


async def test_hang_chuan_is_universal_bi_tu_choi(db, canonical_only):
    """``is_universal=True`` = activity, đứng ngoài pipeline (sts01 NO_ANSWER).

    Đây là cái bẫy THẬT: migration ``v7w8x9y0z1a2`` từng gán
    ``legacy_status='new'`` cho cả ``sts00`` lẫn ``sts01``, và ``sts01`` là hàng
    universal. Truy vấn cũ chỉ trượt khỏi nó nhờ ``ORDER BY id``.
    """
    await _stage(db, "ISC_STG_U")
    await _status(
        db, id="ISC_UNIV", code=INITIAL_CONSULTATION_STATUS_CODE,
        stage_id="ISC_STG_U", is_final=False, is_universal=True,
        phase="universal",
    )

    with pytest.raises(InitialLeadStatusNotConfigured) as e:
        await StatusHelper.get_initial_status(db)
    assert "is_universal" in str(e.value.context["problems"])


async def test_hang_chuan_thieu_stage_bi_tu_choi(db, canonical_only):
    """``stage_id=NULL`` tái tạo ĐÚNG thứ hỏng mà bản vá đóng lại.

    ``sync_lead_status`` gán ``lead.pipeline_stage_id = status.stage_id``, nên
    một hàng chuẩn không có stage tạo ra lead vô hình với mọi phễu — mà HTTP
    vẫn 201.
    """
    await _status(
        db, id="ISC_NOSTAGE", code=INITIAL_CONSULTATION_STATUS_CODE,
        stage_id=None, is_final=False, is_universal=False, phase="consultation",
    )

    with pytest.raises(InitialLeadStatusNotConfigured) as e:
        await StatusHelper.get_initial_status(db)
    assert "stage_id" in str(e.value.context["problems"])


async def test_check_initial_status_row_moi_dieu_kien_doc_lap():
    """Phép kiểm thuần: mỗi thuộc tính hỏng sinh ĐÚNG một lời phàn nàn.

    Ca gộp ở trên vẫn xanh nếu ai đó gộp ba điều kiện thành một biểu thức
    ``or`` — ca này khoá việc thông báo phải chỉ đúng điều kiện nào hỏng.
    """
    class _Gia:
        def __init__(self, is_final=False, is_universal=False, stage_id="stg01"):
            self.is_final = is_final
            self.is_universal = is_universal
            self.stage_id = stage_id
            self.id = "gia"

    assert StatusHelper.check_initial_status_row(_Gia()) == []
    assert len(StatusHelper.check_initial_status_row(_Gia(is_final=True))) == 1
    assert len(StatusHelper.check_initial_status_row(_Gia(is_universal=True))) == 1
    assert len(StatusHelper.check_initial_status_row(_Gia(stage_id=None))) == 1
    # Hàng không tồn tại là một ca RIÊNG, không trộn vào ba cái trên.
    assert StatusHelper.check_initial_status_row(None) != []


# =============================================================================
# 3. THIẾU CẤU HÌNH — fail-closed
# =============================================================================


async def test_thieu_hang_chuan_thi_nem_503_chu_khong_tra_none(db, canonical_only):
    """Không có hàng nào mang mã ⇒ ném, KHÔNG trả ``None``.

    ``None`` là thứ đã cho phép ``create_lead`` và ``submit_lead_claim`` ghi
    lead với ``consultation_status_id=NULL`` + ``pipeline_stage_id=NULL`` rồi
    vẫn trả 201.
    """
    with pytest.raises(InitialLeadStatusNotConfigured) as e:
        await StatusHelper.get_initial_status(db)

    assert e.value.status_code == 503
    assert e.value.error_code == "INITIAL_LEAD_STATUS_NOT_CONFIGURED"
    # Chi tiết cấu hình ở lại trong log, KHÔNG đi ra tới client.
    assert e.value.public_payload == {}
    assert e.value.context["expected_code"] == INITIAL_CONSULTATION_STATUS_CODE


async def test_create_lead_thieu_cau_hinh_khong_de_lai_lead_nua_voi(
    db, canonical_only, monkeypatch
):
    """Lối 503 của ``create_lead`` không được để lại hàng ``lead`` nào.

    Không dựa vào savepoint dọn hộ: phép tra trạng thái đặt TRƯỚC mọi
    ``db.add``, nên không có gì để dọn. Ca này đếm hàng thật trước/sau.
    """
    from app import schemas
    from app.services import lead_service

    truoc = (await db.execute(text("SELECT count(*) FROM lead"))).scalar_one()

    officer = models.User(
        username="isc_officer", email="isc_officer@test.vn",
        password_hash="x", role="officer", status="active",
        unit_id=canonical_only["unit_id"],
    )
    db.add(officer)
    await db.flush()
    # Không để đường tạo lead bắn Celery/notification trong ca này.
    monkeypatch.setattr(
        lead_service, "process_automatic_lead_assignment_task",
        type("_T", (), {"delay": staticmethod(lambda *a, **k: None)}),
        raising=False,
    )

    lead_in = schemas.LeadCreate(
        full_name="ISC Khong Duoc Ghi", phone="0900111222", source="hotline",
        unit_id=officer.unit_id,
    )
    with pytest.raises(InitialLeadStatusNotConfigured):
        await lead_service.create_lead(db, lead_in, created_by=officer)

    sau = (await db.execute(text("SELECT count(*) FROM lead"))).scalar_one()
    assert sau == truoc, "lối 503 đã để lại một lead nửa vời trong DB"


# =============================================================================
# 4. MỘT NGUỒN CHUẨN
# =============================================================================


async def test_fsm_engine_nhap_hang_thay_vi_go_lai_chuoi():
    """``fsm_engine`` phải NHẬP hằng, không gõ lại chuỗi.

    Phép kiểm rẻ, bắt đúng một chuyện: ai đó gỡ ``import`` và viết lại literal.
    Nó KHÔNG đủ một mình (một literal trùng chữ vẫn qua được), nên ca hành vi
    ngay dưới mới là hàng rào chính.
    """
    from app.services import fsm_engine

    assert (
        fsm_engine.INITIAL_CONSULTATION_STATUS_CODE
        is INITIAL_CONSULTATION_STATUS_CODE
    )


async def test_fsm_rule11_chon_dung_hang_ma_duong_ghi_dat_lead_vao(
    db, canonical_only
):
    """Rule #11 (lead chưa có status) phải trả ĐÚNG hàng mà đường GHI dùng.

    Đây là phép kiểm HÀNH VI, chạy thẳng ``_get_raw_transitions(db, None)`` —
    đúng chỗ hằng được dùng — để khỏi lẫn với phase/stage guard ở các bước sau.

    Dựng một hàng mồi nhử thoả TRỌN VẸN tiêu chí cũ (``legacy_status='new'`` +
    ``is_final=False``) và đứng TRƯỚC theo thứ tự id. Nếu FSM tra theo bất cứ
    thứ gì khác ``code`` — cột cũ, thứ tự hàng, "stage đầu tiên" — nó sẽ trả về
    hàng mồi nhử, và officer nhận một danh sách "bước tiếp theo" tính từ một
    trạng thái mà lead KHÔNG hề đang ở.
    """
    from app.services import fsm_engine

    await _stage(db, "ISC_STG_FSM")
    await _status(
        db, id="ISC_AAA_FSM_MOI", stage_id="ISC_STG_FSM",
        legacy_status="new", is_final=False, phase="consultation",
    )
    await _status(
        db, id="ISC_ZZZ_FSM_THAT", code=INITIAL_CONSULTATION_STATUS_CODE,
        stage_id="ISC_STG_FSM", is_final=False, phase="consultation",
    )

    raw = await fsm_engine._get_raw_transitions(db, None)

    assert [s.id for s in raw] == ["ISC_ZZZ_FSM_THAT"]
    # ...và đúng hàng mà đường GHI đặt lead vào — hai nơi, một hàng.
    assert raw[0].id == (await StatusHelper.get_initial_status(db)).id


async def test_import_tinh_lead_status_bang_derive_chu_khong_phai_legacy_or_new(
    db, canonical_only
):
    """``lead.status`` của lô nhập phải khớp CHÍNH ``derive_lead_status``.

    Trước bản vá, đường nhập dùng ``initial_status_obj.legacy_status or "new"``
    — một nguồn chuẩn THỨ HAI cho cùng câu hỏi, bỏ qua hẳn bảng suy diễn. Ca
    này dựng một hàng chuẩn mà hai công thức cho KẾT QUẢ KHÁC NHAU
    (``legacy_status`` NULL + stage ``stg06`` ⇒ ``derive`` cho "converted",
    còn công thức cũ cho "new") nên nó đỏ nếu ai đó khôi phục lối tắt kia.
    """
    from app.services import lead_service

    db.add(models.PipelineStage(id="stg06", name="Đã nhập học", order=6))
    await db.flush()
    st = await _status(
        db, id="ISC_CONV", code=INITIAL_CONSULTATION_STATUS_CODE,
        stage_id="stg06", is_final=False, is_universal=False,
        outcome_type="positive", phase="enrolled",
    )

    got = await StatusHelper.get_initial_status(db)
    assert got.id == st.id

    # Hàng chuẩn được dựng sao cho HAI công thức cho kết quả KHÁC NHAU. Không có
    # điều kiện này thì ca test không phân biệt được lối tắt cũ.
    derived = derive_lead_status(create_status_info_from_model(got))
    assert derived == "converted"
    assert derived != (got.legacy_status or "new"), (
        "ca test mất răng: hai công thức đang cho cùng kết quả nên nó không "
        "phân biệt được lối tắt `.legacy_status or \"new\"`"
    )

    # Và chạy THẬT đường nhập: khẳng định trên hàng ``lead`` được ghi, không chỉ
    # trên hai biểu thức cạnh nhau. Một ca chỉ so hai công thức vẫn xanh nguyên
    # nếu ai đó khôi phục ``.legacy_status or "new"`` trong service.
    csv = (
        "full_name,phone,source\n"
        "ISC Import Derive,0900333444,file_import\n"
    ).encode("utf-8")
    ket_qua, _ = await lead_service.import_leads_from_file_content(
        file_content=csv, filename="isc.csv", db=db,
        default_unit_id=canonical_only["unit_id"],
    )
    assert ket_qua.successful_imports == 1, ket_qua.errors
    status_ghi = (
        await db.execute(
            text("SELECT status FROM lead WHERE phone = :p"),
            {"p": "0900333444"},
        )
    ).scalar_one()
    assert status_ghi == "converted", (
        "đường nhập theo lô đang tính lead.status bằng một công thức RIÊNG "
        f"thay vì derive_lead_status — ghi {status_ghi!r}, đáng lẽ 'converted'"
    )
