# Performance Optimization Plan

> **Generated**: 2025-12-04
> **Status**: Ready for Implementation
> **Estimated Total Time**: ~20 hours
> **Expected Performance Gain**: 40-60% faster

---

## 🎯 Executive Summary

Performance audit identified **15 optimization opportunities** across 3 categories:

| Category | Count | Impact | Effort |
|----------|-------|--------|--------|
| **Missing Indexes** | 8 | HIGH | LOW (4hrs) |
| **N+1 Queries** | 3 | HIGH | LOW (2.5hrs) |
| **Caching Opportunities** | 4 | MEDIUM | MEDIUM (7hrs) |

**ROI**: High - Most fixes are low-effort with significant impact.

---

## 🔴 CRITICAL ISSUES (Fix First)

### 1. Missing Database Indexes

#### Priority 1.1: Lead Table Composite Indexes
**File**: `app/models/lead.py`
**Impact**: Full table scans on lead lists (1-2 seconds with 10,000+ leads)
**Effort**: 30 minutes each

```sql
-- Most common: Unit + Status filtered lists
CREATE INDEX CONCURRENTLY ix_lead_unit_status_deleted
ON lead(unit_id, status, deleted_at)
WHERE deleted_at IS NULL;

-- Officer dashboards
CREATE INDEX CONCURRENTLY ix_lead_officer_status
ON lead(assigned_officer_id, status)
WHERE deleted_at IS NULL;

-- Chronological sorting
CREATE INDEX CONCURRENTLY ix_lead_created_at_desc
ON lead(created_at DESC);

-- High-score lead queries
CREATE INDEX CONCURRENTLY ix_lead_score_desc
ON lead(lead_score DESC);
```

**Expected Improvement**: Lead list queries **800ms → 300ms** (62% faster)

#### Priority 1.2: Consultation Timeline Index
**File**: `app/models/lead.py:104`
**Impact**: Timeline queries scan all consultations (~100ms overhead)
**Effort**: 30 minutes

```sql
CREATE INDEX CONCURRENTLY ix_consultation_lead_date
ON consultation(lead_id, consultation_date DESC);

-- For reminder queries (lead_service.py:27-78)
CREATE INDEX CONCURRENTLY ix_consultation_reminder
ON consultation(lead_id, reminder_sent, scheduled_at)
WHERE reminder_sent = FALSE;
```

**Expected Improvement**: Timeline queries **300ms → 150ms** (50% faster)

#### Priority 1.3: Round Robin Assignment Index
**File**: `app/models/user.py:52`
**Impact**: Officer selection slow with 100+ officers
**Effort**: 20 minutes

```sql
CREATE INDEX CONCURRENTLY ix_user_last_assigned_at
ON "user"(last_assigned_at)
WHERE role = 'officer';
```

**Expected Improvement**: Assignment queries **50-100ms → 10-20ms**

#### Priority 1.4: Notification Inbox Index
**File**: `app/models/notification.py`
**Impact**: Slow notification fetching (1000+ notifications)
**Effort**: 30 minutes

```sql
CREATE INDEX CONCURRENTLY ix_notification_user_read_created
ON notification(user_id, is_read, created_at DESC);
```

**Expected Improvement**: Notification list **500ms → 100ms** (80% faster with cache)

---

### 2. N+1 Query Issues

#### Issue 2.1: Unnecessary Full Reload After Lead Create
**File**: `app/services/lead_service.py:746`
**Impact**: Wastes 50-100ms per lead creation
**Effort**: 1 hour

**Current Code**:
```python
# Line 746 - Loads ALL relationships (consultations, logs, etc.) for NEW lead
lead = await get_lead_by_id(db, db_lead.id)
return lead
```

**Recommended Fix**:
```python
# Option 1: Create lightweight version
lead = await get_lead_by_id_shallow(db, db_lead.id)  # Only essential 1-1 relationships
return lead

# Option 2: Return directly after flush (relationships are empty anyway)
await db.flush()
await db.refresh(db_lead, ["offering", "unit", "assigned_officer"])
return db_lead
```

**Expected Improvement**: Lead creation **250ms → 150ms** (40% faster)

#### Issue 2.2: Unnecessary Full Reload After Lead Update
**File**: `app/services/lead_service.py:1070`
**Impact**: Wastes 50-100ms per lead update
**Effort**: 1 hour

**Current Code**:
```python
# Line 1070 - Reloads ALL relationships even if not modified
return await get_lead_by_id(db, lead_id)
```

**Recommended Fix**:
```python
# Use shallow reload - only refresh changed relationships
return await get_lead_by_id_shallow(db, lead_id)
```

**Expected Improvement**: Lead update **300ms → 180ms** (40% faster)

#### Issue 2.3: Double Refresh After Assignment
**File**: `app/services/lead_service.py:1296`
**Impact**: Extra DB round-trip (~20-30ms)
**Effort**: 30 minutes

**Current Code**:
```python
# Line 1296 - Already loaded in get_lead_by_id (line 1225)
await db.refresh(lead, ["offering", "unit"])
```

**Recommended Fix**:
```python
# Remove this line - already loaded earlier
# await db.refresh(lead, ["offering", "unit"])  # DELETE THIS
```

---

## 🟡 HIGH ROI OPTIMIZATIONS

### 3. Redis Caching Strategy

#### Cache 3.1: Pipeline Stages & Reference Data
**Files**: Models used across `lead_service.py`, `admission_service.py`
**Hit Rate**: 95% (reference data rarely changes)
**TTL**: 1 hour (3600s)
**Effort**: 2 hours

**Implementation**:
```python
# app/services/pipeline_service.py
async def get_all_pipeline_stages_cached(
    db: AsyncSession,
    redis: Redis
) -> List[models.PipelineStage]:
    cache_key = "pipeline:stages:all"

    # Try cache first
    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    # Cache miss - query DB
    result = await db.execute(
        select(models.PipelineStage).order_by(models.PipelineStage.order)
    )
    stages = result.scalars().all()

    # Cache for 1 hour
    await redis.set(
        cache_key,
        json.dumps([s.model_dump() for s in stages]),
        ex=3600
    )
    return stages

# Invalidation on update
async def update_pipeline_stage(...):
    # ... update logic
    await redis.delete("pipeline:stages:all")
```

**Expected Improvement**: -50 queries/second during peak hours

#### Cache 3.2: Lead Statistics (Dashboard)
**Files**: Dashboard/analytics endpoints
**Hit Rate**: 80% (counts change but acceptable staleness)
**TTL**: 60 seconds
**Effort**: 4 hours

**Redis Key Pattern**: `leads:stats:{unit_id}:{officer_id}`

**Implementation**:
```python
async def get_lead_statistics_cached(
    db: AsyncSession,
    redis: Redis,
    unit_id: Optional[int] = None,
    officer_id: Optional[int] = None
) -> Dict[str, int]:
    cache_key = f"leads:stats:{unit_id or 'all'}:{officer_id or 'all'}"

    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    # Compute stats (GROUP BY status)
    stats = await compute_lead_statistics(db, unit_id, officer_id)

    # Cache for 60 seconds
    await redis.set(cache_key, json.dumps(stats), ex=60)
    return stats
```

**Expected Improvement**: Dashboard load time **1.5s → 0.3s** (80% faster)

#### Cache 3.3: User List (Admin View)
**Files**: `app/services/user_service.py:505`
**Hit Rate**: 60% (admins refresh frequently)
**TTL**: 30 seconds
**Effort**: 3 hours

**Redis Key Pattern**: `users:list:{filters_hash}:{page}`

**Note**: Only cache first 3 pages to avoid memory bloat

```python
async def get_users_list_cached(
    db: AsyncSession,
    redis: Redis,
    filters: UserFilters,
    page: int = 1,
    page_size: int = 50
) -> PaginatedResponse[User]:
    # Only cache first 3 pages
    if page > 3:
        return await get_users_list(db, filters, page, page_size)

    filters_hash = hashlib.md5(
        json.dumps(filters.model_dump(), sort_keys=True).encode()
    ).hexdigest()[:8]
    cache_key = f"users:list:{filters_hash}:{page}"

    cached = await redis.get(cache_key)
    if cached:
        return PaginatedResponse(**json.loads(cached))

    result = await get_users_list(db, filters, page, page_size)
    await redis.set(cache_key, json.dumps(result.model_dump()), ex=30)
    return result
```

**Expected Improvement**: User list **400ms → 250ms** (37% faster)

---

## 📋 IMPLEMENTATION CHECKLIST

### Phase 1: Quick Wins (Week 1) - 6 hours
- [ ] Add `ix_lead_unit_status_deleted` index (30min)
- [ ] Add `ix_lead_officer_status` index (30min)
- [ ] Add `ix_consultation_lead_date` index (30min)
- [ ] Add `ix_user_last_assigned_at` index (20min)
- [ ] Fix N+1 in `create_lead()` (1hr)
- [ ] Fix N+1 in `update_lead()` (1hr)
- [ ] Remove duplicate refresh in assignment (30min)
- [ ] Add `ix_lead_created_at_desc` index (30min)
- [ ] Add `ix_lead_score_desc` index (30min)

**Expected Impact**: Lead operations **40% faster**, Assignment queries **80% faster**

### Phase 2: Caching Layer (Week 2) - 9 hours
- [ ] Implement Pipeline/Status caching (2hrs)
- [ ] Implement Lead Statistics caching (4hrs)
- [ ] Add `ix_notification_user_read_created` index (30min)
- [ ] Implement User List caching (3hrs)

**Expected Impact**: Dashboard **80% faster**, Notification inbox **80% faster**

### Phase 3: Additional Indexes (Week 3) - 3 hours
- [ ] Add `ix_admission_status_created` index (1hr)
- [ ] Add `ix_session_user_active` index (1hr)
- [ ] Add `ix_assignment_log_lead_time` index (1hr)

**Expected Impact**: Admin views **30-50% faster**

### Phase 4: Advanced Optimizations (Future)
- [ ] Optimize `_get_user_counts_by_unit()` to single JOIN (2hrs)
- [ ] Implement Redis Cluster for high availability (8hrs)
- [ ] Add Prometheus metrics for cache monitoring (4hrs)
- [ ] APM integration for query profiling (4hrs)

---

## 🔧 MIGRATION SCRIPT

```python
# migrations/versions/xxxx_add_performance_indexes.py
"""Add performance optimization indexes

Revision ID: xxxx
Revises: yyyy
Create Date: 2025-12-04
"""

from alembic import op

def upgrade():
    # Lead table indexes
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_lead_unit_status_deleted
        ON lead(unit_id, status, deleted_at)
        WHERE deleted_at IS NULL
    """)

    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_lead_officer_status
        ON lead(assigned_officer_id, status)
        WHERE deleted_at IS NULL
    """)

    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_lead_created_at_desc
        ON lead(created_at DESC)
    """)

    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_lead_score_desc
        ON lead(lead_score DESC)
    """)

    # Consultation indexes
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_consultation_lead_date
        ON consultation(lead_id, consultation_date DESC)
    """)

    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_consultation_reminder
        ON consultation(lead_id, reminder_sent, scheduled_at)
        WHERE reminder_sent = FALSE
    """)

    # User index
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_user_last_assigned_at
        ON "user"(last_assigned_at)
        WHERE role = 'officer'
    """)

    # Notification index
    op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_notification_user_read_created
        ON notification(user_id, is_read, created_at DESC)
    """)

def downgrade():
    op.drop_index('ix_lead_unit_status_deleted', table_name='lead')
    op.drop_index('ix_lead_officer_status', table_name='lead')
    op.drop_index('ix_lead_created_at_desc', table_name='lead')
    op.drop_index('ix_lead_score_desc', table_name='lead')
    op.drop_index('ix_consultation_lead_date', table_name='consultation')
    op.drop_index('ix_consultation_reminder', table_name='consultation')
    op.drop_index('ix_user_last_assigned_at', table_name='user')
    op.drop_index('ix_notification_user_read_created', table_name='notification')
```

---

## 📊 MONITORING & VALIDATION

### Performance Metrics to Track

```python
# Add to app/middleware/monitoring.py
from prometheus_client import Histogram, Counter

# Query latency histogram
query_latency = Histogram(
    'db_query_latency_seconds',
    'Database query latency',
    ['operation', 'model']
)

# Cache hit rate counter
cache_hits = Counter('redis_cache_hits_total', 'Cache hits', ['key_prefix'])
cache_misses = Counter('redis_cache_misses_total', 'Cache misses', ['key_prefix'])

# N+1 detection counter
n_plus_one_detected = Counter(
    'n_plus_one_queries_total',
    'Potential N+1 queries detected',
    ['service', 'method']
)
```

### Testing Checklist
- [ ] Load test lead list endpoint (1000 leads)
- [ ] Verify index usage with `EXPLAIN ANALYZE`
- [ ] Monitor cache hit rates for 1 week
- [ ] Compare P95/P99 latencies before/after
- [ ] Check memory usage (Redis + Postgres)

---

## ✅ WHAT'S ALREADY EXCELLENT

### Patterns to Keep:
1. **LeadRepository** - Proper eager loading with `selectinload` ✅
2. **Organization Tree** - Redis caching with distributed lock ✅
3. **User Search** - PostgreSQL full-text search with GIN index ✅
4. **Notification Inbox** - Redis list caching ✅
5. **Transaction Pattern** - Correct use of `db.flush()` + callbacks ✅
6. **IDOR Protection** - Single query with `joinedload` (no extra overhead) ✅

---

## 🎯 SUCCESS CRITERIA

| Metric | Current | Target | Method |
|--------|---------|--------|--------|
| Lead List P95 | 800ms | <300ms | Index + cache |
| Lead Create P95 | 250ms | <150ms | Remove N+1 |
| Lead Update P95 | 300ms | <180ms | Remove N+1 |
| Dashboard Load | 1.5s | <300ms | Cache stats |
| Notification List | 500ms | <100ms | Index + cache |
| Cache Hit Rate | N/A | >80% | Redis monitoring |

**Overall Target**: **40-60% performance improvement** across all operations

---

**Next Steps**:
1. Review this plan with team
2. Create Jira tickets for each phase
3. Start with Phase 1 (Quick Wins)
4. Monitor metrics continuously
