# -*- coding: utf-8 -*-
"""Hợp đồng fail-closed tại TỪNG NGƯỜI GỌI ``StatusHelper.get_initial_status``.

``test_initial_status_contract.py`` canh chính cái helper (chọn theo ``code``,
ném 503 thay vì trả ``None``) và đã đo lối 503 của **một** người gọi —
``lead_service.create_lead``. Tệp này canh **những người gọi còn lại**, vì một
helper fail-closed KHÔNG tự động làm mọi lối vào fail-closed: chỉ cần một
``except`` rộng tay ở giữa là ngoại lệ 503 biến thành 201/400 và hàng ``lead``
nửa vời vẫn được ghi.

Bốn đường GHI đi qua helper, mỗi đường một lối vào HTTP khác nhau:

* ``collaborator_service.submit_lead_claim`` — ``POST /api/ctv/leads/submit``
* ``lead_service.import_leads_from_file_content`` — ``POST /api/leads/import``
  **và** ``POST /api/admin/users/leads/import`` (hai router, cùng một service,
  cả hai đều bọc lời gọi bằng ``except ValueError``)
* ``public_lead_intake_service.intake_public_lead`` — ``POST
  /api/public/leads/intake`` (cổng website, bọc ``create_lead`` bằng
  ``except (DuplicateResourceError, IntegrityError)``)
* ``lead_service._resolve_revert_target`` — đường xoá/khôi phục cuộc tư vấn

Phép đo là **đếm hàng thật trước/sau** khi ngoại lệ ném, không phải khẳng định
suông trên đối tượng Python: một ``db.add`` đứng trước phép tra sẽ bị autoflush
INSERT ngay tại câu ``SELECT`` của helper, và assertion trên đối tượng KHÔNG
nhìn thấy chuyện đó.
"""
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.core.status_mapping import INITIAL_CONSULTATION_STATUS_CODE
from app.services.status_helper import StatusHelper
from app.utils.exceptions import InitialLeadStatusNotConfigured

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


@pytest_asyncio.fixture
async def canonical_only(db: AsyncSession, seeded_dependencies: dict):
    """Gỡ mã chuẩn khỏi mọi hàng ⇒ tái tạo ĐÚNG hoàn cảnh "thiếu cấu hình".

    Cùng cách dựng với ``test_initial_status_contract.py``. Cố ý lặp lại ở đây
    thay vì import chéo giữa hai module test: một fixture 4 dòng dùng chung qua
    ``import`` sẽ buộc tệp kia phải import được (và chạy được) mọi lúc tệp này
    chạy, đổi một phụ thuộc rẻ lấy một phụ thuộc đắt.
    """
    await db.execute(
        text("UPDATE consultation_status SET code = NULL WHERE code = :c"),
        {"c": INITIAL_CONSULTATION_STATUS_CODE},
    )
    await db.flush()
    return seeded_dependencies


async def _dem(db: AsyncSession, bang: str) -> int:
    return (await db.execute(text(f'SELECT count(*) FROM "{bang}"'))).scalar_one()


async def _officer(db: AsyncSession, unit_id: int, username: str) -> models.User:
    u = models.User(
        username=username,
        email=f"{username}@test.vn",
        password_hash="x",
        role="officer",
        status="active",
        unit_id=unit_id,
    )
    db.add(u)
    await db.flush()
    return u


# =============================================================================
# 1. CTV — submit_lead_claim
# =============================================================================


async def test_submit_lead_claim_thieu_cau_hinh_khong_de_lai_lead_hay_claim(
    db, canonical_only
):
    """Lối 503 của đường CTV không được để lại ``lead`` NÀO, cũng không ``lead_claim``.

    Nhánh cũ (``lead.status = "new"`` rồi đi tiếp) ghi lead của cộng tác viên với
    ``consultation_status_id=NULL`` + ``pipeline_stage_id=NULL`` rồi vẫn trả 201:
    CTV tưởng đã gửi thành công, còn lead thì biến mất khỏi mọi phễu.

    Đếm CẢ ``lead_claim``: phép tra nằm TRONG ``db.begin_nested()``, nên ca này
    cũng là phép đo savepoint có thật sự lùi hay không.
    """
    from app.schemas.collaborator import LeadClaimCreate, LeadClaimData
    from app.services import collaborator_service

    unit_id = canonical_only["unit_id"]
    ctv = models.Collaborator(
        code="ISCC001",
        full_name="CTV Kiem Thu",
        phone="0912000001",
        status="active",
        unit_id=unit_id,
    )
    db.add(ctv)
    await db.flush()

    lead_truoc = await _dem(db, "lead")
    claim_truoc = await _dem(db, "lead_claim")

    claim = LeadClaimCreate(
        lead_data=LeadClaimData(full_name="Hoc Sinh CTV", phone="0912000002")
    )

    with pytest.raises(InitialLeadStatusNotConfigured):
        await collaborator_service.submit_lead_claim(db, ctv, claim)

    assert await _dem(db, "lead") == lead_truoc, (
        "đường CTV đã ghi một lead nửa vời trước khi 503"
    )
    assert await _dem(db, "lead_claim") == claim_truoc, (
        "đường CTV đã ghi một lead_claim mồ côi trước khi 503"
    )


# =============================================================================
# 2. NHẬP THEO LÔ — import_leads_from_file_content
# =============================================================================


async def test_import_lo_nem_503_chu_khong_phai_valueerror(db, canonical_only):
    """Ngoại lệ phải KHÔNG là ``ValueError`` — nếu không router đổi nó thành 400.

    Cả hai router nhập lô (``routers/leads.py`` và ``routers/admin/users.py``)
    bọc lời gọi bằng ``except ValueError`` rồi dựng ``HTTPException(400,
    detail=str(e))``. Trước bản vá, service ném đúng ``ValueError`` nên người
    nhập nhận **400 "System configuration error"** — một câu tự mâu thuẫn, và họ
    đi sửa một tệp không có lỗi gì.

    Ca này khoá ĐÚNG cái mệnh đề mà hai ``except`` kia hỏi, chứ không khoá gián
    tiếp qua mã trạng thái.
    """
    from app.services import lead_service

    csv = b"full_name,phone,source\nISC Lo,0900555111,file_import\n"

    with pytest.raises(InitialLeadStatusNotConfigured) as e:
        await lead_service.import_leads_from_file_content(
            file_content=csv, filename="isc.csv", db=db,
            default_unit_id=canonical_only["unit_id"],
        )

    assert not isinstance(e.value, ValueError), (
        "`except ValueError` của hai router nhập lô sẽ nuốt ngoại lệ này và trả "
        "400 'lỗi tệp' cho một sự cố cấu hình máy chủ"
    )
    assert e.value.status_code == 503


async def test_import_lo_thieu_cau_hinh_khong_de_lai_lead(db, canonical_only):
    """Lối 503 của đường nhập lô không được ghi hàng ``lead`` nào.

    Tệp có NHIỀU dòng: một tệp một dòng vẫn xanh kể cả khi service ghi xong dòng
    đầu rồi mới đổ ở dòng sau.
    """
    from app.services import lead_service

    truoc = await _dem(db, "lead")
    csv = (
        "full_name,phone,source\n"
        "ISC Lo 1,0900555221,file_import\n"
        "ISC Lo 2,0900555222,file_import\n"
        "ISC Lo 3,0900555223,file_import\n"
    ).encode("utf-8")

    with pytest.raises(InitialLeadStatusNotConfigured):
        await lead_service.import_leads_from_file_content(
            file_content=csv, filename="isc.csv", db=db,
            default_unit_id=canonical_only["unit_id"],
        )

    assert await _dem(db, "lead") == truoc, (
        "đường nhập lô đã ghi lead trước khi phát hiện thiếu cấu hình"
    )


async def test_import_lo_khong_chon_hang_mo_nhu_dung_truoc_theo_id(
    db, canonical_only
):
    """Người gọi không được chọn hàng theo THỨ TỰ — đo trên hàng ``lead`` ĐÃ GHI.

    Dựng một hàng mồi nhử thoả TRỌN VẸN tiêu chí cũ (``legacy_status='new'`` +
    ``is_final=False``) và đứng TRƯỚC theo thứ tự id. Ca ở
    ``test_initial_status_contract.py`` khẳng định điều này trên giá trị TRẢ VỀ
    của helper; ca này khẳng định trên thứ đã được GHI vào ``lead``, tức đường
    nhập lô không có phép chọn riêng nào đứng sau helper.
    """
    from app.services import lead_service

    db.add(models.PipelineStage(id="ISCC_STG", name="Stage ISCC", order=41))
    await db.flush()
    for sid, code in (
        ("ISCC_AAA_MOI_NHU", None),
        ("ISCC_ZZZ_THAT", INITIAL_CONSULTATION_STATUS_CODE),
    ):
        db.add(models.ConsultationStatus(
            id=sid, code=code, name=sid, color_code="#123456",
            stage_id="ISCC_STG", is_final=False, is_universal=False,
            legacy_status="new" if code is None else None,
            phase="consultation",
        ))
    await db.flush()

    csv = b"full_name,phone,source\nISC Thu Tu,0900555331,file_import\n"
    ket_qua, _ = await lead_service.import_leads_from_file_content(
        file_content=csv, filename="isc.csv", db=db,
        default_unit_id=canonical_only["unit_id"],
    )
    assert ket_qua.successful_imports == 1, ket_qua.errors

    ghi = (await db.execute(
        text("SELECT consultation_status_id FROM lead WHERE phone = :p"),
        {"p": "0900555331"},
    )).scalar_one()
    assert ghi == "ISCC_ZZZ_THAT", (
        "đường nhập lô đang chọn trạng thái khởi tạo theo thứ tự hàng / cột "
        f"legacy_status chứ không theo code — đã ghi {ghi!r}"
    )


# =============================================================================
# 3. CỔNG WEBSITE — intake_public_lead
# =============================================================================


async def test_public_intake_thieu_cau_hinh_khong_de_lai_lead(
    db, canonical_only, monkeypatch
):
    """Cổng website: 503 phải đi xuyên ``except (DuplicateResourceError, IntegrityError)``.

    ``intake_public_lead`` bọc ``create_lead`` bằng hai loại ngoại lệ đó để xử lý
    race SĐT: nhánh ``except`` ấy tra lại lead theo SĐT rồi **trả về kết quả
    thành công**. Nếu ngoại lệ thiếu-cấu-hình rơi trúng nhánh này thì website
    nhận ACK "đã nhận" cho một lead chưa bao giờ được ghi.

    (``_resolve_system_user_or_503`` được thay bằng một user seed sẵn: ca này đo
    MỘT bất biến — lối 503 của trạng thái khởi tạo — chứ không đo chuỗi giải
    quyết user hệ thống.)
    """
    from app import schemas
    from app.services import public_lead_intake_service as intake

    unit_id = canonical_only["unit_id"]
    he_thong = await _officer(db, unit_id, "isc_system")
    monkeypatch.setattr(
        intake, "_resolve_system_user_or_503",
        lambda _db: _tra_ve(he_thong), raising=True,
    )
    monkeypatch.setattr(
        intake.settings, "PUBLIC_INTAKE_DEFAULT_UNIT_ID", unit_id, raising=False
    )

    truoc = await _dem(db, "lead")
    payload = schemas.PublicLeadIntake(
        full_name="Khach Website", phone="0900556001", he="Cao dang"
    )

    with pytest.raises(InitialLeadStatusNotConfigured):
        await intake.intake_public_lead(db, payload)

    assert await _dem(db, "lead") == truoc, (
        "cổng website đã ghi lead trước khi phát hiện thiếu cấu hình"
    )


async def _tra_ve(gia_tri):
    """Coroutine trả sẵn một giá trị — thay cho một hàm ``async`` thật."""
    return gia_tri


# =============================================================================
# 4. XOÁ / KHÔI PHỤC CUỘC TƯ VẤN — _resolve_revert_target
# =============================================================================


async def test_resolve_revert_target_thieu_cau_hinh_nem_chu_khong_gop_vao_none(
    db, canonical_only
):
    """Nhánh "chuỗi rỗng → về initial" phải NÉM, không được trả ``(None, None)``.

    ``(None, None)`` đã có nghĩa khác trong chính hàm này: "chuỗi còn lại toàn
    universal → GIỮ NGUYÊN pipeline". Gộp "thiếu cấu hình máy chủ" vào cùng giá
    trị ấy làm lead lặng lẽ giữ một trạng thái tiến xa trong khi người dùng vừa
    xoá cuộc tư vấn cuối cùng và tưởng nó đã lùi về đầu — không ai thấy lỗi.

    Lead ở đây được dựng THẲNG bằng ORM (đường ``create_lead`` đang 503 vì chính
    hoàn cảnh mà ca này dựng) và mang một trạng thái hợp lệ KHÁC hàng chuẩn, để
    khẳng định cuối cùng phân biệt được "giữ nguyên" với "về initial".
    """
    from app.services import lead_service

    db.add(models.PipelineStage(id="ISCC_STG_R", name="Stage R", order=42))
    await db.flush()
    db.add(models.ConsultationStatus(
        id="ISCC_TIEN_XA", name="Tien xa", color_code="#123456",
        stage_id="ISCC_STG_R", is_final=False, is_universal=False,
        phase="consultation", updates_pipeline=True,
    ))
    await db.flush()

    lead = models.Lead(
        full_name="ISC Revert", phone="0900557001", source="hotline",
        unit_id=canonical_only["unit_id"],
        consultation_status_id="ISCC_TIEN_XA",
        pipeline_stage_id="ISCC_STG_R",
        status="contacted",
    )
    db.add(lead)
    await db.flush()

    with pytest.raises(InitialLeadStatusNotConfigured):
        await lead_service._resolve_revert_target(db, lead.id)

    con_lai = (await db.execute(
        text("SELECT consultation_status_id FROM lead WHERE id = :i"),
        {"i": lead.id},
    )).scalar_one()
    assert con_lai == "ISCC_TIEN_XA", (
        "lead bị đổi trạng thái trên lối lỗi — lối 503 phải không chạm gì"
    )


# =============================================================================
# 5. ĐƯỜNG ĐỌC FSM (Rule #11) — CÙNG phép kiểm với đường ghi
# =============================================================================


@pytest.mark.parametrize(
    "khiem_khuyet,thuoc_tinh",
    [
        ("is_final", {"is_final": True}),
        ("is_universal", {"is_universal": True}),
        ("stage_id", {"stage_id": None}),
    ],
)
async def test_rule11_tu_choi_hang_chuan_cau_hinh_sai(
    db, canonical_only, khiem_khuyet, thuoc_tinh
):
    """Rule #11 không được đề nghị một hàng chuẩn mà đường GHI đã từ chối.

    Vì sao đây KHÔNG chỉ là chuyện hiển thị: danh sách này nuôi đường GHI
    ``PATCH /api/leads/{id}/status`` (``deps.validate_status_transition`` →
    ``fsm_engine.is_transition_allowed`` → ``_get_raw_transitions``), và router
    ấy gọi thẳng ``StatusHelper.sync_lead_status`` trên hàng được duyệt — KHÔNG
    đi qua ``get_initial_status``. Nên một hàng mang mã chuẩn nhưng
    ``stage_id=NULL`` vẫn ghi được ``lead.pipeline_stage_id = NULL`` cho lead
    đang ``consultation_status_id IS NULL`` — đúng thứ hỏng mà fail-closed ở
    helper đóng lại, chỉ khác lối vào.

    Mỗi tham số dựng MỘT khiếm khuyết duy nhất, nên ca đỏ chỉ ra được vì sao.
    """
    from app.services import fsm_engine

    db.add(models.PipelineStage(id="ISCC_STG_F", name="Stage F", order=43))
    await db.flush()
    cot = {
        "id": "ISCC_HONG", "code": INITIAL_CONSULTATION_STATUS_CODE,
        "name": "Hong", "color_code": "#123456", "stage_id": "ISCC_STG_F",
        "is_final": False, "is_universal": False, "phase": "consultation",
    }
    cot.update(thuoc_tinh)
    db.add(models.ConsultationStatus(**cot))
    await db.flush()

    # Đường GHI từ chối hàng này — đó là mốc so sánh, không phải giả định.
    with pytest.raises(InitialLeadStatusNotConfigured):
        await StatusHelper.get_initial_status(db)

    raw = await fsm_engine._get_raw_transitions(db, None)
    assert raw == [], (
        f"Rule #11 vẫn đề nghị hàng chuẩn hỏng ({khiem_khuyet}) trong khi đường "
        "GHI từ chối đúng hàng đó — hai nơi đang hỏi cùng một câu bằng hai phép "
        "kiểm khác nhau"
    )
