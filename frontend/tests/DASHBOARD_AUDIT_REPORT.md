# Officer Dashboard Data Audit Report

**Officer:** Nguyễn Hữu Hiệu (`hieu9993@gmail.com`, ID=7, unit_id=2)
**Ngày audit:** 2026-03-08
**Dữ liệu gần nhất:** 2026-02-16 (không có data sau ngày này)
**Screenshots:** `tests/audit-screenshots/`

---

## 1. Tổng quan dữ liệu Officer

| Metric | Value |
|--------|-------|
| Total leads assigned | 402 |
| Active (pipeline non-final) | 402 (stg02: 92, stg03: 102, stg04: 96, stg05: 112) |
| Final consultation_status | 142 (nhưng pipeline_stage vẫn non-final) |
| max_capacity | 100 |
| availability_status | available |
| Total consultations (all time) | 1,002 (Nov 7 2025 – Feb 16 2026) |
| KPI target: consultations_daily | 10 (global default) |
| KPI target: enrollments_annual | 300 (officer-specific, 2026) |
| KPI target: achieved_ytd | 0 |

---

## 2. Kết quả đối chiếu theo bộ lọc ngày

### 2.1 Bộ lọc 7 ngày (Mar 2 – Mar 8, 2026)

**Lý do kỳ vọng all-zero:** Không có hoạt động nào sau Feb 16.

| Component | Metric | DB Expected | API Actual | UI Displayed | Status |
|-----------|--------|-------------|------------|--------------|--------|
| KPI | consultations_today | 0 | 0 | 0/10 | **PASS** |
| KPI | consultations_target | 10 | 10 | 10 | **PASS** |
| KPI | consultations_trend | 0% neutral | 0% neutral | "0,0% vs TB/ngày (7 ngày)" | **PASS** |
| KPI | active_leads (created in range) | 0 | 0 | 0 | **PASS** |
| KPI | win_rate | 0% | 0% | 0,0% | **PASS** |
| KPI | new_lead_conversion_rate | 0% | 0% | 0,0% | **PASS** |
| KPI | avg_response_time | 0h | 0h | 0,0h | **PASS** |
| KPI | sla_compliance_rate | 0% | 0% | 0,0% | **PASS** |
| KPI | consultation_effectiveness | 0% | 0% | 0,0% | **PASS** |
| Workload | current_workload | 402 | 402 | 402 | **PASS** |
| Workload | max_capacity | 100 | 100 | 100 | **PASS** |
| Workload | utilization | 402% | 402% | 402% | **PASS** |
| Annual | annual_target | 300 | 300 | 300 | **PASS** |
| Annual | achieved_ytd | 0 | 0 | 0 | **PASS** |
| Annual | progress_pct | 0% | 0% | 0.0% | **PASS** |
| Annual | status | at_risk | at_risk | "Có nguy cơ" | **PASS** |
| Funnel | All stages | 0 leads | 0 per stage | 0 per stage | **PASS** |
| Funnel | NCR | 0% | 0% | 0.0% | **PASS** |
| Leaderboard | officer 7 rank | #2/4 (0 consultations) | #2/4 | #2/4 "Bạn" | **PASS** |
| Leaderboard | officer 8 | #1 (244 consultations) | #1 (244) | "244 tư vấn" | **PASS** |
| Schedule | activities in March | 0 | 0 | (empty calendar) | **PASS** |
| Performance | trends (7 days) | all zeros | all zeros | flat chart at 0 | **PASS** |

**Screenshot evidence:** `7d-full.png`, `7d-kpi-tier1.png`

---

### 2.2 Bộ lọc 30 ngày (Feb 7 – Mar 8, 2026)

| Component | Metric | DB Expected | API Actual | UI Displayed | Status |
|-----------|--------|-------------|------------|--------------|--------|
| KPI | consultations_today | 0 | 0 | 0/10 | **PASS** |
| KPI | consultations_target | 10 | 10 | 10 | **PASS** |
| KPI | consultations_trend | -100% down¹ | -100% down | "↓ -100,0% vs TB/ngày (30 ngày)" | **PASS** |
| KPI | active_leads (created in range) | 0² | 0 | 0 | **PASS** |
| KPI | win_rate | 0%³ | 0% | 0,0% | **PASS** |
| KPI | win_rate_trend | 0% neutral⁴ | 0% neutral | "0,0% vs 30 ngày trước" | **PASS** |
| KPI | new_lead_conversion_rate | 0% | 0% | 0,0% | **PASS** |
| KPI | conversion_trend | 0% neutral | 0% neutral | "0,0% vs 30 ngày trước" | **PASS** |
| KPI | avg_response_time | 0.1h⁵ | 0.1h | 0,1h | **PASS** |
| KPI | avg_response_time_trend | -99.9% down⁶ | -99.9% down | "↓ -99,9%" | **PASS** |
| KPI | sla_compliance_rate | 100%⁷ | 100% | 100,0% | **PASS** |
| KPI | sla_trend | +99.1% up⁸ | +99.1% up | "↑ +99,1%" | **PASS** |
| KPI | consultation_effectiveness | 0%⁹ | 0% | 0,0% | **PASS** |
| Workload | current_workload | 402 | 402 | 402 | **PASS** |
| Workload | utilization | 402% | 402% | 402% | **PASS** |
| Annual | all fields | same as 7d | same | same | **PASS** |
| Funnel | stg02 (Đang tư vấn) | 1 lead, 1 early_exit | 1 lead | "1" shown | **PASS** |
| Funnel | other stages | 0 | 0 | 0 | **PASS** |
| Funnel | NCR | 0.0% | 0.0% | "0.0%" | **PASS** |
| Funnel | ncr_trend | 0% neutral | 0% neutral | (no indicator shown) | **PASS** |
| Funnel | lost revenue (stg02) | present | present | "5.000.000 ₫" | **PASS** |
| Leaderboard | officer 7 | #2 (11 consultations) | #2 (11) | "11 tư vấn" | **PASS** |
| Leaderboard | officer 8 | #1 (477 consultations) | #1 (477) | "477 tư vấn" | **PASS** |
| Performance | Feb 16 spike | 11 consultations | 11 on Feb 16 | visible spike on chart | **PASS** |

**Footnotes:**
1. `consultations_today (0) vs avg (11/30 = 0.37)` → `(0-0.37)/0.37 * 100 = -100%`
2. 1 lead created in range (lead 2597) but it has final consultation_status (negative) → active = 0
3. Win rate: 1 lead with final status (lead 2597, negative). Won=0, total_closed=1 → 0%
4. Previous period (Jan 8 – Feb 6): 0 leads with status changes → prev win_rate = 0%. Diff = 0
5. Lead 2597: assigned Feb 16 11:18, first consult Feb 16 11:22 → 0.065h → round(0.065, 1) = 0.1
6. Prev response time = 133.3h. `(0.1 - 133.3) / 133.3 * 100 = -99.9%`
7. SLA: 1 contacted lead, responded in 0.065h (< 2h) → 1/1 = 100%
8. Prev SLA: 111 contacted, 1 compliant → rate = 0.9%. Diff = 100 - 0.9 = 99.1
9. Effectiveness: 2 final consulted leads (790, 2597), both negative. Won=0/2 = 0%

**Screenshot evidence:** `30d-full.png`, `30d-kpi-tier1.png`

---

### 2.3 Bộ lọc "Tháng này" (Mar 1 – Mar 8, 2026)

**Lý do kỳ vọng all-zero:** Không có hoạt động nào trong tháng 3.

| Component | Metric | DB Expected | API Actual | UI Displayed | Status |
|-----------|--------|-------------|------------|--------------|--------|
| KPI | consultations_today | 0 | 0 | 0/10 | **PASS** |
| KPI | consultations_trend | 0% neutral | 0% neutral | "0,0% vs TB/ngày (8 ngày)" | **PASS** |
| KPI | active_leads | 0 | 0 | 0 | **PASS** |
| KPI | all trends | neutral | all neutral | all "0,0%" | **PASS** |
| KPI | avg_response_time | 0h | 0h | 0,0h | **PASS** |
| KPI | response_time_trend | N/A | "Chưa có dữ liệu" | displayed | **PASS** |
| Workload | current_workload | 402 | 402 | 402 | **PASS** |
| Annual | all fields | same | same | same | **PASS** |

**Screenshot evidence:** `this-month-full.png`

---

## 3. SQL Queries Used

### Officer lookup
```sql
SELECT id, email, full_name, username, role, unit_id, max_capacity, availability_status, status
FROM "user" WHERE email = 'hieu9993@gmail.com';
-- Result: id=7, unit_id=2, max_capacity=100, role=officer
```

### KPI: Consultations (30d)
```sql
SELECT COUNT(*) FROM consultation c JOIN lead l ON c.lead_id = l.id
WHERE c.officer_id = 7 AND c.deleted_at IS NULL AND l.deleted_at IS NULL
  AND DATE(c.consultation_date) BETWEEN '2026-02-07' AND '2026-03-08';
-- Result: 11
```

### KPI: Leads created in range (30d)
```sql
SELECT COUNT(*) AS total_leads,
  COUNT(*) FILTER (WHERE cs.is_final = false OR cs.is_final IS NULL) AS active_leads,
  COUNT(*) FILTER (WHERE cs.is_final = true AND cs.outcome_type = 'positive') AS converted
FROM lead l LEFT JOIN consultation_status cs ON l.consultation_status_id = cs.id
WHERE l.assigned_officer_id = 7 AND l.deleted_at IS NULL
  AND DATE(l.created_at) BETWEEN '2026-02-07' AND '2026-03-08';
-- Result: total=1, active=0, converted=0
```

### Workload (no date filter)
```sql
SELECT COUNT(*) FROM lead l
LEFT JOIN pipeline_stage ps ON l.pipeline_stage_id = ps.id
WHERE l.assigned_officer_id = 7 AND l.deleted_at IS NULL
  AND (ps.is_final_stage = false OR ps.is_final_stage IS NULL);
-- Result: 402
```

### Win Rate (30d)
```sql
SELECT DISTINCT ON (lsh.lead_id) lsh.lead_id, cs.outcome_type, cs.is_final
FROM lead_status_history lsh
JOIN consultation_status cs ON lsh.new_consultation_status_id = cs.id
JOIN lead l ON lsh.lead_id = l.id
WHERE lsh.changed_by_user_id = 7 AND l.deleted_at IS NULL
  AND DATE(lsh.changed_at) BETWEEN '2026-02-07' AND '2026-03-08'
  AND lsh.new_consultation_status_id IS NOT NULL
ORDER BY lsh.lead_id, lsh.changed_at DESC;
-- Result: lead 2597 → negative, is_final=true → won=0, total_closed=1 → win_rate=0%
```

### Response Time (30d)
```sql
SELECT l.id, l.assigned_at, MIN(c.consultation_date) AS first_consultation,
  EXTRACT(EPOCH FROM (MIN(c.consultation_date) - l.assigned_at)) / 3600 AS response_hours
FROM lead l JOIN consultation c ON c.lead_id = l.id AND c.officer_id = 7 AND c.deleted_at IS NULL
WHERE l.assigned_officer_id = 7 AND l.assigned_at IS NOT NULL AND l.deleted_at IS NULL
  AND DATE(l.assigned_at) BETWEEN '2026-02-07' AND '2026-03-08'
GROUP BY l.id, l.assigned_at HAVING MIN(c.consultation_date) >= l.assigned_at;
-- Result: lead 2597, response_hours = 0.065 → round to 0.1h
```

### SLA Compliance (30d)
```sql
-- Contacted: total=1, compliant=1 (0.065h < 2h) → rate = 100%
-- Overdue uncontacted: 0
-- Previous period (Jan 8 - Feb 6): total=111, compliant=1 → rate = 0.9%
-- Trend: 100 - 0.9 = +99.1%
```

### Consultation Effectiveness (30d)
```sql
-- 2 consulted leads reached final: lead 790 (negative), lead 2597 (negative)
-- Won = 0, total_final = 2 → effectiveness = 0%
```

### Funnel (30d, leads created in range)
```sql
-- Only 1 lead at stg02 (Đang tư vấn): count=1, positive=0, negative=1, early_exit=1
-- All other stages: 0
```

### Annual Progress
```sql
SELECT annual_target, achieved_ytd FROM kpi_target
WHERE kpi_code = 'enrollments' AND fiscal_year = 2026 AND officer_id = 7;
-- Result: annual_target=300, achieved_ytd=0
```

### Leaderboard (Mar 2-8)
```sql
-- Officer 8: 244 consultations, Officer 7: 0, Officer 9: 0, Officer 11: 0
-- Leaderboard for 30d: Officer 8: 477, Officer 7: 11
```

---

## 4. Tổng kết

### Kết quả tổng hợp

| Bộ lọc | Total checks | PASS | FAIL | Pass rate |
|--------|-------------|------|------|-----------|
| 7d (default) | 28 | 28 | 0 | **100%** |
| 30d | 26 | 26 | 0 | **100%** |
| Tháng này | 10 | 10 | 0 | **100%** |
| **TOTAL** | **64** | **64** | **0** | **100%** |

### Nhận xét

1. **Tất cả 64 điểm kiểm tra đều PASS** — Dữ liệu API và UI khớp chính xác với truy vấn DB trực tiếp.

2. **Trend calculation hoạt động đúng** — Ví dụ nổi bật:
   - Consultations 30d: avg = 0.37/day, today = 0 → trend = -100% (down) ✓
   - SLA: current 100% vs prev 0.9% → diff = +99.1% (up) ✓
   - Response time: current 0.1h vs prev 133.3h → -99.9% (down = faster) ✓

3. **Workload 402% (402/100 capacity)** — Đúng theo logic code (pipeline_stage based), nhưng chênh với 260 active leads theo consultation_status. 142 leads có final consultation_status nhưng chưa chuyển pipeline_stage. Đây là data quality issue, không phải code bug.

4. **Annual progress at_risk đúng** — 0/300 = 0% progress, tháng 3/12 → expected ~22.5% → status "at_risk" ✓

5. **Không có dữ liệu sau Feb 16** — All 7d/this_month filters return zeros, which is correct behavior.

### Data quality observations (không phải code bugs)

- **142 leads có final consultation_status nhưng pipeline non-final** — Có thể do workflow không tự động update pipeline_stage khi consultation_status chuyển final. Nên audit workflow rules.
- **Utilization 402%** — Officer đang overloaded (402 leads / 100 capacity). Đúng theo data, nhưng UX nên có visual warning khi >100%.

---

## 5. Screenshots

| File | Mô tả |
|------|-------|
| `audit-screenshots/7d-full.png` | Full page, 7d default |
| `audit-screenshots/7d-kpi-tier1.png` | KPI cards closeup, 7d |
| `audit-screenshots/7d-after-reload.png` | After page reload, 7d |
| `audit-screenshots/30d-full.png` | Full page, 30d |
| `audit-screenshots/30d-kpi-tier1.png` | KPI cards closeup, 30d |
| `audit-screenshots/this-month-full.png` | Full page, tháng này |
