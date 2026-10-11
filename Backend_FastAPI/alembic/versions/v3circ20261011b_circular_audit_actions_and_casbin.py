"""V3 — nhật ký thông tư (``circular_defaulted`` / ``circular_changed``) + quyền Casbin của endpoint đổi thông tư (M4).

Revision ID: v3circ20261011b
Revises: v3circ20261011
Create Date: 2026-10-11

Phải lên TRƯỚC mã ghi hai ``action_type`` mới: ``transition()`` ghi ``circular_defaulted`` ở lần nộp đầu, endpoint
``POST /api/v2/admissions/{id}/applicable-circular`` ghi ``circular_changed``. Thiếu CHECK thì mọi lần nộp đầu
đổ ``CheckViolation``.

Casbin đọc ``casbin_rule`` lúc chạy — khai ở ``policy_templates.py`` thôi thì endpoint trả 403 cho mọi người.
Owner chốt (T2c + Q3): manager + admin được đổi; accountant DENY tường minh (accountant kế thừa officer); officer
không có dòng nào. ``v3`` (eft) BẮT BUỘC có giá trị — NULL làm ``load_policy()`` đổ (memory
``casbin-insert-must-include-eft``).

MỘT CÂU ``DO`` vì ``alembic/env.py`` chạy AUTOCOMMIT: tách lệnh thì ``DROP CONSTRAINT`` đã commit mà ``ADD`` hỏng
sẽ để bảng nhật ký KHÔNG còn CHECK. Câu DO tự kiểm hậu điều kiện rồi mới kết thúc.
"""

from alembic import op

revision = "v3circ20261011b"
down_revision = "v3circ20261011"
branch_labels = None
depends_on = None

CK_NAME = "ck_priority_audit_log_action_type"
ACTIONS_CU = (
    "kv_manual_override",
    "ut_evidence_verified",
    "ut_evidence_rejected",
    "admin_bulk_fill",
    "ut_evidence_untick",
    "ut_evidence_warning_dismissed",
)
ACTIONS_MOI_THEM = ("circular_defaulted", "circular_changed")
ACTIONS_MOI = ACTIONS_CU + ACTIONS_MOI_THEM

ENDPOINT = "/api/v2/admissions/*/applicable-circular"
#: (v0, v1, v2, v3) — admin có wildcard nhưng khai tường minh để grep theo route, như ``q9_07_e0c``.
POLICIES = (
    ("role:manager", ENDPOINT, "POST", "allow"),
    ("role:admin", ENDPOINT, "POST", "allow"),
    ("role:accountant", ENDPOINT, "POST", "deny"),
)
TEMPLATE_ID = "_v3circ20261011b_applicable_circular"


def check_sql(actions) -> str:
    return "action_type IN (%s)" % ", ".join("'%s'" % a for a in actions)


def _chen_policy_sql(v0, v1, v2, v3) -> str:
    return (
        "INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id, applied_at) "
        "SELECT 'p', '{v0}', '{v1}', '{v2}', '{v3}', '{tid}', now() "
        "WHERE NOT EXISTS (SELECT 1 FROM casbin_rule WHERE ptype = 'p' AND v0 = '{v0}' AND v1 = '{v1}' "
        "AND v2 = '{v2}' AND v3 = '{v3}')"
    ).format(v0=v0, v1=v1, v2=v2, v3=v3, tid=TEMPLATE_ID)


def _dem_policy_sql() -> str:
    dk = " OR ".join(
        "(v0 = '%s' AND v1 = '%s' AND v2 = '%s' AND v3 = '%s')" % p for p in POLICIES
    )
    return "SELECT COUNT(DISTINCT (v0, v1, v2, v3)) INTO n FROM casbin_rule WHERE ptype = 'p' AND (%s)" % dk


UPGRADE_DO_SQL = """
DO $m4$
DECLARE n bigint;
BEGIN
    ALTER TABLE priority_audit_log DROP CONSTRAINT {ck};
    ALTER TABLE priority_audit_log ADD CONSTRAINT {ck} CHECK ({moi});
{chen};
    {dem};
    IF n <> {so} THEN
        RAISE EXCEPTION USING MESSAGE = 'V3M4: can ' || {so} || ' dong casbin, thay ' || n;
    END IF;
END
$m4$
""".format(
    ck=CK_NAME,
    moi=check_sql(ACTIONS_MOI),
    chen=";\n".join("    " + _chen_policy_sql(*p) for p in POLICIES),
    dem=_dem_policy_sql(),
    so=len(POLICIES),
)

#: Downgrade chặn khi đã có hàng nhật ký mang action mới — CHECK cũ sẽ không nhận chúng, và xoá nhật ký là mất vết.
DOWNGRADE_DO_SQL = """
DO $m4d$
DECLARE n bigint;
BEGIN
    SELECT COUNT(*) INTO n FROM priority_audit_log WHERE action_type IN ({them});
    IF n > 0 THEN
        RAISE EXCEPTION USING MESSAGE = 'V3M4 downgrade bi chan: ' || n || ' hang nhat ky thong tu';
    END IF;
    ALTER TABLE priority_audit_log DROP CONSTRAINT {ck};
    ALTER TABLE priority_audit_log ADD CONSTRAINT {ck} CHECK ({cu});
    DELETE FROM casbin_rule WHERE ptype = 'p' AND template_id = '{tid}';
END
$m4d$
""".format(
    them=", ".join("'%s'" % a for a in ACTIONS_MOI_THEM),
    ck=CK_NAME,
    cu=check_sql(ACTIONS_CU),
    tid=TEMPLATE_ID,
)


def upgrade() -> None:
    op.execute(UPGRADE_DO_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_DO_SQL)
