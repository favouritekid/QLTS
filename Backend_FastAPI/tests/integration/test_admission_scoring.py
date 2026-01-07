import pytest
from datetime import datetime
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app import models
from app.database import AsyncSessionLocal
from app.models.admission_config.subject import Subject

pytestmark = pytest.mark.asyncio

# ==============================================================================
# HELPER FUNCTIONS (Copied from test_admission_state_transitions.py)
# ==============================================================================

async def create_test_lead(
    unit_id: int, 
    assigned_officer_id: int = None,
    consultation_status_id: str = None
) -> int:
    """Create a test lead for admission profile."""
    async with AsyncSessionLocal() as session:
        async with session.begin():
            lead = models.Lead(
                full_name="Test Applicant Scoring",
                phone="0901234568",
                email="test_scoring@example.com",
                source="website",
                unit_id=unit_id,
                assigned_officer_id=assigned_officer_id,
                consultation_status_id=consultation_status_id,
            )
            session.add(lead)
            await session.flush()
            lead_id = lead.id
    return lead_id

async def create_admission_profile(
    lead_id: int,
    status: str = "submitted",
    citizen_id: str = None,
) -> models.AdmissionProfile:
    """Create an admission profile in specified state."""
    if citizen_id is None:
        citizen_id = f"0{datetime.now().timestamp():.0f}"[:12]
    
    async with AsyncSessionLocal() as session:
        async with session.begin():
            profile = models.AdmissionProfile(
                lead_id=lead_id,
                status=status,
                citizen_id=citizen_id,
                version=1,
                applied_rules={"min_gpa": 6.0, "mandatory_docs": []},
            )
            session.add(profile)
            await session.flush()
            profile_id = profile.id
        
        # Reload to get relationships
        result = await session.execute(
            select(models.AdmissionProfile)
            .where(models.AdmissionProfile.id == profile_id)
        )
        return result.scalar_one()

async def get_auth_headers(client: AsyncClient, user_info: dict) -> dict:
    """Login and get auth headers."""
    login_data = {"username": user_info["username"], "password": user_info["password"]}
    res = await client.post("/api/auth/login", data=login_data)
    
    if res.status_code != 200:
        pytest.fail(f"Login failed: {res.status_code} - {res.text}")
    
    access_token = res.cookies.get("access_token")
    if not access_token:
        pytest.fail("Login succeeded but access_token cookie not found")
    
    return {"Authorization": f"Bearer {access_token}"}

# ==============================================================================
# TESTS
# ==============================================================================

async def test_update_admission_scores(
    client: AsyncClient,
    officer_user_in_db: dict,
    seed_lead_dependencies: dict
):
    """
    Test updating admission scores via PUT /api/admissions/{id}.
    """
    # 1. Setup Data
    unit_id = seed_lead_dependencies["unit_id"]
    
    # Ensure Subjects exist
    async with AsyncSessionLocal() as session:
        async with session.begin():
            # Check/Create MATH
            math = await session.execute(select(Subject).where(Subject.code == "MATH"))
            if not math.scalar_one_or_none():
                session.add(Subject(code="MATH", name_vi="Toan"))
            
            # Check/Create PHYS
            phys = await session.execute(select(Subject).where(Subject.code == "PHYS"))
            if not phys.scalar_one_or_none():
                session.add(Subject(code="PHYS", name_vi="Ly"))

    # Create Profile (Draft) linked to officer's unit
    lead_id = await create_test_lead(unit_id)
    profile = await create_admission_profile(lead_id, status="draft")

    # Get Auth Headers
    headers = await get_auth_headers(client, officer_user_in_db)

    # 2. Call API to update scores
    payload = {
        "version": 1,
        "admission_scores": {
            "subject_scores": {
                "MATH": 8.5,
                "PHYS": 7.0
            }
        }
    }

    response = await client.put(
        f"/api/admissions/{profile.id}",
        json=payload,
        headers=headers
    )

    # 3. Assertions
    assert response.status_code == 200, f"Update failed: {response.text}"
    data = response.json()
    assert data["version"] == 2
    assert data["total_score"] == 15.5
    assert data["average_score"] == 7.75
    
    # 4. Verify DB
    async with AsyncSessionLocal() as session:
        from app.repositories import AdmissionRepository
        repo = AdmissionRepository(session)
        scores = await repo.get_profile_scores(profile.id)
        
        assert len(scores) == 2
        score_map = {s.subject.code: float(s.score) for s in scores}
        assert score_map["MATH"] == 8.5
        assert score_map["PHYS"] == 7.0

    # 5. Logic Check: Verify Sync (Orphan Removal)
    # Send update with ONLY MATH (PHYS removed)
    payload_v2 = {
        "version": 2,
        "admission_scores": {
            "subject_scores": {
                "MATH": 9.0
            }
        }
    }
    
    response_v2 = await client.put(
        f"/api/admissions/{profile.id}",
        json=payload_v2,
        headers=headers
    )
    
    assert response_v2.status_code == 200
    
    # Verify DB has only MATH
    async with AsyncSessionLocal() as session:
        repo = AdmissionRepository(session)
        scores = await repo.get_profile_scores(profile.id)
        
        assert len(scores) == 1
        assert scores[0].subject.code == "MATH"
        assert float(scores[0].score) == 9.0

    # 6. Logic Check: Validation (Score range)
    payload_invalid = {
        "version": 3,
        "admission_scores": {
            "subject_scores": {
                "MATH": 11.0 # Invalid > 10
            }
        }
    }
    
    response_invalid = await client.put(
        f"/api/admissions/{profile.id}",
        json=payload_invalid,
        headers=headers
    )
    
    assert response_invalid.status_code == 422 # Validation Error
