# Kế Hoạch Chi Tiết Refactor Auth Module (Strict Pattern A)

Tài liệu này mô tả chi tiết các thay đổi về mặt kiến trúc để tuân thủ mô hình **Router → Service → Repository** (Pattern A) và loại bỏ hoàn toàn việc gọi SQL từ Router/Service.

---

## 1. Tổng Quan Kiến Trúc

### Hiện Tại (Vi Phạm)
*   **Routers (`auth.py`)**: Gọi trực tiếp `db.execute()`, `select()`.
*   **Services (`session_service.py`)**: Gọi trực tiếp `db.execute()`, chưa có Repository riêng.
*   **Dependencies (`deps.py`)**: Gọi trực tiếp `db.execute()` để fallback kiểm tra session.

### Sau Refactor (Đạt Chuẩn)
*   **Repository Mới**: `SessionRepository` (Chứa toàn bộ câu lệnh SQL).
*   **Services**: Gọi Repository, không chứa SQL.
*   **Routers**: Gọi Service, không chứa SQL, không import `sqlalchemy`.

---

## 2. Chi Tiết Các Thay Đổi

### 2.1. Tạo Mới `app/repositories/session_repository.py`

Tạo repository mới chuyên biệt cho bảng `user_sessions`.

| Function Name | Input | Description |
| :--- | :--- | :--- |
| `get_by_jti` | `jti: str` | Tìm session theo Refresh Token JTI. |
| `get_active_by_user` | `user_id: int` | Lấy danh sách session đang active của user. |
| `get_active_on_device` | `user_id, device, ...` | Tìm session cũ trên cùng thiết bị để revoke (logic chống rác data). |
| `get_for_update` | `session_id, user_id` | Lấy session và khóa record (pessimistic lock) để revoke an toàn. |
| `get_by_refresh_jti_and_user` | `jti, user_id` | Tìm session cụ thể để validate trong `deps.py`. |

### 2.2. Refactor `app/services/session_service.py`

Chuyển đổi toàn bộ logic SQL sang gọi Repository.

| Function | Hành động Refactor |
| :--- | :--- |
| `_revoke_previous_sessions_on_device` | Thay `db.execute` bằng `repo.get_active_on_device(...)` sau đó loop update. |
| `create_session` | Dùng `repo.add()` (kế thừa từ BaseRepo). |
| `check_new_ip_address` | Thay `db.execute` bằng `repo.get_by_ip(...)`. |
| `get_active_sessions` | Thay `db.execute` bằng `repo.get_active_by_user(...)`. |
| `revoke_session` | Thay `select(...).with_for_update()` bằng `repo.get_for_update(...)`. |
| `update_session_activity` | Thay `db.execute` bằng `repo.get_by_jti(...)`, update field và commit. |
| `revoke_all_other_sessions` | Thay `db.execute` bằng `repo.get_active_by_user(...)` (filter ngoại trừ session hiện tại). |
| **[MỚI]** `revoke_session_by_jti` | Hàm wrapper mới để Router `logout` gọi. Logic: tìm session theo JTI -> revoke. (Chuyển logic từ Router xuống). |

### 2.3. Refactor `app/services/user_service.py`

Thêm logic khóa record để phục vụ chức năng Refresh Token (bảo mật).

| Function | Hành động Refactor |
| :--- | :--- |
| **[MỚI]** `get_user_for_refresh` | Thực hiện `select(User).where(...).with_for_update()`. Thay thế logic raw SQL hiện tại trong `auth.py`. |

### 2.4. Refactor `app/core/deps.py`

Loại bỏ SQL Fallback trong hàm `get_current_user`.

| Vị trí | Hành động Refactor |
| :--- | :--- |
| `get_current_user` (Line 138-148) | Thay đoạn SQL check active session bằng `session_repo.get_active_by_user(user.id)`. |
| `get_current_user` (Line 193-202) | Thay đoạn SQL check session validity bằng `session_repo.get_by_refresh_jti_and_user(...)`. |

### 2.5. Refactor `app/routers/auth.py`

Làm sạch hoàn toàn Router.

| Endpoint | Hành động Refactor |
| :--- | :--- |
| `/logout` | Xóa `db.execute`, gọi `await session_service.revoke_session_by_jti(...)`. |
| `/check-status` | Xóa `db.execute`, gọi `await session_service.get_active_sessions(...)`. |
| `/refresh` | Xóa `select(...).with_for_update()`, gọi `await user_service.get_user_for_refresh(...)`. |
| **Imports** | Xóa sạch `from sqlalchemy import select, and_`. |

---

## 3. Lộ Trình Thực Hiện

1.  **Bước 1**: Tạo file `app/repositories/session_repository.py`.
2.  **Bước 2**: Sửa `app/services/session_service.py` để inject và sử dụng Repo mới.
3.  **Bước 3**: Sửa `app/services/user_service.py` thêm hàm `get_user_for_refresh`.
4.  **Bước 4**: Sửa `app/core/deps.py` dùng Repo thay vì SQL.
5.  **Bước 5**: Sửa `app/routers/auth.py` dùng Service thay vì SQL.
6.  **Bước 6**: Chạy `py_compile` và verify toàn bộ flow Login/Logout/Refresh.

---
**Tài liệu này đã sẵn sàng để review.**
