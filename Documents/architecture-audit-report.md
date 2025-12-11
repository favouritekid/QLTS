# 🏛️ Backend Architecture Compliance Report 

> **Ngày tạo:** 2025-12-11  
> **Phạm vi:** Backend FastAPI + PostgreSQL + SQLAlchemy Async  
> **Tiêu chuẩn áp dụng:** Enterprise Architecture Rules A-F

---

## 📊 Executive Summary

| Tiêu chí | Mức tuân thủ | Chi tiết |
|----------|--------------|----------|
| **A. Layered Architecture** | 🟡 **70%** | Service vẫn chứa nhiều direct DB queries, chưa triệt để qua Repository |
| **B. Router Rules** | ✅ **98%** | Tuân thủ tốt: không logic, commit đúng cách, clean dependencies |
| **C. Security Layer** | ✅ **95%** | RBAC/IDOR chặt chẽ. IDOR check qua Dependency injection |
| **D. Service Rules** | 🟡 **75%** | Không import HTTPException (Tốt), nhưng Query trực tiếp nhiều (Xấu) |
| **E. Repository Pattern** | 🔴 **45%** | Adoption không đồng nhất. User dùng cho Detail, Lead dùng cho List |
| **F. Models & Schemas** | ✅ **90%** | Models chuẩn, timezone-aware. Indexing cần review định kỳ |

**Điểm tổng: 75/100** 🟡

---

## A. Layered Architecture (BẮT BUỘC)

### Luồng dữ liệu chuẩn:
```
Router (Controller) → Security Deps → Service (Business Logic) → Repository (Data Access) → Models
```

### Hiện trạng thực tế:

| Component | Vi phạm chính | Mức độ nghiêm trọng |
|-----------|---------------|---------------------|
| `lead_service.py` | Query trực tiếp (`db.execute`) trong `get_lead_by_id`, `update_lead_next_activity` | 🔴 High |
| `user_service.py` | Query trực tiếp trong `get_users` (List/Search) | 🟠 Medium |
| `organization_service.py` | Query trực tiếp toàn bộ | 🔴 High |

**Nhận xét:** Việc phân tách lớp `Router` và `Service` đã làm tốt. Tuy nhiên, ranh giới giữa `Service` và `Data Access` (Repository) bị mờ nhạt. Service đang "làm quá nhiều việc" của tầng Data (build queries, filter logic).

---

## B. Router Rules

### ✅ Điểm mạnh:
*   **Transaction Management:** Pattern chuẩn `create_lead` return `(result, callback)`. Commit thực hiện tại Router -> `await callback()`.
*   **Dependencies:** Sử dụng `LeadAccessDep` và `PermissionDep` giúp Router code rất sạch.
*   **Notification Dispatch:** Đã tách ra khỏi logic chính, dùng `SystemEvents`.

### 🔍 Ví dụ tuân thủ (app/routers/leads.py):
```python
@router.post("")
async def create_new_lead(...):
    # Logic in Service
    result, callback = await lead_service.create_lead(db, lead_in, created_by=current_user)
    
    # Transaction Control in Router
    await db.commit()
    await callback()  # Post-commit actions (e.g. notifications)
    
    return result
```

---

## C. Security Layer Rules

### ✅ Điểm mạnh:
*   **RBAC:** Tích hợp Casbin sâu vào `user_service` (transactional updates) và Router dependencies.
*   **IDOR:** Tất cả endpoints thao tác trên resource cụ thể (`/{lead_id}`) đều dùng `LeadAccessDep` để verify quyền ownership/unit access trước khi vào logic.

---

## D. Service Rules & E. Repository Pattern (Phân tích sâu)

Đây là khu vực có nhiều vấn đề nhất. Quy tắc "Service chứa 100% business logic" được tuân thủ, NHƯNG quy tắc "Service không query trực tiếp Model" bị vi phạm rộng rãi.

### 1. `lead_service.py` (Adoption: Partial - List Only)
*   ✅ **Tuân thủ:** Hàm `get_leads` DÙNG `LeadRepository`.
*   ❌ **Vi phạm:**
    *   `get_lead_by_id`: Tự build query với `selectinload/joinedload` khổng lồ (Lines 418-445).
    *   `update_lead_next_activity`: Query trực tiếp (Lines 58-68).
    *   `calculate_lead_score`: Query trực tiếp config (Lines 240-244).

### 2. `user_service.py` (Adoption: Partial - Detail Only)
*   ✅ **Tuân thủ:** Các hàm `get_by_username`, `get_by_email`, `get_by_id` DÙNG `UserRepository`.
*   ❌ **Vi phạm:**
    *   `get_users` (List View): Tự build query filter/search rất phức tạp ngay trong Service (Lines 506-618). Đáng lẽ logic filter dynamic này phải nằm trong Repository (`repo.get_many(...)`).

### 3. Missing/Unused Repositories
*   `organization_repository.py`: Có file nhưng gần như không được service sử dụng.

---

## F. Models & Schemas

*   ✅ **Timezone:** Sử dụng `datetime.now(timezone.utc)` đồng bộ.
*   ⚠️ **Foreign Keys:** Cần rà soát lại migration để đảm bảo tất cả FK đều có Index (SQLAlchemy không tự tạo Index cho FK trừ khi khai báo rõ hoặc DB engine tự optimize).
*   ✅ **Validation:** Pydantic models (Schemas) làm tốt việc validate input đầu vào.

---

## 📋 Recommendations (Kế hoạch hành động)

### 🔴 Critical (Cần làm ngay)

1.  **Refactor `lead_service.get_lead_by_id` vào Repository:**
    *   Hiện tại query này quá phức tạp và nằm sai chỗ.
    *   **Action:** Di chuyển logic Eager Loading (selectinload, joinedload) vào method `LeadRepository.get_with_relations(id)`.

2.  **Refactor `user_service.get_users` vào Repository:**
    *   Logic search/filter (đặc biệt là Full-text search và CTE hierarchy) nên được gói gọn trong `UserRepository.search_users(...)`.
    *   Service chỉ nên gọi: `return await repo.search_users(params)`.

### � Medium (Ưu tiên tiếp theo)

3.  **Chuẩn hóa patterns:**
    *   Hiện tại `lead_service` dùng Repo cho List, `user_service` dùng Repo cho Detail. Cần thống nhất cả 2 service đều dùng Repo cho CẢ List và Detail.

4.  **Audit Indexing:**
    *   Chạy script kiểm tra index database để đảm bảo các cột hay query (status, pipeline_stage_id, unit_id) đều được index.

### 🟢 Low (Cải thiện dài hạn)

5.  **Clean up imports:**
    *   Loại bỏ hoàn toàn `from sqlalchemy import select` trong các file Service sau khi migration hoàn tất.

---

*Báo cáo được cập nhật tự động bởi Antigravity Audit Agent.*
