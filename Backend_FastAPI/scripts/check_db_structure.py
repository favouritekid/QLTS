#!/usr/bin/env python3
"""
Database Structure Checker

A lightweight script to check database table structure directly via SQL.
Does not require SQLAlchemy models to be importable.

Usage:
    python scripts/check_db_structure.py

Outputs:
    - Table column counts
    - Column details for each finance table
    - Foreign key relationships
    - Constraint information
"""

import os
import sys
from pathlib import Path

# Try to load .env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    pass


# Finance tables to check
FINANCE_TABLES = [
    'installment_plan',
    'payment_method',
    'accounting_period',
    'processed_event',
    'fee',
    'fee_applied_discount',
    'invoice',
    'payment_intent',
    'payment',
    'payment_transaction',
    'refund_request',
    'overpayment_record',
]

# Expected column counts (from migration fin20260131001)
# Updated to match actual migration definitions
EXPECTED_COLUMN_COUNTS = {
    'installment_plan': 12,
    'payment_method': 11,      # code, name, desc, is_online, requires_verification, gateway_code, gateway_config, is_active, display_order, created_at, id
    'accounting_period': 11,   # id, period_month, period_year, is_closed, closed_at, closed_by_id, total_revenue, total_payments, total_refunds, notes, created_at
    'processed_event': 9,      # id, event_id, event_type, event_version, consumer_id, processed_at, processing_result, error_message, event_payload
    'fee': 19,                 # Added notes column
    'fee_applied_discount': 8,
    'invoice': 18,             # All columns including both user FK columns
    'payment_intent': 18,      # Full online payment tracking
    'payment': 19,
    'payment_transaction': 14,
    'refund_request': 16,      # Full refund workflow columns
    'overpayment_record': 16,
}


def get_connection():
    """Get database connection."""
    database_url = os.getenv("DATABASE_URL", "")

    if not database_url:
        print("❌ DATABASE_URL not set")
        sys.exit(1)

    # Parse URL
    # Format: postgresql+asyncpg://user:pass@host:port/dbname
    import re
    match = re.match(
        r'postgresql(?:\+\w+)?://([^:]+):([^@]+)@([^:]+):(\d+)/(.+)',
        database_url
    )

    if not match:
        print(f"❌ Cannot parse DATABASE_URL: {database_url[:50]}...")
        sys.exit(1)

    user, password, host, port, dbname = match.groups()

    try:
        import psycopg2
        conn = psycopg2.connect(
            host=host,
            port=int(port),
            dbname=dbname,
            user=user,
            password=password
        )
        return conn
    except ImportError:
        print("❌ psycopg2 not installed. Run: pip install psycopg2-binary")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        sys.exit(1)


def check_tables(conn):
    """Check which finance tables exist."""
    print("=" * 70)
    print("DATABASE STRUCTURE CHECK")
    print("=" * 70)

    cursor = conn.cursor()

    # Get all tables
    cursor.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
    """)
    all_tables = {row[0] for row in cursor.fetchall()}

    print(f"\n📊 Total tables in database: {len(all_tables)}")

    # Check finance tables
    print("\n📋 Finance Tables Status:")
    print("-" * 50)

    existing = []
    missing = []

    for table in FINANCE_TABLES:
        if table in all_tables:
            existing.append(table)
            print(f"  ✅ {table}")
        else:
            missing.append(table)
            print(f"  ❌ {table} - NOT FOUND")

    if missing:
        print(f"\n⚠️  Missing {len(missing)} tables: {missing}")
    else:
        print(f"\n✅ All {len(FINANCE_TABLES)} finance tables exist")

    return existing


def check_columns(conn, tables):
    """Check column structure for each table."""
    print("\n" + "=" * 70)
    print("TABLE COLUMN DETAILS")
    print("=" * 70)

    cursor = conn.cursor()

    for table in tables:
        # Get columns
        cursor.execute("""
            SELECT
                column_name,
                data_type,
                is_nullable,
                column_default,
                character_maximum_length
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position
        """, (table,))

        columns = cursor.fetchall()
        expected_count = EXPECTED_COLUMN_COUNTS.get(table, '?')
        actual_count = len(columns)

        status = "✅" if actual_count == expected_count else "⚠️"
        print(f"\n{status} {table.upper()} ({actual_count} columns, expected {expected_count})")
        print("-" * 50)

        for col in columns:
            name, dtype, nullable, default, max_len = col
            nullable_str = "NULL" if nullable == 'YES' else "NOT NULL"

            # Format type
            if max_len:
                type_str = f"{dtype}({max_len})"
            else:
                type_str = dtype

            # Format default
            default_str = ""
            if default:
                if len(str(default)) > 30:
                    default_str = f" DEFAULT {str(default)[:27]}..."
                else:
                    default_str = f" DEFAULT {default}"

            print(f"    {name:30} {type_str:20} {nullable_str}{default_str}")


def check_foreign_keys(conn, tables):
    """Check foreign key relationships."""
    print("\n" + "=" * 70)
    print("FOREIGN KEY RELATIONSHIPS")
    print("=" * 70)

    cursor = conn.cursor()

    for table in tables:
        cursor.execute("""
            SELECT
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
                AND tc.table_name = %s
        """, (table,))

        fks = cursor.fetchall()

        if fks:
            print(f"\n{table}:")
            for fk in fks:
                col, ref_table, ref_col = fk
                print(f"    {col} → {ref_table}.{ref_col}")


def check_constraints(conn, tables):
    """Check unique and check constraints."""
    print("\n" + "=" * 70)
    print("CONSTRAINTS")
    print("=" * 70)

    cursor = conn.cursor()

    for table in tables:
        # Unique constraints
        cursor.execute("""
            SELECT
                tc.constraint_name,
                string_agg(kcu.column_name, ', ' ORDER BY kcu.ordinal_position)
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
            WHERE tc.table_name = %s
                AND tc.constraint_type = 'UNIQUE'
            GROUP BY tc.constraint_name
        """, (table,))

        unique_constraints = cursor.fetchall()

        # Check constraints
        cursor.execute("""
            SELECT
                constraint_name,
                check_clause
            FROM information_schema.check_constraints
            WHERE constraint_name LIKE %s
        """, (f'{table}%',))

        check_constraints = cursor.fetchall()

        if unique_constraints or check_constraints:
            print(f"\n{table}:")

            for uc in unique_constraints:
                print(f"    UNIQUE ({uc[1]})")

            for cc in check_constraints:
                # Clean up check clause display
                clause = cc[1]
                if len(clause) > 60:
                    clause = clause[:57] + "..."
                print(f"    CHECK: {clause}")


def check_indexes(conn, tables):
    """Check indexes."""
    print("\n" + "=" * 70)
    print("INDEXES")
    print("=" * 70)

    cursor = conn.cursor()

    for table in tables:
        cursor.execute("""
            SELECT
                indexname,
                indexdef
            FROM pg_indexes
            WHERE tablename = %s
                AND indexname NOT LIKE '%%_pkey'
            ORDER BY indexname
        """, (table,))

        indexes = cursor.fetchall()

        if indexes:
            print(f"\n{table}:")
            for idx in indexes:
                # Extract just the column part
                idx_def = idx[1]
                if 'USING' in idx_def:
                    cols_part = idx_def.split('(')[1].rstrip(')')
                    print(f"    {idx[0]}: ({cols_part})")


def generate_summary(conn, tables):
    """Generate summary table."""
    print("\n" + "=" * 70)
    print("SUMMARY TABLE")
    print("=" * 70)

    cursor = conn.cursor()

    print(f"\n{'Table':<25} {'Columns':>8} {'Expected':>10} {'Status':>8}")
    print("-" * 55)

    all_match = True

    for table in tables:
        cursor.execute("""
            SELECT COUNT(*)
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
        """, (table,))

        actual = cursor.fetchone()[0]
        expected = EXPECTED_COLUMN_COUNTS.get(table, actual)
        status = "✅" if actual == expected else "❌"

        if actual != expected:
            all_match = False

        print(f"{table:<25} {actual:>8} {expected:>10} {status:>8}")

    print("-" * 55)

    if all_match:
        print("✅ All tables match expected column counts")
    else:
        print("❌ Some tables have unexpected column counts")


def main():
    """Main entry point."""
    conn = get_connection()

    try:
        existing_tables = check_tables(conn)

        if existing_tables:
            check_columns(conn, existing_tables)
            check_foreign_keys(conn, existing_tables)
            check_constraints(conn, existing_tables)
            check_indexes(conn, existing_tables)
            generate_summary(conn, existing_tables)

        print("\n" + "=" * 70)
        print("CHECK COMPLETE")
        print("=" * 70)

    finally:
        conn.close()


if __name__ == "__main__":
    main()
