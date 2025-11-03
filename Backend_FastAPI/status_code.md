Chào bạn, tôi sẽ giải thích rõ ràng hai vấn đề này.

## 1. Giải thích các trường hợp User (Vai trò)

Trong bài test `test_permissions_matrix.py`, bạn đang kiểm tra 4 cấp độ truy cập khác nhau, tương ứng với 4 "loại" user (vai trò) mà bạn đã định nghĩa. Mỗi loại user này được đại diện bởi một _fixture_ cung cấp token xác thực riêng:

- **`admin` (dùng `admin_token_headers`) 👑**

  - **Họ là ai:** Đây là quản trị viên cấp cao nhất (Super Admin).
  - **Vai trò Casbin:** `role:admin`.
  - **Mục tiêu test:** Xác minh rằng user này có **toàn quyền** (đọc, ghi, xóa, cấu hình) trên _tất cả_ các endpoint, bao gồm cả việc quản lý user khác, cấu hình hệ thống (pipeline, policies), và xem/sửa mọi Lead. Chúng ta mong đợi họ nhận được `200 OK` (hoặc `201`, `204`) ở mọi nơi. (Ngoại lệ duy nhất là lỗi logic nghiệp vụ, như `409 Conflict` khi cố xóa một Stage đang được sử dụng).

- **`manager` (dùng `manager_token_headers`) 👔**

  - **Họ là ai:** Đây là cấp quản lý (ví dụ: trưởng phòng tuyển sinh).
  - **Vai trò Casbin:** `role:manager`.
  - **Mục tiêu test:** Xác minh rằng user này có quyền hạn **giới hạn** trong phạm vi admin. Họ có thể quản lý cấp dưới (`GET /api/admin/users`) và quản lý dữ liệu (`GET /api/leads`, `PUT /api/leads/{id}`), nhưng **không** được phép thay đổi cấu hình cốt lõi của hệ thống (như `GET /api/admin/pipeline-stages` hay `DELETE /api/admin/policies`). Test này kiểm tra xem họ có nhận đúng `200 OK` cho các quyền được phép và `403 Forbidden` cho các quyền bị cấm hay không.

- **`officer` (dùng `officer_token_headers`) 🧑‍💼**

  - **Họ là ai:** Đây là nhân viên nghiệp vụ chính (ví dụ: nhân viên tư vấn, chuyên viên).
  - **Vai trò Casbin:** `role:officer`.
  - **Mục tiêu test:** Xác minh rằng user này chỉ có quyền trên các chức năng **cơ bản** liên quan đến công việc của họ. Họ có thể xem danh sách Lead (`GET /api/leads`), xem chi tiết Lead _của mình_ (`GET /api/leads/{id}`), thêm tư vấn (`POST /consultations`), và quản lý hồ sơ cá nhân (`GET /api/profile`). Quan trọng là, họ bị **cấm** truy cập vào _bất kỳ_ endpoint nào trong `/api/admin/*` và cũng bị cấm thực hiện các hành động quản lý cấp cao (như `PUT /api/leads/{id}` - sửa thông tin Lead, hoặc `POST /assign` - tự gán Lead).

- **`regular` (dùng `regular_user_token_headers`) 👤**
  - **Họ là ai:** Đây là user cơ bản nhất, đã được xác thực (đăng nhập). Trong hệ thống của bạn, họ có `role:user`.
  - **Vai trò Casbin:** `role:user`.
  - **Mục tiêu test:** Xác minh rằng user này bị **chặn** ở hầu hết mọi nơi. Họ chỉ được phép truy cập và cập nhật hồ sơ cá nhân của chính mình (`/api/profile`). Mọi truy cập khác đến `/api/leads`, `/api/admin`, hoặc thậm chí `/api/pipeline/all` đều phải trả về `403 Forbidden`.

---

## 2. Mục tiêu của các Mã Trạng Thái (Status Code) trong Test

Các mã trạng thái HTTP là cách tiêu chuẩn để máy chủ (API của bạn) thông báo cho máy khách (trình duyệt hoặc test client) về kết quả của một yêu cầu. Trong testing, chúng ta dùng chúng để **xác nhận rằng API đã hành xử đúng như mong đợi**.

Dưới đây là các mã phổ biến nhất trong bài test của bạn:

### Nhóm Thành Công (2xx)

- **`200 OK` (Thành công):**

  - **Ý nghĩa:** Yêu cầu đã được thực hiện thành công.
  - **Mục tiêu test:** Xác nhận rằng một hành động (thường là `GET` để lấy dữ liệu, hoặc `PUT` để cập nhật) đã hoàn tất đúng như dự kiến. Ví dụ: `admin` gọi `GET /api/admin/users` và nhận về `200` chứng tỏ họ có quyền và API hoạt động.

- **`201 Created` (Đã tạo):**

  - **Ý nghĩa:** Yêu cầu thành công và một tài nguyên mới đã được tạo ra (ví dụ: tạo Lead mới).
  - **Mục tiêu test:** Xác nhận rằng một hành động `POST` không chỉ thành công (có quyền) mà còn thực sự tạo ra một đối tượng mới trong cơ sở dữ liệu.

- **`204 No Content` (Thành công, không có nội dung):**
  - **Ý nghĩa:** Yêu cầu thành công, nhưng máy chủ không cần trả về bất kỳ nội dung nào (ví dụ: sau khi `DELETE` thành công).
  - **Mục tiêu test:** Xác nhận hành động `DELETE` (hoặc `POST /logout`) đã hoàn tất.

### Nhóm Lỗi Phía Client (4xx)

Đây là nhóm quan trọng nhất để kiểm tra logic bảo mật và validation.

- **`401 Unauthorized` (Chưa xác thực):**

  - **Ý nghĩa:** Bạn chưa đăng nhập. Yêu cầu thiếu thông tin xác thực (token) hoặc token không hợp lệ/hết hạn.
  - **Mục tiêu test:** Đảm bảo các endpoint được bảo vệ sẽ chặn người dùng nếu họ không gửi token. (Bài test matrix không kiểm tra lỗi này, nhưng các bài test auth khác thì có).

- **`403 Forbidden` (Bị cấm):**

  - **Ý nghĩa:** Bạn đã đăng nhập và được xác thực (token hợp lệ), nhưng bạn **không có quyền** thực hiện hành động này.
  - **Mục tiêu test:** Đây là mã **quan trọng nhất** trong `test_permissions_matrix`. Khi `regular` user cố gắng gọi `GET /api/admin/users` và nhận về `403`, điều đó chứng tỏ hệ thống Casbin của bạn đang hoạt động chính xác.

- **`404 Not Found` (Không tìm thấy):**

  - **Ý nghĩa:** Tài nguyên bạn yêu cầu (ví dụ: `GET /api/users/99999`) không tồn tại trên máy chủ.
  - **Mục tiêu test:** Đảm bảo API xử lý đúng trường hợp ID không tồn tại (trả về 404) thay vì bị sập (lỗi 500) hoặc trả về `403` (lỗi logic).

- **`405 Method Not Allowed` (Phương thức không được phép):**

  - **Ý nghĩa:** Bạn đang gọi một endpoint bằng phương thức HTTP sai. Ví dụ: gọi `GET /api/auth/login` trong khi endpoint này chỉ chấp nhận `POST`.
  - **Mục tiêu test (trong trường hợp của bạn):** Đây là một lỗi _trong bài test_. Nó xảy ra khi bạn test một endpoint không tồn tại (ví dụ `GET /api/admin/pipeline-stages` trong khi chỉ có `POST`).

- **`409 Conflict` (Xung đột):**

  - **Ý nghĩa:** Yêu cầu hợp lệ, nhưng không thể thực hiện do xung đột với trạng thái hiện tại của tài nguyên.
  - **Mục tiêu test:** Xác nhận logic nghiệp vụ của bạn hoạt động. Ví dụ: admin _có quyền_ (`200`) xóa stage, nhưng test mong đợi `409` vì stage đó _đang được sử dụng_. Nhận được `409` ở đây là một **thành công** của logic code.

- **`422 Unprocessable Entity` (Không thể xử lý dữ liệu):**
  - **Ý nghĩa:** Máy chủ hiểu yêu cầu, nhưng không thể xử lý dữ liệu bạn gửi lên (payload) do lỗi validation (ví dụ: thiếu trường bắt buộc, email sai định dạng, mật khẩu quá yếu).
  - **Mục tiêu test:** Đảm bảo Pydantic schemas (hoặc logic validation trong endpoint) đang bắt lỗi đầu vào một cách chính xác. Lỗi bạn gặp (`Expected 403, Got 422` khi Officer gán Lead) là do test của bạn thiếu payload, và API đã bắt lỗi `422` này _trước khi_ kịp kiểm tra quyền `403`.
