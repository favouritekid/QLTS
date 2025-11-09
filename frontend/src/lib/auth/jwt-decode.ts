// src/lib/auth/jwt-decode.ts

/**
 * JWT Decode Utility for Server-Side Middleware
 *
 * ⚠️ SECURITY NOTE:
 * This utility only DECODES JWT tokens (does NOT verify signature).
 * It's safe to use in middleware because:
 * 1. Tokens come from httpOnly cookies (cannot be manipulated by client JS)
 * 2. Backend already verified and signed these tokens
 * 3. We only use this to check expiry and read claims for routing
 *
 * DO NOT use this to verify authenticity - trust the httpOnly cookie source.
 */

export interface JWTPayload {
  sub: string; // username
  exp: number; // expiration timestamp (seconds since epoch)
  jti: string; // JWT ID
  type: "access" | "refresh";
  role?: string; // User role (if embedded in token by backend)
  user_id?: number; // User ID (if embedded in token by backend)
}

/**
 * Decode a JWT token without verifying signature
 *
 * @param token - The JWT token string
 * @returns Decoded payload or null if invalid format
 */
export function decodeJWT(token: string): JWTPayload | null {
  try {
    // JWT format: header.payload.signature
    const parts = token.split(".");
    if (parts.length !== 3) {
      return null;
    }

    // Decode the payload (base64url encoded)
    const payload = parts[1];

    // Base64url to Base64 conversion
    const base64 = payload.replace(/-/g, "+").replace(/_/g, "/");

    // Decode base64 to JSON
    const jsonPayload = Buffer.from(base64, "base64").toString("utf-8");

    return JSON.parse(jsonPayload) as JWTPayload;
  } catch (error) {
    console.error("[JWT Decode] Failed to decode token:", error);
    return null;
  }
}

/**
 * Check if a JWT token is expired
 *
 * @param token - The JWT token string
 * @returns true if expired, false if still valid
 */
export function isTokenExpired(token: string): boolean {
  const payload = decodeJWT(token);
  if (!payload || !payload.exp) {
    return true; // Consider invalid tokens as expired
  }

  // exp is in seconds, Date.now() is in milliseconds
  const expirationTime = payload.exp * 1000;
  const currentTime = Date.now();

  return currentTime >= expirationTime;
}

/**
 * Get the user role from a JWT token
 *
 * @param token - The JWT token string
 * @returns User role or null if not found
 */
export function getRoleFromToken(token: string): string | null {
  const payload = decodeJWT(token);
  return payload?.role ?? null;
}

/**
 * Validate that a token is an access token (not refresh token)
 *
 * @param token - The JWT token string
 * @returns true if it's an access token
 */
export function isAccessToken(token: string): boolean {
  const payload = decodeJWT(token);
  return payload?.type === "access";
}
