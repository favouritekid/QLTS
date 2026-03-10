// frontend/src/types/session.ts
/**
 * TypeScript types for user session management.
 * Matches backend Pydantic schemas in app/schemas/user_session.py
 */

export interface UserSession {
  id: number;
  user_id: number;
  refresh_jti: string;
  ip_address: string | null;
  user_agent: string | null;
  device_type: string | null;
  browser: string | null;
  os: string | null;
  country: string | null;
  city: string | null;
  created_at: string; // ISO 8601 datetime
  last_activity_at: string; // ISO 8601 datetime
  expires_at: string; // ISO 8601 datetime
  is_suspicious: boolean;
  revoked_at: string | null; // ISO 8601 datetime or null
  is_active: boolean; // Computed field
  is_current: boolean; // Computed field
}

export interface UserSessionListResponse {
  sessions: UserSession[];
  total: number;
  current_session_id: number | null;
}

export interface RevokeAllSessionsRequest {
  current_session_id?: number;
}

// Helper types for UI
export interface SessionWithActions extends UserSession {
  // Add UI-specific fields if needed
  isRevoking?: boolean;
}

// Device type enum (matches backend)
export enum DeviceType {
  PC = "PC",
  Mobile = "Mobile",
  Tablet = "Tablet",
  Other = "Other",
}

// Session status for UI
export enum SessionStatus {
  Active = "active",
  Expired = "expired",
  Revoked = "revoked",
}

// Helper function to get session status
export function getSessionStatus(session: UserSession): SessionStatus {
  if (session.revoked_at) {
    return SessionStatus.Revoked;
  }
  
  const now = new Date();
  const expiresAt = new Date(session.expires_at);
  
  if (expiresAt < now) {
    return SessionStatus.Expired;
  }
  
  return SessionStatus.Active;
}

// Helper function to format device info
export function formatDeviceInfo(session: UserSession): string {
  const parts: string[] = [];
  
  if (session.device_type) {
    parts.push(session.device_type);
  }
  
  if (session.browser) {
    parts.push(session.browser);
  }
  
  if (session.os) {
    parts.push(`on ${session.os}`);
  }
  
  return parts.join(" • ") || "Unknown Device";
}

// Helper function to format location
export function formatLocation(session: UserSession): string {
  const parts: string[] = [];
  
  if (session.city) {
    parts.push(session.city);
  }
  
  if (session.country) {
    parts.push(session.country);
  }
  
  if (parts.length === 0 && session.ip_address) {
    return session.ip_address;
  }
  
  return parts.join(", ") || "Unknown Location";
}

// Helper function to get device icon name
export function getDeviceIcon(session: UserSession): string {
  switch (session.device_type?.toLowerCase()) {
    case "mobile":
      return "smartphone";
    case "tablet":
      return "tablet";
    case "pc":
    default:
      return "monitor";
  }
}

// Helper function to get relative time for PAST dates (created_at, last_activity_at)
export function getRelativeTime(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 1) {
    return "Just now";
  } else if (diffMins < 60) {
    return `${diffMins} minute${diffMins > 1 ? "s" : ""} ago`;
  } else if (diffHours < 24) {
    return `${diffHours} hour${diffHours > 1 ? "s" : ""} ago`;
  } else if (diffDays < 7) {
    return `${diffDays} day${diffDays > 1 ? "s" : ""} ago`;
  } else {
    return date.toLocaleDateString();
  }
}

// Helper function to get time until expiration for FUTURE dates (expires_at)
export function getTimeUntilExpiration(dateString: string): string {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = date.getTime() - now.getTime();

  // If already expired
  if (diffMs < 0) {
    return "Expired";
  }

  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 60) {
    return `in ${diffMins} minute${diffMins !== 1 ? "s" : ""}`;
  } else if (diffHours < 24) {
    return `in ${diffHours} hour${diffHours !== 1 ? "s" : ""}`;
  } else if (diffDays < 30) {
    return `in ${diffDays} day${diffDays !== 1 ? "s" : ""}`;
  } else {
    return `on ${date.toLocaleDateString()}`;
  }
}

