"""suspicious login: canonical device fingerprint

Revision ID: sl20260524_canonical
Revises: cleanup_upper_notif
Create Date: 2026-05-24

Option-B Commit 1 — canonical device fingerprint contract.

Adds family columns (browser_family/os_family) + device_fingerprint hash
to login_history, and (browser_family/os_family/device_type) to
trusted_device, so all 5 fingerprint call sites (record_login,
_check_device_seen, confirm_login, trusted_repo.is_device_trusted,
trusted_repo.trust_device) hash from the SAME inputs.

Root cause being fixed: pre-PR, fingerprint hashed display strings
("Mobile Safari 26.4" / "iOS 18.7") which drift on every browser/OS
minor update → trusted_device row never matches next login → user must
re-confirm every iOS update. Post-PR, fingerprint hashes family only
("Mobile Safari" / "iOS") → stable across version drift.

Backfill strategy (single Alembic transaction):

  Step 1: Snapshot trusted_device → backup table (versioned + idempotent).
  Step 2-3: ALTER login_history + trusted_device add new cols + index.
  Step 4: Backfill login_history family (regex strip version) + per-row
          device_fingerprint via LOCAL helper (immutable copy of service
          logic at commit time — replay-safe).
  Step 5: Backfill trusted_device.device_type from login_history JOIN
          (closest trusted_at), fallback heuristic by os/browser pattern
          for unmatched rows, audit log every fallback.
  Step 6: Backfill trusted_device family columns (same regex).
  Step 7: MERGE duplicate trusted_device rows (post-family collapse)
          + re-hash device_fingerprint via LOCAL helper. Winner = oldest
          first_seen_at, losers DELETE'd. Merge metadata: last_used_at
          = MAX, ip/name from row with newest last_used_at. Audit log
          every merge into trusted_device_sl20260524_merge_map (tombstone
          source for downgrade row preservation).

Downgrade preserves ALL post-deploy writes (Plan v10):
  - NEW rows (user "Là tôi"): re-hash to OLD display fingerprint via
    LOCAL helper, INSERT with ON CONFLICT DO UPDATE merge.
  - UPDATE on existing rows: MERGE post-deploy last_used_at/IP/name
    into restored backup rows (NULL-safe via -infinity sentinel +
    NULLIF), keep immutable first_seen_at/trusted_at from backup.
  - DELETE rows (secure_account/single delete/remove_all): CONDITIONAL
    restore — only rows whose winner is still alive in current snapshot,
    or rows that are losers of a still-alive winner (via merge_map).
    User-revoked devices are NOT resurrected (security-critical).

Backup table `trusted_device_pre_sl20260524_canonical_backup` and
merge_map table `trusted_device_sl20260524_merge_map` are versioned
(revision-id suffix) so re-upgrade after downgrade is idempotent:
upgrade() DROP IF EXISTS guard recreates them fresh.

Idempotent re-run: backup table guarded; merge_map dropped at end of
downgrade so subsequent upgrade recreates it. login_history backfill
re-applies safely (regexp_replace is deterministic; device_fingerprint
update is idempotent — same input → same hash). trusted_device dedupe
is NOT idempotent on its own (rows are physically deleted) but the
backup table preserves pre-merge state for downgrade rollback.
"""
from typing import Sequence, Union
import hashlib
import logging

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


revision: str = "sl20260524_canonical"
down_revision: Union[str, None] = "cleanup_upper_notif"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


log = logging.getLogger("alembic.runtime.migration")


# =============================================================================
# IMMUTABLE LOCAL HELPERS
# =============================================================================
# These MUST NOT import from app.services.login_history_service. Migration
# revisions must be reproducible months/years later even if the service
# helper logic drifts. Pin the exact hash inputs and component order here.
# Parity test (tests/alembic/test_sl20260524_canonical_migration.py)
# asserts these match service helper output at PR commit time.


def _generate_device_fingerprint_canonical_v1(
    browser_family, os_family, device_type, user_id, salt
):
    """Canonical fingerprint hash — family-only inputs.

    Pinned copy of `app.services.login_history_service.generate_device_fingerprint`
    at the time of this migration commit. The two MUST produce identical
    output for identical inputs; parity is asserted by the migration test
    so any future service refactor either updates this copy in a new
    migration or breaks the test loudly.
    """
    components = [
        browser_family or "unknown",
        os_family or "unknown",
        device_type or "unknown",
        str(user_id) if user_id else "anonymous",
        salt,
    ]
    return hashlib.sha256("|".join(components).encode()).hexdigest()


def _generate_device_fingerprint_old_display_v1(
    browser_display, os_display, device_type, user_id, salt
):
    """OLD display-string fingerprint hash — pre-PR logic.

    Used ONLY by downgrade Step D3 to convert post-deploy NEW rows
    (created with canonical fingerprint) back to the display-string
    format expected by reverted service code. Inputs are the display
    strings ("Mobile Safari 26.4" / "iOS 18.7") — same component order
    + same salt as canonical helper.
    """
    components = [
        browser_display or "unknown",
        os_display or "unknown",
        device_type or "unknown",
        str(user_id) if user_id else "anonymous",
        salt,
    ]
    return hashlib.sha256("|".join(components).encode()).hexdigest()


def _get_salt():
    """Read DEVICE_FINGERPRINT_SALT from settings (active at migration time)."""
    from app.config import settings
    return settings.DEVICE_FINGERPRINT_SALT


# Regex strips trailing version-like suffix: " 26.4", " 147.0.0", " 10"
# Postgres equivalent: regexp_replace(col, '\s+[\d][\d.]*$', '')
_VERSION_SUFFIX_REGEX_PG = r"\s+[\d][\d.]*$"


# =============================================================================
# UPGRADE
# =============================================================================


def upgrade() -> None:
    conn = op.get_bind()
    salt = _get_salt()

    # -------------------------------------------------------------------------
    # Step 1: Snapshot trusted_device to versioned backup table.
    # Idempotent: DROP IF EXISTS ensures re-upgrade after downgrade works.
    # -------------------------------------------------------------------------
    conn.execute(text(
        "DROP TABLE IF EXISTS trusted_device_pre_sl20260524_canonical_backup"
    ))
    conn.execute(text(
        "CREATE TABLE trusted_device_pre_sl20260524_canonical_backup "
        "AS SELECT * FROM trusted_device"
    ))
    conn.execute(text(
        "CREATE INDEX ix_tdpcb_sl20260524_user_id "
        "ON trusted_device_pre_sl20260524_canonical_backup(user_id)"
    ))
    backup_count = conn.execute(text(
        "SELECT COUNT(*) FROM trusted_device_pre_sl20260524_canonical_backup"
    )).scalar()
    log.info(
        "sl20260524: backup table created (rows=%d)", backup_count
    )

    # -------------------------------------------------------------------------
    # Step 2: ALTER login_history — add canonical columns + index.
    # -------------------------------------------------------------------------
    op.add_column(
        "login_history",
        sa.Column("browser_family", sa.String(64), nullable=True),
    )
    op.add_column(
        "login_history",
        sa.Column("os_family", sa.String(64), nullable=True),
    )
    op.add_column(
        "login_history",
        sa.Column("device_fingerprint", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_login_history_user_fp_response",
        "login_history",
        ["user_id", "device_fingerprint", "user_response"],
    )

    # -------------------------------------------------------------------------
    # Step 3: ALTER trusted_device — add family + device_type columns.
    # device_type is critical: canonical fingerprint hashes (browser_family,
    # os_family, device_type, user_id, salt). Pre-PR trusted_device had no
    # device_type column.
    # -------------------------------------------------------------------------
    op.add_column(
        "trusted_device",
        sa.Column("browser_family", sa.String(64), nullable=True),
    )
    op.add_column(
        "trusted_device",
        sa.Column("os_family", sa.String(64), nullable=True),
    )
    op.add_column(
        "trusted_device",
        sa.Column("device_type", sa.String(50), nullable=True),
    )

    # -------------------------------------------------------------------------
    # Step 4: Backfill login_history.browser_family / os_family / device_fingerprint.
    # Regex via Postgres regexp_replace (deterministic, idempotent).
    # Then per-row device_fingerprint via LOCAL helper (must match service
    # helper output at commit time — see parity test).
    # -------------------------------------------------------------------------
    conn.execute(text(
        "UPDATE login_history SET "
        "  browser_family = NULLIF(regexp_replace(browser, :rx, ''), ''), "
        "  os_family = NULLIF(regexp_replace(os, :rx, ''), '')"
    ), {"rx": _VERSION_SUFFIX_REGEX_PG})

    lh_rows = conn.execute(text(
        "SELECT id, browser_family, os_family, device_type, user_id "
        "FROM login_history"
    )).fetchall()
    for row in lh_rows:
        fp = _generate_device_fingerprint_canonical_v1(
            row.browser_family, row.os_family, row.device_type, row.user_id, salt
        )
        conn.execute(
            text("UPDATE login_history SET device_fingerprint = :fp WHERE id = :id"),
            {"fp": fp, "id": row.id},
        )
    log.info(
        "sl20260524: login_history backfill complete (rows=%d)", len(lh_rows)
    )

    # -------------------------------------------------------------------------
    # Step 5: Backfill trusted_device.device_type.
    # JOIN with login_history by (user_id, browser, os) — pick the row whose
    # login_at is closest to trusted_device.trusted_at (most contextually
    # relevant device_type at trust time).
    # -------------------------------------------------------------------------
    conn.execute(text(
        "UPDATE trusted_device td SET device_type = sub.device_type "
        "FROM ( "
        "  SELECT DISTINCT ON (td2.id) td2.id AS td_id, lh.device_type "
        "  FROM trusted_device td2 "
        "  JOIN login_history lh ON lh.user_id = td2.user_id "
        "    AND lh.browser = td2.browser "
        "    AND lh.os = td2.os "
        "  ORDER BY td2.id, "
        "    abs(extract(epoch FROM lh.login_at - td2.trusted_at)) ASC "
        ") sub "
        "WHERE td.id = sub.td_id"
    ))

    # -------------------------------------------------------------------------
    # Step 5b: Fallback heuristic for trusted_device rows whose device_type
    # remained NULL (no login_history match). Audit log every fallback.
    # -------------------------------------------------------------------------
    fallback_rows = conn.execute(text(
        "SELECT id, user_id, browser, os FROM trusted_device WHERE device_type IS NULL"
    )).fetchall()
    for row in fallback_rows:
        os_lower = (row.os or "").lower()
        browser_lower = (row.browser or "").lower()
        if "ipad" in os_lower or (browser_lower.startswith("mobile") and "ipad" in os_lower):
            device_type = "tablet"
        elif any(m in os_lower for m in ("ios", "android", "windows phone")):
            device_type = "mobile"
        else:
            device_type = "desktop"
        conn.execute(
            text("UPDATE trusted_device SET device_type = :dt WHERE id = :id"),
            {"dt": device_type, "id": row.id},
        )
        log.warning(
            "sl20260524: device_type fallback heuristic "
            "user_id=%s td_id=%s browser=%r os=%r fallback=%s reason=no_login_history_match",
            row.user_id, row.id, row.browser, row.os, device_type,
        )

    # -------------------------------------------------------------------------
    # Step 6: Backfill trusted_device.browser_family / os_family.
    # Same regex as Step 4 (deterministic, replay-safe).
    # -------------------------------------------------------------------------
    conn.execute(text(
        "UPDATE trusted_device SET "
        "  browser_family = NULLIF(regexp_replace(browser, :rx, ''), ''), "
        "  os_family = NULLIF(regexp_replace(os, :rx, ''), '')"
    ), {"rx": _VERSION_SUFFIX_REGEX_PG})

    # -------------------------------------------------------------------------
    # Step 7b: Create merge_map BEFORE dedupe so we can audit-log each merge
    # into it as we go. Versioned name + idempotent guard for re-upgrade.
    # -------------------------------------------------------------------------
    conn.execute(text(
        "DROP TABLE IF EXISTS trusted_device_sl20260524_merge_map"
    ))
    conn.execute(text(
        "CREATE TABLE trusted_device_sl20260524_merge_map ( "
        "  loser_id INTEGER NOT NULL, "
        "  winner_id INTEGER NOT NULL, "
        "  user_id INTEGER NOT NULL, "
        "  old_fingerprint VARCHAR(64) NOT NULL, "
        "  new_fingerprint VARCHAR(64) NOT NULL, "
        "  merged_at TIMESTAMPTZ NOT NULL DEFAULT NOW() "
        ")"
    ))
    conn.execute(text(
        "CREATE INDEX ix_tdmm_sl20260524_winner "
        "ON trusted_device_sl20260524_merge_map(winner_id)"
    ))
    conn.execute(text(
        "CREATE INDEX ix_tdmm_sl20260524_loser "
        "ON trusted_device_sl20260524_merge_map(loser_id)"
    ))

    # -------------------------------------------------------------------------
    # Step 7: MERGE duplicates + RE-HASH device_fingerprint.
    # Group by canonical fingerprint inputs. Winner = oldest first_seen_at,
    # tiebreaker = smallest id. Losers merge metadata then DELETE. Winner
    # gets canonical fingerprint.
    # -------------------------------------------------------------------------
    groups = conn.execute(text(
        "SELECT user_id, browser_family, os_family, device_type, "
        "       array_agg(id ORDER BY first_seen_at ASC NULLS LAST, id ASC) AS ids "
        "FROM trusted_device "
        "GROUP BY user_id, browser_family, os_family, device_type"
    )).fetchall()

    merge_count = 0
    for grp in groups:
        ids = list(grp.ids)
        winner_id = ids[0]
        loser_ids = ids[1:]
        new_fp = _generate_device_fingerprint_canonical_v1(
            grp.browser_family, grp.os_family, grp.device_type, grp.user_id, salt
        )

        # Display name normalized to family form (drop noisy version suffix).
        merged_name = None
        if grp.browser_family and grp.os_family:
            merged_name = f"{grp.browser_family} on {grp.os_family}"

        if not loser_ids:
            # Single-row group — only re-hash + normalize name.
            conn.execute(
                text(
                    "UPDATE trusted_device "
                    "SET device_fingerprint = :fp, name = COALESCE(:name, name) "
                    "WHERE id = :id"
                ),
                {"fp": new_fp, "name": merged_name, "id": winner_id},
            )
            continue

        # Multi-row group: gather losers + winner for metadata merge.
        all_rows = conn.execute(
            text(
                "SELECT id, device_fingerprint, last_used_at, trusted_from_ip, name "
                "FROM trusted_device WHERE id = ANY(:ids)"
            ),
            {"ids": ids},
        ).fetchall()
        winner_row = next(r for r in all_rows if r.id == winner_id)
        loser_rows = [r for r in all_rows if r.id != winner_id]

        # last_used_at = MAX (NULL-safe via NULL <= anything semantics).
        max_last_used = winner_row.last_used_at
        latest_row = winner_row
        for r in all_rows:
            if r.last_used_at is None:
                continue
            if max_last_used is None or r.last_used_at > max_last_used:
                max_last_used = r.last_used_at
                latest_row = r

        merged_ip = latest_row.trusted_from_ip or winner_row.trusted_from_ip
        # name: prefer normalized family form, else fall back to winner's name.
        final_name = merged_name or winner_row.name

        # Audit log + merge_map row per loser.
        for loser in loser_rows:
            conn.execute(
                text(
                    "INSERT INTO trusted_device_sl20260524_merge_map "
                    "(loser_id, winner_id, user_id, old_fingerprint, new_fingerprint) "
                    "VALUES (:loser_id, :winner_id, :user_id, :old_fp, :new_fp)"
                ),
                {
                    "loser_id": loser.id,
                    "winner_id": winner_id,
                    "user_id": grp.user_id,
                    "old_fp": loser.device_fingerprint,
                    "new_fp": new_fp,
                },
            )
            merge_count += 1
            log.info(
                "sl20260524: merging trusted_device loser_id=%s winner_id=%s "
                "user_id=%s old_fp=%s new_fp=%s",
                loser.id, winner_id, grp.user_id,
                loser.device_fingerprint, new_fp,
            )

        # Delete losers BEFORE updating winner — avoids UNIQUE collision on
        # (user_id, device_fingerprint) when winner gets the new shared fp.
        conn.execute(
            text("DELETE FROM trusted_device WHERE id = ANY(:ids)"),
            {"ids": loser_ids},
        )

        # Update winner with merged metadata + canonical fingerprint.
        conn.execute(
            text(
                "UPDATE trusted_device SET "
                "  device_fingerprint = :fp, "
                "  last_used_at = :last_used, "
                "  trusted_from_ip = :ip, "
                "  name = :name "
                "WHERE id = :id"
            ),
            {
                "fp": new_fp,
                "last_used": max_last_used,
                "ip": merged_ip,
                "name": final_name,
                "id": winner_id,
            },
        )

    log.info(
        "sl20260524: trusted_device dedupe complete "
        "(groups=%d, merges=%d, remaining_rows=%d)",
        len(groups), merge_count,
        conn.execute(text("SELECT COUNT(*) FROM trusted_device")).scalar(),
    )


# =============================================================================
# DOWNGRADE
# =============================================================================


def downgrade() -> None:
    conn = op.get_bind()
    salt = _get_salt()

    # -------------------------------------------------------------------------
    # Step D1: Snapshot CURRENT trusted_device (includes both backup-derived
    # and post-deploy rows). Needed for Step D5 metadata MERGE and Step D6
    # NEW rows preservation.
    # -------------------------------------------------------------------------
    conn.execute(text("DROP TABLE IF EXISTS _td_current_snapshot"))
    conn.execute(text(
        "CREATE TEMP TABLE _td_current_snapshot AS SELECT * FROM trusted_device"
    ))

    # -------------------------------------------------------------------------
    # Step D2: Identify NEW rows (id NOT IN backup) — created post-deploy
    # by user clicking "Là tôi".
    # -------------------------------------------------------------------------
    conn.execute(text("DROP TABLE IF EXISTS _td_new_rows"))
    conn.execute(text(
        "CREATE TEMP TABLE _td_new_rows AS "
        "SELECT s.* FROM _td_current_snapshot s "
        "LEFT JOIN trusted_device_pre_sl20260524_canonical_backup b "
        "  ON b.id = s.id "
        "WHERE b.id IS NULL"
    ))
    new_count = conn.execute(text("SELECT COUNT(*) FROM _td_new_rows")).scalar()
    log.info("sl20260524 downgrade: %d post-deploy NEW rows to preserve", new_count)

    # -------------------------------------------------------------------------
    # Step D3: Re-hash NEW rows to OLD display fingerprint so old code can
    # match them after revert. Uses LOCAL old-display helper (immutable).
    # -------------------------------------------------------------------------
    new_rows = conn.execute(text(
        "SELECT id, browser, os, device_type, user_id FROM _td_new_rows"
    )).fetchall()
    for row in new_rows:
        old_fp = _generate_device_fingerprint_old_display_v1(
            row.browser, row.os, row.device_type, row.user_id, salt
        )
        conn.execute(
            text("UPDATE _td_new_rows SET device_fingerprint = :fp WHERE id = :id"),
            {"fp": old_fp, "id": row.id},
        )

    # -------------------------------------------------------------------------
    # Step D4: TOMBSTONE-AWARE restore from backup.
    # Restore backup row only if:
    #   (a) its id still exists in current snapshot (winner alive), OR
    #   (b) it's a loser of a winner that's still alive (via merge_map).
    # Rows the user explicitly deleted (secure_account / single delete /
    # remove_all_devices) are NOT resurrected — security-critical.
    # -------------------------------------------------------------------------
    conn.execute(text("DELETE FROM trusted_device"))
    restored = conn.execute(text(
        "WITH inserted AS ( "
        "  INSERT INTO trusted_device ( "
        "    id, user_id, device_fingerprint, name, browser, os, "
        "    first_seen_at, trusted_at, last_used_at, trusted_from_ip "
        "  ) "
        "  SELECT "
        "    b.id, b.user_id, b.device_fingerprint, b.name, b.browser, b.os, "
        "    b.first_seen_at, b.trusted_at, b.last_used_at, b.trusted_from_ip "
        "  FROM trusted_device_pre_sl20260524_canonical_backup b "
        "  WHERE EXISTS ( "
        "    SELECT 1 FROM _td_current_snapshot c WHERE c.id = b.id "
        "  ) OR EXISTS ( "
        "    SELECT 1 FROM trusted_device_sl20260524_merge_map m "
        "    JOIN _td_current_snapshot c ON c.id = m.winner_id "
        "    WHERE m.loser_id = b.id "
        "  ) "
        "  RETURNING id "
        ") "
        "SELECT COUNT(*) FROM inserted"
    )).scalar()
    backup_total = conn.execute(text(
        "SELECT COUNT(*) FROM trusted_device_pre_sl20260524_canonical_backup"
    )).scalar()
    log.info(
        "sl20260524 downgrade: tombstone restore (%d/%d backup rows restored, "
        "%d skipped — user deleted)",
        restored, backup_total, backup_total - restored,
    )

    # -------------------------------------------------------------------------
    # Step D5: MERGE post-deploy UPDATE on existing rows.
    # last_used_at = NULL-safe GREATEST (-infinity sentinel → NULLIF restores
    # NULL when both sides NULL). IP/name follow the row with newer
    # last_used_at. first_seen_at + trusted_at stay backup (immutable trust
    # history).
    # -------------------------------------------------------------------------
    conn.execute(text(
        "UPDATE trusted_device t SET "
        "  last_used_at = NULLIF( "
        "    GREATEST( "
        "      COALESCE(t.last_used_at, '-infinity'::timestamptz), "
        "      COALESCE(s.last_used_at, '-infinity'::timestamptz) "
        "    ), "
        "    '-infinity'::timestamptz "
        "  ), "
        "  trusted_from_ip = CASE "
        "    WHEN COALESCE(s.last_used_at, '-infinity'::timestamptz) "
        "       > COALESCE(t.last_used_at, '-infinity'::timestamptz) "
        "    THEN s.trusted_from_ip ELSE t.trusted_from_ip END, "
        "  name = CASE "
        "    WHEN COALESCE(s.last_used_at, '-infinity'::timestamptz) "
        "       > COALESCE(t.last_used_at, '-infinity'::timestamptz) "
        "    THEN s.name ELSE t.name END "
        "FROM _td_current_snapshot s "
        "WHERE t.id = s.id "
        "  AND s.id IN ( "
        "    SELECT id FROM trusted_device_pre_sl20260524_canonical_backup "
        "  )"
    ))

    # -------------------------------------------------------------------------
    # Step D6: INSERT NEW rows with ON CONFLICT DO UPDATE (NULL-safe merge).
    # Conflict happens when a NEW row's old-display fingerprint collides
    # with a restored backup row's fingerprint (rare edge case). MERGE
    # metadata rather than dropping new row's writes.
    # -------------------------------------------------------------------------
    conn.execute(text(
        "INSERT INTO trusted_device ( "
        "  id, user_id, device_fingerprint, name, browser, os, "
        "  first_seen_at, trusted_at, last_used_at, trusted_from_ip "
        ") "
        "SELECT "
        "  id, user_id, device_fingerprint, name, browser, os, "
        "  first_seen_at, trusted_at, last_used_at, trusted_from_ip "
        "FROM _td_new_rows "
        "ON CONFLICT (user_id, device_fingerprint) DO UPDATE SET "
        "  last_used_at = NULLIF( "
        "    GREATEST( "
        "      COALESCE(trusted_device.last_used_at, '-infinity'::timestamptz), "
        "      COALESCE(EXCLUDED.last_used_at, '-infinity'::timestamptz) "
        "    ), "
        "    '-infinity'::timestamptz "
        "  ), "
        "  trusted_from_ip = CASE "
        "    WHEN COALESCE(EXCLUDED.last_used_at, '-infinity'::timestamptz) "
        "       > COALESCE(trusted_device.last_used_at, '-infinity'::timestamptz) "
        "    THEN EXCLUDED.trusted_from_ip "
        "    ELSE trusted_device.trusted_from_ip END, "
        "  name = CASE "
        "    WHEN COALESCE(EXCLUDED.last_used_at, '-infinity'::timestamptz) "
        "       > COALESCE(trusted_device.last_used_at, '-infinity'::timestamptz) "
        "    THEN EXCLUDED.name "
        "    ELSE trusted_device.name END"
    ))

    # -------------------------------------------------------------------------
    # Step D7: Reset sequence + DROP merge_map (audit lives in structlog).
    # Drop new columns + index. Backup table kept — operator drops manually
    # after verifying rollback stable (N weeks).
    # -------------------------------------------------------------------------
    conn.execute(text(
        "SELECT setval('trusted_device_id_seq', "
        "  COALESCE((SELECT MAX(id) FROM trusted_device), 1))"
    ))
    conn.execute(text("DROP TABLE IF EXISTS trusted_device_sl20260524_merge_map"))
    # _td_current_snapshot + _td_new_rows are TEMP — auto-dropped at session end.

    op.drop_column("trusted_device", "device_type")
    op.drop_column("trusted_device", "os_family")
    op.drop_column("trusted_device", "browser_family")
    op.drop_index("ix_login_history_user_fp_response", table_name="login_history")
    op.drop_column("login_history", "device_fingerprint")
    op.drop_column("login_history", "os_family")
    op.drop_column("login_history", "browser_family")
