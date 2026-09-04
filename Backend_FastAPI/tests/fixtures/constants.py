# tests/fixtures/constants.py
# -*- coding: utf-8 -*-
"""
Tập trung hóa các hằng số được sử dụng trong bộ test. ⚙️
"""

# ==================================
# URLs Endpoints 🌐
# ==================================


class AuthURLs:
    """URLs cho module Authentication."""

    LOGIN = "/api/auth/login"
    REFRESH = "/api/auth/refresh"
    LOGOUT = "/api/auth/logout"
    CHANGE_PASSWORD = "/api/auth/change-password"
    FORGOT_PASSWORD = "/api/auth/forgot-password"
    RESET_PASSWORD = "/api/auth/reset-password"
    REGISTER = "/api/auth/register"  # Thêm URL đăng ký nếu có test

    # MFA endpoints
    VERIFY_MFA = "/api/auth/verify-mfa"
    MFA_SETUP = "/api/auth/mfa/setup"
    MFA_ENABLE = "/api/auth/mfa/enable"
    MFA_DISABLE = "/api/auth/mfa/disable"
    MFA_STATUS = "/api/auth/mfa/status"
    MFA_BACKUP_CODES = "/api/auth/mfa/backup-codes"


class AdminURLs:
    """URLs cho các endpoint /api/admin."""

    """URLs cho các endpoint /api/admin."""
    BASE = "/api/admin"
    USERS = f"{BASE}/users"
    USER_DETAIL = lambda user_id: f"{AdminURLs.USERS}/{user_id}"  # Tham chiếu qua class
    # Router declares ``POST /{user_id}/password`` (admin/users.py:310);
    # constant earlier said ``/set-password``, so the 3 set-password +
    # bulk-action tests in ``tests/api/test_admin_users.py`` were
    # hitting non-existent paths and the expected 404/405 assertions
    # were drifting. Aligned 2026-04-30.
    USER_SET_PASSWORD = (
        lambda user_id: f"{AdminURLs.USER_DETAIL(user_id)}/password"
    )  # Tham chiếu qua class
    # Router declares ``POST /bulk`` (admin/users.py:433); constant
    # earlier said ``/bulk-action`` which collided with
    # ``/users/{user_id}`` and surfaced as a 405 instead of the real
    # 404 / endpoint. Aligned 2026-04-30.
    BULK_ACTION = f"{USERS}/bulk"

    ORGANIZATION_UNITS = f"{BASE}/organization-units"
    ORGANIZATION_UNIT_DETAIL = (
        lambda unit_id: f"{AdminURLs.ORGANIZATION_UNITS}/{unit_id}"
    )  # Tham chiếu qua class

    # `/majors` KHÔNG còn được đăng ký: migration 3 tầng đổi endpoint thành
    # `/programs` (router trả `schemas.MajorProgram`). `MAJORS`/`MAJOR_DETAIL`
    # đã bị GỠ HẲN thay vì giữ lại — chúng không còn caller nào, nên "giữ để
    # khỏi phá" là lý lẽ vòng tròn, và một hằng số trỏ tới đường chết chỉ chờ
    # người sau dùng lại rồi nhận 404.
    PROGRAMS = f"{BASE}/programs"
    PROGRAM_DETAIL = (
        lambda program_id: f"{AdminURLs.PROGRAMS}/{program_id}"
    )  # Tham chiếu qua class

    PIPELINE_STAGES = f"{BASE}/pipeline-stages"
    PIPELINE_STAGE_DETAIL = (
        lambda stage_id: f"{AdminURLs.PIPELINE_STAGES}/{stage_id}"
    )  # Tham chiếu qua class

    CONSULTATION_STATUSES = f"{BASE}/consultation-statuses"
    CONSULTATION_STATUS_DETAIL = (
        lambda status_id: f"{AdminURLs.CONSULTATION_STATUSES}/{status_id}"
    )  # Tham chiếu qua class

    ASSIGNMENT_CONFIG = f"{BASE}/assignment-config"
    # SỬA DÒNG NÀY:
    ASSIGNMENT_CONFIG_DETAIL = (
        lambda unit_id: f"{AdminURLs.ASSIGNMENT_CONFIG}/{unit_id}"
    )  # Tham chiếu qua AdminURLs.ASSIGNMENT_CONFIG

    SKILL_RULES = f"{BASE}/skill-rules"
    # SỬA DÒNG NÀY:
    SKILL_RULE_DETAIL = (
        lambda rule_id: f"{AdminURLs.SKILL_RULES}/{rule_id}"
    )  # Tham chiếu qua AdminURLs.SKILL_RULES

    # Đường THẬT ghép từ ba chỗ, KHÔNG suy từ tên hằng:
    #   app/routers/admin/roles.py:61      APIRouter(prefix="/roles")
    #   app/routers/admin/__init__.py:54   APIRouter(prefix="/admin")
    #   app/main.py:957                    include_router(admin_router, prefix="/api")
    # ⇒ `/api/admin/roles/...`. `/api/admin/policies` và `/api/admin/assign-role`
    # KHÔNG còn router nào phục vụ (đã grep toàn `app/`), nên hai ca của
    # `tests/api/test_admin_casbin.py` nhận `{"detail":"Not Found",
    # "error_code":"HTTP_404"}` — 404 của FastAPI cho route không tồn tại, KHÔNG
    # phải 404-thay-403 của hợp đồng IDOR. Hạ kỳ vọng xuống 404 sẽ khoá vĩnh
    # viễn một ca không hề chạm tới endpoint nào.
    #
    # Alias cũ cố ý KHÔNG được dựng lại ở backend: nó là nguồn chuẩn thứ hai cho
    # cùng một hành động và chính nó che mất lỗi này ở lần sau.
    POLICIES = f"{BASE}/roles/policies"
    # HAI hằng TÁCH RIÊNG — backend phục vụ hai đường KHÁC NHAU:
    #   POST   /api/admin/roles/assign   (roles.py:358)
    #   DELETE /api/admin/roles/revoke   (roles.py:394)
    # Một hằng dùng chung cho cả hai hành động rồi phân biệt bằng HTTP method là
    # đúng cái hình dạng đã đẻ ra lỗi ở frontend; đừng tái tạo nó trong tests.
    ASSIGN_ROLE = f"{BASE}/roles/assign"
    REVOKE_ROLE = f"{BASE}/roles/revoke"

    # Audit Logs URLs
    AUDIT_LOGS = f"{BASE}/audit-logs"
    AUDIT_LOGS_ENTITY = (
        lambda entity_type, entity_id: f"{AdminURLs.AUDIT_LOGS}/entity/{entity_type}/{entity_id}"
    )
    AUDIT_LOGS_SUMMARY = f"{AUDIT_LOGS}/summary"


class SecurityURLs:
    """URLs cho module Security (login history, trusted devices)."""

    LOGIN_HISTORY = "/api/security/login-history"
    SUSPICIOUS_LOGINS = "/api/security/suspicious-logins"
    CONFIRM_LOGIN = "/api/security/confirm-login"
    SECURE_ACCOUNT = "/api/security/secure-account"
    TRUSTED_DEVICES = "/api/security/trusted-devices"
    TRUSTED_DEVICE_DETAIL = lambda device_id: f"/api/security/trusted-devices/{device_id}"


class ProfileURLs:
    """URLs cho module Profile."""

    PROFILE = "/api/profile"


class PipelineURLs:
    """URLs cho module Pipeline (public)."""

    ALL = "/api/pipeline/all"


class LeadsURLs:
    LEADS = "/api/leads"

    # 1. Định nghĩa chi tiết Lead (Giữ nguyên)
    LEAD_DETAIL = lambda lead_id: f"{LeadsURLs.LEADS}/{lead_id}"

    # 2. SỬA LỖI: Thêm LeadsURLs. vào trước các hàm lambda

    # URL gán lead: POST /api/leads/{lead_id}/assign
    ASSIGN = lambda lead_id: f"{LeadsURLs.LEAD_DETAIL(lead_id)}/assign"

    # URL actions: POST /api/leads/{lead_id}/action
    ACTION = lambda lead_id: f"{LeadsURLs.LEAD_DETAIL(lead_id)}/action"

    # URL consultations: POST /api/leads/{lead_id}/consultations
    CONSULTATIONS = lambda lead_id: f"{LeadsURLs.LEAD_DETAIL(lead_id)}/consultations"

    # URL timeline: GET /api/leads/{lead_id}/timeline
    TIMELINE = lambda lead_id: f"{LeadsURLs.LEAD_DETAIL(lead_id)}/timeline"

    INSIGHTS = lambda lead_id: f"{LeadsURLs.LEAD_DETAIL(lead_id)}/insights"

    ADMIN_REVERT_STATUS = (
        lambda lead_id: f"{AdminURLs.BASE}/leads/{lead_id}/revert-status"
    )


class OrganizationURLs:
    """URLs cho module Organization (public)."""

    UNITS = "/api/organization/organization-units"
    MAJORS = "/api/organization/majors"


class UsersURLs:
    """URLs cho module Users (public)."""

    ME = "/api/users/me"


class HealthURLs:
    """URLs cho Health Checks."""

    HEALTH = "/health"
    DETAILED_HEALTH = "/health/detailed"


# ==================================
# Dữ Liệu Người Dùng Mẫu 🧑‍💻
# ==================================


class TestUsers:
    """Thông tin đăng nhập và dữ liệu cho người dùng mẫu."""

    # --- User Admin ---
    ADMIN = {
        "username": "testadmin",
        "email": "admin@example.com",
        # QUAN TRỌNG: Mật khẩu này PHẢI đáp ứng validation rules (độ dài, ký tự đặc biệt,...)
        "password": "AdminPassword!123",
        "role": "admin",
        "status": "active",
    }

    # --- User Thường (Regular) ---
    REGULAR = {
        "username": "testuser_regular",
        "email": "regular@example.com",
        # QUAN TRỌNG: Mật khẩu này PHẢI đáp ứng validation rules
        "password": "RegularPassword?456",
        "role": "user",
        "status": "active",
    }

    # --- User Mặc Định (Thường dùng trong các test auth cơ bản) ---
    DEFAULT = {
        "username": "testuser_default",
        "email": "test_default@example.com",
        # QUAN TRỌNG: Mật khẩu này PHẢI đáp ứng validation rules
        "password": "ValidPassword123!",
        # Hash thật của "ValidPassword123!" (Lấy từ generate_password_hash.py hoặc conftest.py cũ)
        # $2b$12$Ocybw6M1qmA1KVo9Z3VhY.hNGgnn1N/rA/tdlFWFuKtIfhNw7t5Hi
        "real_hash": "$2b$12$Ocybw6M1qmA1KVo9Z3VhY.hNGgnn1N/rA/tdlFWFuKtIfhNw7t5Hi",
        "role": "user",
        "status": "active",
    }

    # --- User Manager (Bổ sung) ---
    MANAGER = {
        "username": "testmanager",
        "email": "manager@example.com",
        "password": "ManagerPassword!789",
        "role": "manager",  # Role trong DB
        "status": "active",
    }

    # Manager in a DIFFERENT organization unit from the default
    # ``seed_lead_dependencies`` unit. Use with the
    # ``manager_other_unit_user_in_db`` fixture for cross-unit IDOR
    # tests (manager attempting to access a profile outside their
    # unit). Distinct username/email so it can coexist with MANAGER
    # in the same test database without unique constraint conflicts.
    MANAGER_OTHER_UNIT = {
        "username": "testmanager_unit2",
        "email": "manager_unit2@example.com",
        "password": "ManagerPassword!789",
        "role": "manager",
        "status": "active",
    }

    # --- User Officer (Bổ sung) ---
    OFFICER = {
        "username": "testofficer",
        "email": "officer@example.com",
        "password": "OfficerPassword!012",
        "role": "officer",  # Role trong DB
        "status": "active",
    }

    # --- Dữ liệu không hợp lệ ---
    INVALID_PASSWORD = "wrongpassword"  # Mật khẩu sai
    WEAK_PASSWORD = "123"  # Mật khẩu yếu
    NON_EXISTENT_USERNAME = "nosuchuser"  # Username không tồn tại
    NON_EXISTENT_EMAIL = "noemail@example.com"  # Email không tồn tại

    # --- Dữ liệu cho các test khác ---
    USER_FOR_UPDATE = {
        "username": "update_me",
        "email": "update_me@example.com",
        "password": "UpdatePassword!789",
        "full_name": "User To Update",
        "role": "officer",
        "status": "active",
    }
    USER_FOR_DELETE = {
        "username": "delete_me",
        "email": "delete_me@example.com",
        "password": "DeletePassword!000",
        "full_name": "User To Delete",
        "role": "user",
        "status": "pending",
    }


# ==================================
# Hằng Số Bảo Mật 🔒
# ==================================


class SecurityConstants:
    """Các giá trị liên quan đến bảo mật (hash, token...)."""

    # Hash của "a_very_random_dummy_password_for_timing_attack_$%^&*"
    # Lấy từ generate_password_hash.py hoặc conftest.py cũ
    # $2b$12$d5AUHnn4.BNHoa2kuIWmt.40hvBLF4YYAjtyE9gHDNQFgypctRf62
    DUMMY_BCRYPT_HASH = "$2b$12$d5AUHnn4.BNHoa2kuIWmt.40hvBLF4YYAjtyE9gHDNQFgypctRf62"

    # Token mẫu (có thể dùng để test lỗi giải mã, hết hạn...)
    INVALID_TOKEN_STRING = "this.is.not.a.valid.token"
    # Có thể tạo token hết hạn ở đây nếu cần test nhiều lần
    # EXPIRED_REFRESH_TOKEN = create_refresh_token(data={"sub": "any"}, expires_delta=timedelta(seconds=-1))
    INVALID_RESET_TOKEN_STRING = "invalid.reset.token"


# ==================================
# Dữ Liệu Test Khác ⚙️
# ==================================


class TestPipelineData:
    """Dữ liệu mẫu cho pipeline stages và statuses."""

    STAGE_A = {"id": "stage_a", "name": "Stage A", "order": 10}
    STAGE_B = {"id": "stage_b", "name": "Stage B", "order": 20}
    STAGE_C = {
        "id": "stage_c",
        "name": "Stage C (No Status)",
        "order": 30,
    }  # Stage không có status

    STATUS_A1 = {
        "id": "status_a1",
        "name": "Status A1",
        "color_code": "#AAAAAA",
        "stage_id": STAGE_A["id"],
    }
    STATUS_B1 = {
        "id": "status_b1",
        "name": "Status B1",
        "color_code": "#BBBBBB",
        "stage_id": STAGE_B["id"],
    }
    # Thêm status khác nếu cần


class TestOrgData:
    """Dữ liệu mẫu cho Organization Units và MajorPrograms."""

    UNIT_1 = {"id": 1, "name": "Test Unit 1", "type": "Faculty"}
    # Distinct second unit for cross-unit IDOR fixtures. ``id`` is
    # picked above the seed_lead_dependencies range so it never
    # collides with auto-allocated org unit IDs in the test DB.
    UNIT_2 = {"id": 9001, "name": "Test Unit 2", "type": "department"}
    # ✅ FIX: Updated to match MajorProgram schema (added degree_level)
    MAJOR_1 = {
        "id": 1,
        "name": "Test Major 1",
        "code": "TM1",
        "degree_level": "Cao đẳng",  # Required field for MajorProgram
        "unit_id": UNIT_1["id"]
    }


class TestLeadData:
    """Dữ liệu mẫu cho Leads."""

    LEAD_1 = {
        "full_name": "Test Lead 1",
        "email": "lead1@example.com",
        "phone": "0901111111",
        "source": "website",
        "unit_id": TestOrgData.UNIT_1["id"],
        "major_id": TestOrgData.MAJOR_1["id"],
        # Giả sử lead này đang ở trạng thái STATUS_A1
        "status": TestPipelineData.STATUS_A1["id"],
        "consultation_status_id": TestPipelineData.STATUS_A1["id"],
        "pipeline_stage_id": TestPipelineData.STAGE_A["id"],
    }
    LEAD_CREATE_PAYLOAD = {
        "full_name": "New Lead Payload",
        "email": "new_lead@example.com",
        "phone": "0909888777",
        "source": "event",
        "unit_id": TestOrgData.UNIT_1["id"],
    }


class TestConfigData:
    """Dữ liệu mẫu cho Assignment Config và Skill Rules."""

    ASSIGNMENT_PARAMS = {"strategy": "round_robin", "max_concurrent": 5}
    SKILL_RULE_1 = {
        "lead_attribute": "source",
        "attribute_value": "event",
        "required_skill": "EventHandling",
    }


# Thêm các hằng số ID không tồn tại
NON_EXISTENT_ID = 99999
NON_EXISTENT_STAGE_ID = "no_stage"
NON_EXISTENT_STATUS_ID = "no_status"
NON_EXISTENT_LEAD_ID = 88888  # Bổ sung ID lead không tồn tại
