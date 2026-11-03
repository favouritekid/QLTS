"""Quyền Casbin của API văn bản Hội đồng (Lần xét tuyển GĐ1, lượt E2) — manager ĐỌC bộ văn bản.

Revision ID: hdts20261103b
Revises: hdts20261103
Create Date: 2026-11-03

Casbin đọc ``casbin_rule`` lúc chạy; production KHÔNG tự đồng bộ ``policy_templates.py``
(``AUTO_SYNC_TEMPLATES`` chỉ ở dev / test) ⇒ thiếu migration này thì manager nhận 403 thật
dù mọi test API xanh (memory / ``test_finance_decision_policies_have_migration``).

Ba dòng ``role:manager`` cho ba route ĐỌC bộ văn bản. Admin qua wildcard ``/*`` (không khai
thêm). Officer / accountant / user KHÔNG có dòng nào ⇒ mọi route của module bị từ chối. Phạm
vi đơn vị do ``deps.get_council_document_set_for_user`` quyết (không phải Casbin). ``v3``
(eft) BẮT BUỘC có giá trị — NULL làm ``load_policy()`` đổ.

MỘT câu ``DO`` vì ``alembic/env.py`` chạy AUTOCOMMIT: câu tự kiểm hậu điều kiện (đủ 3 dòng)
rồi mới kết thúc; chèn ``WHERE NOT EXISTS`` ⇒ chạy lại được. Downgrade xoá đúng các dòng
mang ``template_id`` của migration này.
"""

from alembic import op

revision = "hdts20261103b"
down_revision = "hdts20261103"
branch_labels = None
depends_on = None

TIEN_TO = "/api/admission-config/council-documents"
#: (v0, v1, v2, v3)
POLICIES = (
    ("role:manager", TIEN_TO + "/sets", "GET", "allow"),
    ("role:manager", TIEN_TO + "/sets/{set_id}", "GET", "allow"),
    ("role:manager", TIEN_TO + "/sets/{set_id}/files/{thu_tu}", "GET", "allow"),
)
TEMPLATE_ID = "_hdts20261103b_council_document_read"


def _chen_policy_sql(v0, v1, v2, v3) -> str:
    return (
        "INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id, applied_at) "
        "SELECT 'p', '{v0}', '{v1}', '{v2}', '{v3}', '{tid}', now() "
        "WHERE NOT EXISTS (SELECT 1 FROM casbin_rule WHERE ptype = 'p' AND v0 = '{v0}' "
        "AND v1 = '{v1}' AND v2 = '{v2}' AND v3 = '{v3}')"
    ).format(v0=v0, v1=v1, v2=v2, v3=v3, tid=TEMPLATE_ID)


def _dem_policy_sql() -> str:
    dk = " OR ".join(
        "(v0 = '%s' AND v1 = '%s' AND v2 = '%s' AND v3 = '%s')" % p for p in POLICIES
    )
    return (
        "SELECT COUNT(DISTINCT (v0, v1, v2, v3)) INTO n FROM casbin_rule "
        "WHERE ptype = 'p' AND (%s)" % dk
    )


UPGRADE_DO_SQL = """
DO $hdtsb$
DECLARE n bigint;
BEGIN
{chen};
    {dem};
    IF n <> {so} THEN
        RAISE EXCEPTION USING MESSAGE = 'HDTSB: can ' || {so} || ' dong casbin, thay ' || n;
    END IF;
END
$hdtsb$
""".format(
    chen=";\n".join("    " + _chen_policy_sql(*p) for p in POLICIES),
    dem=_dem_policy_sql(),
    so=len(POLICIES),
)

DOWNGRADE_SQL = (
    "DELETE FROM casbin_rule WHERE ptype = 'p' AND template_id = '%s'" % TEMPLATE_ID
)


def upgrade() -> None:
    op.execute(UPGRADE_DO_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
