"""Tests cho branch ``fix/admission-path-activator-method-filter``.

Hai fix độc lập, cùng domain AdmissionPath:

* **Fix A — for-offering 500 MissingGreenlet.**
  ``get_active_paths_by_offering_id`` thiếu ``selectinload(AdmissionPath.
  activator)`` → khi ``build_path_response`` serialize
  ``AdmissionPathResponse.activator`` (Optional[UserNested]), path có
  ``activated_by`` NOT NULL trigger lazy-load async → MissingGreenlet → 500.
  Officer/admin KHÔNG tạo được hồ sơ cho ngành có đường đã kích hoạt (vd 7
  ngành Trung cấp THCS TS2026).

* **Fix B — lọc phương thức theo trình độ văn hóa (AddChoiceDialog).**
  ``get_active_paths_by_round(audience=...)`` ẩn path gắn tag bậc văn hóa ĐỐI
  LẬP (``_audience_visibility_filter``): path NULL / ``[]`` / chỉ gắn loại hình
  (LIEN_THONG_*/VLVH) VẪN hiện. Service ``list_active_paths_by_round(cultural)``
  suy audience qua ``cultural_to_audience``. Dependency
  ``get_optional_profile_cultural_for_audience`` đọc cultural có IDOR-scope
  (404 nếu hồ sơ ngoài phạm vi officer).
"""
from __future__ import annotations

import inspect
from datetime import datetime, timezone

import pytest
import pytest_asyncio

from app import models
from app.core.deps import get_optional_profile_cultural_for_audience
from app.database import AsyncSessionLocal
from app.repositories.admission_path_repository import AdmissionPathRepository
from app.schemas.admission_path import AdmissionPathResponse
from app.security import get_password_hash
from app.services.admission_path_service import AdmissionPathService
from app.services.document_resolution_service import cultural_to_audience
from app.utils.exceptions import ResourceNotFoundError


# ===========================================================================
# Integration fixture — 1 round + 1 published academic_info + 6 active paths
# phủ mọi nhánh _audience_visibility_filter (mỗi path 1 method để thoả UNIQUE
# (round, academic_info, method)) + activator user trên mỗi path (Fix A).
#   thcs      applicable_to = [POST_THCS]      → ẩn khi audience=POST_THPT
#   thpt      applicable_to = [POST_THPT]      → ẩn khi audience=POST_THCS
#   legacy    applicable_to = NULL             → luôn hiện (nhánh IS NULL)
#   lien_thong applicable_to = [LIEN_THONG_CD] → luôn hiện (loại hình thuần)
#   vlvh      applicable_to = [VLVH]           → luôn hiện (loại hình thuần)
#   empty     applicable_to = []               → luôn hiện (nhánh NOT &&)
# ===========================================================================
@pytest_asyncio.fixture
async def audience_seed(seed_lead_dependencies: dict) -> dict:
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    async with AsyncSessionLocal() as s:
        async with s.begin():
            activator = models.User(
                username=f"activator_{ts}",
                email=f"activator_{ts}@test.local",
                full_name="Path Activator",
                password_hash=get_password_hash("test"),
                role="admin",
                status="active",
            )
            s.add(activator)
            await s.flush()

            rnd = models.OfferingAdmissionRound(
                academic_year=2026,
                round_code=f"AUD_{ts}",
                round_name=f"Audience round {ts}",
                is_active=True,
            )
            s.add(rnd)
            await s.flush()

            offering = models.ProgramOffering(
                program_id=seed_lead_dependencies["major_program_id"],
                offering_type="full_time",
                duration_semesters=8,
            )
            s.add(offering)
            await s.flush()

            ai = models.OfferingAcademicInfo(
                offering_id=offering.id,
                academic_year=2026,
                annual_admission_quota=20,
                tuition_fee_per_year=1_000_000,
                is_published=True,
            )
            s.add(ai)
            await s.flush()

            path_ids: dict[str, int] = {}
            specs = (
                ("thcs", ["POST_THCS"]),
                ("thpt", ["POST_THPT"]),
                ("legacy", None),  # NULL = áp mọi đối tượng
                ("lien_thong", ["LIEN_THONG_CD"]),  # loại hình thuần
                ("vlvh", ["VLVH"]),  # loại hình thuần
                ("empty", []),  # mảng rỗng (KHÁC NULL)
                ("both", ["POST_THCS", "POST_THPT"]),  # cả 2 bậc văn hóa
                ("mixed_thcs", ["POST_THCS", "LIEN_THONG_CD"]),  # văn hóa + loại hình
            )
            for key, audience in specs:
                method = models.AdmissionMethod(
                    code=f"M_{key}_{ts}",
                    name=f"Method {key} {ts}",
                    requires_subject_scores=True,
                    is_active=True,
                )
                s.add(method)
                await s.flush()
                path = models.AdmissionPath(
                    academic_info_id=ai.id,
                    admission_method_id=method.id,
                    admission_round_id=rnd.id,
                    status="active",
                    visibility="public",
                    applicable_to=audience,
                    # activated_by NOT NULL → reproduce Fix A.
                    activated_by=activator.id,
                )
                s.add(path)
                await s.flush()
                path_ids[key] = path.id

            return {
                "round_id": rnd.id,
                "offering_id": offering.id,
                "academic_info_id": ai.id,
                "activator_id": activator.id,
                "path_ids": path_ids,
            }


# ===========================================================================
# Fix B — repo audience filter (runtime, seeded): chỉ ẩn bậc văn hóa ĐỐI LẬP
# ===========================================================================
@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_active_paths_by_round_filters_by_audience(audience_seed):
    pid = audience_seed["path_ids"]
    # NULL / loại-hình-thuần / [] / cả-2-bậc PHẢI luôn hiện cho mọi audience.
    always_visible = {
        pid["legacy"], pid["lien_thong"], pid["vlvh"], pid["empty"], pid["both"]
    }
    async with AsyncSessionLocal() as s:
        repo = AdmissionPathRepository(s)

        # POST_THCS → giữ THCS + mixed_thcs (có tag THCS) + always-visible; ẩn THPT.
        thcs_ids = {
            p.id
            for p in await repo.get_active_paths_by_round(
                audience_seed["round_id"], audience="POST_THCS"
            )
        }
        assert pid["thcs"] in thcs_ids
        assert pid["mixed_thcs"] in thcs_ids  # văn hóa THCS + loại hình → hiện cho THCS
        assert always_visible <= thcs_ids
        assert pid["thpt"] not in thcs_ids

        # POST_THPT → giữ THPT + always-visible; ẩn THCS + mixed_thcs (gắn tag THCS).
        thpt_ids = {
            p.id
            for p in await repo.get_active_paths_by_round(
                audience_seed["round_id"], audience="POST_THPT"
            )
        }
        assert pid["thpt"] in thpt_ids
        assert always_visible <= thpt_ids
        assert pid["thcs"] not in thpt_ids
        assert pid["mixed_thcs"] not in thpt_ids  # gắn POST_THCS → ẩn khỏi THPT

        # audience=None (mặc định) → KHÔNG lọc, trả cả 8.
        all_ids = {
            p.id
            for p in await repo.get_active_paths_by_round(audience_seed["round_id"])
        }
        assert set(pid.values()) <= all_ids


def test_cultural_audience_values_parity():
    """#6: ``_CULTURAL_AUDIENCE_VALUES`` (repo) PHẢI = range của
    ``_CULTURAL_TO_AUDIENCE`` (document_resolution_service). Khoá drift mà KHÔNG
    đảo dependency layer (repo KHÔNG import service) — test import cả 2 private
    rồi so set. Nếu ai thêm bậc văn hóa mới vào map mà quên repo → test đỏ."""
    from app.repositories.admission_path_repository import _CULTURAL_AUDIENCE_VALUES
    from app.services.document_resolution_service import _CULTURAL_TO_AUDIENCE

    assert set(_CULTURAL_AUDIENCE_VALUES) == set(_CULTURAL_TO_AUDIENCE.values())


# ===========================================================================
# Fix A — serialize activator KHÔNG MissingGreenlet + đúng activator (seeded)
# ===========================================================================
@pytest.mark.integration
@pytest.mark.asyncio
async def test_get_active_paths_by_offering_id_serializes_activator(audience_seed):
    """Reproduce prod 500: path có ``activated_by`` NOT NULL. Trước fix,
    ``AdmissionPathResponse.model_validate`` raise MissingGreenlet khi truy cập
    ``activator`` (lazy). Sau fix (eager-load) → serialize OK + đúng activator
    đã seed (loại trừ eager-load nhầm relationship)."""
    async with AsyncSessionLocal() as s:
        repo = AdmissionPathRepository(s)
        paths = await repo.get_active_paths_by_offering_id(
            audience_seed["offering_id"]
        )
        assert paths, "seed phải trả active published paths"

        # KHÔNG raise MissingGreenlet — activator đã eager-load.
        responses = [AdmissionPathResponse.model_validate(p) for p in paths]
        assert all(r.activator is not None for r in responses)
        # Đúng activator đã seed (không load nhầm user khác).
        assert all(
            r.activator.id == audience_seed["activator_id"] for r in responses
        )


# ===========================================================================
# Fix B — cultural_to_audience (pure function, nguồn map chung)
# ===========================================================================
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cultural,expected",
    [
        ("completed_thcs", "POST_THCS"),
        ("graduated_thcs", "POST_THCS"),
        ("completed_thpt", "POST_THPT"),
        ("graduated_thpt", "POST_THPT"),
        ("graduated_gdtx", "POST_THPT"),
        (None, None),  # hồ sơ chưa khai trình độ → KHÔNG lọc
        ("", None),  # rỗng (falsy) → KHÔNG lọc
        ("unmapped_value", None),  # giá trị lạ → fail-safe KHÔNG lọc
    ],
)
async def test_cultural_to_audience_mapping(cultural, expected):
    assert cultural_to_audience(cultural) == expected


# ===========================================================================
# Fix B — service → repo e2e (seeded): cultural thật → đúng tập path hiển thị
# ===========================================================================
@pytest.mark.integration
@pytest.mark.asyncio
async def test_service_list_active_paths_filters_by_cultural(audience_seed):
    pid = audience_seed["path_ids"]
    async with AsyncSessionLocal() as s:
        svc = AdmissionPathService(s)

        # cultural=graduated_thpt → audience POST_THPT → ẩn THCS, giữ THPT.
        paths, _ = await svc.list_active_paths_by_round(
            audience_seed["round_id"], cultural="graduated_thpt"
        )
        ids = {p.id for p in paths}
        assert pid["thpt"] in ids
        assert pid["lien_thong"] in ids  # loại hình thuần vẫn hiện
        assert pid["thcs"] not in ids

        # cultural=None → KHÔNG lọc, trả cả 6.
        paths_all, _ = await svc.list_active_paths_by_round(
            audience_seed["round_id"], cultural=None
        )
        assert set(pid.values()) <= {p.id for p in paths_all}


# ===========================================================================
# Fix B / #4 — IDOR scope của dependency get_optional_profile_cultural_for_audience
# (profile thật + unauthorized profile → 404; mirror get_admission_for_user_read)
# ===========================================================================
@pytest_asyncio.fixture
async def idor_seed(seed_lead_dependencies: dict, seed_other_unit: dict) -> dict:
    """1 hồ sơ THCS thuộc unit A + officer được phân công, 1 officer cùng unit
    NHƯNG không phân công, 1 admin, 1 officer unit khác (seed_other_unit =
    UNIT_2 id 9001, trên dải autoincrement → không đụng PK seeded)."""
    ts = int(datetime.now(timezone.utc).timestamp() * 1000) % 1_000_000
    unit_a = seed_lead_dependencies["unit_id"]
    unit_b = seed_other_unit["unit_id"]
    async with AsyncSessionLocal() as s:
        async with s.begin():
            def _mk_user(tag, role, unit_id):
                u = models.User(
                    username=f"{tag}_{ts}",
                    email=f"{tag}_{ts}@test.local",
                    full_name=f"{tag} {ts}",
                    password_hash=get_password_hash("test"),
                    role=role,
                    status="active",
                    unit_id=unit_id,
                )
                s.add(u)
                return u

            officer_assigned = _mk_user("off_assigned", "officer", unit_a)
            officer_unassigned = _mk_user("off_unassigned", "officer", unit_a)
            officer_other_unit = _mk_user("off_other", "officer", unit_b)
            manager_user = _mk_user("mgr", "manager", unit_a)
            admin_user = _mk_user("adm", "admin", unit_a)
            await s.flush()

            lead = models.Lead(
                full_name="IDOR Cultural Lead",
                phone=f"09010{ts % 100000:05d}",
                email=f"idor_cult_{ts}@test.local",
                source="website",
                unit_id=unit_a,
                assigned_officer_id=officer_assigned.id,
            )
            s.add(lead)
            await s.flush()

            profile = models.AdmissionProfile(
                lead_id=lead.id,
                status="draft",
                citizen_id=f"IDOR{ts:08d}",
                academic_year=2026,
                version=1,
                applied_rules={"min_gpa": 0, "mandatory_docs": []},
                cultural_education_level="graduated_thcs",
            )
            s.add(profile)
            await s.flush()

            return {
                "profile_id": profile.id,
                "officer_assigned_id": officer_assigned.id,
                "officer_assigned_username": officer_assigned.username,
                "officer_unassigned_id": officer_unassigned.id,
                "officer_other_unit_id": officer_other_unit.id,
                "officer_other_unit_username": officer_other_unit.username,
                "manager_id": manager_user.id,
                "admin_id": admin_user.id,
            }


async def _call_dep(profile_id, user_id):
    """Gọi dependency trực tiếp với 1 session + current_user đã load."""
    async with AsyncSessionLocal() as s:
        user = None
        if user_id is not None:
            user = await s.get(models.User, user_id)
        return await get_optional_profile_cultural_for_audience(
            profile_id=profile_id, current_user=user, db=s
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_idor_officer_assigned_reads_cultural(idor_seed):
    # Officer được phân công + cùng unit → đọc được cultural.
    got = await _call_dep(idor_seed["profile_id"], idor_seed["officer_assigned_id"])
    assert got == "graduated_thcs"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_idor_admin_reads_any_cultural(idor_seed):
    got = await _call_dep(idor_seed["profile_id"], idor_seed["admin_id"])
    assert got == "graduated_thcs"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_idor_officer_unassigned_same_unit_blocked(idor_seed):
    # Officer cùng unit nhưng KHÔNG được phân công → 404 (không leak cultural).
    with pytest.raises(ResourceNotFoundError):
        await _call_dep(idor_seed["profile_id"], idor_seed["officer_unassigned_id"])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_idor_officer_other_unit_blocked(idor_seed):
    with pytest.raises(ResourceNotFoundError):
        await _call_dep(idor_seed["profile_id"], idor_seed["officer_other_unit_id"])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_idor_nonexistent_profile_blocked(idor_seed):
    with pytest.raises(ResourceNotFoundError):
        await _call_dep(2_000_000_000, idor_seed["officer_assigned_id"])


@pytest.mark.integration
@pytest.mark.asyncio
async def test_idor_no_profile_id_returns_none(idor_seed):
    # profile_id None → KHÔNG query, KHÔNG lọc.
    assert await _call_dep(None, idor_seed["officer_assigned_id"]) is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_idor_manager_same_unit_reads_cultural(idor_seed):
    # Manager cùng unit → đọc được cultural DÙ không được phân công (nhánh scope
    # riêng: non-admin + same-unit + role != OFFICER → bỏ qua assigned check).
    got = await _call_dep(idor_seed["profile_id"], idor_seed["manager_id"])
    assert got == "graduated_thcs"


# ===========================================================================
# #5 — HTTP end-to-end: router → deps(IDOR) → service → repo (khoá wiring +
# fake-404 thật qua tầng HTTP/Query parsing/auth, KHÔNG chỉ gọi dependency tay)
# ===========================================================================
async def _login_bearer(client, username, password="test"):
    """Login → Bearer header. Clear cookie jar trước+sau để Bearer không bị
    cookie phiên trước ghi đè (memory test-httpx-cookie-jar-contamination)."""
    client.cookies.clear()
    res = await client.post(
        "/api/auth/login", data={"username": username, "password": password}
    )
    assert res.status_code == 200, f"login failed: {res.status_code} {res.text}"
    token = res.cookies.get("access_token")
    assert token, "login OK nhưng thiếu access_token cookie"
    client.cookies.clear()
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_by_round_endpoint_idor_and_filter(client, audience_seed, idor_seed):
    pid = audience_seed["path_ids"]
    url = f"/api/admission-config/paths/by-round/{audience_seed['round_id']}"

    # Officer được phân công + sở hữu hồ sơ graduated_thcs → 200 + lọc POST_THCS.
    hdr = await _login_bearer(client, idor_seed["officer_assigned_username"])
    res = await client.get(
        url, params={"profile_id": idor_seed["profile_id"]}, headers=hdr
    )
    assert res.status_code == 200, res.text
    ids = {item["id"] for item in res.json()["items"]}
    assert pid["thcs"] in ids
    assert pid["legacy"] in ids
    assert pid["thpt"] not in ids  # ẩn đường THPT cho hồ sơ THCS

    # KHÔNG truyền profile_id → KHÔNG lọc (trả cả 8) — khoá nhánh "bỏ trống".
    res_all = await client.get(url, headers=hdr)
    assert res_all.status_code == 200, res_all.text
    assert set(pid.values()) <= {item["id"] for item in res_all.json()["items"]}

    # Officer unit khác xin profile_id hồ sơ unit A → 404 FAKE (IDOR thật qua HTTP).
    hdr_other = await _login_bearer(client, idor_seed["officer_other_unit_username"])
    res_404 = await client.get(
        url, params={"profile_id": idor_seed["profile_id"]}, headers=hdr_other
    )
    assert res_404.status_code == 404, res_404.text


# ===========================================================================
# Signature / contract (unit) — khoá API surface của 2 fix
# ===========================================================================
def test_repo_get_active_paths_by_round_has_audience_param():
    sig = inspect.signature(AdmissionPathRepository.get_active_paths_by_round)
    assert "audience" in sig.parameters
    assert sig.parameters["audience"].default is None


def test_service_list_active_paths_by_round_has_cultural_param():
    sig = inspect.signature(AdmissionPathService.list_active_paths_by_round)
    assert "cultural" in sig.parameters
    assert sig.parameters["cultural"].default is None
    # profile_id đã chuyển sang tầng deps (IDOR-scope) — service KHÔNG nhận id.
    assert "profile_id" not in sig.parameters
