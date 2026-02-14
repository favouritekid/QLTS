# alembic/versions/seed20260214001_seed_tuition_and_offering_config.py
"""Seed tuition fees, offering_admission_config, and link profiles.

Revision ID: seed20260214001
Revises: ctv20260212001
Create Date: 2026-02-14

This migration seeds:
1. offering_academic_info for all offerings missing year 2026 data
2. tuition_fee_per_year for all offerings (realistic amounts)
3. offering_admission_config from admission_path data
4. Links existing profiles to their offering_admission_config
"""
from alembic import op


revision = "seed20260214001"
down_revision = "ctv20260212001"
branch_labels = None
depends_on = None


# Tuition fees by program name pattern (VND/year)
# Based on typical Vietnamese vocational/college tuition ranges
TUITION_MAP = {
    "Điều dưỡng": 6690000,
    "Dược": 7200000,
    "Y sỹ đa khoa": 7500000,
    "Y học cổ truyền": 7000000,
    "Công nghệ thông tin": 5500000,
    "Quản lý và kinh doanh du lịch": 5000000,
    "Quản trị văn phòng": 4800000,
    "Kinh doanh vận tải": 5000000,
    "Quản trị kinh doanh": 5200000,
    "Kế toán": 5000000,
    "Kỹ thuật chế biến món ăn": 5500000,
    "Chăn nuôi": 5000000,
    "Công nghệ ô tô": 5800000,
    "Công nghệ Ô tô": 5800000,
    "Hướng dẫn du lịch": 5000000,
    "Tiếng Anh": 5200000,
}


def upgrade() -> None:
    """Seed tuition, offering_admission_config, and link profiles."""

    # ===== 1. Seed offering_academic_info for offerings without 2026 data =====
    # Insert year 2026 records for offerings that don't have them yet
    # Use program name matching for tuition fees
    op.execute("""
        INSERT INTO offering_academic_info (
            offering_id, academic_year, tuition_fee_per_year,
            is_published, created_at, updated_at
        )
        SELECT
            po.id,
            2026,
            CASE
                WHEN mp.name ILIKE '%Điều dưỡng%' THEN 6690000
                WHEN mp.name ILIKE '%Dược%' THEN 7200000
                WHEN mp.name ILIKE '%Y sỹ%' OR mp.name ILIKE '%Y si%' THEN 7500000
                WHEN mp.name ILIKE '%Y học cổ truyền%' THEN 7000000
                WHEN mp.name ILIKE '%Công nghệ thông tin%' THEN 5500000
                WHEN mp.name ILIKE '%Quản lý%du lịch%' THEN 5000000
                WHEN mp.name ILIKE '%Quản trị văn phòng%' THEN 4800000
                WHEN mp.name ILIKE '%Kinh doanh vận tải%' THEN 5000000
                WHEN mp.name ILIKE '%Quản trị kinh doanh%' THEN 5200000
                WHEN mp.name ILIKE '%Kế toán%' THEN 5000000
                WHEN mp.name ILIKE '%Kỹ thuật chế biến%' THEN 5500000
                WHEN mp.name ILIKE '%Chăn nuôi%' THEN 5000000
                WHEN mp.name ILIKE '%ô tô%' OR mp.name ILIKE '%Ô tô%' THEN 5800000
                WHEN mp.name ILIKE '%Hướng dẫn du lịch%' THEN 5000000
                WHEN mp.name ILIKE '%Tiếng Anh%' THEN 5200000
                ELSE 5000000
            END,
            true,
            NOW(),
            NOW()
        FROM program_offering po
        JOIN major_program mp ON po.program_id = mp.id
        WHERE po.is_active = true
          AND NOT EXISTS (
              SELECT 1 FROM offering_academic_info oai
              WHERE oai.offering_id = po.id AND oai.academic_year = 2026
          );
    """)

    # ===== 2. Update tuition_fee_per_year for existing 2026 records that are NULL =====
    op.execute("""
        UPDATE offering_academic_info oai
        SET tuition_fee_per_year = 5000000,
            is_published = true,
            updated_at = NOW()
        WHERE oai.academic_year = 2026
          AND oai.tuition_fee_per_year IS NULL;
    """)

    # ===== 3. Seed offering_admission_config from admission_path data =====
    # Each admission_path has (academic_info_id, criteria_id) which maps to
    # offering_admission_config (academic_info_id, criteria_id)
    op.execute("""
        INSERT INTO offering_admission_config (
            academic_info_id, criteria_id, is_active, created_at
        )
        SELECT DISTINCT
            ap.academic_info_id,
            ap.criteria_id,
            true,
            NOW()
        FROM admission_path ap
        WHERE ap.criteria_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM offering_admission_config oac
              WHERE oac.academic_info_id = ap.academic_info_id
                AND oac.criteria_id = ap.criteria_id
          );
    """)

    # ===== 4. Link existing profiles to offering_admission_config =====
    # Match via applied_rules->>'academic_info_id' and admission_path criteria
    op.execute("""
        UPDATE admission_profile prof
        SET offering_admission_config_id = oac.id
        FROM admission_path ap
        JOIN offering_admission_config oac
          ON oac.academic_info_id = ap.academic_info_id
         AND oac.criteria_id = ap.criteria_id
        WHERE (prof.applied_rules->>'admission_path_id')::int = ap.id
          AND prof.offering_admission_config_id IS NULL;
    """)


def downgrade() -> None:
    """Remove seeded data (dev/test only)."""
    # Unlink profiles
    op.execute("""
        UPDATE admission_profile
        SET offering_admission_config_id = NULL
        WHERE offering_admission_config_id IS NOT NULL;
    """)

    # Remove offering_admission_config records
    op.execute("DELETE FROM offering_admission_config;")

    # Remove seeded offering_academic_info (only the ones we added)
    # Keep IDs <= 20 (pre-existing)
    op.execute("""
        DELETE FROM offering_academic_info
        WHERE id > 20 AND academic_year = 2026;
    """)
