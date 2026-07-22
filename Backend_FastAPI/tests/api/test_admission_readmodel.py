"""Read-model (perf/admissions-list) — cached_completion/readiness đúng, lean
list đọc cột (không graph), stats AVG(cached_completion).

conftest truncate mọi bảng mỗi test → mỗi test tự kiểm soát dataset.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.orm import joinedload, selectinload

from app import models
from app.database import AsyncSessionLocal
from app.repositories.admission_repository import _choices_eager_load_options
from app.services import admission_service

pytestmark = pytest.mark.asyncio

_SEQ = iter(range(30000, 90000))


async def _make_profile(unit_id, *, status="submitted", reviewer_id=None) -> int:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            n = next(_SEQ)
            lead = models.Lead(
                full_name="ReadModel Test Lead",
                phone="0901112233",
                email=f"rm_{n}@test.com",
                source="website",
                unit_id=unit_id,
            )
            session.add(lead)
            await session.flush()
            profile = models.AdmissionProfile(
                lead_id=lead.id,
                status=status,
                citizen_id=f"0791{n:08d}",
                academic_year=2026,
                version=1,
                applied_rules={"min_gpa": 0, "mandatory_docs": []},
                assigned_reviewer_id=reviewer_id,
            )
            session.add(profile)
            await session.flush()
            return profile.id


async def _set_cached(pid: int, completion: int, readiness: str = "ineligible"):
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                update(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == pid)
                .values(cached_completion=completion, cached_readiness=readiness)
            )


def _find(payload, pid):
    return next(r for r in payload["profiles"] if r["id"] == pid)


class TestAdmissionReadModel:
    async def test_refresh_matches_live_and_persists(self, seed_lead_dependencies):
        """refresh_derived_fields ghi cột == đúng giá trị live (_compute_*).
        Đây là bất biến eventual-consistency: cached khớp detail-live cùng data.
        """
        unit_id = seed_lead_dependencies["unit_id"]
        pid = await _make_profile(unit_id)
        async with AsyncSessionLocal() as session:
            stmt = (
                select(models.AdmissionProfile)
                .where(models.AdmissionProfile.id == pid)
                .options(
                    selectinload(models.AdmissionProfile.lead),
                    # joinedload(document_type) KHỚP eager của sweep task — validator
                    # đọc doc.document_type.code; thiếu nó + hồ sơ có giấy = Missing
                    # Greenlet. Test giữ đúng graph sweep để không cho cảm giác an
                    # toàn giả (dù fixture hiện không có ProfileDocument).
                    selectinload(models.AdmissionProfile.documents).joinedload(
                        models.ProfileDocument.document_type
                    ),
                    selectinload(models.AdmissionProfile.subject_scores),
                    *_choices_eager_load_options(),
                )
            )
            p = (await session.execute(stmt)).scalars().first()
            # _compute_completion_percent → _validate_scores (single-NV) đọc
            # profile.average_score (transient) nên PHẢI _calculate_and_update_
            # totals trước — đúng thứ tự mọi đường thật + refresh_derived_fields.
            admission_service._calculate_and_update_totals(p)
            live_c = admission_service._compute_completion_percent(p, p.documents)
            live_r = admission_service._compute_readiness_status(p, p.documents)
            comp, ready = admission_service.refresh_derived_fields(p, p.documents)
            assert comp == live_c
            assert ready == live_r
            assert p.cached_completion == live_c
            assert p.cached_readiness == live_r
            assert p.cached_derived_at is not None
            await session.commit()

    async def test_lean_list_reads_cached_no_graph(
        self, client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies: dict
    ):
        """List NHẸ đọc completion/eligibility TỪ cột cached; KHÔNG serialize
        choices/documents_checklist; available_actions là list."""
        unit_id = seed_lead_dependencies["unit_id"]
        pid = await _make_profile(unit_id)
        await _set_cached(pid, 73, "eligible")

        resp = await client.get("/api/admissions", headers=admin_token_headers)
        assert resp.status_code == 200, resp.text
        row = _find(resp.json(), pid)
        assert row["completion_percent"] == 73
        assert row["eligibility_status"] == "eligible"
        assert "choices" not in row
        assert "documents_checklist" not in row
        assert isinstance(row["available_actions"], list)

    async def test_stats_avg_from_cached_column(
        self, client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies: dict
    ):
        """stats.avg_completion = AVG(cached_completion) SQL (không fetch-all)."""
        unit_id = seed_lead_dependencies["unit_id"]
        p1 = await _make_profile(unit_id)
        p2 = await _make_profile(unit_id)
        await _set_cached(p1, 40)
        await _set_cached(p2, 60)

        resp = await client.get(
            "/api/admissions/stats?academic_year=2026", headers=admin_token_headers
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["avg_completion"] == 50.0

    async def test_lean_list_actions_reject_claim_for_submitted(
        self, client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies: dict
    ):
        """_compute_list_actions: submitted + admin + chưa claim → reject+claim;
        approve chỉ khi không nợ giấy (hồ sơ này không có debt snapshot → approve
        có mặt); admin luôn có assign_officer (bulk-assign bar). unclaim KHÔNG lọt
        vào output list (không UI list nào đọc)."""
        unit_id = seed_lead_dependencies["unit_id"]
        pid = await _make_profile(unit_id)
        await _set_cached(pid, 50, "ineligible")
        resp = await client.get("/api/admissions", headers=admin_token_headers)
        row = _find(resp.json(), pid)
        acts = set(row["available_actions"])
        assert "reject" in acts
        assert "claim" in acts  # chưa có reviewer
        assert "approve" in acts  # no document_debt snapshot → không gate
        # Regression guard: bulk "Phân công hàng loạt" cần assign_officer trên MỌI
        # hàng (FE canAssign = every('assign_officer')). Admin → luôn có.
        assert "assign_officer" in acts
        assert "unclaim" not in acts  # dead-data đã bỏ khỏi output list

    async def test_lean_list_actions_dropped_seat_collapses(
        self, client: AsyncClient, admin_token_headers: dict, seed_lead_dependencies: dict
    ):
        """Ghế thôi học (is_dropped=True, status vẫn 'enrolled') → list KHÔNG bày
        action nào (mirror detail-collapse), kể cả assign_officer."""
        unit_id = seed_lead_dependencies["unit_id"]
        pid = await _make_profile(unit_id, status="enrolled")
        async with AsyncSessionLocal() as session:
            async with session.begin():
                await session.execute(
                    update(models.AdmissionProfile)
                    .where(models.AdmissionProfile.id == pid)
                    .values(is_dropped=True, cached_completion=100, cached_readiness="eligible")
                )
        resp = await client.get("/api/admissions", headers=admin_token_headers)
        row = _find(resp.json(), pid)
        assert row["available_actions"] == []
