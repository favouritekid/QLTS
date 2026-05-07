"""phase1_05: add subject_kind + score bounds + 6 virtual subject seed

Revision ID: phase1_05
Revises: phase1_03
Create Date: 2026-05-04

#184 Wave 1 PR-1C' — fifth migration in Phase 1 Schema chain
(PLAN §4 line 2662-2666). Three additive columns on ``subject``
plus a 6-row idempotent seed of virtual subjects (TERM_AVERAGE
buckets, ABILITY_TEST scores, CERTIFICATE marks) needed by the
multi-NV scoring engine that ships in Phase 3.

Schema additions
----------------
* ``subject_kind`` ENUM type — 4 values per PLAN line 733-737:
  ``ACADEMIC_SUBJECT`` (Toán/Lý/Hóa/Văn), ``TERM_AVERAGE``
  (TB học kỳ/cả năm), ``ABILITY_TEST`` (DGNL/V-ACT), ``CERTIFICATE``
  (IELTS/nghề). Created BEFORE the column add so the column type
  resolves cleanly. Down migration drops AFTER column.

* ``subject.subject_kind subject_kind NOT NULL DEFAULT
  'ACADEMIC_SUBJECT'`` — server default backfills every existing
  row at ALTER time (PG fast path on default, no row-by-row
  UPDATE). Stays NOT NULL post-migration so the scoring engine
  never has to handle a NULL kind.

* ``subject.max_score`` Numeric(6,2) nullable. Stores the ceiling
  for this subject's score (10 for academic, 150 for DGNL,
  1200 for V-ACT, 9.0 for IELTS). NULL is legitimate for
  legacy rows pre-seed; service should default to 10 when
  reading a NULL ``max_score`` on an ACADEMIC_SUBJECT row.

* ``subject.min_possible_score`` Numeric(6,2) nullable. Floor
  for the subject score, NULL = 0. Used by the scoring engine
  to clamp + percentage-normalize scores cross-kind.

Seed
----
6 virtual subjects ON CONFLICT DO NOTHING (PLAN line 4174-4181
+ PLAN line 745 "TB_HK1_L12, TB_CN_L12, DGNL_DHQGHN, V_ACT, IELTS..."):

* ``TB_HK1_L12`` — TERM_AVERAGE, max=10 — TB học kỳ 1 lớp 12
* ``TB_HK2_L12`` — TERM_AVERAGE, max=10 — TB học kỳ 2 lớp 12
* ``TB_CN_L12`` — TERM_AVERAGE, max=10 — TB cả năm lớp 12
* ``DGNL_DHQGHN`` — ABILITY_TEST, max=150 — ĐGNL ĐHQG Hà Nội
* ``V_ACT`` — ABILITY_TEST, max=1200 — V-ACT (ĐH Bách khoa HN)
* ``IELTS`` — CERTIFICATE, max=9 — IELTS

Idempotency: ``ON CONFLICT (code) DO NOTHING`` — re-applying
upgrade after partial failure leaves existing rows untouched.
The unique constraint on ``code`` (created by the initial
migration) is what makes the conflict guard work; no need to
add it here.

Down-revision chain: ``phase1_03 → phase1_05``. Note: phase1_04
is DEFERRED Q1/2027 (Q9 chốt 2026-05-01), so the chain skips it
intentionally.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "phase1_05"
down_revision: Union[str, None] = "phase1_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ENUM values per PLAN line 733-737. Frozen here as the migration
# is the source-of-truth for the type definition; SQLAlchemy
# model mirrors via ``postgresql.ENUM(name=..., create_type=False)``.
SUBJECT_KIND_VALUES: tuple[str, ...] = (
    "ACADEMIC_SUBJECT",
    "TERM_AVERAGE",
    "ABILITY_TEST",
    "CERTIFICATE",
)


def upgrade() -> None:
    # 1. Create the subject_kind ENUM type. ``checkfirst=True`` makes
    #    the call idempotent on partial-failure replay.
    subject_kind_enum = postgresql.ENUM(
        *SUBJECT_KIND_VALUES,
        name="subject_kind",
        create_type=False,
    )
    subject_kind_enum.create(op.get_bind(), checkfirst=True)

    # 2. subject.subject_kind — NOT NULL with server default to
    #    backfill every existing row (academic subjects only at
    #    this point in time; the seed below adds the non-academic
    #    virtual subjects under their proper kinds).
    op.add_column(
        "subject",
        sa.Column(
            "subject_kind",
            subject_kind_enum,
            nullable=False,
            server_default=sa.text("'ACADEMIC_SUBJECT'::subject_kind"),
            comment=(
                "Subject category. ACADEMIC_SUBJECT for legacy rows; "
                "TERM_AVERAGE / ABILITY_TEST / CERTIFICATE for virtual "
                "subjects seeded by phase1_05."
            ),
        ),
    )

    # 3. subject.max_score — score ceiling. NULL for legacy rows;
    #    seeded values explicit per-row.
    op.add_column(
        "subject",
        sa.Column(
            "max_score",
            sa.Numeric(precision=6, scale=2),
            nullable=True,
            comment=(
                "Score ceiling for this subject (10 for academic, "
                "150 for DGNL, 1200 for V-ACT, 9 for IELTS). NULL = "
                "service falls back to 10 for ACADEMIC_SUBJECT."
            ),
        ),
    )

    # 4. subject.min_possible_score — score floor. NULL = service
    #    treats as 0.
    op.add_column(
        "subject",
        sa.Column(
            "min_possible_score",
            sa.Numeric(precision=6, scale=2),
            nullable=True,
            comment=(
                "Score floor for this subject. NULL = 0. Used by the "
                "scoring engine to clamp + percentage-normalize."
            ),
        ),
    )

    # 5. Seed 6 virtual subjects. Idempotent via ON CONFLICT (code).
    #    Names use Vietnamese display labels per PLAN line 4174-4181.
    op.execute(
        sa.text(
            """
            INSERT INTO subject (code, name_vi, subject_kind, max_score, display_order, is_active)
            VALUES
                ('TB_HK1_L12',  'TB học kỳ 1 lớp 12',      'TERM_AVERAGE', 10,   100, true),
                ('TB_HK2_L12',  'TB học kỳ 2 lớp 12',      'TERM_AVERAGE', 10,   101, true),
                ('TB_CN_L12',   'TB cả năm lớp 12',        'TERM_AVERAGE', 10,   102, true),
                ('DGNL_DHQGHN', 'ĐGNL ĐHQG Hà Nội',        'ABILITY_TEST', 150,  200, true),
                ('V_ACT',       'V-ACT (ĐH Bách khoa HN)', 'ABILITY_TEST', 1200, 201, true),
                ('IELTS',       'IELTS',                   'CERTIFICATE',  9,    300, true)
            ON CONFLICT (code) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    # 1. Delete the seeded virtual subjects FIRST (before dropping the
    #    enum, otherwise the rows hold a reference to the type and
    #    the type drop fails). Strict predicate on ``code`` so admin-
    #    edited rows with these codes (unlikely but possible) still
    #    get removed cleanly — admin should be using the catalog UI
    #    if they need to override seeded rows.
    op.execute(
        sa.text(
            """
            DELETE FROM subject
            WHERE code IN (
                'TB_HK1_L12', 'TB_HK2_L12', 'TB_CN_L12',
                'DGNL_DHQGHN', 'V_ACT', 'IELTS'
            )
            """
        )
    )

    # 2. Drop columns in inverse order — score bounds before kind so
    #    if the enum drop fails (e.g. another column we don't know
    #    about references it) the column drop has already cleared.
    op.drop_column("subject", "min_possible_score")
    op.drop_column("subject", "max_score")
    op.drop_column("subject", "subject_kind")

    # 3. Drop the ENUM type LAST so PG doesn't error on type-still-
    #    in-use. ``checkfirst=True`` keeps the downgrade re-runnable.
    subject_kind_enum = postgresql.ENUM(
        *SUBJECT_KIND_VALUES,
        name="subject_kind",
        create_type=False,
    )
    subject_kind_enum.drop(op.get_bind(), checkfirst=True)
