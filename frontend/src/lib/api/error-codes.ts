/**
 * Backend `error_code` values the frontend branches on — ONE place per code.
 *
 * A code spelled twice drifts, and a drifted code fails silently: the branch
 * simply stops matching and the user is back to the generic message.
 */

/**
 * T6 ("Công bố kết quả") DỪNG hồ sơ, không ghi quyết định nào — thiếu dữ liệu
 * hoặc cấu hình (mức điểm, KV, năm, đóng băng, cấu hình trình độ ngành).
 * `detail` của backend nói cán bộ phải làm gì; giao diện PHẢI hiện nó ở MỌI
 * status (400/500/503) thay vì câu chung "thử lại sau".
 *
 * Backend source: `T6_PER_PROFILE_STOP_ERRORS` in
 * `Backend_FastAPI/app/services/admission_choice_engine_service.py`
 * (a backend test locks the two sets equal).
 */
export const T6_PUBLISH_STOP_ERROR_CODES: ReadonlySet<string> = new Set([
  "PRIORITY_RATE_NOT_CONFIGURED",
  "PRIORITY_YEAR_MISMATCH",
  "PRIORITY_KV_UNRESOLVED",
  "PRIORITY_FREEZE_FAILED",
  "CHOICE_TARGET_LEVEL_NOT_CONFIGURED",
]);

/** `detail` of a T6 stop error (any status), or null for any other response. */
export function t6PublishStopDetail(
  response: { status?: number; data?: unknown } | undefined,
): string | null {
  const data = response?.data;
  if (typeof data !== "object" || data === null) return null;
  const { error_code: code, detail } = data as { error_code?: unknown; detail?: unknown };
  if (typeof code !== "string" || !T6_PUBLISH_STOP_ERROR_CODES.has(code)) return null;
  return typeof detail === "string" && detail ? detail : null;
}

/**
 * The backend refused an auth request because it could not verify auth state
 * kept in Redis (the account lockout checked by `/auth/login`; the user
 * blacklist / session reads of `/auth/refresh`, before any rotation). Always
 * sent with status 503, the same response on both endpoints.
 *
 * Also the code of the 503 pair `refresh-coordination/safe-retry.ts` retries.
 *
 * Backend source of the code (and of its `Retry-After` hint):
 * `AuthStateUnavailable` in `Backend_FastAPI/app/utils/exceptions.py`.
 */
export const AUTH_STATE_UNAVAILABLE_ERROR_CODE = "AUTH_STATE_UNAVAILABLE";

/**
 * True ONLY for a 503 whose JSON body carries exactly
 * `AUTH_STATE_UNAVAILABLE` (case-sensitive).
 *
 * Status AND code: nginx answers its own 503 (e.g. `limit_req` on
 * `/api/auth/login`) with an HTML body and no code, and other backend 503s
 * carry other codes. None of them means "auth state could not be verified".
 */
export function isAuthStateUnavailable(
  response: { status?: number; data?: unknown } | undefined,
): boolean {
  if (response?.status !== 503) return false;
  const data = response.data;
  if (typeof data !== "object" || data === null) return false;
  return (
    (data as { error_code?: unknown }).error_code ===
    AUTH_STATE_UNAVAILABLE_ERROR_CODE
  );
}
