# 🛠️ Architecture Refactoring Roadmap

> **Tạo ngày:** 2025-12-11  
> **Cập nhật:** 2025-12-11  
> **Dựa trên:** [Architecture Audit Report](./architecture-audit-report.md) (Score: 75/100)  
> **Mục tiêu:** Nâng điểm tuân thủ từ **75% → 90%** trong 3 sprints

---

## 🎯 Assumptions & Constraints

| Assumption | Giá trị |
|------------|--------|
| **Team Velocity** | ~15 story points/sprint (1 dev full-time, 2 tuần/sprint) |
| **Sprint Duration** | 2 tuần |
| **Feature Flag System** | Sử dụng biến môi trường hoặc config DB |
| **Rollback Strategy** | Toggle feature flags trong production nếu gặp lỗi |

---

## 📋 Tổng quan Workstreams

| Workstream | Mô tả | Effort | Priority |
|------------|-------|--------|----------|
| **WS-1** | Repository Pattern Adoption | 🔴 High (50-70h) | P0 |
| **WS-2** | Service Layer Cleanup | 🟠 Medium (20-30h) | P1 |
| **WS-3** | Database Optimization | 🟡 Low (10-15h) | P2 |
| **WS-4** | Code Quality & Standards | 🟢 Ongoing | P3 |

---

## 🔴 WS-1: Repository Pattern Adoption (P0 - Critical)

### Mục tiêu
Đưa Repository Adoption từ **45% → 85%** bằng cách migrate direct queries sang Repository.

---

### Task 1.1: Refactor `lead_service.get_lead_by_id` → Repository

> **📝 Rationale:** Chọn task này làm đầu tiên vì độ phức tạp thấp (chỉ eager loading, không có CTE/full-text search). Đây là "pattern mẫu" để team học hỏi trước khi tackle các tasks phức tạp hơn.

**Vấn đề hiện tại:**
```python
# lead_service.py (Lines 418-445)
query = (
    select(models.Lead)
    .options(
        selectinload(models.Lead.offering),
        selectinload(models.Lead.unit),
        selectinload(models.Lead.assigned_officer),
        # ... 10+ more relations
    )
    .where(models.Lead.id == lead_id)
)
result = await db.execute(query)  # ❌ Direct query in Service
```

**Solution:**

| Step | Action | File | LOC Change |
|------|--------|------|------------|
| 1.1.1 | Tạo method `LeadRepository.get_by_id_with_relations(id, relations: List[str])` | `lead_repository.py` | +50 |
| 1.1.2 | Di chuyển eager loading logic vào Repository | `lead_repository.py` | +30 |
| 1.1.3 | Refactor `lead_service.get_lead_by_id` để dùng Repo | `lead_service.py` | -80, +10 |
| 1.1.4 | Refactor `lead_service.get_lead_by_id_shallow` tương tự | `lead_service.py` | -50, +5 |
| 1.1.5 | Unit test cho Repository method mới | `test_lead_repository.py` | +100 |
| 1.1.6 | **Clean as you go:** Remove unused SQLAlchemy imports | `lead_service.py` | -1 |

**Acceptance Criteria:**
- [ ] `lead_service.py` không còn import `select` từ sqlalchemy cho get_by_id
- [ ] All existing tests pass
- [ ] Response time không tăng quá 10%
- [ ] Không còn unused imports trong file

**Estimate:** 12-16 hours

---

### Task 1.2: Refactor `user_service.get_users` → Repository

**Vấn đề hiện tại:**
```python
# user_service.py (Lines 506-618) - 112 lines of complex query building
query = select(models.User).options(...)
# ... CTE for hierarchy
# ... Full-text search
# ... Dynamic filters
# ... Pagination
```

**Solution:**

| Step | Action | File | LOC Change |
|------|--------|------|------------|
| 1.2.1 | Tạo `UserRepository.search(params: UserSearchParams)` | `user_repository.py` | +150 |
| 1.2.2 | Di chuyển CTE hierarchy query | `user_repository.py` | +40 |
| 1.2.3 | Di chuyển full-text search logic | `user_repository.py` | +30 |
| 1.2.4 | Tạo Pydantic schema `UserSearchParams` | `schemas/user.py` | +20 |
| 1.2.5 | Refactor `user_service.get_users` | `user_service.py` | -110, +15 |
| 1.2.6 | Unit tests | `test_user_repository.py` | +120 |
| 1.2.7 | **Clean as you go:** Remove unused SQLAlchemy imports | `user_service.py` | -2 |

**Acceptance Criteria:**
- [ ] `user_service.get_users` chỉ còn ~20 lines
- [ ] Search performance không giảm
- [ ] Full-text search vẫn hoạt động
- [ ] Không còn `text`, `func` imports nếu không dùng elsewhere

**Estimate:** 16-20 hours

---

### Task 1.3: Integrate `organization_repository.py`

**Vấn đề:** Repository tồn tại nhưng không được sử dụng.

> ⚠️ **Rollback Strategy:** Do file này có 1600+ lines, cần triển khai phased rollout.

| Step | Action | File | LOC Change |
|------|--------|------|------------|
| 1.3.0 | **Tạo Feature Flag** `USE_ORG_REPOSITORY` | `config.py`, `.env` | +5 |
| 1.3.1 | Audit `organization_service.py` - list direct queries | - | - |
| 1.3.2 | Map queries → Repository methods | `organization_repository.py` | +100 |
| 1.3.3 | Refactor service với feature flag toggle | `organization_service.py` | -200, +80 |
| 1.3.4 | Integration tests cho cả 2 code paths | `test_organization.py` | +100 |
| 1.3.5 | Gradual rollout: 10% → 50% → 100% traffic | - | - |
| 1.3.6 | Remove feature flag sau 1 tuần stable | `organization_service.py` | -30 |

**Estimate:** 25-30 hours (bao gồm monitoring period)

---

### Task 1.4: Standardize Repository Usage Pattern

Tạo coding guideline để đảm bảo consistency.

**Deliverables:**
- [ ] Tài liệu `docs/repository-pattern-guide.md`
- [ ] Code template cho new repositories
- [ ] PR checklist item: "Service không import `select` từ SQLAlchemy"

**Estimate:** 4-6 hours

---

### Task 1.5: Migrate Remaining Services (Phase 2)

> 📌 **Note:** Các services này nhỏ hơn, có thể gộp thành 1 task hoặc xử lý tùy priority.

| Service | LOC | Direct Queries | Priority | Estimate |
|---------|-----|----------------|----------|----------|
| `application_service.py` | 409 | ~5 functions | P1 | 8-10h |
| `pipeline_service.py` | ~1000 | ~8 functions | P1 | 12-15h |
| `admission_service.py` | ~800 | ~6 functions | P2 | 10-12h |

**Total Estimate:** 30-37 hours (có thể schedule vào Sprint 4 hoặc Phase 2)

**Acceptance Criteria:**
- [ ] Tất cả services không còn import `select` từ SQLAlchemy
- [ ] Repository coverage đạt 90%+

---

## 🟠 WS-2: Service Layer Cleanup (P1)

### ~~Task 2.1: Remove Direct SQLAlchemy Imports from Services~~

> ✅ **MERGED:** Task này đã được tích hợp vào từng task WS-1 ("Clean as you go" approach).
> Mỗi task WS-1.x giờ bao gồm bước cuối cùng là remove unused imports ngay sau khi migrate.
> Điều này đảm bảo codebase luôn sạch và không có debt tích lũy.

---

### Task 2.2: Notification Dispatch Standardization

**Vấn đề:** Một số routers vẫn có inline notification code.

| Step | Action | Files |
|------|--------|-------|
| 2.2.1 | Audit tất cả notification dispatch patterns | All routers |
| 2.2.2 | Apply helper function pattern (như `organization.py`) | `leads.py`, `applications.py` |
| 2.2.3 | Document pattern trong `notification-system-guide.md` | ✅ Done |

**Estimate:** 6-8 hours

---

## 🟡 WS-3: Database Optimization (P2)

### Task 3.1: Foreign Key Index Audit

**Script kiểm tra:**
```sql
-- Check FK columns without indexes
SELECT 
    tc.table_name, 
    kcu.column_name,
    CASE WHEN i.indexname IS NULL THEN '❌ Missing' ELSE '✅ OK' END as index_status
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu 
    ON tc.constraint_name = kcu.constraint_name
LEFT JOIN pg_indexes i 
    ON i.tablename = tc.table_name AND i.indexdef LIKE '%' || kcu.column_name || '%'
WHERE tc.constraint_type = 'FOREIGN KEY'
    AND tc.table_schema = 'public';
```

**Deliverables:**
- [ ] Script chạy trong CI/CD
- [ ] Migration để thêm missing indexes

**Estimate:** 4-6 hours

---

### Task 3.2: Query Performance Baseline

| Step | Action |
|------|--------|
| 3.2.1 | Enable PostgreSQL slow query log (> 100ms) |
| 3.2.2 | Run load test với 100 concurrent users |
| 3.2.3 | Identify top 10 slow queries |
| 3.2.4 | Create JIRA tickets cho optimization |

**Estimate:** 6-8 hours

---

## 🟢 WS-4: Code Quality & Standards (Ongoing)

### Task 4.1: PR Review Checklist

Thêm vào `.github/PULL_REQUEST_TEMPLATE.md`:

```markdown
## Architecture Compliance
- [ ] Service không import `HTTPException`
- [ ] Service không import `select` từ SQLAlchemy (sử dụng Repository)
- [ ] Router không chứa business logic
- [ ] Transaction commit chỉ ở Router level
- [ ] New endpoints có IDOR protection (nếu applicable)
```

---

### Task 4.2: Automated Linting Rules

| Rule ID | Description | Implementation |
|---------|-------------|----------------|
| ARCH-001 | Cấm `HTTPException` trong `/services/` | Semgrep rule (đơn giản hơn Ruff) |
| ARCH-002 | Cấm `db.commit()` trong `/services/` | Semgrep rule |
| ARCH-003 | Warn `from sqlalchemy import select` trong `/services/` | Semgrep rule |

> 💡 **Implementation Note:** Dùng **Semgrep** thay vì custom Ruff rules vì:
> - Semgrep rules viết bằng YAML, dễ maintain
> - Không cần biết Rust/AST như Ruff plugins
> - Có thể chạy trong CI/CD với `semgrep ci`

**Estimate:** 4-6 hours (giảm từ 8-10h nhờ Semgrep)

---

## 📈 Compliance Tracking

| Aspect | Định nghĩa |
|--------|------------|
| **Tần suất đo** | Cuối mỗi Sprint (Demo Day) |
| **Người thực hiện** | Tech Lead hoặc designated team member |
| **Công cụ** | Script audit tự động + manual review |
| **Output** | Cập nhật `architecture-audit-report.md` với scores mới |
| **CI Integration** | Chạy Semgrep rules trong PR checks |

### Audit Script (chạy thủ công hoặc trong CI):
```bash
# Check for architecture violations
grep -rn "from fastapi import.*HTTPException" app/services/ && echo "❌ ARCH-001 violated"
grep -rn "db.commit()" app/services/ && echo "❌ ARCH-002 violated"
grep -rn "from sqlalchemy import.*select" app/services/ && echo "⚠️ ARCH-003 warning"
```

---

## 📅 Sprint Planning

> **Velocity Assumption:** 1 developer full-time = ~15 story points/sprint (2 tuần)

### Sprint 1 (Tuần 1-2): Foundation

| Task | Owner | Status | Points |
|------|-------|--------|--------|
| WS-1.4: Repository Pattern Guide | - | 📋 Planned | 3 |
| WS-1.1: `lead_service.get_lead_by_id` | - | 📋 Planned | 8 |
| WS-4.1: PR Checklist | - | 📋 Planned | 2 |
| **Total** | | | **13** |

**Sprint Goal:** Establish pattern với `lead_service` làm mẫu.

---

### Sprint 2 (Tuần 3-4): Core Migration

| Task | Owner | Status | Points |
|------|-------|--------|--------|
| WS-1.2: `user_service.get_users` | - | 📋 Planned | 13 |
| WS-2.2: Notification Standardization | - | 📋 Planned | 5 |
| **Total** | | | **18** |

> ⚠️ **Capacity Warning:** 18 points là sát limit. Có thể đẩy WS-2.2 sang Sprint 3 nếu cần.

**Sprint Goal:** 2 core services hoàn thành migration.

---

### Sprint 3 (Tuần 5-6): Completion

| Task | Owner | Status | Points |
|------|-------|--------|--------|
| WS-1.3: `organization_service` | - | 📋 Planned | 15 |
| WS-3.1: FK Index Audit | - | 📋 Planned | 3 |
| **Total** | | | **18** |

**Sprint Goal:** Đạt 90% compliance score.

---

### Sprint 4 (Tuần 7-8): Phase 2 - Remaining Services

| Task | Owner | Status | Points |
|------|-------|--------|--------|
| WS-1.5a: `application_service` migration | - | 📋 Planned | 5 |
| WS-1.5b: `pipeline_service` migration | - | 📋 Planned | 8 |
| WS-4.2: Automated Linting (Semgrep) | - | 📋 Planned | 3 |
| **Total** | | | **16** |

**Sprint Goal:** Repository coverage 90%+, CI linting rules active.

> 📌 WS-3.2 (Query Performance Baseline) và `admission_service` có thể defer sang Sprint 5 tùy priority.

---

## 📊 Expected Outcome

### Điểm tuân thủ sau refactoring:

| Tiêu chí | Trước | Sau Sprint 3 | Mục tiêu |
|----------|-------|--------------|----------|
| A. Layered Architecture | 70% | 90% | ✅ |
| B. Router Rules | 98% | 98% | ✅ |
| C. Security Layer | 95% | 95% | ✅ |
| D. Service Rules | 75% | 90% | ✅ |
| E. Repository Pattern | 45% | 85% | ✅ |
| F. Models & Schemas | 90% | 92% | ✅ |
| **Tổng** | **75%** | **92%** | ✅ |

---

## 🚦 Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Breaking changes during refactor | Medium | High | Feature flags, phased rollout |
| Performance regression | Low | High | Performance baseline trước/sau |
| Team không follow pattern | Medium | Medium | Code review strict, linting rules |
| Timeline slip | Medium | Medium | Buffer 20% cho mỗi task |

---

## ✅ Definition of Done

Mỗi task được coi là hoàn thành khi:
1. Code được merge vào `main`
2. All tests pass (unit + integration)
3. Code review approved bởi ít nhất 1 senior
4. Documentation được cập nhật
5. Performance không giảm quá 10%

---

*Roadmap được tạo bởi Architecture Team - Cập nhật định kỳ mỗi Sprint.*
