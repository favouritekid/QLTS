"""Casbin policy lock for the 3 enrollment-letter routes.

Non-tautological (memory ``pattern-change-impact-audit``): loads the ACTUAL
templates + an in-memory Casbin enforcer wired with the REAL production diamond
edges (queried from casbin_rule ptype='g'):

    role:admin      -> role:manager
    role:manager    -> role:officer
    role:accountant -> role:officer
    role:officer    -> role:user

There is NO ``role:admin -> role:accountant`` edge in prod, so the accountant
DENY rows do NOT bounce admin — admin reaches ALLOW via admin→manager→officer.

Matrix (3 routes × 5 roles):
    officer     ALLOW  (direct allow rules)
    manager     ALLOW  (inherits officer)
    admin       ALLOW  (inherits manager → officer; NOT accountant)
    accountant  DENY   (explicit deny overrides inherited officer allow)
    user        DENY   (no allow; officer inherits user, not vice-versa)
"""
from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

import casbin
import pytest

from app.casbin_config.policy_templates import (
    ACCOUNTANT_TEMPLATE,
    ADMIN_TEMPLATE,
    BASIC_USER_TEMPLATE,
    MANAGER_TEMPLATE,
    OFFICER_TEMPLATE,
    apply_template,
)

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
AUTH_MODEL_PATH = REPO_BACKEND_ROOT / "auth_model.conf"

# (object, action) — the template objects keep {id}/{lid} placeholders; the
# enforce() calls below use concrete ids that keyMatch4 collapses per segment.
LETTER_ROUTES = [
    ("/api/admissions/{id}/enrollment-letter", "POST"),
    ("/api/admissions/{id}/enrollment-letter/{lid}/download", "GET"),
    ("/api/admissions/{id}/enrollment-letters", "GET"),
]
CONCRETE_ROUTES = [
    ("/api/admissions/123/enrollment-letter", "POST"),
    ("/api/admissions/123/enrollment-letter/456/download", "GET"),
    ("/api/admissions/123/enrollment-letters", "GET"),
]


# ----------------------------------------------------------------------
# Template-level locks (cheap — no Casbin runtime)
# ----------------------------------------------------------------------


def test_officer_template_has_enrollment_letter_grants():
    """OFFICER_TEMPLATE must carry the 3 enrollment-letter ALLOW rules
    (manager/admin inherit them). Drift guard: rename/remove → fail loud."""
    objects = {
        (r["object"], r["action"])
        for r in apply_template("officer", "role:officer")
    }
    for route in LETTER_ROUTES:
        assert route in objects, f"OFFICER_TEMPLATE missing allow for {route}"


def test_accountant_template_has_enrollment_letter_denies():
    """ACCOUNTANT_TEMPLATE must carry the 3 explicit DENY rows — without them
    accountant would reach the routes via inherited officer allow."""
    deny_objects = {
        (r["object"], r["action"])
        for r in apply_template("accountant", "role:accountant")
        if r.get("eft") == "deny"
    }
    for route in LETTER_ROUTES:
        assert route in deny_objects, f"ACCOUNTANT_TEMPLATE missing deny for {route}"


# ----------------------------------------------------------------------
# Enforce() runtime matrix via in-memory Casbin (real diamond)
# ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def enforcer():
    """Enforcer with admin+manager+officer+accountant templates + the REAL
    production diamond edges (module-scoped; read-only enforce calls)."""
    lines = []
    for name, tmpl in (
        ("admin", ADMIN_TEMPLATE),
        ("manager", MANAGER_TEMPLATE),
        ("officer", OFFICER_TEMPLATE),
        ("accountant", ACCOUNTANT_TEMPLATE),
        # PHẢI nạp: không có nó thì role:user không có rule NÀO, và cell
        # user=DENY đúng vì lý do tầm thường ("chẳng có policy nào") chứ không
        # chứng minh được điều ta muốn khoá — rằng user CÓ quyền khác nhưng
        # KHÔNG có quyền trên 3 route này.
        ("user", BASIC_USER_TEMPLATE),
    ):
        for r in apply_template(name, f"role:{name}"):
            lines.append(
                f"p, {r['subject']}, {r['object']}, {r['action']}, "
                f"{r.get('eft', 'allow')}"
            )
    # Real diamond (matches casbin_rule ptype='g'); NO admin→accountant.
    lines += [
        "g, role:admin, role:manager",
        "g, role:manager, role:officer",
        "g, role:accountant, role:officer",
        "g, role:officer, role:user",
    ]
    tmp = NamedTemporaryFile(mode="w", suffix=".csv", delete=False, encoding="utf-8")
    tmp.write("\n".join(lines) + "\n")
    tmp.close()
    return casbin.Enforcer(str(AUTH_MODEL_PATH), tmp.name)


@pytest.mark.parametrize(
    "role,expected",
    [
        ("role:officer", True),
        ("role:manager", True),
        ("role:admin", True),
        ("role:accountant", False),
        ("role:user", False),
    ],
)
@pytest.mark.parametrize("obj,action", CONCRETE_ROUTES)
def test_enrollment_letter_enforce_matrix(enforcer, role, expected, obj, action):
    """15-cell anchor (3 routes × 5 roles). officer/manager/admin ALLOW;
    accountant DENY (explicit); user DENY (no allow)."""
    result = enforcer.enforce(role, obj, action)
    assert result is expected, (
        f"Casbin enforce drift: ({role}, {obj}, {action}) "
        f"expected {expected}, got {result}"
    )


# ----------------------------------------------------------------------
# Chống tự-đúng: hai cell dễ pass vì lý do sai
# ----------------------------------------------------------------------


def test_basic_user_template_is_not_empty():
    """Cell ``user=DENY`` chỉ có nghĩa nếu role:user THỰC SỰ có policy khác.
    Template rỗng ⇒ mọi enforce đều False và ma trận không khoá được gì."""
    policies = apply_template("user", "role:user")
    assert policies, "BASIC_USER_TEMPLATE rỗng — cell user trong ma trận vô nghĩa"


def test_admin_allow_survives_without_the_admin_wildcard(enforcer):
    """``ADMIN_TEMPLATE`` là wildcard ``/*`` + ``.*``, nên cell admin=ALLOW ở ma
    trận trên pass BẤT KỂ diamond có đúng hay không — nó không chứng minh điều
    docstring module khẳng định (admin tới được ALLOW qua admin→manager→officer,
    KHÔNG qua accountant).

    Ở đây dựng enforcer KHÔNG có ADMIN_TEMPLATE: nếu admin vẫn ALLOW thì đường
    kế thừa thật sự hoạt động. Nếu ai đó gỡ cạnh admin→manager, test này đỏ còn
    ma trận kia vẫn xanh nhờ wildcard.
    """
    lines = []
    for name, tmpl in (
        ("manager", MANAGER_TEMPLATE),
        ("officer", OFFICER_TEMPLATE),
        ("accountant", ACCOUNTANT_TEMPLATE),
    ):
        for r in apply_template(name, f"role:{name}"):
            lines.append(
                f"p, {r['subject']}, {r['object']}, {r['action']}, "
                f"{r.get('eft', 'allow')}"
            )
    lines += [
        "g, role:admin, role:manager",
        "g, role:manager, role:officer",
        "g, role:accountant, role:officer",
        "g, role:officer, role:user",
    ]
    tmp = NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    )
    tmp.write("\n".join(lines) + "\n")
    tmp.close()
    no_wildcard = casbin.Enforcer(str(AUTH_MODEL_PATH), tmp.name)

    for obj, action in CONCRETE_ROUTES:
        assert no_wildcard.enforce("role:admin", obj, action) is True, (
            f"admin KHÔNG tới được ALLOW qua diamond cho ({obj}, {action}) — "
            "ma trận chính đang pass nhờ wildcard của ADMIN_TEMPLATE"
        )
    # Và deny của accountant vẫn thắng allow kế thừa từ officer.
    for obj, action in CONCRETE_ROUTES:
        assert no_wildcard.enforce("role:accountant", obj, action) is False


# ----------------------------------------------------------------------
# keyMatch4: hai placeholder phải KHÁC TÊN
# ----------------------------------------------------------------------


def test_download_route_uses_two_distinct_placeholders():
    """Route download có HAI id trên cùng một path. keyMatch4 bắt các
    placeholder TRÙNG TÊN phải khớp CÙNG giá trị, nên viết ``{id}`` cho cả hai
    vị trí sẽ chỉ match khi ``profile_id == letter_id`` — officer nhận 403 âm
    thầm cho mọi hồ sơ khác, và không test nào hiện có bắt được.

    Khoá tên placeholder ở tầng template để đổi tên là fail loud."""
    objects = {
        r["object"] for r in apply_template("officer", "role:officer")
    }
    download = "/api/admissions/{id}/enrollment-letter/{lid}/download"
    assert download in objects, (
        "Route download phải giữ nguyên hai placeholder KHÁC TÊN {id}/{lid}"
    )


def test_same_name_placeholders_would_break_mismatched_ids():
    """Chứng minh hậu quả bằng chính Casbin, không phải bằng lời: policy dùng
    ``{id}`` cho cả hai vị trí chỉ match khi hai id BẰNG NHAU."""
    lines = [
        "p, role:officer, "
        "/api/admissions/{id}/enrollment-letter/{id}/download, GET, allow",
    ]
    tmp = NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    )
    tmp.write("\n".join(lines) + "\n")
    tmp.close()
    broken = casbin.Enforcer(str(AUTH_MODEL_PATH), tmp.name)

    same = "/api/admissions/123/enrollment-letter/123/download"
    differ = "/api/admissions/123/enrollment-letter/456/download"
    assert broken.enforce("role:officer", same, "GET") is True
    assert broken.enforce("role:officer", differ, "GET") is False, (
        "keyMatch4 lẽ ra phải TỪ CHỐI khi hai placeholder cùng tên nhận giá trị "
        "khác nhau — nếu assert này đỏ thì lập luận của test trên đã sai"
    )
