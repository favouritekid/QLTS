// src/lib/api/csrf.ts
/**
 * CSRF Protection Utilities
 *
 * Implements client-side of Double-Submit Cookie pattern:
 * 1. Backend sets csrf_token cookie on login (httpOnly=false, readable by JS)
 * 2. Frontend reads token and sends in X-CSRF-Token header
 * 3. Backend validates cookie === header
 *
 * This protects against CSRF because:
 * - Attacker cannot read csrf_token cookie (Same-Origin Policy)
 * - Attacker cannot set custom headers in cross-origin requests
 */

// CSRF cookie and header names (must match backend)
export const CSRF_COOKIE_NAME = "csrf_token";
export const CSRF_HEADER_NAME = "X-CSRF-Token";

// HTTP methods that require CSRF protection
export const CSRF_PROTECTED_METHODS = ["POST", "PUT", "DELETE", "PATCH"];

/**
 * Get CSRF token from cookie.
 *
 * Token is set by backend on login/refresh and stored in a readable cookie.
 * Returns null if cookie doesn't exist (user not logged in).
 *
 * @returns CSRF token string or null
 */
export function getCSRFToken(): string | null {
  // SSR check - cookies only available in browser
  if (typeof document === "undefined") {
    return null;
  }

  const cookies = document.cookie.split("; ");
  const csrfCookie = cookies.find((cookie) =>
    cookie.startsWith(`${CSRF_COOKIE_NAME}=`)
  );

  if (!csrfCookie) {
    return null;
  }

  // Extract value after "csrf_token="
  return csrfCookie.substring(CSRF_COOKIE_NAME.length + 1);
}

/**
 * Check if a request method requires CSRF protection.
 *
 * @param method HTTP method (GET, POST, etc.)
 * @returns true if method requires CSRF token
 */
export function requiresCSRFToken(method: string | undefined): boolean {
  if (!method) return false;
  return CSRF_PROTECTED_METHODS.includes(method.toUpperCase());
}

/**
 * CSRF error codes returned by backend
 */
export const CSRF_ERROR_CODES = {
  TOKEN_MISSING: "CSRF_TOKEN_MISSING",
  HEADER_MISSING: "CSRF_HEADER_MISSING",
  TOKEN_INVALID: "CSRF_TOKEN_INVALID",
  ORIGIN_INVALID: "CSRF_ORIGIN_INVALID",
  REFERER_INVALID: "CSRF_REFERER_INVALID",
} as const;

export type CSRFErrorCode = (typeof CSRF_ERROR_CODES)[keyof typeof CSRF_ERROR_CODES];

/**
 * Check if an error response is a CSRF error.
 *
 * @param errorCode Error code from response
 * @returns true if this is a CSRF-related error
 */
export function isCSRFError(errorCode: string | undefined): boolean {
  if (!errorCode) return false;
  return errorCode.startsWith("CSRF_");
}
