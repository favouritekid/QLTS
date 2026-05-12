"""Phase 3 PR-3A — admission_profile_choice + profile_choice_score tables

Bundle migration per plan v0.6 G1:
1. 2 NEW tables (admission_profile_choice + profile_choice_score)
2. 3 ALTER columns:
   - offering_admission_round.allow_multi_nv (Q-P3-02 per-round flag)
   - offering_admission_round.confirm_expiry_hours (Q-P3-06 per-round)
   - notification_rule.bypass_consent (Q-P3-07 per-rule)
3. 1 INSERT system_config row (Q-P3-01 max_choices_per_profile=5)
4. 1 UPDATE notification_rule bypass_consent=true cho 5 system-critical events

FK ON DELETE CASCADE/RESTRICT per GAP-18 v0.6:
- admission_profile_choice.admission_profile_id ON DELETE CASCADE
- admission_profile_choice.admission_path_id ON DELETE RESTRICT
- admission_profile_choice.path_subject_group_config_id ON DELETE RESTRICT
- profile_choice_score.admission_profile_choice_id ON DELETE CASCADE
- profile_choice_score.subject_id ON DELETE RESTRICT

UNIQUE constraints:
- (admission_profile_id, admission_path_id, path_subject_group_config_id) — P1 fix #4 v1.3
- (admission_profile_id, display_order) — chặn 2 NV cùng priority

CHECK constraints:
- display_order BETWEEN 1 AND 10 (Q-P3-01 hard upper bound; system_config soft default 5)

GAP-29 v0.6: notification_rule column name là `event` (NOT `event_code`)
GAP-31 v0.6: 12 events match SystemEvents enum (8 wired + 4 deferred)

Revision ID: phase3_01
Revises: phase2_06
Create Date: 2026-05-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "phase3_01"
down_revision: Union[str, None] = "phase2_06"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ============================================================
    # 0. PRE-FLIGHT AUDIT — C1 fix v0.6 (memory migration-predicate-safety)
    # ============================================================
    # Verify 5 system-critical events exist trong notification_rule
    # (Phase 1 #19c-d seed). Block migration nếu seed missing — better
    # than silent UPDATE-0 leaving bypass_consent uninitialized.
    conn = op.get_bind()
    events_count = conn.execute(
        sa.text(
            """
            SELECT COUNT(*) FROM notification_rule
            WHERE event IN (
                'admission_result_published',
                'admission_decision_admitted',
                'admission_decision_waitlisted',
                'admission_decision_rejected',
                'admission_enrolled'
            )
            """
        )
    ).scalar()
    if events_count is None or int(events_count) < 5:
        raise RuntimeError(
            f"Pre-flight fail: {events_count}/5 system-critical events found "
            f"trong notification_rule. Phase 1 #19c-d seed missing — apply "
            f"prerequisite migrations trước phase3_01."
        )

    # ============================================================
    # 1. Create admission_profile_choice table
    # ============================================================
    op.create_table(
        "admission_profile_choice",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "admission_profile_id",
            sa.Integer(),
            sa.ForeignKey("admission_profile.id", ondelete="CASCADE"),
            nullable=False,
            comment="Phase 3 multi-NV — link profile (GAP-18: CASCADE on profile delete)",
        ),
        sa.Column(
            "admission_path_id",
            sa.Integer(),
            sa.ForeignKey("admission_path.id", ondelete="RESTRICT"),
            nullable=False,
            comment="Path = ngành × phương thức × đợt (GAP-18: RESTRICT — path archive via status flag)",
        ),
        sa.Column(
            "path_subject_group_config_id",
            sa.Integer(),
            sa.ForeignKey("path_subject_group_config.id", ondelete="RESTRICT"),
            nullable=False,
            comment="Tổ hợp môn snapshot (GAP-18: RESTRICT)",
        ),
        sa.Column(
            "display_order",
            sa.Integer(),
            nullable=False,
            comment="Thứ tự ưu tiên NV (1 = cao nhất, max 10 per Q-P3-01)",
        ),
        sa.Column(
            "decision",
            sa.String(20),
            nullable=False,
            server_default="pending",
            comment="Engine decision: pending/admitted/waitlisted/rejected/skip",
        ),
        sa.Column(
            "waitlist_rank",
            sa.Integer(),
            nullable=True,
            comment="Rank trong waitlist (GAP-30: assigned at T6 engine, 1-based, unique per path×round)",
        ),
        sa.Column(
            "eligibility_check_result",
            sa.dialects.postgresql.JSONB(),
            nullable=True,
            comment="JSONB snapshot 6-rule engine result (computed at T6 publish)",
        ),
        sa.Column(
            "bonus_rule_snapshot",
            sa.dialects.postgresql.JSONB(),
            nullable=True,
            comment="BonusRule snapshot tại T6 publish time (Q-P3-11 NOT T1 submit)",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # UNIQUE: chặn duplicate (profile, path, config) — P1 fix #4 v1.3
        sa.UniqueConstraint(
            "admission_profile_id", "admission_path_id", "path_subject_group_config_id",
            name="uq_admission_profile_choice_path_config",
        ),
        # UNIQUE: chặn 2 NV cùng priority per profile
        sa.UniqueConstraint(
            "admission_profile_id", "display_order",
            name="uq_admission_profile_choice_display_order",
        ),
        # CHECK: display_order range 1-10 (Q-P3-01 hard upper bound)
        sa.CheckConstraint(
            "display_order BETWEEN 1 AND 10",
            name="ck_admission_profile_choice_display_order_range",
        ),
        # CHECK: decision enum
        sa.CheckConstraint(
            "decision IN ('pending', 'admitted', 'waitlisted', 'rejected', 'skip')",
            name="ck_admission_profile_choice_decision",
        ),
    )

    # Indexes (engine query + admin queue)
    op.create_index(
        "ix_admission_profile_choice_profile_decision",
        "admission_profile_choice",
        ["admission_profile_id", "decision"],
    )
    op.create_index(
        "ix_admission_profile_choice_path_id",
        "admission_profile_choice",
        ["admission_path_id"],
    )

    # ============================================================
    # 2. Create profile_choice_score table
    # ============================================================
    op.create_table(
        "profile_choice_score",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "admission_profile_choice_id",
            sa.BigInteger(),
            sa.ForeignKey("admission_profile_choice.id", ondelete="CASCADE"),
            nullable=False,
            comment="Link choice (GAP-18: CASCADE on choice delete)",
        ),
        sa.Column(
            "subject_id",
            sa.Integer(),
            sa.ForeignKey("subject.id", ondelete="RESTRICT"),
            nullable=False,
            comment="Subject (GAP-18: RESTRICT — không delete subject đang used)",
        ),
        sa.Column(
            "score",
            sa.Numeric(8, 2),
            nullable=False,
            comment="Điểm thí sinh (V-ACT/DGNL 1200-point max precision)",
        ),
        sa.Column(
            "max_score_snapshot",
            sa.Numeric(8, 2),
            nullable=False,
            comment="Max score tại submit time (snapshot)",
        ),
        sa.Column(
            "min_possible_score_snapshot",
            sa.Numeric(8, 2),
            nullable=True,
            comment="Min possible score snapshot (P2 fix #8 v1.9 — default 0 cho legacy)",
        ),
        sa.Column(
            "weight_snapshot",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="1.00",
            comment="Subject weight in scoring formula (snapshot)",
        ),
        # UNIQUE per (choice, subject)
        sa.UniqueConstraint(
            "admission_profile_choice_id", "subject_id",
            name="uq_profile_choice_score_choice_subject",
        ),
        # CHECK: score >= 0 (snapshot bounds enforced trong engine, NOT DB CHECK
        # vì max varies per path config)
        sa.CheckConstraint(
            "score >= 0",
            name="ck_profile_choice_score_non_negative",
        ),
    )

    op.create_index(
        "ix_profile_choice_score_choice_id",
        "profile_choice_score",
        ["admission_profile_choice_id"],
    )

    # ============================================================
    # 3. ALTER offering_admission_round — Q-P3-02 + Q-P3-06
    # ============================================================
    op.add_column(
        "offering_admission_round",
        sa.Column(
            "allow_multi_nv",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="Q-P3-02 per-round flag — 2026 false, 2027 admin enable",
        ),
    )
    op.add_column(
        "offering_admission_round",
        sa.Column(
            "confirm_expiry_hours",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("168"),
            comment="Q-P3-06 magic-link confirm expiry per-round (default 168h = 7d)",
        ),
    )

    # ============================================================
    # 4. ALTER notification_rule — Q-P3-07
    # ============================================================
    op.add_column(
        "notification_rule",
        sa.Column(
            "bypass_consent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment="Q-P3-07 per-rule bypass consent flag — system-critical events override consent",
        ),
    )

    # ============================================================
    # 5. INSERT system_config Q-P3-01
    # ============================================================
    op.execute(
        sa.text(
            """
            INSERT INTO system_config (key, value, description, updated_at)
            VALUES (
                'max_choices_per_profile',
                '5'::jsonb,
                'Max NV per profile, mùa 2026 default. DB CHECK display_order BETWEEN 1 AND 10 hard upper bound.',
                now()
            )
            ON CONFLICT (key) DO NOTHING
            """
        )
    )

    # ============================================================
    # 6. UPDATE notification_rule bypass_consent cho 5 events
    # GAP-29: column name là `event` (NOT `event_code`)
    # ============================================================
    op.execute(
        sa.text(
            """
            UPDATE notification_rule
            SET bypass_consent = true
            WHERE event IN (
                'admission_result_published',
                'admission_decision_admitted',
                'admission_decision_waitlisted',
                'admission_decision_rejected',
                'admission_enrolled'
            )
            """
        )
    )


def downgrade() -> None:
    # Reverse order: drop tables → drop columns → cleanup data

    # Rollback bypass_consent UPDATE (set back to false)
    op.execute(
        sa.text(
            """
            UPDATE notification_rule
            SET bypass_consent = false
            WHERE event IN (
                'admission_result_published',
                'admission_decision_admitted',
                'admission_decision_waitlisted',
                'admission_decision_rejected',
                'admission_enrolled'
            )
            """
        )
    )

    # Rollback system_config row
    op.execute(
        sa.text(
            "DELETE FROM system_config WHERE key = 'max_choices_per_profile'"
        )
    )

    # Drop ALTER columns
    op.drop_column("notification_rule", "bypass_consent")
    op.drop_column("offering_admission_round", "confirm_expiry_hours")
    op.drop_column("offering_admission_round", "allow_multi_nv")

    # Drop tables (CASCADE handles FK cleanup automatically)
    op.drop_index("ix_profile_choice_score_choice_id", table_name="profile_choice_score")
    op.drop_table("profile_choice_score")

    op.drop_index("ix_admission_profile_choice_path_id", table_name="admission_profile_choice")
    op.drop_index("ix_admission_profile_choice_profile_decision", table_name="admission_profile_choice")
    op.drop_table("admission_profile_choice")
