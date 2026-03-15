"""seed: operational baseline data for system bootstrap

Revision ID: zq6w7x8y9z0a1
Revises: zp5v6w7x8y9z0
Create Date: 2026-03-15 21:00:00.000000

Seeds the minimum data required for the system to operate:
- Organization units (1 root + 3 departments)
- Users (admin update + manager + 2 officers + accountant)
- User unit assignments + Casbin role mappings
- Pipeline stages (5) + Consultation statuses (16) + Allowed transitions (~25)
- Major programs (6) + Program offerings (8) + Academic info (8, year 2026)
- Subjects (9) + Subject groups (7) + Subject-group mappings (21)
- Admission methods (3) + Criteria (3) + Criteria-subject-group mappings
- Document groups (2) + Document group items (~13)
- System categories (nationality, ethnicity, religion)
- Notification templates (5) + rules (3)

All INSERTs use ON CONFLICT DO NOTHING for idempotency.
Password hashes are pre-computed bcrypt (15 rounds).
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "zq6w7x8y9z0a1"
down_revision: Union[str, None] = "zp5v6w7x8y9z0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # =========================================================================
    # PHASE 1: Organization Units
    # =========================================================================
    conn.execute(text("""
        INSERT INTO organization_unit (id, name, type, description, parent_id, is_active, created_at, updated_at) VALUES
        (1, 'Trường Cao Đẳng Mẫu', 'truong', 'Đơn vị gốc', NULL, true, NOW(), NOW()),
        (2, 'Khoa Công Nghệ Thông Tin', 'khoa', 'Khoa CNTT', 1, true, NOW(), NOW()),
        (3, 'Khoa Y Dược', 'khoa', 'Khoa Y Dược', 1, true, NOW(), NOW()),
        (4, 'Phòng Tuyển Sinh', 'phong', 'Phòng tuyển sinh', 1, true, NOW(), NOW())
        ON CONFLICT (id) DO NOTHING
    """))
    conn.execute(text("SELECT setval('organization_unit_id_seq', (SELECT COALESCE(MAX(id),0) FROM organization_unit))"))
    print("  [seed] Phase 1: organization_unit done")

    # =========================================================================
    # PHASE 2: Users + Assignments + Casbin
    # =========================================================================
    # Update existing admin user
    conn.execute(text("""
        UPDATE "user" SET unit_id = 1, full_name = 'System Admin'
        WHERE username = 'admin' AND unit_id IS NULL
    """))

    # Insert new users (pre-computed bcrypt hashes, 15 rounds)
    conn.execute(text("""
        INSERT INTO "user" (username, email, password_hash, full_name, role, unit_id, status, total_lead_score, max_capacity, availability_status)
        VALUES
        ('manager01', 'manager01@qlts.vn',
         '$2b$15$utxg59L2N6oPzXZZdtylMu/692Q2UvVnSvPg1Ulsei/HYGJ0YNtdO',
         'Nguyễn Văn Bình', 'manager', 4, 'active', 0, 100, 'available'),
        ('officer01', 'officer01@qlts.vn',
         '$2b$15$1nvVhRZ/MLrrp.JR2JI5NulL/tMqZD1zc2CV7eEyOlGfTOaxU/456',
         'Trần Thị Cẩm', 'officer', 4, 'active', 0, 100, 'available'),
        ('officer02', 'officer02@qlts.vn',
         '$2b$15$1nvVhRZ/MLrrp.JR2JI5NulL/tMqZD1zc2CV7eEyOlGfTOaxU/456',
         'Lê Văn Đức', 'officer', 4, 'active', 0, 100, 'available'),
        ('accountant01', 'accountant01@qlts.vn',
         '$2b$15$ZVMmIMdeVU0NjrfvHce1reNF4Wd1D8uGnDuhuEufy.dgfrIftIg1a',
         'Phạm Thị Yến', 'accountant', 4, 'active', 0, 100, 'available')
        ON CONFLICT (username) DO NOTHING
    """))

    # User-unit assignments
    conn.execute(text("""
        INSERT INTO user_unit_assignment (user_id, unit_id, role, is_active, start_date, created_at, updated_at)
        SELECT u.id, u.unit_id, u.role, true, NOW(), NOW(), NOW()
        FROM "user" u
        WHERE u.unit_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM user_unit_assignment a WHERE a.user_id = u.id AND a.is_active = true
        )
    """))

    # Update current_assignment_id
    conn.execute(text("""
        UPDATE "user" u SET current_assignment_id = a.id
        FROM user_unit_assignment a
        WHERE a.user_id = u.id AND a.is_active = true
        AND u.current_assignment_id IS NULL
    """))

    # Casbin role mappings
    conn.execute(text("""
        INSERT INTO casbin_rule (ptype, v0, v1) VALUES
        ('g', 'user:1', 'role:admin')
        ON CONFLICT DO NOTHING
    """))
    conn.execute(text("""
        INSERT INTO casbin_rule (ptype, v0, v1)
        SELECT 'g', 'user:' || u.id, 'role:' || u.role
        FROM "user" u
        WHERE u.id > 1
        AND NOT EXISTS (
            SELECT 1 FROM casbin_rule c WHERE c.ptype = 'g' AND c.v0 = 'user:' || u.id
        )
    """))
    print("  [seed] Phase 2: users + assignments + casbin done")

    # =========================================================================
    # PHASE 3: Pipeline Stages + Consultation Statuses + Transitions
    # =========================================================================
    conn.execute(text("""
        INSERT INTO pipeline_stage (id, name, "order", is_final_stage, color_code) VALUES
        ('new',        'Mới',      0, false, '#3B82F6'),
        ('contacted',  'Tiếp cận', 1, false, '#F59E0B'),
        ('consulting', 'Tư vấn',   2, false, '#8B5CF6'),
        ('evaluation', 'Đánh giá', 3, false, '#10B981'),
        ('result',     'Kết quả',  4, true,  '#EF4444')
        ON CONFLICT (id) DO NOTHING
    """))

    conn.execute(text("""
        INSERT INTO consultation_status
        (id, code, name, stage_id, color_code, outcome_type, is_final, status_type, selectable_mode, is_universal, updates_pipeline, counts_for_funnel, phase, display_order) VALUES
        -- Stage: new
        ('not_contacted',       'NOT_CONTACTED',       'Chưa liên lạc',              'new',        '#94A3B8', 'neutral',  false, 'transition', 'user',   false, true,  true,  'consultation', 10),
        ('contact_failed',      'CONTACT_FAILED',      'Không liên lạc được',        'new',        '#EF4444', 'negative', false, 'transition', 'user',   false, true,  true,  'consultation', 20),
        -- Stage: contacted
        ('contacted_interested',     'CONTACTED_INTERESTED',     'Quan tâm',              'contacted',  '#22C55E', 'positive', false, 'transition', 'user',   false, true,  true,  'consultation', 30),
        ('contacted_not_interested', 'CONTACTED_NOT_INTERESTED', 'Không quan tâm',        'contacted',  '#F97316', 'negative', false, 'transition', 'user',   false, true,  true,  'consultation', 40),
        -- Stage: consulting
        ('consulting_scheduled', 'CONSULTING_SCHEDULED', 'Hẹn tư vấn',              'consulting', '#A78BFA', 'neutral',  false, 'transition', 'user',   false, true,  true,  'consultation', 50),
        ('consulting_done',      'CONSULTING_DONE',      'Đã tư vấn',               'consulting', '#6366F1', 'positive', false, 'transition', 'user',   false, true,  true,  'consultation', 60),
        ('consulting_no_show',   'CONSULTING_NO_SHOW',   'Không đến',               'consulting', '#DC2626', 'negative', false, 'transition', 'user',   false, true,  true,  'consultation', 70),
        -- Stage: evaluation
        ('profile_created',   'PROFILE_CREATED',   'Đã tạo hồ sơ',   'evaluation', '#14B8A6', 'positive', false, 'transition', 'user',   false, true,  true,  'admission', 80),
        ('profile_submitted', 'PROFILE_SUBMITTED', 'Đã nộp hồ sơ',   'evaluation', '#0EA5E9', 'positive', false, 'transition', 'user',   false, true,  true,  'admission', 90),
        ('profile_approved',  'PROFILE_APPROVED',  'Hồ sơ được duyệt','evaluation', '#22C55E', 'positive', false, 'transition', 'role',   false, true,  true,  'admission', 100),
        -- Stage: result (finals)
        ('enrolled', 'ENROLLED', 'Đã nhập học', 'result', '#16A34A', 'positive', true,  'transition', 'role',   false, true,  true,  'enrolled',     110),
        ('rejected', 'REJECTED', 'Từ chối',     'result', '#DC2626', 'negative', true,  'transition', 'role',   false, true,  true,  'consultation', 120),
        ('lost',     'LOST',     'Mất lead',    'result', '#6B7280', 'negative', true,  'transition', 'role',   false, true,  true,  'consultation', 130),
        -- Universal (no stage)
        ('callback_requested', 'CALLBACK_REQUESTED', 'Yêu cầu gọi lại',  NULL, '#FBBF24', 'neutral',  false, 'activity', 'user',   true,  false, false, 'universal', 200),
        ('info_sent',          'INFO_SENT',          'Đã gửi thông tin',  NULL, '#60A5FA', 'neutral',  false, 'activity', 'user',   true,  false, false, 'universal', 210),
        ('duplicate_flagged',  'DUPLICATE_FLAGGED',  'Trùng lead',        NULL, '#F87171', 'negative', false, 'system',   'system', true,  false, false, 'universal', 220)
        ON CONFLICT (id) DO NOTHING
    """))

    conn.execute(text("""
        INSERT INTO allowed_transitions (from_status_id, to_status_id, trigger_type, is_active, created_at, updated_at) VALUES
        ('not_contacted', 'contacted_interested',     'user', true, NOW(), NOW()),
        ('not_contacted', 'contact_failed',           'user', true, NOW(), NOW()),
        ('not_contacted', 'contacted_not_interested', 'user', true, NOW(), NOW()),
        ('not_contacted', 'lost',                     'role', true, NOW(), NOW()),
        ('contact_failed', 'not_contacted',           'user', true, NOW(), NOW()),
        ('contact_failed', 'contacted_interested',    'user', true, NOW(), NOW()),
        ('contact_failed', 'lost',                    'role', true, NOW(), NOW()),
        ('contacted_interested', 'consulting_scheduled', 'user', true, NOW(), NOW()),
        ('contacted_interested', 'consulting_done',      'user', true, NOW(), NOW()),
        ('contacted_interested', 'lost',                 'role', true, NOW(), NOW()),
        ('contacted_not_interested', 'contacted_interested', 'user', true, NOW(), NOW()),
        ('contacted_not_interested', 'lost',                 'role', true, NOW(), NOW()),
        ('consulting_scheduled', 'consulting_done',    'user', true, NOW(), NOW()),
        ('consulting_scheduled', 'consulting_no_show', 'user', true, NOW(), NOW()),
        ('consulting_scheduled', 'lost',               'role', true, NOW(), NOW()),
        ('consulting_no_show', 'consulting_scheduled', 'user', true, NOW(), NOW()),
        ('consulting_done', 'profile_created',         'user', true, NOW(), NOW()),
        ('consulting_done', 'lost',                    'role', true, NOW(), NOW()),
        ('profile_created', 'profile_submitted',       'user', true, NOW(), NOW()),
        ('profile_created', 'lost',                    'role', true, NOW(), NOW()),
        ('profile_submitted', 'profile_approved',      'role', true, NOW(), NOW()),
        ('profile_submitted', 'rejected',              'role', true, NOW(), NOW()),
        ('profile_approved', 'enrolled',               'role', true, NOW(), NOW()),
        ('profile_approved', 'rejected',               'role', true, NOW(), NOW()),
        ('rejected', 'consulting_scheduled',           'role', true, NOW(), NOW()),
        ('rejected', 'not_contacted',                  'role', true, NOW(), NOW())
        ON CONFLICT DO NOTHING
    """))
    print("  [seed] Phase 3: pipeline + statuses + transitions done")

    # =========================================================================
    # PHASE 4: Major Programs
    # =========================================================================
    conn.execute(text("""
        INSERT INTO major_program (id, name, degree_level, code, unit_id, is_active, is_heavy) VALUES
        (1, 'Công nghệ thông tin',   'Cao đẳng', '6480201', 2, true, false),
        (2, 'Điều dưỡng',           'Cao đẳng', '6720301', 3, true, false),
        (3, 'Dược',                 'Cao đẳng', '6720201', 3, true, false),
        (4, 'Quản trị kinh doanh',  'Cao đẳng', '6340101', 2, true, false),
        (5, 'Kế toán',             'Cao đẳng', '6340301', 2, true, false),
        (6, 'Công nghệ ô tô',     'Cao đẳng', '6510216', 2, true, true)
        ON CONFLICT (id) DO NOTHING
    """))
    conn.execute(text("SELECT setval('major_program_id_seq', (SELECT COALESCE(MAX(id),0) FROM major_program))"))
    print("  [seed] Phase 4: major_program done")

    # =========================================================================
    # PHASE 5: Program Offerings
    # =========================================================================
    conn.execute(text("""
        INSERT INTO program_offering (id, offering_type, program_id, offering_type_id, is_active, duration_semesters, total_credits) VALUES
        (1, 'Chính quy',  1, 1, true, 6, 90),
        (2, 'Liên thông', 1, 2, true, 4, 60),
        (3, 'Chính quy',  2, 1, true, 6, 95),
        (4, 'Chính quy',  3, 1, true, 6, 95),
        (5, 'Chính quy',  4, 1, true, 6, 90),
        (6, 'Chính quy',  5, 1, true, 6, 90),
        (7, 'Liên thông', 5, 2, true, 4, 60),
        (8, 'Chính quy',  6, 1, true, 6, 90)
        ON CONFLICT (id) DO NOTHING
    """))
    conn.execute(text("SELECT setval('program_offering_id_seq', (SELECT COALESCE(MAX(id),0) FROM program_offering))"))
    print("  [seed] Phase 5: program_offering done")

    # =========================================================================
    # PHASE 6: Offering Academic Info (Year 2026)
    # =========================================================================
    conn.execute(text("""
        INSERT INTO offering_academic_info (id, offering_id, academic_year, tuition_fee_per_year, annual_admission_quota, is_published, created_at, updated_at) VALUES
        (1, 1, 2026, 5500000,  120, true,  NOW(), NOW()),
        (2, 2, 2026, 6000000,   60, true,  NOW(), NOW()),
        (3, 3, 2026, 6690000,  100, true,  NOW(), NOW()),
        (4, 4, 2026, 7200000,   80, true,  NOW(), NOW()),
        (5, 5, 2026, 5200000,  100, true,  NOW(), NOW()),
        (6, 6, 2026, 5000000,   80, true,  NOW(), NOW()),
        (7, 7, 2026, 5500000,   50, true,  NOW(), NOW()),
        (8, 8, 2026, 5800000,   80, true,  NOW(), NOW())
        ON CONFLICT (id) DO NOTHING
    """))
    conn.execute(text("SELECT setval('offering_academic_info_id_seq', (SELECT COALESCE(MAX(id),0) FROM offering_academic_info))"))
    print("  [seed] Phase 6: offering_academic_info done")

    # =========================================================================
    # PHASE 7: Subjects + Subject Groups
    # =========================================================================
    conn.execute(text("""
        INSERT INTO subject (id, code, name_vi, display_order, is_active) VALUES
        (1, 'math',            'Toán',               1, true),
        (2, 'physics',         'Vật lý',             2, true),
        (3, 'chemistry',       'Hóa học',            3, true),
        (4, 'biology',         'Sinh học',            4, true),
        (5, 'literature',      'Ngữ văn',            5, true),
        (6, 'english',         'Tiếng Anh',          6, true),
        (7, 'history',         'Lịch sử',            7, true),
        (8, 'geography',       'Địa lý',             8, true),
        (9, 'civic_education', 'Giáo dục công dân',  9, true)
        ON CONFLICT (id) DO NOTHING
    """))
    conn.execute(text("SELECT setval('subject_id_seq', (SELECT COALESCE(MAX(id),0) FROM subject))"))

    conn.execute(text("""
        INSERT INTO subject_group (id, code, name, display_order, is_active) VALUES
        (1, 'A00', 'Toán, Vật lý, Hóa học',         1, true),
        (2, 'A01', 'Toán, Vật lý, Tiếng Anh',       2, true),
        (3, 'B00', 'Toán, Hóa học, Sinh học',         3, true),
        (4, 'D01', 'Toán, Ngữ văn, Tiếng Anh',       4, true),
        (5, 'D07', 'Toán, Hóa học, Tiếng Anh',       5, true),
        (6, 'C00', 'Ngữ văn, Lịch sử, Địa lý',       6, true),
        (7, 'D14', 'Ngữ văn, Lịch sử, Giáo dục CD', 7, true)
        ON CONFLICT (id) DO NOTHING
    """))
    conn.execute(text("SELECT setval('subject_group_id_seq', (SELECT COALESCE(MAX(id),0) FROM subject_group))"))

    conn.execute(text("""
        INSERT INTO subject_group_subject (subject_group_id, subject_id, position) VALUES
        (1,1,1),(1,2,2),(1,3,3),
        (2,1,1),(2,2,2),(2,6,3),
        (3,1,1),(3,3,2),(3,4,3),
        (4,1,1),(4,5,2),(4,6,3),
        (5,1,1),(5,3,2),(5,6,3),
        (6,5,1),(6,7,2),(6,8,3),
        (7,5,1),(7,7,2),(7,9,3)
        ON CONFLICT DO NOTHING
    """))
    print("  [seed] Phase 7: subjects + groups done")

    # =========================================================================
    # PHASE 8: Admission Methods + Criteria
    # =========================================================================
    conn.execute(text("""
        INSERT INTO admission_method (id, code, name, description, requires_gpa, requires_subject_scores, display_order, is_active) VALUES
        (1, 'hoc_ba',         'Xét học bạ THPT',           'Xét tuyển dựa trên điểm trung bình học bạ THPT', true,  false, 1, true),
        (2, 'thpt_qg',        'Xét điểm thi THPT Quốc gia','Xét tuyển dựa trên điểm thi THPT Quốc gia',    false, true,  2, true),
        (3, 'xet_tuyen_thang','Xét tuyển thẳng',           'Xét tuyển thẳng (đối tượng ưu tiên)',           false, false, 3, true)
        ON CONFLICT (id) DO NOTHING
    """))
    conn.execute(text("SELECT setval('admission_method_id_seq', (SELECT COALESCE(MAX(id),0) FROM admission_method))"))

    conn.execute(text("""
        INSERT INTO admission_criteria (id, method_id, code, name, min_gpa, min_score, required_subject_count, subject_selection_mode, scoring_method, max_possible_score, policy_version, is_active) VALUES
        (1, 1, 'HB2026_CQ',     'Xét học bạ 2026 - Chính quy',    6.0,  NULL, 3, 'fixed', 'average', 10.0, '2026.1', true),
        (2, 1, 'HB2026_LT',     'Xét học bạ 2026 - Liên thông',   5.5,  NULL, 3, 'fixed', 'average', 10.0, '2026.1', true),
        (3, 2, 'THPTQG2026_CQ', 'Xét THPT QG 2026 - Chính quy',  NULL, 15.0, 3, 'fixed', 'sum',     30.0, '2026.1', true)
        ON CONFLICT (id) DO NOTHING
    """))
    conn.execute(text("SELECT setval('admission_criteria_id_seq', (SELECT COALESCE(MAX(id),0) FROM admission_criteria))"))

    # Criteria-subject-group mappings
    conn.execute(text("""
        INSERT INTO criteria_subject_group (criteria_id, subject_group_id) VALUES
        (1,1),(1,2),(1,3),(1,4),(1,5),
        (2,1),(2,4),
        (3,1),(3,2),(3,3),(3,4),(3,5)
        ON CONFLICT DO NOTHING
    """))
    print("  [seed] Phase 8: admission methods + criteria done")

    # =========================================================================
    # PHASE 9: Document Groups + Items
    # =========================================================================
    conn.execute(text("""
        INSERT INTO document_group (id, offering_type_id, code, name, is_active) VALUES
        (1, 1, 'HS_CHINH_QUY',  'Hồ sơ chính quy',  true),
        (2, 2, 'HS_LIEN_THONG', 'Hồ sơ liên thông', true)
        ON CONFLICT (id) DO NOTHING
    """))
    conn.execute(text("SELECT setval('document_group_id_seq', (SELECT COALESCE(MAX(id),0) FROM document_group))"))

    # Document group items (lookup config_document_type by code)
    conn.execute(text("""
        INSERT INTO document_group_item (group_id, document_type_id, is_mandatory, display_order, requires_upload, submission_format)
        SELECT 1, id, true, 1, true, 'certified_copy' FROM config_document_type WHERE code = 'hoc_ba_thpt'
        ON CONFLICT DO NOTHING
    """))
    conn.execute(text("""
        INSERT INTO document_group_item (group_id, document_type_id, is_mandatory, display_order, requires_upload, submission_format)
        SELECT 1, id, true, 2, true, 'certified_copy' FROM config_document_type WHERE code = 'bang_tot_nghiep_thpt'
        ON CONFLICT DO NOTHING
    """))
    conn.execute(text("""
        INSERT INTO document_group_item (group_id, document_type_id, is_mandatory, display_order, requires_upload, submission_format)
        SELECT 1, id, true, 3, true, 'photo' FROM config_document_type WHERE code = 'cccd'
        ON CONFLICT DO NOTHING
    """))
    conn.execute(text("""
        INSERT INTO document_group_item (group_id, document_type_id, is_mandatory, display_order, requires_upload, submission_format)
        SELECT 1, id, true, 4, true, 'certified_copy' FROM config_document_type WHERE code = 'giay_khai_sinh'
        ON CONFLICT DO NOTHING
    """))
    conn.execute(text("""
        INSERT INTO document_group_item (group_id, document_type_id, is_mandatory, display_order, requires_upload, submission_format)
        SELECT 1, id, true, 5, true, 'original' FROM config_document_type WHERE code = 'anh_3x4'
        ON CONFLICT DO NOTHING
    """))
    conn.execute(text("""
        INSERT INTO document_group_item (group_id, document_type_id, is_mandatory, display_order, requires_upload, submission_format)
        SELECT 1, id, true, 6, true, 'original' FROM config_document_type WHERE code = 'giay_kham_suc_khoe'
        ON CONFLICT DO NOTHING
    """))
    conn.execute(text("""
        INSERT INTO document_group_item (group_id, document_type_id, is_mandatory, display_order, requires_upload, submission_format)
        SELECT 1, id, false, 7, true, 'certified_copy' FROM config_document_type WHERE code = 'giay_chung_nhan_uu_tien'
        ON CONFLICT DO NOTHING
    """))
    # Liên thông group
    for code, order in [('bang_tot_nghiep_thpt',1),('cccd',2),('giay_khai_sinh',3),('anh_3x4',4),('giay_kham_suc_khoe',5),('bang_diem_thpt',6)]:
        fmt = 'original' if code in ('anh_3x4','giay_kham_suc_khoe') else 'certified_copy' if code != 'cccd' else 'photo'
        conn.execute(text(f"""
            INSERT INTO document_group_item (group_id, document_type_id, is_mandatory, display_order, requires_upload, submission_format)
            SELECT 2, id, true, {order}, true, '{fmt}' FROM config_document_type WHERE code = '{code}'
            ON CONFLICT DO NOTHING
        """))
    print("  [seed] Phase 9: document groups done")

    # =========================================================================
    # PHASE 10: System Categories
    # =========================================================================
    conn.execute(text("""
        INSERT INTO config_system_category (type, code, name, display_order, is_active) VALUES
        ('nationality', 'VN', 'Việt Nam',   1, true),
        ('nationality', 'LA', 'Lào',        2, true),
        ('nationality', 'KH', 'Campuchia',  3, true),
        ('ethnicity', '01', 'Kinh',   1, true),
        ('ethnicity', '02', 'Tày',    2, true),
        ('ethnicity', '03', 'Thái',   3, true),
        ('ethnicity', '04', 'Mường',  4, true),
        ('ethnicity', '05', 'Hoa',    5, true),
        ('religion', '00', 'Không tôn giáo', 1, true),
        ('religion', '01', 'Phật giáo',      2, true),
        ('religion', '02', 'Công giáo',      3, true),
        ('religion', '03', 'Tin lành',       4, true)
        ON CONFLICT DO NOTHING
    """))
    print("  [seed] Phase 10: system categories done")

    # =========================================================================
    # PHASE 11: Officer Assignment Config
    # =========================================================================
    conn.execute(text("""
        INSERT INTO officer_assignment_config (unit_id, params) VALUES
        (4, '{"method": "round_robin", "max_capacity": 100, "fallback": "manager"}')
        ON CONFLICT (unit_id) DO NOTHING
    """))
    print("  [seed] Phase 11: officer assignment config done")

    print("  [seed] ALL PHASES COMPLETE")


def downgrade() -> None:
    conn = op.get_bind()

    # Reverse order
    conn.execute(text("DELETE FROM officer_assignment_config WHERE unit_id = 4"))
    conn.execute(text("DELETE FROM config_system_category WHERE type IN ('nationality','ethnicity','religion')"))
    conn.execute(text("DELETE FROM document_group_item WHERE group_id IN (1,2)"))
    conn.execute(text("DELETE FROM document_group WHERE id IN (1,2)"))
    conn.execute(text("DELETE FROM criteria_subject_group"))
    conn.execute(text("DELETE FROM admission_criteria WHERE id IN (1,2,3)"))
    conn.execute(text("DELETE FROM admission_method WHERE id IN (1,2,3)"))
    conn.execute(text("DELETE FROM subject_group_subject"))
    conn.execute(text("DELETE FROM subject_group WHERE id BETWEEN 1 AND 7"))
    conn.execute(text("DELETE FROM subject WHERE id BETWEEN 1 AND 9"))
    conn.execute(text("DELETE FROM offering_academic_info WHERE id BETWEEN 1 AND 8"))
    conn.execute(text("DELETE FROM program_offering WHERE id BETWEEN 1 AND 8"))
    conn.execute(text("DELETE FROM major_program WHERE id BETWEEN 1 AND 6"))
    conn.execute(text("DELETE FROM allowed_transitions"))
    conn.execute(text("DELETE FROM consultation_status"))
    conn.execute(text("DELETE FROM pipeline_stage"))
    conn.execute(text("DELETE FROM casbin_rule WHERE ptype = 'g' AND v0 LIKE 'user:%'"))
    conn.execute(text('UPDATE "user" SET current_assignment_id = NULL'))
    conn.execute(text("DELETE FROM user_unit_assignment"))
    conn.execute(text('DELETE FROM "user" WHERE id > 1'))
    conn.execute(text('UPDATE "user" SET unit_id = NULL WHERE id = 1'))
    conn.execute(text("DELETE FROM organization_unit"))
