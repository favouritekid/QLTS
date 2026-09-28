// src/lib/api/refresh-coordination/safe-retry.ts
/**
 * Danh sách DUY NHẤT các response của `POST /auth/refresh` được phép THỬ LẠI.
 *
 * Hai nơi hỏi cùng một câu — `classify()` ở `refresh.ts` (quyết định lúc nhận
 * response) và `validateRecord()` ở `storage.ts` (quyết định có tin bản ghi
 * `safe-retryable` của tab khác không) — nên câu trả lời chỉ được nằm ở MỘT
 * chỗ. Hai bản chép tay sẽ lệch nhau: nới một bên thì tab này thử lại còn tab
 * kia coi nhật ký là hỏng, hoặc ngược lại.
 *
 * Tiêu chí vào danh sách rất hẹp: backend phải CHỨNG MINH được lỗi xảy ra
 * TRƯỚC rotation, tức refresh token client đang giữ còn nguyên và trình lại nó
 * không bị tính là reuse. Khớp theo CẶP (status, error_code), không bao giờ
 * theo status một mình:
 *
 * - `429 RATE_LIMITED` — slowapi chặn ở decorator, trước khi thân hàm chạy.
 * - `503 AUTH_STATE_UNAVAILABLE` — Redis không TRẢ LỜI được một trong ba phép
 *   đọc quyết định (`blacklist:{jti}`, `user_blacklist`, `session`) ở
 *   `auth.py`; backend ném NGAY tại ba phép đọc ấy, trước mọi lần ghi
 *   Redis/DB/cookie. Mọi `503` khác — nginx `limit_req` (không có
 *   `error_code`), `503` sau khi rotation đã bắt đầu (`HTTP_503`) — KHÔNG có
 *   bảo đảm đó và vẫn là `ambiguous`.
 *
 * Thêm một cặp vào đây là cấp quyền POST lại cho mọi tab: chỉ làm khi backend
 * có test khoá "lỗi này xảy ra trước rotation".
 *
 * Mã `AUTH_STATE_UNAVAILABLE` KHÔNG được viết lại ở đây: nó đến từ
 * `error-codes.ts` — cùng hằng mà `LoginForm` dùng cho 503 của `/login`, và là
 * bản phản chiếu của `AuthStateUnavailable` ở backend (`/login` và `/refresh`
 * trả CÙNG một 503). Hai chuỗi chép tay sẽ trôi lệch nhau một cách im lặng:
 * nhánh này thôi khớp và mọi 503 đó quay về `ambiguous`.
 */
import { AUTH_STATE_UNAVAILABLE_ERROR_CODE } from "../error-codes";

export const RATE_LIMITED_CODE = "RATE_LIMITED";

const SAFE_RETRYABLE_RESPONSES: ReadonlyArray<{
  readonly status: number;
  readonly errorCode: string;
}> = [
  { status: 429, errorCode: RATE_LIMITED_CODE },
  { status: 503, errorCode: AUTH_STATE_UNAVAILABLE_ERROR_CODE },
];

/** Cặp (status, error_code) này có chứng minh lỗi xảy ra TRƯỚC rotation không? */
export function isSafeRetryableResponse(
  status: unknown,
  errorCode: unknown,
): boolean {
  return SAFE_RETRYABLE_RESPONSES.some(
    (pair) => pair.status === status && pair.errorCode === errorCode,
  );
}
