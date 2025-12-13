# FK Index Audit Script

> **Purpose:** Find foreign key columns missing indexes  
> **Run in:** PostgreSQL

---

## Query: Find FK columns without indexes

```sql
SELECT 
    tc.table_name AS "Table",
    kcu.column_name AS "FK Column",
    ccu.table_name AS "References Table",
    CASE 
        WHEN idx.indexname IS NULL THEN '❌ MISSING INDEX'
        ELSE '✅ ' || idx.indexname
    END AS "Index Status"
FROM 
    information_schema.table_constraints AS tc 
    JOIN information_schema.key_column_usage AS kcu
        ON tc.constraint_name = kcu.constraint_name
    JOIN information_schema.constraint_column_usage AS ccu
        ON ccu.constraint_name = tc.constraint_name
    LEFT JOIN (
        SELECT 
            t.relname AS tablename,
            i.relname AS indexname,
            a.attname AS column_name
        FROM 
            pg_catalog.pg_class t
            JOIN pg_catalog.pg_index ix ON t.oid = ix.indrelid
            JOIN pg_catalog.pg_class i ON i.oid = ix.indexrelid
            JOIN pg_catalog.pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
        WHERE t.relkind = 'r'
    ) idx ON idx.tablename = tc.table_name AND idx.column_name = kcu.column_name
WHERE 
    tc.constraint_type = 'FOREIGN KEY'
    AND tc.table_schema = 'public'
ORDER BY "Index Status" DESC, tc.table_name;
```

---

## High Priority FKs to Check

| Table | FK Column | Referenced |
|-------|-----------|------------|
| lead | assigned_officer_id | users.id |
| lead | unit_id | organization_unit.id |
| lead | offering_id | program_offering.id |
| lead | pipeline_stage_id | pipeline_stage.id |
| application | lead_id | lead.id |
| consultation | lead_id | lead.id |
| consultation | officer_id | users.id |

---

## Create Missing Indexes Template

```sql
-- Use CONCURRENTLY to avoid locking in production
CREATE INDEX CONCURRENTLY idx_lead_assigned_officer_id ON lead(assigned_officer_id);
CREATE INDEX CONCURRENTLY idx_lead_unit_id ON lead(unit_id);
CREATE INDEX CONCURRENTLY idx_application_lead_id ON application(lead_id);
CREATE INDEX CONCURRENTLY idx_consultation_lead_id ON consultation(lead_id);
```
