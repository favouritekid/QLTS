#!/usr/bin/env python3
"""
KPI Data Integrity Audit Script

Checks for data mismatches between KPI targets and actual lead data.
Run inside the backend container:
    docker compose exec backend python scripts/kpi_audit.py

Checks performed:
1. Officer-scoped kpi_target rows missing unit_id (invisible to resolver)
2. Officer-scoped kpi_config rows missing unit_id
3. Active target unit_id != officer's current unit (stale after transfer)
4. achieved_ytd vs actual enrollment count (Celery sync drift)
5. KPI plan unit_id consistency
6. Lead pipeline distribution for officers with targets
"""
import asyncio
import sys

from sqlalchemy import text


async def run_audit():
    from app.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        issues = 0
        warnings = 0

        print("=" * 70)
        print("KPI DATA INTEGRITY AUDIT")
        print("=" * 70)

        # =====================================================================
        # CHECK 1: Officer-scoped kpi_target missing unit_id
        # =====================================================================
        r = await db.execute(text("""
            SELECT t.id, t.officer_id, t.fiscal_year, t.kpi_code
            FROM kpi_target t
            WHERE t.officer_id IS NOT NULL AND t.unit_id IS NULL
        """))
        rows = r.fetchall()
        if rows:
            issues += len(rows)
            print(f"\n[FAIL] {len(rows)} kpi_target rows: officer_id set but unit_id NULL")
            for row in rows:
                print(f"  id={row.id} officer={row.officer_id} year={row.fiscal_year} code={row.kpi_code}")
        else:
            print("\n[OK] kpi_target: all officer-scoped rows have unit_id")

        # =====================================================================
        # CHECK 2: Officer-scoped kpi_config missing unit_id
        # =====================================================================
        r = await db.execute(text("""
            SELECT c.id, c.officer_id, c.kpi_code
            FROM kpi_config c
            WHERE c.officer_id IS NOT NULL AND c.unit_id IS NULL
        """))
        rows = r.fetchall()
        if rows:
            issues += len(rows)
            print(f"\n[FAIL] {len(rows)} kpi_config rows: officer_id set but unit_id NULL")
            for row in rows:
                print(f"  id={row.id} officer={row.officer_id} code={row.kpi_code}")
        else:
            print("\n[OK] kpi_config: all officer-scoped rows have unit_id")

        # =====================================================================
        # CHECK 3: Active target unit_id != officer's current unit
        # =====================================================================
        r = await db.execute(text("""
            SELECT t.id, t.officer_id, t.unit_id AS target_unit,
                   u.unit_id AS user_unit, t.fiscal_year
            FROM kpi_target t
            JOIN "user" u ON t.officer_id = u.id
            WHERE t.officer_id IS NOT NULL
              AND t.unit_id IS NOT NULL
              AND t.unit_id != u.unit_id
              AND t.is_active = true
        """))
        rows = r.fetchall()
        if rows:
            warnings += len(rows)
            print(f"\n[WARN] {len(rows)} active kpi_target: unit_id != officer current unit (transfer?)")
            for row in rows:
                print(f"  id={row.id} officer={row.officer_id} target_unit={row.target_unit} "
                      f"user_unit={row.user_unit} year={row.fiscal_year}")
        else:
            print("\n[OK] kpi_target: all active unit_ids match officer current unit")

        # =====================================================================
        # CHECK 4: achieved_ytd vs actual enrollment count
        # =====================================================================
        r = await db.execute(text("""
            SELECT t.id, t.officer_id, t.fiscal_year, t.achieved_ytd, t.annual_target,
                   COALESCE(actual.cnt, 0) AS actual_count
            FROM kpi_target t
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS cnt
                FROM lead l
                JOIN pipeline_stage ps ON l.pipeline_stage_id = ps.id
                JOIN consultation_status cs ON l.consultation_status_id = cs.id
                WHERE l.assigned_officer_id = t.officer_id
                  AND ps.is_final_stage = true
                  AND cs.counts_for_funnel = true
                  AND cs.outcome_type = 'positive'
                  AND l.deleted_at IS NULL
                  AND l.updated_at >= make_date(t.fiscal_year, 1, 1)
                  AND l.updated_at < make_date(t.fiscal_year + 1, 1, 1)
            ) actual ON true
            WHERE t.officer_id IS NOT NULL
              AND t.is_active = true
            ORDER BY t.fiscal_year, t.officer_id
        """))
        rows = r.fetchall()
        ytd_mismatches = 0
        print(f"\n--- YTD Accuracy ({len(rows)} active officer targets) ---")
        for row in rows:
            match = row.achieved_ytd == row.actual_count
            label = "OK" if match else "MISMATCH"
            if not match:
                ytd_mismatches += 1
            print(f"  officer={row.officer_id} year={row.fiscal_year}: "
                  f"ytd={row.achieved_ytd} actual={row.actual_count} "
                  f"target={row.annual_target} [{label}]")
        if ytd_mismatches:
            issues += ytd_mismatches
            print(f"  -> {ytd_mismatches} mismatch(es) — run sync to fix")

        # =====================================================================
        # CHECK 5: KPI plan unit_id consistency
        # =====================================================================
        r = await db.execute(text("""
            SELECT p.id, p.officer_id, p.unit_id AS plan_unit,
                   u.unit_id AS user_unit, p.fiscal_year
            FROM kpi_plan p
            JOIN "user" u ON p.officer_id = u.id
            WHERE p.officer_id IS NOT NULL
              AND p.is_active = true
              AND p.unit_id != u.unit_id
        """))
        rows = r.fetchall()
        if rows:
            warnings += len(rows)
            print(f"\n[WARN] {len(rows)} active kpi_plan: unit_id != officer current unit")
            for row in rows:
                print(f"  plan={row.id} officer={row.officer_id} "
                      f"plan_unit={row.plan_unit} user_unit={row.user_unit}")
        else:
            print("\n[OK] kpi_plan: all active unit_ids match officer current unit")

        # =====================================================================
        # CHECK 6: Lead pipeline distribution for officers with targets
        # =====================================================================
        r = await db.execute(text("""
            SELECT DISTINCT t.officer_id
            FROM kpi_target t
            WHERE t.officer_id IS NOT NULL AND t.is_active = true
        """))
        officer_ids = [row.officer_id for row in r.fetchall()]

        if officer_ids:
            print(f"\n--- Lead Pipeline Distribution ({len(officer_ids)} officers) ---")
            for oid in officer_ids:
                r = await db.execute(text("""
                    SELECT
                        COUNT(*) AS total,
                        COUNT(*) FILTER (WHERE ps.is_final_stage = true) AS at_final,
                        COUNT(*) FILTER (
                            WHERE ps.is_final_stage = true
                              AND cs.counts_for_funnel = true
                              AND cs.outcome_type = 'positive'
                        ) AS enrolled,
                        COUNT(*) FILTER (
                            WHERE ps.is_final_stage = true
                              AND cs.outcome_type = 'negative'
                        ) AS dropped
                    FROM lead l
                    JOIN pipeline_stage ps ON l.pipeline_stage_id = ps.id
                    JOIN consultation_status cs ON l.consultation_status_id = cs.id
                    WHERE l.assigned_officer_id = :oid AND l.deleted_at IS NULL
                """), {"oid": oid})
                row = r.fetchone()
                in_pipeline = row.total - row.at_final
                print(f"  officer={oid}: total={row.total} in_pipeline={in_pipeline} "
                      f"enrolled={row.enrolled} dropped={row.dropped}")
                if row.total > 0 and row.at_final == 0:
                    print(f"    -> NOTE: {row.total} leads but NONE at final stage")

        # =====================================================================
        # SUMMARY
        # =====================================================================
        print("\n" + "=" * 70)
        if issues == 0 and warnings == 0:
            print("RESULT: ALL CHECKS PASSED")
        else:
            parts = []
            if issues:
                parts.append(f"{issues} error(s)")
            if warnings:
                parts.append(f"{warnings} warning(s)")
            print(f"RESULT: {', '.join(parts)}")
        print("=" * 70)

        return issues


if __name__ == "__main__":
    exit_code = asyncio.run(run_audit())
    sys.exit(1 if exit_code > 0 else 0)
