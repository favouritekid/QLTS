/**
 * Backend `error_code` values the frontend branches on — ONE place per code.
 *
 * A code spelled twice drifts, and a drifted code fails silently: the branch
 * simply stops matching and the user is back to the generic message.
 */

/**
 * The backend refused an auth request because it could not verify auth state
 * kept in Redis (e.g. the account lockout checked by `/auth/login`). Always
 * sent with status 503.
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
