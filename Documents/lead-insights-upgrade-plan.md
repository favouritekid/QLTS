# Kế hoạch Nâng cấp Lead Insights & Data Visualization

**Ngày tạo:** 2024-12-13  
**Phiên bản:** 2.0 (REVISED)  
**Người tạo:** AI Assistant  
**Cập nhật:** Đã tích hợp góp ý từ `lead-insights-upgrade-plan-supplement.md`

---

## 📋 Mục lục

1. [Tổng quan](#1-tổng-quan)
2. [Phân tích hiện trạng](#2-phân-tích-hiện-trạng)
3. [Yêu cầu nâng cấp](#3-yêu-cầu-nâng-cấp)
4. [Thiết kế kỹ thuật](#4-thiết-kế-kỹ-thuật)
5. [Kế hoạch triển khai](#5-kế-hoạch-triển-khai)
6. [Rủi ro và giải pháp](#6-rủi-ro-và-giải-pháp)

---

## 1. Tổng quan

### 1.1 Mục tiêu
Nâng cấp hệ thống Lead Insights để cung cấp các chỉ số chính xác hơn cho officer, đồng thời expose các metrics quan trọng ra DataTable giúp officer ưu tiên công việc hiệu quả.

### 1.2 Phạm vi
- **Backend:** Nâng cấp `insights_service.py`, thêm fields mới vào Lead model
- **Frontend:** Cập nhật `LeadsTable.tsx`, `LeadDetailPanel.tsx`
- **Database:** Migration thêm cached fields

### 1.3 Kết quả mong đợi
- Officer có thể nhanh chóng nhận biết lead nào cần ưu tiên liên hệ
- Giảm thời gian phân tích thủ công
- Tăng tỷ lệ follow-up đúng hạn

---

## 2. Phân tích hiện trạng

### 2.1 Lead Insights hiện tại

| Chỉ số | Cách tính | Vấn đề |
|--------|-----------|--------|
| **Engagement Score** | Consultation count, method, duration, inactivity | ✅ Đã tốt |
| **Fit Score** | Source, GPA, education, location | ✅ Đã tốt |
| **Urgency Score** | Stage order, transition speed | ⚠️ Thiếu nhiều yếu tố |
| **Overall Score** | Weighted average | ✅ Đã tốt |

### 2.2 Các yếu tố thiếu trong Urgency Score

| Yếu tố | Hiện trạng | Ảnh hưởng |
|--------|------------|-----------|
| `next_activity_at` overdue | ❌ Chưa dùng | Không biết lead nào quá hạn |
| Lead Score bonus | ❌ Chưa dùng | Hot lead không được ưu tiên |
| Consultation count = 0 | ❌ Chưa dùng | Lead mới không được highlight |
| Final stage penalty | ❌ Logic ngược | Converted lead vẫn urgent |

### 2.3 ActivityIndicator hiện tại

**Vấn đề:** Đang dùng `created_at` thay vì `last_consultation_at`

```
Hiện tại:  Tính từ ngày TẠO lead
Cần đổi:   Tính từ ngày TƯ VẤN CUỐI
```

---

## 3. Yêu cầu nâng cấp

### 3.1 Backend Requirements

#### 3.1.1 Thêm cached fields vào Lead model

```python
# app/models/lead.py - Thêm mới
class Lead(Base):
    # ... existing fields
    
    # Cached metrics (updated on consultation change)
    last_consultation_at = Column(DateTime, nullable=True, index=True)
    consultation_count = Column(Integer, default=0)
    cached_urgency_score = Column(Integer, default=50)
    
    # Computed flags
    is_hot_lead = Column(Boolean, default=False)  # lead_score >= 70
    is_overdue = Column(Boolean, default=False)   # next_activity_at < now
```

#### 3.1.2 Nâng cấp Urgency Score calculation

```python
# Công thức mới
URGENCY = (
    30                                    # Base
    + min(days_since_contact × 3, 45)     # Inactivity (max +45)
    + (lead_score >= 70 ? +15 : 0)        # Hot bonus
    + (consultation_count == 0 ? +25 : 0) # Never contacted
    + min(overdue_days × 5, 30)           # Overdue (max +30)
    - (is_final_stage ? -50 : 0)          # Final stage
)
```

#### 3.1.3 Trigger update cached fields

Cập nhật khi:
- Tạo/Xóa/Sửa Consultation
- Cập nhật `next_activity_at`
- Cập nhật `lead_score`
- Chuyển pipeline stage

### 3.2 Frontend Requirements

#### 3.2.1 DataTable columns mới

| Cột | Source | Visual |
|-----|--------|--------|
| Urgency | `cached_urgency_score` | Color-coded badge |
| Hot Lead | `is_hot_lead` | 🔥 icon on Lead Score |
| Activity | `last_consultation_at` | ActivityIndicator |

#### 3.2.2 Lead Insights Panel upgrade

- Thêm Urgency Breakdown section
- Thêm Priority Indicators section
- Hiển thị Activity Metrics

---

## 4. Thiết kế kỹ thuật

### 4.1 Database Schema Changes

```sql
-- Migration: add_lead_insights_cache_fields

ALTER TABLE lead ADD COLUMN last_consultation_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE lead ADD COLUMN consultation_count INTEGER DEFAULT 0;
ALTER TABLE lead ADD COLUMN cached_urgency_score INTEGER DEFAULT 50;
ALTER TABLE lead ADD COLUMN is_hot_lead BOOLEAN DEFAULT FALSE;
ALTER TABLE lead ADD COLUMN is_overdue BOOLEAN DEFAULT FALSE;

-- Index for sorting/filtering
CREATE INDEX idx_lead_urgency_score ON lead(cached_urgency_score DESC);
CREATE INDEX idx_lead_last_consultation ON lead(last_consultation_at DESC);
CREATE INDEX idx_lead_is_overdue ON lead(is_overdue) WHERE is_overdue = TRUE;
```

### 4.2 API Response Changes

```typescript
// types/lead.types.ts - Thêm fields
interface Lead {
  // ... existing fields
  
  // New cached metrics
  last_consultation_at?: string | null;
  consultation_count: number;
  cached_urgency_score: number;
  is_hot_lead: boolean;
  is_overdue: boolean;
}
```

### 4.3 Urgency Score Calculation

```python
# app/services/insights_service.py

def calculate_urgency_score(
    days_since_contact: int,
    lead_score: int,
    consultation_count: int,
    overdue_days: int,
    is_final_stage: bool
) -> int:
    """
    Calculate Urgency Score (0-100)
    
    Components:
    - Base: 30
    - Inactivity: days × 3 (max 45)
    - Hot Lead: +15 if score >= 70
    - Never Contacted: +25 if count = 0
    - Overdue: days × 5 (max 30)
    - Final Stage: -50
    """
    score = 30  # Base
    
    # Inactivity penalty
    score += min(days_since_contact * 3, 45)
    
    # Hot lead bonus
    if lead_score >= 70:
        score += 15
    
    # Never contacted penalty
    if consultation_count == 0:
        score += 25
    
    # Overdue penalty
    if overdue_days > 0:
        score += min(overdue_days * 5, 30)
    
    # Final stage reduction
    if is_final_stage:
        score -= 50
    
    return max(0, min(score, 100))
```

### 4.4 Cache Update Service

```python
# app/services/lead_cache_service.py

async def update_lead_cache(db: AsyncSession, lead_id: int) -> None:
    """
    Update cached fields for a lead.
    Called after consultation changes or scheduled updates.
    """
    lead = await db.get(Lead, lead_id)
    if not lead:
        return
    
    # 1. Update last_consultation_at and count
    result = await db.execute(
        select(
            func.max(Consultation.consultation_date),
            func.count(Consultation.id)
        ).where(Consultation.lead_id == lead_id)
    )
    row = result.one()
    lead.last_consultation_at = row[0]
    lead.consultation_count = row[1] or 0
    
    # 2. Calculate days since contact
    now = datetime.now(timezone.utc)
    if lead.last_consultation_at:
        days_since = (now - lead.last_consultation_at).days
    else:
        days_since = (now - lead.created_at).days
    
    # 3. Calculate overdue days
    overdue_days = 0
    if lead.next_activity_at and lead.next_activity_at < now:
        overdue_days = (now - lead.next_activity_at).days
    
    # 4. Check final stage
    is_final = False
    if lead.pipeline_stage:
        is_final = lead.pipeline_stage.is_final
    
    # 5. Calculate urgency score
    lead.cached_urgency_score = calculate_urgency_score(
        days_since_contact=days_since,
        lead_score=lead.lead_score or 0,
        consultation_count=lead.consultation_count,
        overdue_days=overdue_days,
        is_final_stage=is_final
    )
    
    # 6. Update flags
    lead.is_hot_lead = (lead.lead_score or 0) >= 70
    lead.is_overdue = overdue_days > 0
    
    await db.commit()
```

### 4.5 Frontend Components

#### UrgencyBadge Component

```tsx
// components/common/UrgencyBadge.tsx

interface UrgencyBadgeProps {
  score: number;
  showLabel?: boolean;
}

const URGENCY_LEVELS = {
  urgent: { min: 80, color: 'red', label: 'URGENT' },
  high:   { min: 60, color: 'yellow', label: 'HIGH' },
  medium: { min: 40, color: 'blue', label: 'MEDIUM' },
  normal: { min: 20, color: 'green', label: 'NORMAL' },
  done:   { min: 0,  color: 'gray', label: 'DONE' },
};

export function UrgencyBadge({ score, showLabel = true }: UrgencyBadgeProps) {
  const level = getUrgencyLevel(score);
  
  return (
    <div className="flex items-center gap-1.5">
      <div className={`h-2 w-2 rounded-full bg-${level.color}-500`} />
      <span className={`text-xs font-medium text-${level.color}-600`}>
        {score}
      </span>
      {showLabel && (
        <span className="text-[10px] text-muted-foreground">
          {level.label}
        </span>
      )}
    </div>
  );
}
```

---

## 5. Kế hoạch triển khai

### 5.1 Timeline

```
Phase 1: Backend (2-3 giờ)
├── Step 1.1: Database migration
├── Step 1.2: Update Lead model
├── Step 1.3: Create cache update service
├── Step 1.4: Update consultation service triggers
└── Step 1.5: Backfill existing data

Phase 2: API (1 giờ)
├── Step 2.1: Update Lead schema
├── Step 2.2: Include new fields in responses
└── Step 2.3: Add sorting by urgency_score

Phase 3: Frontend (2-3 giờ)
├── Step 3.1: Update Lead types
├── Step 3.2: Create UrgencyBadge component
├── Step 3.3: Update LeadsTable columns
├── Step 3.4: Update ActivityIndicator
└── Step 3.5: Upgrade Lead Insights Panel

Phase 4: Testing & Deploy (1-2 giờ)
├── Step 4.1: Unit tests
├── Step 4.2: Integration tests
├── Step 4.3: Manual QA
└── Step 4.4: Deploy
```

### 5.2 Chi tiết từng bước

#### Phase 1: Backend

| Step | Task | File | Est. Time |
|------|------|------|-----------|
| 1.1 | Tạo migration | `alembic/versions/xxx_add_lead_cache_fields.py` | 15 min |
| 1.2 | Update Lead model | `app/models/lead.py` | 15 min |
| 1.3 | Create cache service | `app/services/lead_cache_service.py` | 45 min |
| 1.4 | Update triggers | `app/services/consultation_service.py` | 30 min |
| 1.5 | Backfill script | `scripts/backfill_lead_cache.py` | 30 min |

#### Phase 2: API

| Step | Task | File | Est. Time |
|------|------|------|-----------|
| 2.1 | Update schema | `app/schemas/lead.py` | 15 min |
| 2.2 | Update response | `app/routers/leads.py` | 15 min |
| 2.3 | Add sorting | `app/services/lead_service.py` | 30 min |

#### Phase 3: Frontend

| Step | Task | File | Est. Time |
|------|------|------|-----------|
| 3.1 | Update types | `types/lead.types.ts` | 10 min |
| 3.2 | UrgencyBadge | `components/common/UrgencyBadge.tsx` | 30 min |
| 3.3 | Update table | `components/leads/command-center/LeadsTable.tsx` | 45 min |
| 3.4 | ActivityIndicator | `components/common/ActivityIndicator.tsx` | 15 min |
| 3.5 | Insights Panel | `components/leads/command-center/LeadDetailPanel.tsx` | 45 min |

#### Phase 4: Testing

| Step | Task | Est. Time |
|------|------|-----------|
| 4.1 | Unit tests | 30 min |
| 4.2 | Integration tests | 30 min |
| 4.3 | Manual QA | 30 min |
| 4.4 | Deploy | 15 min |

### 5.3 Tổng thời gian ước tính

| Phase | Time |
|-------|------|
| Phase 1: Backend | 2.5 giờ |
| Phase 2: API | 1 giờ |
| Phase 3: Frontend | 2.5 giờ |
| Phase 4: Testing | 2 giờ |
| **TOTAL** | **~8 giờ** |

---

## 6. Rủi ro và giải pháp

### 6.1 Rủi ro kỹ thuật

| Rủi ro | Xác suất | Ảnh hưởng | Giải pháp |
|--------|----------|-----------|-----------|
| Migration fail | Thấp | Cao | Backup DB trước, test staging |
| Cache không đồng bộ | Trung bình | Trung bình | Cron job recalculate hàng đêm |
| Performance chậm | Thấp | Cao | Index đúng, lazy load |

### 6.2 Rủi ro kinh doanh

| Rủi ro | Giải pháp |
|--------|-----------|
| Officer không hiểu Urgency Score | Training + tooltips giải thích |
| Công thức không phù hợp thực tế | Config trọng số có thể chỉnh |

### 6.3 Kế hoạch rollback

```
1. Nếu migration fail:
   → alembic downgrade -1

2. Nếu cache không chính xác:
   → Chạy lại backfill script

3. Nếu frontend lỗi:
   → Revert git commit, redeploy
```

---

## 📎 Phụ lục

### A. Urgency Score Lookup Table

| Days Since | Score = 50 | Score = 70 | Score = 80 |
|------------|------------|------------|------------|
| 0 ngày | 30 | 45 | 55 |
| 3 ngày | 39 | 54 | 64 |
| 7 ngày | 51 | 66 | 76 |
| 14 ngày | 72 | 87 | 97 |

### B. Files cần thay đổi

**Backend:**
- `app/models/lead.py`
- `app/schemas/lead.py`
- `app/services/insights_service.py`
- `app/services/lead_cache_service.py` (NEW)
- `app/services/consultation_service.py`
- `app/routers/leads.py`
- `alembic/versions/xxx_add_lead_cache_fields.py` (NEW)

**Frontend:**
- `src/types/lead.types.ts`
- `src/components/common/UrgencyBadge.tsx` (NEW)
- `src/components/common/ActivityIndicator.tsx`
- `src/components/leads/command-center/LeadsTable.tsx`
- `src/components/leads/command-center/LeadDetailPanel.tsx`
- `src/components/leads/command-center/TableToolbar.tsx`

---

**Người phê duyệt:** ________________  
**Ngày phê duyệt:** ________________
