"""q9_07_e4e: seed KV business resolution baseline (priority_area_config + default_bonus_rule)

Revision ID: q9_07_e4e
Revises: q9_07_e4d
Create Date: 2026-05-21

Q9 #07 Phase E.4 — engine KV chỉ hoạt động khi có 2 catalog seed này:

1. ``priority_area_config`` (academic_year=2026): 4 hàng KV1/KV2-NT/KV2/KV3.
   Không có hàng nào → ``_resolve_area_bonus()`` trả về None → mọi candidate
   cộng 0đ KV bất kể engine resolve ra KV nào. Audit verified
   (2026-05-21): ``SELECT count(*) FROM priority_area_config = 0``.

2. ``admission_method.default_bonus_rule`` cho 3 method codes (hoc_ba,
   thpt_qg, xet_tuyen_thang). Không có default → ``resolve_effective_bonus_rule()``
   trả về None → engine treats as "no bonus" → 0đ. Audit verified
   (2026-05-21): 0/3 methods có default; 52/55 admission_path có
   ``bonus_rule_override`` NULL + 3/55 có jsonb `null` string. → mọi path
   fall qua method default chain.

Bonus rules đã chốt với product (Q4 trong báo cáo rà soát 2026-05-21):
  hoc_ba          = area:true,  object:true,  max:2.75
  thpt_qg         = area:true,  object:true,  max:2.75
  xet_tuyen_thang = area:false, object:false, max:0.00  (tuyển thẳng không cộng ưu tiên)

Per memory ``migration-predicate-safety``: idempotent guards (INSERT WHERE
NOT EXISTS + UPDATE WHERE current_value matches pre-state) — safe re-run.

Downgrade revert chỉ những giá trị engine seed (so sánh JSONB exact match);
nếu admin đã chỉnh sau migration, downgrade KHÔNG ghi đè để bảo toàn ops change.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "q9_07_e4e"
down_revision: Union[str, None] = "q9_07_e4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (area_code, area_name, bonus_points, description)
_AREA_CONFIG_2026 = [
    ("KV1", "Khu vực 1", 0.75, "Vùng miền núi, dân tộc thiểu số, biên giới, hải đảo (TT 05/2021 Phụ lục 01)"),
    ("KV2-NT", "Khu vực 2 - Nông thôn", 0.50, "Nông thôn không thuộc KV1"),
    ("KV2", "Khu vực 2", 0.25, "Thành phố thuộc tỉnh, phường ngoại thành TP trực thuộc TƯ"),
    ("KV3", "Khu vực 3", 0.00, "Nội thành TP trực thuộc TƯ (không cộng ưu tiên)"),
]

# (method_code, default_bonus_rule JSONB)
_METHOD_BONUS_RULES = [
    (
        "hoc_ba",
        {
            "apply_area_bonus": True,
            "apply_object_bonus": True,
            "max_total_bonus": 2.75,
            "exception_codes": [],
        },
    ),
    (
        "thpt_qg",
        {
            "apply_area_bonus": True,
            "apply_object_bonus": True,
            "max_total_bonus": 2.75,
            "exception_codes": [],
        },
    ),
    (
        "xet_tuyen_thang",
        {
            "apply_area_bonus": False,
            "apply_object_bonus": False,
            "max_total_bonus": 0.00,
            "exception_codes": [],
        },
    ),
]


def upgrade() -> None:
    conn = op.get_bind()

    # ============================================================
    # 1. Seed priority_area_config (academic_year=2026)
    # ============================================================
    pre_count = conn.execute(
        sa.text(
            "SELECT COUNT(*) FROM priority_area_config "
            "WHERE academic_year = 2026 AND effective_to IS NULL"
        )
    ).scalar()
    print(f"[q9_07_e4e] Pre-flight priority_area_config active 2026 rows={pre_count}")

    area_inserted = 0
    for area_code, area_name, bonus_points, description in _AREA_CONFIG_2026:
        result = conn.execute(
            sa.text(
                """
                INSERT INTO priority_area_config
                    (academic_year, area_code, area_name, bonus_points,
                     description, effective_from)
                SELECT 2026,
                       CAST(:area_code AS VARCHAR),
                       CAST(:area_name AS VARCHAR),
                       CAST(:bonus_points AS NUMERIC(4,2)),
                       CAST(:description AS TEXT),
                       DATE '2026-01-01'
                WHERE NOT EXISTS (
                    SELECT 1 FROM priority_area_config
                    WHERE academic_year = 2026
                      AND area_code = CAST(:area_code AS VARCHAR)
                      AND effective_to IS NULL
                )
                """
            ),
            {
                "area_code": area_code,
                "area_name": area_name,
                "bonus_points": bonus_points,
                "description": description,
            },
        )
        area_inserted += result.rowcount

    print(f"[q9_07_e4e] Seeded priority_area_config rows inserted={area_inserted}")

    # ============================================================
    # 2. Update admission_method.default_bonus_rule
    # ============================================================
    # Idempotent: chỉ UPDATE khi default_bonus_rule IS NULL (chưa được
    # seed/admin chỉnh). Trường hợp admin đã set sau migration → giữ
    # nguyên ops change, KHÔNG ghi đè.
    method_updated = 0
    for method_code, rule_dict in _METHOD_BONUS_RULES:
        import json
        rule_json = json.dumps(rule_dict)
        result = conn.execute(
            sa.text(
                """
                UPDATE admission_method
                SET default_bonus_rule = CAST(:rule_json AS JSONB)
                WHERE code = CAST(:method_code AS VARCHAR)
                  AND default_bonus_rule IS NULL
                """
            ),
            {"method_code": method_code, "rule_json": rule_json},
        )
        method_updated += result.rowcount

    print(f"[q9_07_e4e] Updated admission_method.default_bonus_rule rows={method_updated}")

    # ============================================================
    # 3. Verification report
    # ============================================================
    post_areas = conn.execute(
        sa.text(
            "SELECT count(*) FROM priority_area_config "
            "WHERE academic_year = 2026 AND effective_to IS NULL"
        )
    ).scalar()
    post_methods = conn.execute(
        sa.text(
            "SELECT count(*) FROM admission_method "
            "WHERE code IN ('hoc_ba', 'thpt_qg', 'xet_tuyen_thang') "
            "  AND default_bonus_rule IS NOT NULL"
        )
    ).scalar()
    print(
        f"[q9_07_e4e] Post-state priority_area_config active 2026={post_areas} "
        f"(expected 4), methods with default_bonus_rule={post_methods} (expected 3)"
    )


def downgrade() -> None:
    """Revert seeded values ONLY if they still match seed shape.

    Admin có thể đã chỉnh post-migration; downgrade KHÔNG ghi đè change đó.
    Match logic:
      - priority_area_config: match on (area_code, bonus_points)
      - admission_method.default_bonus_rule: match exact JSONB shape
    """
    conn = op.get_bind()

    # Revert priority_area_config — chỉ DELETE rows match seed value
    area_deleted = 0
    for area_code, _area_name, bonus_points, _description in _AREA_CONFIG_2026:
        result = conn.execute(
            sa.text(
                """
                DELETE FROM priority_area_config
                WHERE academic_year = 2026
                  AND area_code = CAST(:area_code AS VARCHAR)
                  AND bonus_points = CAST(:bonus_points AS NUMERIC(4,2))
                  AND effective_to IS NULL
                """
            ),
            {"area_code": area_code, "bonus_points": bonus_points},
        )
        area_deleted += result.rowcount
    print(f"[q9_07_e4e] Downgrade: deleted priority_area_config rows={area_deleted}")

    # Revert admission_method.default_bonus_rule — match exact JSONB
    method_reverted = 0
    for method_code, rule_dict in _METHOD_BONUS_RULES:
        import json
        rule_json = json.dumps(rule_dict)
        result = conn.execute(
            sa.text(
                """
                UPDATE admission_method
                SET default_bonus_rule = NULL
                WHERE code = CAST(:method_code AS VARCHAR)
                  AND default_bonus_rule = CAST(:rule_json AS JSONB)
                """
            ),
            {"method_code": method_code, "rule_json": rule_json},
        )
        method_reverted += result.rowcount
    print(f"[q9_07_e4e] Downgrade: reverted admission_method default_bonus_rule rows={method_reverted}")
