// src/types/api.types.ts

// Định nghĩa cấu trúc User dựa trên backend model (app/models/user.py)
// và response schema (app/schemas/user.py -> User)
export interface User {
  id: number; // Backend dùng Integer
  username: string;
  email: string;
  full_name?: string | null; // Có thể null
  avatar_url?: string | null; // Có thể null
  phone_number?: string | null; // Có thể null
  role: "user" | "admin" | "manager" | "officer"; // Các role có trong backend
  status: "active" | "pending" | "banned"; // Các status có trong backend
  unit_id?: number | null; // Có thể null
  // Thêm các trường khác nếu cần từ schema backend (skills, max_capacity, etc.)
}

// Kiểu dữ liệu cho request body khi login (khớp schemas/user.py -> LoginSchema)
export interface LoginRequest {
  username: string; // Backend dùng username thay vì email
  password: string;
}

// Kiểu dữ liệu cho response khi login thành công (khớp schemas/user.py -> Token)
// Backend trả về access_token, refresh_token, token_type.
// Chúng ta cần gọi thêm /users/me để lấy User object.
export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  // User object không được trả về trực tiếp từ /login backend này
}

// Kiểu dữ liệu cho response từ /users/me
export type MeResponse = User;

// Kiểu dữ liệu chung cho lỗi API (có thể mở rộng)
export interface ApiErrorResponse {
  detail?: string | { msg: string; type: string }[]; // FastAPI validation errors
  message?: string; // Hoặc dùng 'message' nếu backend trả về
}

// Schema for user registration - matches backend UserCreate
// Note: confirm_password is validated on frontend only, not sent to backend
export interface UserCreate {
  username: string;
  email: string;
  password: string;
  full_name?: string | null;
}

// Schema for forgot password request
export interface ForgotPasswordSchema {
  email: string;
}

// Schema for reset password - matches backend ResetPasswordSchema
// Note: confirm_new_password is validated on frontend only, not sent to backend
export interface ResetPasswordSchema {
  token: string;
  new_password: string;
}

// Schema for change password - matches backend ChangePasswordSchema
// Note: confirm_new_password is validated on frontend only, not sent to backend
export interface ChangePasswordSchema {
  old_password: string;
  new_password: string;
}
