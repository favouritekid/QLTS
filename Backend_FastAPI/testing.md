# Kế hoạch Chi tiết Testing Dự án Quản lý Tuyển sinh (QLTS)

## 1. Module: Authentication (`user_service.py`, `auth.py`, `security.py`)

### 1.1. Hàm `authenticate_user` (Unit Test)

- **Loại test:** Unit test
- **Mô tả:** Test xác thực người dùng với username/password hợp lệ, không hợp lệ, và username không tồn tại.
- **Edge cases:**
  - Username rỗng hoặc chứa khoảng trắng.
  - Password sai định dạng (quá ngắn, thiếu ký tự yêu cầu).
  - Password đúng nhưng username không tồn tại (phải thực hiện verify với dummy hash).
  - Kiểm tra `dummy_hash` có đúng định dạng bcrypt (`$2b$...`) và đủ độ dài.
- **Lý do:** Đảm bảo logic auth an toàn, chống brute-force và **timing attacks**.
- **Mock/Setup:** `get_user_by_username` (từ service khác hoặc DB mock), `verify_password` (từ `security`).

### 1.2. Các hàm `create_access_token`, `create_refresh_token` (Unit Test)

- **Loại test:** Unit test
- **Mô tả:** Test tạo JWT token (access/refresh) với payload hợp lệ. Kiểm tra token decode đúng `sub` (username), `exp` (expiry).
- **Edge cases:**
  - Payload thiếu `sub`.
  - Kiểm tra sự tồn tại và định dạng đúng của **`jti`** (UUID string) và **`type`** ('access'/'refresh').
  - Decode token vừa tạo để kiểm tra tính toàn vẹn.
- **Lý do:** Đảm bảo token được tạo hợp lệ, chứa đủ thông tin và có thể decode.
- **Mock/Setup:** Có thể mock `datetime.now` để kiểm soát expiry.

### 1.3. API Endpoint `/api/auth/login` (Integration Test) ⭐️

- **Loại test:** Integration test
- **Mô tả:** Test endpoint login với credentials hợp lệ, sai username, sai password.
- **Edge cases:** Request thiếu field username/password (422). Rate limiting (nếu có).
- **Lý do:** Đảm bảo API xử lý đúng và trả về HTTP status phù hợp (200, 401). Kiểm tra **side effects**: `active_jti` trong DB user được cập nhật, `refresh_jti:<user_id>` được lưu vào Redis với TTL hợp lệ.
- **Mock/Setup:** Test DB, Redis client.

### 1.4. API Endpoint `/api/auth/forgot-password` (Integration Test)

- **Loại test:** Integration test
- **Mô tả:** Test gửi yêu cầu reset password với email tồn tại/không tồn tại.
- **Edge cases:** Email sai định dạng (422). Rate limiting.
- **Lý do:** Đảm bảo flow hoạt động, không lộ thông tin user không tồn tại, và kiểm tra việc gọi task nền.
- **Mock/Setup:** Test DB, `send_password_reset_email_task.delay`, `FastMail` sender (để kiểm tra nội dung email và `reset_url`).

### 1.5. API Endpoint `/api/auth/reset-password` (Integration Test) ✨

- **Loại test:** Integration test
- **Mô tả:** Test đổi mật khẩu với token hợp lệ, token hết hạn/không hợp lệ, token đã được sử dụng (nếu có cơ chế). Kiểm tra password mới đã được hash và lưu vào DB.
- **Edge cases:** Password mới không khớp confirm (422), password mới quá yếu (422).
- **Lý do:** Đảm bảo luồng reset hoạt động an toàn và chỉ token hợp lệ mới đổi được pass.
- **Mock/Setup:** Test DB, `verify_password_reset_token`, `get_password_hash`.

### 1.6. API Endpoint `/api/auth/change-password` (Integration Test) ✨

- **Loại test:** Integration test
- **Mô tả:** Test đổi mật khẩu khi đang đăng nhập (cần token hợp lệ). Kiểm tra mật khẩu cũ đúng/sai (400). Kiểm tra mật khẩu mới được hash và lưu. Kiểm tra **side effects**: `user_blacklist:<user_id>` được thêm vào Redis với TTL phù hợp, `active_jti` bị xóa khỏi DB, `refresh_jti:<user_id>` bị xóa khỏi Redis.
- **Edge cases:** Mật khẩu mới không khớp confirm (422), mật khẩu mới yếu (422).
- **Lý do:** Đảm bảo user có thể tự đổi mật khẩu an toàn và **tất cả session cũ bị vô hiệu hóa**.
- **Mock/Setup:** Test DB, Redis client, `verify_password`, `get_password_hash`. Cần Auth dependency hoạt động.

### 1.7. API Endpoint `/api/auth/refresh` (Integration Test) ✨

- **Loại test:** Integration test
- **Mô tả:** Test làm mới token với refresh token hợp lệ. Kiểm tra token cũ (cả access và refresh JTI) bị blacklist (Redis), token mới (access + refresh) được trả về, `active_jti` (DB) và `refresh_jti:<user_id>` (Redis) được cập nhật. Test với refresh token hết hạn/không hợp lệ/đã bị blacklist (do reuse).
- **Edge cases:** **Concurrent requests** với cùng refresh token (cực kỳ quan trọng, cần mô phỏng đồng thời để đảm bảo chỉ một request thành công, các request sau bị lỗi 401 và token bị blacklist).
- **Lý do:** Đảm bảo cơ chế **token rotation** hoạt động an toàn, chống replay attacks và race conditions.
- **Mock/Setup:** Test DB, Redis client. Cần setup để mô phỏng concurrent requests (ví dụ: dùng `asyncio.gather`).

### 1.8. API Endpoint `/api/auth/logout` (Integration Test) ✨

- **Loại test:** Integration test
- **Mô tả:** Test logout (cần token hợp lệ). Kiểm tra **side effects**: access token JTI hiện tại bị blacklist (Redis), `refresh_jti:<user_id>` bị xóa (Redis), refresh JTI tương ứng bị blacklist (Redis), `active_jti` bị xóa (DB).
- **Edge cases:** Logout khi không đăng nhập (401). Logout nhiều lần với cùng token (lần 2 sẽ fail vì token đã blacklist).
- **Lý do:** Đảm bảo vô hiệu hóa token đúng cách khi người dùng chủ động đăng xuất.
- **Mock/Setup:** Test DB, Redis client. Cần Auth dependency.

---

## 2. Module: User Management (`user_service.py`, `routers/admin.py`, `routers/profile.py`)

### 2.1. Hàm `create_user`, `create_user_by_admin` (Unit Test)

- **Loại test:** Unit test
- **Mô tả:** Test tạo user mới với data hợp lệ, kiểm tra password được hash. Test việc xử lý `avatar_file`.
- **Edge cases:** Username/email trùng lặp (raise `DuplicateResourceError`). Input rỗng hoặc không hợp lệ (nên được validate bởi Pydantic trước khi gọi service).
- **Lý do:** Đảm bảo user được tạo đúng và không vi phạm DB constraints.
- **Mock/Setup:** `AsyncSession`, `get_password_hash`, `file_helpers.save_avatar`.

### 2.2. Hàm `get_user_by_id`, `get_user_by_username`, `get_user_by_email` (Unit Test)

- **Loại test:** Unit test
- **Mô tả:** Test lấy user theo ID/username/email. Kiểm tra trả về `User` hoặc `None`/raise `ResourceNotFoundError` (tùy hàm).
- **Edge cases:** ID/username/email không tồn tại, ID âm.
- **Lý do:** Đảm bảo truy vấn user hoạt động đúng.
- **Mock/Setup:** `AsyncSession`.

### 2.3. Hàm `get_users` (Unit Test)

- **Loại test:** Unit test
- **Mô tả:** Test lấy danh sách users với skip/limit, các tham số **filter** (`role`, `status`), **search** (username/email/full_name), và **sort** (`sort_by`, `order`).
- **Edge cases:** Skip/limit âm hoặc lớn. Search query rỗng hoặc chứa ký tự đặc biệt (kiểm tra không gây lỗi SQL). Kết hợp nhiều filter/search/sort.
- **Lý do:** Đảm bảo pagination, filter, search, sort hoạt động hiệu quả.
- **Mock/Setup:** `AsyncSession`.

### 2.4. Hàm `perform_bulk_action` (Unit Test) ✨

- **Loại test:** Unit test
- **Mô tả:** Test cả action `delete` (kiểm tra skip admin self) và `change_status` (kiểm tra `new_status` hợp lệ).
- **Edge cases:** Danh sách `user_ids` chứa admin ID (phải bị bỏ qua khi delete), IDs không tồn tại, duplicates. Danh sách rỗng. `new_status` không hợp lệ khi action là `change_status` (raise `BadRequest`).
- **Lý do:** Đảm bảo cả hai hành động bulk hoạt động đúng và an toàn.
- **Mock/Setup:** `AsyncSession`, `admin_user` (đối tượng User).

### 2.5. API Endpoints `/api/admin/users/*` (Integration Test) ⭐️

- **Loại test:** Integration test
- **Mô tả:** Test toàn diện CRUD cho admin:
  - `GET /api/admin/users` (list với pagination, filter, search, sort).
  - `POST /api/admin/users` (tạo user, có/không có avatar).
  - `GET /api/admin/users/{user_id}` (lấy chi tiết user).
  - `PUT /api/admin/users/{user_id}` (cập nhật user, có/không có avatar).
  - `POST /api/admin/users/{user_id}/set-password` (admin đặt pass).
  - `POST /api/admin/users/bulk-action` (cả delete và change_status).
- **Edge cases:** Thiếu quyền admin (403). Payload không hợp lệ (422). ID không tồn tại (404). Email/username trùng (409). Upload file không hợp lệ (400, 413).
- **Lý do:** Đảm bảo admin có thể quản lý user qua API.
- **Mock/Setup:** Test DB, Redis client, Auth dependency (Admin), `file_helpers.save_avatar`.

### 2.6. API Endpoints `/api/profile` (Integration Test) ✨

- **Loại test:** Integration test
- **Mô tả:** Test `GET /api/profile` (lấy profile). Test `PUT /api/profile` (cập nhật profile: full_name, phone, email, avatar).
- **Edge cases:** Cập nhật email trùng với user khác (409), email sai định dạng (422), upload file không hợp lệ (400, 413). Thiếu quyền (401).
- **Lý do:** Đảm bảo user có thể quản lý profile của mình.
- **Mock/Setup:** Test DB, Auth dependency, `file_helpers.save_avatar`.

---

## 3. Module: Pipeline & Config (`pipeline_service.py`, `config_service.py`, `routers/*`)

### 3.1. Hàm `get_all_pipeline_stages`, `get_all_consultation_statuses` (Unit Test)

- **Loại test:** Unit test
- **Mô tả:** Test lấy danh sách stages/statuses. Kiểm tra **cache hit** (trả về data từ Redis), **cache miss** (gọi DB, lưu cache), cấu trúc dữ liệu trả về (list of dicts).
- **Edge cases:** Cache expired. Redis down (phải fallback về DB). Không có stages/statuses trong DB (trả về list rỗng).
- **Lý do:** Đảm bảo cache hoạt động đúng và fallback khi cần.
- **Mock/Setup:** `Redis client` (`safe_redis_get`, `safe_redis_set`), `AsyncSession`.

### 3.2. Hàm `invalidate_pipeline_cache` (Unit Test)

- **Loại test:** Unit test
- **Mô tả:** Test việc gọi `safe_redis_delete` cho cả hai keys cache (`PIPELINE_STAGES_CACHE_KEY`, `PIPELINE_STATUSES_CACHE_KEY`).
- **Edge cases:** Redis connection error (kiểm tra không raise lỗi nghiêm trọng, chỉ log).
- **Lý do:** Đảm bảo cache được xóa khi dữ liệu thay đổi.
- **Mock/Setup:** `Redis client` (`safe_redis_delete`).

### 3.3. API Endpoint `/api/pipeline/all` (Integration Test)

- **Loại test:** Integration test
- **Mô tả:** Test `GET /api/pipeline/all`. Kiểm tra cấu trúc response (`stages` và `statuses`).
- **Edge cases:** Thiếu quyền (401). Cache có/không có dữ liệu.
- **Lý do:** Đảm bảo endpoint trả về cấu trúc pipeline cho frontend.
- **Mock/Setup:** Test DB, Redis client, Auth dependency.

### 3.4. API Endpoints CRUD Pipeline (`/api/admin/pipeline-stages/*`, `/api/admin/consultation-statuses/*`) (Integration Test) ✨

- **Loại test:** Integration test
- **Mô tả:** Test các endpoint POST, GET (single), PUT, DELETE cho cả `pipeline-stages` và `consultation-statuses` trong `routers/admin.py`.
- **Edge cases:** ID trùng (POST - 409). ID không tồn tại (GET/PUT/DELETE - 404). Order trùng (POST/PUT Stage - 409). **Xóa stage/status đang được sử dụng** bởi Lead hoặc Consultation (phải trả về 409 Conflict). Payload không hợp lệ (422). Thiếu quyền admin (403). Kiểm tra **cache được invalidate** sau mỗi lần POST/PUT/DELETE thành công.
- **Lý do:** Đảm bảo admin có thể quản lý cấu trúc pipeline và cache được cập nhật.
- **Mock/Setup:** Test DB, Redis client, Auth dependency (Admin).

### 3.5. Hàm `config_service` (Unit Test) - MỚI ✨

- **Loại test:** Unit test
- **Mô tả:** Test `get_assignment_config`, `update_assignment_config`, `get_all_skill_rules`, `create_skill_rule`, `delete_skill_rule`. Kiểm tra logic cache (hit/miss/invalidate) cho `assignment_config`.
- **Edge cases:** Config/Rule không tồn tại (404). Unit ID không tồn tại khi tạo/update config. Redis down.
- **Lý do:** Đảm bảo logic quản lý cấu hình hoạt động đúng.
- **Mock/Setup:** `Redis client`, `AsyncSession`.

### 3.6. API Endpoints CRUD Config (`/api/admin/assignment-config/*`, `/api/admin/skill-rules/*`) (Integration Test) - MỚI ✨

- **Loại test:** Integration test
- **Mô tả:** Test các endpoint GET, PUT cho `assignment-config` và GET, POST, DELETE cho `skill-rules` trong `routers/admin.py`.
- **Edge cases:** Unit ID/Rule ID không tồn tại (404). Payload không hợp lệ (422). Thiếu quyền admin (403). Kiểm tra cache `assignment-config` được invalidate sau PUT.
- **Lý do:** Đảm bảo admin có thể quản lý cấu hình qua API.
- **Mock/Setup:** Test DB, Redis client, Auth dependency (Admin).

---

## 4. Module: File Handling (`utils/file_helpers.py`, Endpoints liên quan)

### 4.1. Hàm `save_avatar` (Unit Test)

- **Loại test:** Unit test
- **Mô tả:** Test lưu file avatar với các kịch bản: file hợp lệ, file quá lớn, sai extension, sai MIME type, file rỗng, đọc file lỗi. Kiểm tra việc xóa `old_avatar_url`. Kiểm tra việc tạo tên file UUID và trả về URL tương đối đúng. Test phòng chống Path Traversal.
- **Edge cases:** Filename chứa `../`. `old_avatar_url` không hợp lệ. Lỗi khi ghi file.
- **Lý do:** Đảm bảo file upload **an toàn tuyệt đối** và xử lý lỗi đúng cách.
- **Mock/Setup:** Mock `UploadFile` object, `aiofiles.open`, `magic.from_buffer`, `os.path`, `os.remove`, `uuid.uuid4`, `Path(...).resolve`.

### 4.2. API Endpoints Upload Avatar (Integration Test) ⭐️

- **Loại test:** Integration test
- **Endpoints:**
  - `POST /api/admin/users`
  - `PUT /api/admin/users/{user_id}`
  - `PUT /api/profile`
- **Mô tả:** Test upload avatar thành công kèm theo data form. Test các trường hợp lỗi: file không hợp lệ (size 413, type 400), không có file, thiếu auth token (401/403). Kiểm tra `avatar_url` trong DB được cập nhật đúng.
- **Lý do:** Đảm bảo endpoint xử lý đúng file upload và trả về lỗi phù hợp.
- **Mock/Setup:** Test DB, Auth dependency, Mock `file_helpers.save_avatar` (hoặc mock sâu hơn `aiofiles`, `magic` nếu muốn).

---

## 5. Module: Utilities & Core (`utils`, `config`, `logging`, `security`, `core`)

### 5.1. Các hàm `security.py` (Unit Test) ✨

- **Mô tả:**
  - Test `get_password_hash`, `verify_password` (đúng/sai).
  - Test `create_password_reset_token`, `verify_password_reset_token` (valid, invalid, expired).
  - Test `decode_token_for_invalidation` (lấy đúng jti, ttl).
- **Edge cases:** Password rỗng/quá dài cho hash. Token bị sửa đổi.
- **Lý do:** Đảm bảo các hàm tiện ích bảo mật hoạt động chính xác.
- **Mock/Setup:** Mock `bcrypt` (passlib context), `datetime.now` (cho expiry), `jwt.encode/decode` (chỉ khi cần test xử lý lỗi JWTError).

### 5.2. Config Loading (`config.py`) (Unit Test)

- **Loại test:** Unit test
- **Mô tả:** Test load các biến môi trường quan trọng (DB*URL, REDIS_URL, JWT_SECRET, MAIL*_). Test các giá trị được tính toán (`MAX_AVATAR_CONTENT_LENGTH`, `AVATAR_UPLOAD_FOLDER`). Test các list (`ALLOWED\__`).
- **Edge cases:** Biến môi trường thiếu (kiểm tra default hoặc lỗi), sai định dạng (vd: PORT không phải số).
- **Lý do:** Đảm bảo app khởi động đúng với config hợp lệ.
- **Mock/Setup:** `os.getenv`, `os.path.join`, `os.makedirs`.

### 5.3. Logging (`main.py`, `structlog`) (Integration/Manual Test)

- **Loại test:** Integration/Manual
- **Mô tả:** Kiểm tra logs output (console/file) có đúng định dạng JSON (production) hoặc console (development). Kiểm tra các thông tin quan trọng được log (request_id, user_id, lỗi chi tiết).
- **Edge cases:** Log khi có exception (kiểm tra traceback). Log từ Celery worker.
- **Lý do:** Đảm bảo logs hữu ích cho việc giám sát và gỡ lỗi.
- **Mock/Setup:** Chạy app ở chế độ dev/prod, kiểm tra output. Mock logger trong unit test nếu cần kiểm tra việc gọi log.

### 5.4. Dependency `get_current_user` (`core/deps.py`) (Integration Test) - MỚI ✨

- **Loại test:** Integration test
- **Mô tả:** Test dependency này bằng cách gọi một endpoint bất kỳ yêu cầu auth. Test các trường hợp: token hợp lệ, token hết hạn, token sai chữ ký, token có JTI bị blacklist, token có user bị blacklist, token access không khớp `active_jti`.
- **Edge cases:** Redis down (kiểm tra fail-open). DB down.
- **Lý do:** Đây là dependency cốt lõi, cần đảm bảo hoạt động đúng trong mọi tình huống.
- **Mock/Setup:** Test DB, Redis client. Cần tạo các loại token khác nhau để test.

---

## 6. Edge Cases Chung & Resilience Testing

- **Race Conditions:**
  - `/api/auth/refresh`: Dùng `asyncio.gather` để gửi nhiều request refresh đồng thời với CÙNG MỘT refresh token hợp lệ. Chỉ MỘT request được thành công (200), các request còn lại phải thất bại (401/400) và token đó phải bị blacklist.
  - `/api/leads/{lead_id}/assign` hoặc `automatically_assign_lead`: Nếu có logic phức tạp (ngoài `with_for_update` đã có), cần mô phỏng việc gán cùng lúc.
- **DB Failures:** Mock `AsyncSession` (ví dụ: `session.commit`) để raise `SQLAlchemyError`. Kiểm tra API trả về lỗi 500 và log được ghi lại. Kiểm tra transaction được rollback (dữ liệu không bị thay đổi).
- **Redis Failures:** Tắt Redis server hoặc mock `Redis client` (`safe_redis_*`) để raise `ConnectionError`/`TimeoutError`. Kiểm tra:
  - Circuit Breaker hoạt động (log lỗi, API có thể trả lỗi 503 hoặc fallback nếu có).
  - Các chức năng phụ thuộc Redis (cache, rate limit, JTI check) xử lý lỗi một cách duyên dáng (fail-open hoặc báo lỗi).
- **Invalid Inputs (422):** Mọi endpoint nhận payload (POST/PUT) đều cần test với: payload rỗng, thiếu trường bắt buộc, sai kiểu dữ liệu, giá trị không hợp lệ (vd: email sai format, số âm khi yêu cầu dương).
- **Auth Failures (401/403):** Mọi endpoint yêu cầu quyền (Auth dependency):
  - Gọi không có token (401/403 tùy FastAPI setup).
  - Gọi với token sai chữ ký/hết hạn (401).
  - Gọi với token hợp lệ nhưng không đủ quyền (ví dụ: officer gọi API admin -> 403).

---

## 7. Casbin & Phân quyền (Integration Test) ✨

- **Loại test:** Integration Test
- **Mô tả:**
  - Tạo user test: admin, manager, officer, user thường.
  - Gán vai trò tương ứng qua API admin (`/assign-role`) hoặc setup trực tiếp trong CSDL test.
  - Với mỗi user, gọi các API endpoints quan trọng và assert status code:
    - Admin: Phải truy cập được mọi thứ (2xx).
    - Manager: Truy cập được API admin users, leads (2xx), không truy cập được API admin pipeline (403).
    - Officer: Truy cập được GET leads, POST consultations (2xx), không truy cập được PUT leads, API admin (403).
    - User thường: Chỉ truy cập được profile, change-password (2xx), không truy cập được leads, admin (403).
  - Test API admin `GET/POST/DELETE /policies` và `POST/DELETE /assign-role`.
- **Edge cases:** User có nhiều vai trò. Policy bị xóa/thay đổi.
- **Lý do:** Đảm bảo hệ thống phân quyền động hoạt động đúng như mong đợi.
- **Mock/Setup:** Cần setup Casbin enforcer với adapter trỏ đến CSDL test và load policy (`auth_model.conf`) trong `setUp` của test.

---

## 8. Khuyến nghị Testing Framework & Tools

- **Unit tests:** `pytest` + `pytest-asyncio`. Mocking: `unittest.mock` hoặc `pytest-mock`.
- **Integration tests:** `pytest` + `pytest-asyncio`. HTTP Client: `httpx` (thay thế `TestClient` nếu cần gọi API từ bên ngoài app context). DB: **Docker container PostgreSQL riêng biệt cho test** (khuyến nghị mạnh mẽ) hoặc Testcontainers. Redis: Docker container Redis riêng biệt.
- **Coverage:** Mục tiêu **85%+**. Tool: `pytest-cov`. Báo cáo: `coverage html`.
- **CI/CD:** Tích hợp vào GitHub Actions / GitLab CI / Jenkins. Chạy test trên mỗi push/PR vào nhánh chính.

---

## 9. Ưu tiên và Ước tính Effort

- **Ưu tiên:**
  1.  **Critical:** Authentication (đặc biệt là refresh, change pass, logout), Phân quyền (Casbin), File Upload (`save_avatar`).
  2.  **High:** User CRUD (Admin & Profile), Lead Assignment (`assignment_service`), Lead State Changes (`lead_service`), DB/Redis Resilience.
  3.  **Medium:** Pipeline & Config CRUD, Lead/User Listing (filter, sort, search), Caching logic.
  4.  **Low:** Utilities (security helpers, config loading), Logging format.
- **Effort:** (Giữ nguyên ước tính, có thể +1 tuần cho setup môi trường test DB/Redis)
  - Unit tests: ~0.5-1 ngày/hàm phức tạp.
  - Integration tests: ~1-2 ngày/luồng API phức tạp.
  - Tổng: **~3-4 tuần** cho 85%+ coverage với team 2-3 developers tập trung.

---
