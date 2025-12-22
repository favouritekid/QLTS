// src/types/security.ts
/**
 * ✅ LOGIN SECURITY: Phase 5 - TypeScript Types
 * 
 * Types for login history, trusted devices, and security responses.
 */

/**
 * Login history entry
 */
export interface LoginHistoryItem {
  id: number;
  login_at: string;
  ip_address: string | null;
  country: string | null;
  city: string | null;
  device_type: string | null;
  browser: string | null;
  os: string | null;
  is_new_ip: boolean;
  is_new_device: boolean;
  is_new_location: boolean;
  risk_score: number;
  is_suspicious: boolean;
  user_response: 'confirmed' | 'secured' | null;
  responded_at: string | null;
}

/**
 * Paginated login history response
 */
export interface LoginHistoryResponse {
  total: number;
  items: LoginHistoryItem[];
}

/**
 * Trusted device entry
 */
export interface TrustedDevice {
  id: number;
  name: string | null;
  browser: string | null;
  os: string | null;
  first_seen_at: string;
  trusted_at: string;
  last_used_at: string | null;
}

/**
 * Paginated trusted devices response
 */
export interface TrustedDevicesResponse {
  total: number;
  items: TrustedDevice[];
}

/**
 * Confirm login request
 */
export interface ConfirmLoginRequest {
  login_id: number;
  trust_device?: boolean;
}

/**
 * Confirm login response
 */
export interface ConfirmLoginResponse {
  message: string;
  device_trusted: boolean;
}

/**
 * Secure account response
 */
export interface SecureAccountResponse {
  message: string;
  sessions_revoked: number;
}
