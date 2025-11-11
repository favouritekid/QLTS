"""refactor to 3-tier major architecture

Revision ID: k6l7m8n9o0p1
Revises: j5k6l7m8n9o0
Create Date: 2025-11-11 09:00:00.000000

This migration implements the 3-tier major/program architecture:

OLD STRUCTURE (2-tier):
- Major (Cấp 1) → MajorAcademicInfo (Cấp 2 - dynamic data)
- Lead.major_id → Major

NEW STRUCTURE (3-tier):
- MajorProgram (Cấp 1 - static info) → ProgramOffering (Cấp 2 - static offering type) →
  OfferingAcademicInfo (Cấp 3 - dynamic yearly data)
- Lead.offering_id → ProgramOffering

CHANGES:
1. Create 3 new tables: major_program, program_offering, offering_academic_info
2. Add Lead.offering_id column
3. Migrate data from major → major_program + default program_offering
4. Migrate data from major_academic_info → offering_academic_info
5. Update Lead.major_id → Lead.offering_id mapping
6. Drop Lead.major_id column
7. Drop major_academic_info table
8. Drop major table

IMPORTANT:
- ⚠️  BACKUP YOUR DATABASE BEFORE RUNNING THIS MIGRATION!
- Data migration creates a default "Chính quy" offering for each major
- All academic info is migrated to the default offering
- Lead assignments are updated to point to default offerings

ROLLBACK:
- Downgrade recreates major and major_academic_info tables
- Data loss is minimal if downgrade is run immediately after upgrade
- See downgrade() function for details
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'k6l7m8n9o0p1'
down_revision: Union[str, None] = 'j5k6l7m8n9o0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Upgrade to 3-tier architecture.

    This migration is complex and touches multiple tables.
    Each step is clearly marked and can be monitored.
    """

    print("\n" + "=" * 80)
    print("MIGRATION: Refactoring to 3-Tier Major/Program Architecture")
    print("=" * 80)

    # =========================================================================
    # STEP 1: Create major_program table (Cấp 1)
    # =========================================================================
    print("\n[STEP 1/9] Creating major_program table...")
    op.create_table(
        'major_program',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False,
                  comment="Tên hiển thị (vd: 'Cao đẳng Công nghệ thông tin')"),
        sa.Column('degree_level', sa.String(length=50), nullable=False,
                  comment="Trình độ (vd: 'Cao đẳng')"),
        sa.Column('code', sa.String(length=50), nullable=False,
                  comment="Mã ngành tuyển sinh (vd: '6480201')"),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true'),
                  comment="Cờ Soft Delete"),
        sa.Column('unit_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['unit_id'], ['organization_unit.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', name='uq_major_program_code')
    )
    op.create_index(op.f('ix_major_program_id'), 'major_program', ['id'])
    op.create_index(op.f('ix_major_program_code'), 'major_program', ['code'])
    op.create_index(op.f('ix_major_program_is_active'), 'major_program', ['is_active'])
    print("   ✓ major_program table created")

    # =========================================================================
    # STEP 2: Create program_offering table (Cấp 2)
    # =========================================================================
    print("\n[STEP 2/9] Creating program_offering table...")
    op.create_table(
        'program_offering',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('offering_type', sa.String(length=100), nullable=False,
                  comment="Tên loại hình (vd: 'Chính quy', 'Liên thông')"),
        sa.Column('duration_semesters', sa.Integer(), nullable=True),
        sa.Column('total_credits', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true'),
                  comment="Cờ Soft Delete"),
        sa.Column('program_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['program_id'], ['major_program.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('program_id', 'offering_type', name='uq_program_offering_type')
    )
    op.create_index(op.f('ix_program_offering_id'), 'program_offering', ['id'])
    op.create_index(op.f('ix_program_offering_is_active'), 'program_offering', ['is_active'])
    print("   ✓ program_offering table created")

    # =========================================================================
    # STEP 3: Create offering_academic_info table (Cấp 3)
    # =========================================================================
    print("\n[STEP 3/9] Creating offering_academic_info table...")
    op.create_table(
        'offering_academic_info',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('academic_year', sa.Integer(), nullable=False),
        sa.Column('tuition_fee_per_year', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('annual_admission_quota', sa.Integer(), nullable=True),
        sa.Column('is_published', sa.Boolean(), nullable=False, server_default=sa.text('false'),
                  comment="Đã công bố thông tin ra public chưa?"),
        sa.Column('admission_criteria', postgresql.JSON(astext_type=sa.Text()), nullable=True,
                  comment="Tiêu chí tuyển sinh (JSON)"),
        sa.Column('target_audience', sa.String(length=1000), nullable=True,
                  comment="Đối tượng phù hợp với ngành học này"),
        sa.Column('cutoff_score_previous_year', sa.Numeric(precision=5, scale=2), nullable=True,
                  comment="Điểm chuẩn năm trước"),
        sa.Column('offering_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.Column('updated_by_user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['offering_id'], ['program_offering.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['updated_by_user_id'], ['user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('offering_id', 'academic_year', name='uq_offering_academic_year')
    )
    op.create_index(op.f('ix_offering_academic_info_id'), 'offering_academic_info', ['id'])
    op.create_index(op.f('ix_offering_academic_info_academic_year'), 'offering_academic_info', ['academic_year'])
    op.create_index(op.f('ix_offering_academic_info_is_published'), 'offering_academic_info', ['is_published'])
    print("   ✓ offering_academic_info table created")

    # =========================================================================
    # STEP 4: Add offering_id column to lead table
    # =========================================================================
    print("\n[STEP 4/9] Adding offering_id column to lead table...")
    op.add_column('lead',
        sa.Column('offering_id', sa.Integer(), nullable=True)
    )
    op.create_foreign_key(
        'fk_lead_offering_id', 'lead', 'program_offering',
        ['offering_id'], ['id'], ondelete='SET NULL'
    )
    op.create_index(op.f('ix_lead_offering_id'), 'lead', ['offering_id'])
    print("   ✓ offering_id column added to lead")

    # =========================================================================
    # STEP 5: Data Migration - major → major_program + program_offering
    # =========================================================================
    print("\n[STEP 5/9] Migrating data from major to major_program + program_offering...")

    conn = op.get_bind()

    # Get all majors from old table
    result = conn.execute(text("""
        SELECT id, name, code, unit_id, is_active, description
        FROM major
        ORDER BY id
    """))
    majors = result.fetchall()

    print(f"   Found {len(majors)} majors to migrate")

    # Mapping from old major_id to new offering_id (for default "Chính quy" offering)
    major_to_offering_map = {}

    for major in majors:
        old_major_id = major[0]
        name = major[1]
        code = major[2]
        unit_id = major[3]
        is_active = major[4]
        description = major[5]

        # Extract degree_level from name if possible, otherwise default to "Cao đẳng"
        degree_level = "Cao đẳng"  # Default
        if "Đại học" in name or "ĐH" in name:
            degree_level = "Đại học"
        elif "Thạc sĩ" in name or "Thạc sỹ" in name:
            degree_level = "Thạc sĩ"
        elif "Tiến sĩ" in name:
            degree_level = "Tiến sĩ"

        # Create MajorProgram (Cấp 1)
        result = conn.execute(text("""
            INSERT INTO major_program (name, degree_level, code, is_active, unit_id)
            VALUES (:name, :degree_level, :code, :is_active, :unit_id)
            RETURNING id
        """), {
            'name': name,
            'degree_level': degree_level,
            'code': code,
            'is_active': is_active,
            'unit_id': unit_id
        })
        new_program_id = result.scalar()

        # Create default ProgramOffering "Chính quy" (Cấp 2)
        result = conn.execute(text("""
            INSERT INTO program_offering (offering_type, program_id, is_active)
            VALUES ('Chính quy', :program_id, :is_active)
            RETURNING id
        """), {
            'program_id': new_program_id,
            'is_active': is_active
        })
        new_offering_id = result.scalar()

        # Store mapping
        major_to_offering_map[old_major_id] = new_offering_id

        print(f"   ✓ Migrated major {old_major_id} '{name}' → program {new_program_id} + offering {new_offering_id}")

    print(f"   ✓ Migrated {len(majors)} majors successfully")

    # =========================================================================
    # STEP 6: Data Migration - major_academic_info → offering_academic_info
    # =========================================================================
    print("\n[STEP 6/9] Migrating data from major_academic_info to offering_academic_info...")

    result = conn.execute(text("""
        SELECT id, major_id, academic_year, target_audience, detailed_info,
               current_year_benefits, tuition_fee_per_year, annual_admission_quota,
               is_published, created_at, updated_at, created_by_user_id
        FROM major_academic_info
        ORDER BY id
    """))
    academic_infos = result.fetchall()

    print(f"   Found {len(academic_infos)} academic info records to migrate")

    migrated_count = 0
    skipped_count = 0

    for info in academic_infos:
        old_major_id = info[1]

        # Get corresponding offering_id
        new_offering_id = major_to_offering_map.get(old_major_id)

        if new_offering_id is None:
            print(f"   ⚠️  Skipping academic info {info[0]}: major_id {old_major_id} not found in mapping")
            skipped_count += 1
            continue

        # Migrate to offering_academic_info
        conn.execute(text("""
            INSERT INTO offering_academic_info (
                offering_id, academic_year, target_audience,
                tuition_fee_per_year, annual_admission_quota, is_published,
                cutoff_score_previous_year, created_at, updated_at, created_by_user_id
            ) VALUES (
                :offering_id, :academic_year, :target_audience,
                :tuition_fee, :quota, :is_published,
                NULL, :created_at, :updated_at, :created_by
            )
        """), {
            'offering_id': new_offering_id,
            'academic_year': info[2],
            'target_audience': info[3],
            'tuition_fee': info[6],
            'quota': info[7],
            'is_published': info[8],
            'created_at': info[9],
            'updated_at': info[10],
            'created_by': info[11]
        })
        migrated_count += 1

    print(f"   ✓ Migrated {migrated_count} academic info records")
    if skipped_count > 0:
        print(f"   ⚠️  Skipped {skipped_count} records (orphaned)")

    # =========================================================================
    # STEP 7: Update lead.major_id → lead.offering_id
    # =========================================================================
    print("\n[STEP 7/9] Updating lead assignments...")

    updated_count = 0
    for old_major_id, new_offering_id in major_to_offering_map.items():
        result = conn.execute(text("""
            UPDATE lead
            SET offering_id = :offering_id
            WHERE major_id = :major_id
        """), {
            'offering_id': new_offering_id,
            'major_id': old_major_id
        })
        updated_count += result.rowcount

    print(f"   ✓ Updated {updated_count} lead assignments")

    # =========================================================================
    # STEP 8: Drop old major_id column from lead
    # =========================================================================
    print("\n[STEP 8/9] Dropping major_id column from lead...")
    op.drop_constraint('lead_major_id_fkey', 'lead', type_='foreignkey')
    op.drop_column('lead', 'major_id')
    print("   ✓ major_id column dropped from lead")

    # =========================================================================
    # STEP 9: Drop old tables (major_academic_info, major)
    # =========================================================================
    print("\n[STEP 9/9] Dropping old tables...")

    # Drop major_academic_info table
    op.drop_index('ix_major_academic_info_academic_year', table_name='major_academic_info')
    op.drop_index('ix_major_academic_info_major_id', table_name='major_academic_info')
    op.drop_index('ix_major_academic_info_id', table_name='major_academic_info')
    op.drop_index('ix_year_published', table_name='major_academic_info')
    op.drop_index('ix_major_year_published', table_name='major_academic_info')
    op.drop_table('major_academic_info')
    print("   ✓ major_academic_info table dropped")

    # Drop major table
    op.drop_index('ix_major_is_active', table_name='major')
    op.drop_index('ix_major_id', table_name='major')
    op.drop_table('major')
    print("   ✓ major table dropped")

    print("\n" + "=" * 80)
    print("✅ MIGRATION COMPLETED SUCCESSFULLY!")
    print("=" * 80)
    print(f"""
Summary:
  ✓ Created 3 new tables (major_program, program_offering, offering_academic_info)
  ✓ Migrated {len(majors)} majors → major_program + program_offering
  ✓ Migrated {migrated_count} academic info records
  ✓ Updated {updated_count} lead assignments
  ✓ Dropped old tables (major, major_academic_info)

Next Steps:
  1. Run verification: python verify_phase2_migration.py
  2. Test API endpoints
  3. If issues found, downgrade: alembic downgrade -1
""")


def downgrade() -> None:
    """
    Rollback to 2-tier architecture.

    ⚠️  WARNING: This downgrade attempts to restore the old structure,
    but some data loss may occur:
    - Multiple offerings per program will be merged back into one major
    - Only the first offering's academic info will be preserved
    - Custom offering types will be lost

    ONLY use this immediately after upgrade if something went wrong!
    """

    print("\n" + "=" * 80)
    print("ROLLBACK: Reverting to 2-Tier Major Architecture")
    print("=" * 80)
    print("\n⚠️  WARNING: Some data loss may occur!")
    print("   - Multiple offerings will be merged")
    print("   - Custom offering types will be lost")

    conn = op.get_bind()

    # =========================================================================
    # STEP 1: Recreate major table
    # =========================================================================
    print("\n[STEP 1/7] Recreating major table...")
    op.create_table(
        'major',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('unit_id', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.ForeignKeyConstraint(['unit_id'], ['organization_unit.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )
    op.create_index(op.f('ix_major_id'), 'major', ['id'])
    op.create_index(op.f('ix_major_is_active'), 'major', ['is_active'])
    print("   ✓ major table recreated")

    # =========================================================================
    # STEP 2: Recreate major_academic_info table
    # =========================================================================
    print("\n[STEP 2/7] Recreating major_academic_info table...")
    op.create_table(
        'major_academic_info',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('major_id', sa.Integer(), nullable=False),
        sa.Column('academic_year', sa.Integer(), nullable=False),
        sa.Column('target_audience', sa.Text(), nullable=True),
        sa.Column('detailed_info', sa.Text(), nullable=True),
        sa.Column('current_year_benefits', sa.Text(), nullable=True),
        sa.Column('tuition_fee_per_year', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('annual_admission_quota', sa.Integer(), nullable=True),
        sa.Column('is_published', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('created_by_user_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['created_by_user_id'], ['user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['major_id'], ['major.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('major_id', 'academic_year', name='uq_major_academic_year')
    )
    op.create_index('ix_major_year_published', 'major_academic_info', ['major_id', 'academic_year', 'is_published'])
    op.create_index('ix_year_published', 'major_academic_info', ['academic_year', 'is_published'])
    op.create_index(op.f('ix_major_academic_info_id'), 'major_academic_info', ['id'])
    op.create_index(op.f('ix_major_academic_info_major_id'), 'major_academic_info', ['major_id'])
    op.create_index(op.f('ix_major_academic_info_academic_year'), 'major_academic_info', ['academic_year'])
    print("   ✓ major_academic_info table recreated")

    # =========================================================================
    # STEP 3: Add major_id column back to lead
    # =========================================================================
    print("\n[STEP 3/7] Adding major_id column back to lead...")
    op.add_column('lead', sa.Column('major_id', sa.Integer(), nullable=True))
    op.create_foreign_key('lead_major_id_fkey', 'lead', 'major', ['major_id'], ['id'])
    print("   ✓ major_id column added to lead")

    # =========================================================================
    # STEP 4: Migrate data back - major_program → major
    # =========================================================================
    print("\n[STEP 4/7] Migrating data from major_program to major...")

    # Map program_id → major_id for reverse migration
    program_to_major_map = {}

    result = conn.execute(text("""
        SELECT id, name, code, unit_id, is_active
        FROM major_program
        ORDER BY id
    """))
    programs = result.fetchall()

    for program in programs:
        result = conn.execute(text("""
            INSERT INTO major (name, code, unit_id, is_active, description)
            VALUES (:name, :code, :unit_id, :is_active, NULL)
            RETURNING id
        """), {
            'name': program[1],
            'code': program[2],
            'unit_id': program[3],
            'is_active': program[4]
        })
        new_major_id = result.scalar()
        program_to_major_map[program[0]] = new_major_id

    print(f"   ✓ Migrated {len(programs)} programs back to majors")

    # =========================================================================
    # STEP 5: Migrate academic info back
    # =========================================================================
    print("\n[STEP 5/7] Migrating academic info back...")

    # Map offering_id → program_id
    result = conn.execute(text("""
        SELECT id, program_id FROM program_offering
    """))
    offering_to_program = {row[0]: row[1] for row in result.fetchall()}

    result = conn.execute(text("""
        SELECT offering_id, academic_year, target_audience,
               tuition_fee_per_year, annual_admission_quota, is_published,
               created_at, updated_at, created_by_user_id
        FROM offering_academic_info
        ORDER BY id
    """))

    migrated = 0
    for row in result.fetchall():
        offering_id = row[0]
        program_id = offering_to_program.get(offering_id)
        if program_id is None:
            continue
        major_id = program_to_major_map.get(program_id)
        if major_id is None:
            continue

        conn.execute(text("""
            INSERT INTO major_academic_info (
                major_id, academic_year, target_audience,
                tuition_fee_per_year, annual_admission_quota, is_published,
                created_at, updated_at, created_by_user_id
            ) VALUES (
                :major_id, :year, :audience, :tuition, :quota, :published,
                :created, :updated, :created_by
            )
        """), {
            'major_id': major_id,
            'year': row[1],
            'audience': row[2],
            'tuition': row[3],
            'quota': row[4],
            'published': row[5],
            'created': row[6],
            'updated': row[7],
            'created_by': row[8]
        })
        migrated += 1

    print(f"   ✓ Migrated {migrated} academic info records")

    # =========================================================================
    # STEP 6: Update lead.offering_id → lead.major_id
    # =========================================================================
    print("\n[STEP 6/7] Updating lead assignments...")

    result = conn.execute(text("""
        SELECT id, offering_id FROM lead WHERE offering_id IS NOT NULL
    """))

    updated = 0
    for row in result.fetchall():
        lead_id = row[0]
        offering_id = row[1]
        program_id = offering_to_program.get(offering_id)
        if program_id:
            major_id = program_to_major_map.get(program_id)
            if major_id:
                conn.execute(text("""
                    UPDATE lead SET major_id = :major_id WHERE id = :lead_id
                """), {'major_id': major_id, 'lead_id': lead_id})
                updated += 1

    print(f"   ✓ Updated {updated} lead assignments")

    # =========================================================================
    # STEP 7: Drop new tables and lead.offering_id
    # =========================================================================
    print("\n[STEP 7/7] Dropping new tables...")

    # Drop lead.offering_id
    op.drop_constraint('fk_lead_offering_id', 'lead', type_='foreignkey')
    op.drop_index(op.f('ix_lead_offering_id'), table_name='lead')
    op.drop_column('lead', 'offering_id')

    # Drop offering_academic_info
    op.drop_index(op.f('ix_offering_academic_info_is_published'), table_name='offering_academic_info')
    op.drop_index(op.f('ix_offering_academic_info_academic_year'), table_name='offering_academic_info')
    op.drop_index(op.f('ix_offering_academic_info_id'), table_name='offering_academic_info')
    op.drop_table('offering_academic_info')

    # Drop program_offering
    op.drop_index(op.f('ix_program_offering_is_active'), table_name='program_offering')
    op.drop_index(op.f('ix_program_offering_id'), table_name='program_offering')
    op.drop_table('program_offering')

    # Drop major_program
    op.drop_index(op.f('ix_major_program_is_active'), table_name='major_program')
    op.drop_index(op.f('ix_major_program_code'), table_name='major_program')
    op.drop_index(op.f('ix_major_program_id'), table_name='major_program')
    op.drop_table('major_program')

    print("\n" + "=" * 80)
    print("✅ ROLLBACK COMPLETED!")
    print("=" * 80)
    print("\nOld 2-tier structure restored.")
    print("⚠️  Note: Some data may have been lost during rollback.")
