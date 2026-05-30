"""Integration — config-panel audience support (feat/document-group-audience-merge §10.8).

Anchor cho BE config-panel sau ĐỢT B (split lớp → nhiều shared group/ot):
- **R10 fix**: get/upsert lookup CHÍNH XÁC theo (ot, audience), KHÔNG ``groups[0]``
  nondeterministic. get NỀN (None) trả group applicable_audience NULL; get
  POST_THCS trả đúng lớp THCS.
- **G4**: NỀN lookup theo (ot, audience IS NULL) — KHÔNG theo code (reuse group
  seed/upsert bất kể code, không tạo 2 NỀN/ot).
- **list layers**: trả TẤT CẢ shared group ordered (NỀN trước).
- **upsert**: update đúng lớp (không đụng lớp khác); tạo lớp mới với code
  deterministic + applicable_audience khi chưa có; validate audience.
- **preview** (§5b/G5): graduated_thcs→bộ THCS (KHÔNG THPT); graduated_thpt→bộ
  THPT (KHÔNG THCS); completed_thpt→loại bằng TN (§6); None→chỉ NỀN.

Test DB dùng ``Base.metadata.create_all`` (cột applicable_audience có trong model).
"""
import random

import pytest
from sqlalchemy import select

from app import models
from app.database import AsyncSessionLocal
from app.schemas.admission_config import (
    DocumentGroupItemCreate,
    SharedDocumentGroupUpdate,
)
from app.services.admission_config_service import AdmissionConfigService
from app.utils.exceptions import ValidationError

pytestmark = pytest.mark.asyncio


async def _get_or_create_doc_type(session, code: str, name: str) -> int:
    existing = (
        await session.execute(
            select(models.ConfigDocumentType).where(
                models.ConfigDocumentType.code == code
            )
        )
    ).scalar_one_or_none()
    if existing:
        return existing.id
    dt = models.ConfigDocumentType(code=code, name=name, is_active=True)
    session.add(dt)
    await session.flush()
    return dt.id


async def _setup(ot_code_prefix: str = "cfgpanel") -> dict:
    """Tạo offering_type + doc types + 3 shared group (NỀN/POST_THPT/POST_THCS)."""
    suffix = random.randint(100000, 999999)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            ot = models.ConfigOfferingType(
                code=f"{ot_code_prefix}_{suffix}",
                name=f"Cfg Panel OT {suffix}",
                is_active=True,
            )
            session.add(ot)
            await session.flush()

            cccd = await _get_or_create_doc_type(session, "cccd", "CCCD")
            hb_thpt = await _get_or_create_doc_type(session, "hoc_ba_thpt", "Học bạ THPT")
            bts_thpt = await _get_or_create_doc_type(
                session, "bang_tot_nghiep_thpt", "Bằng TN THPT"
            )
            hb_thcs = await _get_or_create_doc_type(session, "hoc_ba_thcs", "Học bạ THCS")
            bts_thcs = await _get_or_create_doc_type(
                session, "bang_tot_nghiep_thcs", "Bằng TN THCS"
            )

            def _mk_group(code, audience):
                g = models.DocumentGroup(
                    offering_type_id=ot.id,
                    admission_method_id=None,
                    admission_path_id=None,
                    code=code,
                    name=code,
                    is_active=True,
                    applicable_audience=audience,
                )
                session.add(g)
                return g

            g_base = _mk_group(f"CFG_BASE_{suffix}", None)
            g_thpt = _mk_group(f"CFG_THPT_{suffix}", ["POST_THPT"])
            g_thcs = _mk_group(f"CFG_THCS_{suffix}", ["POST_THCS"])
            await session.flush()

            def _mk_item(group_id, dt_id, order):
                session.add(
                    models.DocumentGroupItem(
                        group_id=group_id,
                        document_type_id=dt_id,
                        is_mandatory=True,
                        requires_upload=True,
                        submission_format="photo",
                        display_order=order,
                    )
                )

            _mk_item(g_base.id, cccd, 1)
            _mk_item(g_thpt.id, hb_thpt, 2)
            _mk_item(g_thpt.id, bts_thpt, 3)
            _mk_item(g_thcs.id, hb_thcs, 2)
            _mk_item(g_thcs.id, bts_thcs, 3)

            return {
                "ot_id": ot.id,
                "base_id": g_base.id,
                "thpt_id": g_thpt.id,
                "thcs_id": g_thcs.id,
                "cccd": cccd,
                "hb_thpt": hb_thpt,
                "bts_thpt": bts_thpt,
                "hb_thcs": hb_thcs,
                "bts_thcs": bts_thcs,
            }


# ---------------------------------------------------------------------------
# get_shared_group_by_audience — R10 / G4 fix
# ---------------------------------------------------------------------------


async def test_get_by_audience_none_returns_nen():
    d = await _setup()
    async with AsyncSessionLocal() as s:
        svc = AdmissionConfigService(s)
        g = await svc.get_shared_document_group(d["ot_id"], None)
        assert g is not None and g.id == d["base_id"]
        assert not g.applicable_audience  # NỀN = NULL/empty


async def test_get_by_audience_post_thcs_returns_thcs_layer():
    d = await _setup()
    async with AsyncSessionLocal() as s:
        svc = AdmissionConfigService(s)
        g = await svc.get_shared_document_group(d["ot_id"], "POST_THCS")
        assert g is not None and g.id == d["thcs_id"]
        assert g.applicable_audience == ["POST_THCS"]
        codes = {i.document_type.code for i in g.items}
        assert codes == {"hoc_ba_thcs", "bang_tot_nghiep_thcs"}


async def test_list_layers_ordered_nen_first():
    d = await _setup()
    async with AsyncSessionLocal() as s:
        svc = AdmissionConfigService(s)
        groups = await svc.list_shared_document_groups(d["ot_id"])
        assert [g.id for g in groups] == [d["base_id"], d["thpt_id"], d["thcs_id"]]
        # NỀN đứng đầu (id ASC) — deterministic (fix groups[0] nondeterministic).
        assert not groups[0].applicable_audience


# ---------------------------------------------------------------------------
# upsert — target đúng lớp, tạo lớp mới, validate
# ---------------------------------------------------------------------------


async def test_upsert_targets_correct_audience_layer_not_groups0():
    d = await _setup()
    async with AsyncSessionLocal() as s:
        svc = AdmissionConfigService(s)
        # Update lớp POST_THPT → chỉ còn 1 item (hoc_ba_thpt).
        payload = SharedDocumentGroupUpdate(
            items=[DocumentGroupItemCreate(document_type_id=d["hb_thpt"], display_order=1)]
        )
        updated, _ = await svc.upsert_shared_document_group(
            d["ot_id"], payload, None, audience="POST_THPT"
        )
        await s.commit()
        assert updated.id == d["thpt_id"]  # đúng lớp THPT, KHÔNG phải NỀN
        assert {i.document_type_id for i in updated.items} == {d["hb_thpt"]}

    # NỀN + THCS KHÔNG bị đụng.
    async with AsyncSessionLocal() as s:
        svc = AdmissionConfigService(s)
        nen = await svc.get_shared_document_group(d["ot_id"], None)
        assert {i.document_type_id for i in nen.items} == {d["cccd"]}
        thcs = await svc.get_shared_document_group(d["ot_id"], "POST_THCS")
        assert len(thcs.items) == 2


async def test_upsert_creates_layer_when_missing_with_code_and_audience():
    """ot CHỈ có NỀN → upsert POST_THCS tạo lớp mới (code + applicable_audience)."""
    suffix = random.randint(100000, 999999)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            ot = models.ConfigOfferingType(
                code=f"cfgnew_{suffix}", name=f"New OT {suffix}", is_active=True
            )
            session.add(ot)
            await session.flush()
            ot_id = ot.id
            hb_thcs = await _get_or_create_doc_type(session, "hoc_ba_thcs", "Học bạ THCS")

    async with AsyncSessionLocal() as s:
        svc = AdmissionConfigService(s)
        payload = SharedDocumentGroupUpdate(
            items=[DocumentGroupItemCreate(document_type_id=hb_thcs, display_order=1)]
        )
        created, _ = await svc.upsert_shared_document_group(
            ot_id, payload, None, audience="POST_THCS"
        )
        await s.commit()
        assert created.applicable_audience == ["POST_THCS"]
        assert created.code == f"SHARED_DOC_OT_{ot_id}_POST_THCS"
        assert created.admission_method_id is None
        assert created.admission_path_id is None


async def test_upsert_rejects_invalid_audience():
    d = await _setup()
    async with AsyncSessionLocal() as s:
        svc = AdmissionConfigService(s)
        payload = SharedDocumentGroupUpdate(items=[])
        with pytest.raises(ValidationError):
            await svc.upsert_shared_document_group(
                d["ot_id"], payload, None, audience="NOT_A_REAL_AUDIENCE"
            )


# ---------------------------------------------------------------------------
# preview (§5b/G5) — derive raw cultural → resolve
# ---------------------------------------------------------------------------


async def test_preview_graduated_thcs_gets_thcs_not_thpt():
    d = await _setup()
    async with AsyncSessionLocal() as s:
        svc = AdmissionConfigService(s)
        docs = await svc.preview_shared_documents(d["ot_id"], "graduated_thcs", None)
        codes = {x.document_type_code for x in docs}
        assert "hoc_ba_thcs" in codes and "bang_tot_nghiep_thcs" in codes
        assert "hoc_ba_thpt" not in codes and "bang_tot_nghiep_thpt" not in codes
        assert "cccd" in codes  # NỀN luôn gộp


async def test_preview_graduated_thpt_gets_thpt_not_thcs():
    d = await _setup()
    async with AsyncSessionLocal() as s:
        svc = AdmissionConfigService(s)
        docs = await svc.preview_shared_documents(d["ot_id"], "graduated_thpt", None)
        codes = {x.document_type_code for x in docs}
        assert "hoc_ba_thpt" in codes and "bang_tot_nghiep_thpt" in codes
        assert "hoc_ba_thcs" not in codes


async def test_preview_completed_thpt_drops_diploma():
    """§6: completed_* → loại bằng TN (chưa có bằng)."""
    d = await _setup()
    async with AsyncSessionLocal() as s:
        svc = AdmissionConfigService(s)
        docs = await svc.preview_shared_documents(d["ot_id"], "completed_thpt", None)
        codes = {x.document_type_code for x in docs}
        assert "hoc_ba_thpt" in codes  # học bạ giữ
        assert "bang_tot_nghiep_thpt" not in codes  # bằng TN loại


async def test_preview_no_cultural_returns_nen_only():
    d = await _setup()
    async with AsyncSessionLocal() as s:
        svc = AdmissionConfigService(s)
        docs = await svc.preview_shared_documents(d["ot_id"], None, None)
        codes = {x.document_type_code for x in docs}
        assert codes == {"cccd"}  # chỉ NỀN


# ---------------------------------------------------------------------------
# P1 review — path-override group (method NULL + path SET) KHÔNG lẫn shared
# ---------------------------------------------------------------------------


async def _setup_with_path_override(major_id: int) -> dict:
    """ot + NỀN group + 1 admission_path + path-override group (method NULL,
    path SET, item marker). Path-override ĐƯỢC PHÉP method NULL (invariant) →
    phải bị get_shared_groups loại khỏi tier shared.

    ``major_id`` từ fixture ``seed_lead_dependencies`` (tránh tự tạo
    OrganizationUnit/MajorProgram → collision id=1 với seed test khác trong CI).
    """
    from tests.fixtures.builders import AdmissionRoundBuilder

    suffix = random.randint(100000, 999999)
    async with AsyncSessionLocal() as session:
        async with session.begin():
            ot = models.ConfigOfferingType(
                code=f"cfgpath_{suffix}", name=f"Path OT {suffix}", is_active=True
            )
            session.add(ot)
            await session.flush()

            offering = models.ProgramOffering(
                offering_type=f"PathTest_{suffix}",
                program_id=major_id,
                offering_type_id=ot.id,
            )
            session.add(offering)
            await session.flush()

            academic_info = models.OfferingAcademicInfo(
                offering_id=offering.id, academic_year=2025, is_published=True
            )
            session.add(academic_info)
            await session.flush()

            method = models.AdmissionMethod(
                code=f"pathm_{suffix}", name="Path Method", is_active=True
            )
            session.add(method)
            await session.flush()

            criteria = models.AdmissionCriteria(
                method_id=method.id, code=f"pathc_{suffix}", name="C",
                min_gpa=0, is_active=True,
            )
            session.add(criteria)
            await session.flush()

            round_id = await AdmissionRoundBuilder.get_or_create_default_round(
                session, academic_year=2025
            )
            path = models.AdmissionPath(
                academic_info_id=academic_info.id,
                admission_method_id=method.id,
                admission_round_id=round_id,
                criteria_id=criteria.id,
                status="active",
            )
            session.add(path)
            await session.flush()

            cccd = await _get_or_create_doc_type(session, "cccd", "CCCD")
            marker = await _get_or_create_doc_type(
                session, "marker_path_doc", "Marker Path Doc"
            )

            # NỀN (method+path NULL).
            g_nen = models.DocumentGroup(
                offering_type_id=ot.id, admission_method_id=None,
                admission_path_id=None, code=f"PNEN_{suffix}", name="nen",
                is_active=True, applicable_audience=None,
            )
            # Path-override: method NULL NHƯNG path SET (invariant cho phép).
            g_path = models.DocumentGroup(
                offering_type_id=ot.id, admission_method_id=None,
                admission_path_id=path.id, code=f"PPATH_{suffix}", name="path",
                is_active=True, applicable_audience=None,
            )
            session.add_all([g_nen, g_path])
            await session.flush()

            session.add(models.DocumentGroupItem(
                group_id=g_nen.id, document_type_id=cccd, is_mandatory=True,
                requires_upload=True, display_order=1,
            ))
            session.add(models.DocumentGroupItem(
                group_id=g_path.id, document_type_id=marker, is_mandatory=True,
                requires_upload=True, display_order=1,
            ))

            return {"ot_id": ot.id, "nen_id": g_nen.id, "path_id": g_path.id}


async def test_list_layers_excludes_path_override(seed_lead_dependencies):
    d = await _setup_with_path_override(seed_lead_dependencies["major_program_id"])
    async with AsyncSessionLocal() as s:
        svc = AdmissionConfigService(s)
        groups = await svc.list_shared_document_groups(d["ot_id"])
        ids = {g.id for g in groups}
        assert d["nen_id"] in ids
        assert d["path_id"] not in ids  # path-override KHÔNG phải shared layer


async def test_preview_excludes_path_override(seed_lead_dependencies):
    d = await _setup_with_path_override(seed_lead_dependencies["major_program_id"])
    async with AsyncSessionLocal() as s:
        svc = AdmissionConfigService(s)
        docs = await svc.preview_shared_documents(d["ot_id"], "graduated_thpt", None)
        codes = {x.document_type_code for x in docs}
        assert "cccd" in codes  # NỀN có
        assert "marker_path_doc" not in codes  # path-override KHÔNG merge vào preview
