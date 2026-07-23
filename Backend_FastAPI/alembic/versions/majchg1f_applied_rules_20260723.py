"""major-change reprice 1F — relax applied_rules whitelist for major change.

## Why

``applied_rules`` chốt danh tính ngành của hồ sơ tại create-time:
``admission_path_id`` (:4648), ``admission_round_id`` (:4652), ``academic_info_id``
(:4653). Trigger ``prevent_applied_rules_update`` (body hiện tại từ ``ardockeys01``)
CHẶN mọi thay đổi 3 key này sau create.

Nhưng feature đổi ngành cần officer chuyển hồ sơ sang path/ngành KHÁC. Nếu snapshot
đứng yên ở path CŨ thì:
* ``_reresolve_documents_snapshot`` (:5310) đọc path từ ``applied_rules`` → resolve
  BỘ GIẤY ngành cũ (lỗ nghiệp vụ);
* ``get_round_for_profile_cutoff`` (admission_repository.py:1160) derive round từ
  path cũ → cổng cutoff sai đợt;
* ``submit_and_evaluate`` (:6899) tăng ``submission_count`` cho path CŨ.

## Fix

Thêm 3 key ``admission_path_id`` / ``admission_round_id`` / ``academic_info_id``
vào whitelist. Ba key này là MỘT snapshot danh tính path nguyên khối — nới cả ba
để ``_apply_major_change_snapshot`` ghi lại đồng bộ (đổi path thì round + academic
cũng phải đổi theo, không để nửa-cập-nhật gây bug ngầm). Mọi key khác (scoring,
fee toggle, audience…) VẪN immutable — chống-tamper giữ nguyên.

Hiệu lực ở tầng DB ngay lập tức, KHÔNG theo feature flag — nhưng nó chỉ CHO PHÉP
ghi 3 key; không code nào ghi khi ``MAJOR_CHANGE_REPRICE_ENABLED=False``.

Giữ nguyên: per-key classifier, deletion guard (whitelisted key được add/update
nhưng KHÔNG được xoá), wipe-entire-object guard. ``_apply_major_change_snapshot``
luôn ASSIGN (không xoá) nên deletion guard không cản.

## Downgrade

Khôi phục whitelist ``ardockeys01`` (7 key: 5 fee + mandatory_docs + doc_configs).

Revision ID: majchg1f_applied_rules_20260723
Revises: majchg1b_profile_col_20260723
Create Date: 2026-07-23
"""
from typing import Sequence, Union

from alembic import op

revision: str = "majchg1f_applied_rules_20260723"
down_revision: Union[str, None] = "majchg1b_profile_col_20260723"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Stable whitelist — 7 keys từ ardockeys01 + 3 major-change identity keys.
ALLOWED_KEYS: tuple[str, ...] = (
    "fee_status",
    "fee_paid_at",
    "fee_payment_data",
    "fee_calculated_at",
    "fee_invoice_id",
    "mandatory_docs",
    "doc_configs",
    "admission_path_id",
    "admission_round_id",
    "academic_info_id",
)


def upgrade() -> None:
    op.execute(
        """
CREATE OR REPLACE FUNCTION prevent_applied_rules_update()
RETURNS TRIGGER AS $$
DECLARE
    -- 7 keys (ardockeys01) + 3 major-change identity keys
    -- (admission_path_id, admission_round_id, academic_info_id) rewritten by
    -- _apply_major_change_snapshot khi officer đổi ngành. Deletion still rejected.
    allowed_keys TEXT[] := ARRAY[
        'fee_status',
        'fee_paid_at',
        'fee_payment_data',
        'fee_calculated_at',
        'fee_invoice_id',
        'mandatory_docs',
        'doc_configs',
        'admission_path_id',
        'admission_round_id',
        'academic_info_id'
    ];
    v_key TEXT;
    v_all_keys TEXT[];
    v_old_value JSONB;
    v_new_value JSONB;
    v_old_has BOOLEAN;
    v_new_has BOOLEAN;
BEGIN
    IF TG_OP = 'INSERT' THEN
        RETURN NEW;
    END IF;

    IF TG_OP = 'UPDATE' THEN
        -- Legacy snapshots without applied_rules: nothing to guard.
        IF OLD.applied_rules IS NULL THEN
            RETURN NEW;
        END IF;

        -- Fast path: identical JSONB -> no change at all.
        IF OLD.applied_rules IS NOT DISTINCT FROM NEW.applied_rules THEN
            RETURN NEW;
        END IF;

        -- NEW NULL but OLD wasn't -> wholesale wipe.
        IF NEW.applied_rules IS NULL THEN
            RAISE EXCEPTION
                'applied_rules is immutable; cannot wipe entire object';
        END IF;

        -- Walk every key in OLD union NEW.
        SELECT ARRAY(
            SELECT DISTINCT k FROM (
                SELECT jsonb_object_keys(OLD.applied_rules) AS k
                UNION
                SELECT jsonb_object_keys(NEW.applied_rules) AS k
            ) sub
        ) INTO v_all_keys;

        FOREACH v_key IN ARRAY v_all_keys LOOP
            v_old_has := OLD.applied_rules ? v_key;
            v_new_has := NEW.applied_rules ? v_key;
            v_old_value := OLD.applied_rules -> v_key;
            v_new_value := NEW.applied_rules -> v_key;

            -- Did this key actually change?
            IF v_old_value IS DISTINCT FROM v_new_value
               OR v_old_has <> v_new_has THEN
                -- Non-whitelisted key changed -> reject.
                IF NOT (v_key = ANY(allowed_keys)) THEN
                    RAISE EXCEPTION
                        'applied_rules: key % is immutable after '
                        'creation; only fee payment, document-resolution '
                        'and major-change identity keys may change',
                        v_key;
                END IF;
                -- Whitelisted key, but is this a deletion?
                IF v_old_has AND NOT v_new_has THEN
                    RAISE EXCEPTION
                        'applied_rules: deletion of key % is not '
                        'allowed; only add/update permitted',
                        v_key;
                END IF;
            END IF;
        END LOOP;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    """Restore the ardockeys01 behaviour (7 keys: 5 fee + 2 doc-resolution)."""
    op.execute(
        """
CREATE OR REPLACE FUNCTION prevent_applied_rules_update()
RETURNS TRIGGER AS $$
DECLARE
    allowed_keys TEXT[] := ARRAY[
        'fee_status',
        'fee_paid_at',
        'fee_payment_data',
        'fee_calculated_at',
        'fee_invoice_id',
        'mandatory_docs',
        'doc_configs'
    ];
    v_key TEXT;
    v_all_keys TEXT[];
    v_old_value JSONB;
    v_new_value JSONB;
    v_old_has BOOLEAN;
    v_new_has BOOLEAN;
BEGIN
    IF TG_OP = 'INSERT' THEN
        RETURN NEW;
    END IF;

    IF TG_OP = 'UPDATE' THEN
        IF OLD.applied_rules IS NULL THEN
            RETURN NEW;
        END IF;

        IF OLD.applied_rules IS NOT DISTINCT FROM NEW.applied_rules THEN
            RETURN NEW;
        END IF;

        IF NEW.applied_rules IS NULL THEN
            RAISE EXCEPTION
                'applied_rules is immutable; cannot wipe entire object';
        END IF;

        SELECT ARRAY(
            SELECT DISTINCT k FROM (
                SELECT jsonb_object_keys(OLD.applied_rules) AS k
                UNION
                SELECT jsonb_object_keys(NEW.applied_rules) AS k
            ) sub
        ) INTO v_all_keys;

        FOREACH v_key IN ARRAY v_all_keys LOOP
            v_old_has := OLD.applied_rules ? v_key;
            v_new_has := NEW.applied_rules ? v_key;
            v_old_value := OLD.applied_rules -> v_key;
            v_new_value := NEW.applied_rules -> v_key;

            IF v_old_value IS DISTINCT FROM v_new_value
               OR v_old_has <> v_new_has THEN
                IF NOT (v_key = ANY(allowed_keys)) THEN
                    RAISE EXCEPTION
                        'applied_rules: key % is immutable after '
                        'creation; only fee payment and '
                        'document-resolution keys may change',
                        v_key;
                END IF;
                IF v_old_has AND NOT v_new_has THEN
                    RAISE EXCEPTION
                        'applied_rules: deletion of key % is not '
                        'allowed; only add/update permitted',
                        v_key;
                END IF;
            END IF;
        END LOOP;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
        """
    )
