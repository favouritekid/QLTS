"""seed casbin_rule for the 3 enrollment-letter routes (officer allow + accountant deny)

The enrollment-letter router gates each route with ``CasbinAuth``. Prod does NOT
auto-sync templates (AUTO_SYNC_TEMPLATES False; only honoured in dev/test), and
docker-entrypoint.sh has no template-sync step — so this migration is the only
automatic write path into casbin_rule for the live DB.

Grants (mirrors OFFICER_TEMPLATE):
    POST /api/admissions/{id}/enrollment-letter                       (issue)
    GET  /api/admissions/{id}/enrollment-letter/{lid}/download        (re-download)
    GET  /api/admissions/{id}/enrollment-letters                      (list)
to role:officer — manager/admin inherit via the role tree. Because
role:accountant inherits role:officer, insert explicit accountant DENY rows for
the same three (separation-of-duties: finance never issues the official
admission letter, which also carries candidate PII). Casbin's deny-overrides
effect bounces the inherited officer allow → clean 403 at the gateway.

Insert WITH v3 ('allow' / 'deny') — a NULL eft makes Casbin ``load_policy`` crash
on next reload (memory casbin-insert-must-include-eft). ``template_id='_legacy'``
matches the sibling accountant-deny blocks and is special-cased by the template
drift/sync logic so these rows are never treated as orphans. Idempotent
(WHERE NOT EXISTS) so re-runs are safe. The policy is also added to
policy_templates.py so a future template sync regenerates it (does not drop it).

NOTE: the backend container must be RESTARTED after upgrade — the enforcer loads
policy once per process at lifespan (load_policy).

Revision ID: enrolllettercasbin20260718
Revises: enroll_letter_20260718
Create Date: 2026-07-18
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "enrolllettercasbin20260718"
down_revision = "enroll_letter_20260718"
branch_labels = None
depends_on = None


# (object, action) mirroring the OFFICER_TEMPLATE enrollment-letter grants.
_TARGETS = [
    ("/api/admissions/{id}/enrollment-letter", "POST"),
    ("/api/admissions/{id}/enrollment-letter/{lid}/download", "GET"),
    ("/api/admissions/{id}/enrollment-letters", "GET"),
]


def _insert(role: str, obj: str, act: str, eft: str) -> None:
    """Chèn một policy row nếu (role, object, action, EFT) chưa tồn tại.

    Guard PHẢI gồm cả v3: nếu chỉ so (v0,v1,v2) thì một row drift mang
    ``v3='allow'`` (hoặc NULL) cho role:accountant sẽ khớp, migration bỏ qua
    việc chèn row DENY, alembic báo thành công — và accountant giữ nguyên
    quyền trên 3 route chứa PII. Guard cũng khớp đúng điều kiện của
    ``downgrade()`` (vốn DELETE kèm v3), nên upgrade/downgrade đối xứng.
    """
    op.execute(
        f"""
        INSERT INTO casbin_rule (ptype, v0, v1, v2, v3, template_id)
        SELECT 'p', '{role}', '{obj}', '{act}', '{eft}', '_legacy'
        WHERE NOT EXISTS (
            SELECT 1 FROM casbin_rule
            WHERE ptype = 'p'
              AND v0 = '{role}'
              AND v1 = '{obj}'
              AND v2 = '{act}'
              AND v3 IS NOT DISTINCT FROM '{eft}'
        )
        """
    )


def upgrade() -> None:
    for obj, act in _TARGETS:
        _insert("role:officer", obj, act, "allow")
        _insert("role:accountant", obj, act, "deny")


def downgrade() -> None:
    for obj, act in _TARGETS:
        for role, eft in (("role:officer", "allow"), ("role:accountant", "deny")):
            op.execute(
                f"""
                DELETE FROM casbin_rule
                WHERE ptype = 'p'
                  AND v0 = '{role}'
                  AND v1 = '{obj}'
                  AND v2 = '{act}'
                  AND v3 = '{eft}'
                """
            )
