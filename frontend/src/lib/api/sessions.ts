// src/lib/api/sessions.ts
/**
 * Session management API functions
 */
import { api } from "./client";
import { API_ENDPOINTS } from "./endpoints";
import type { UserSession } from "@/types/session";

export interface UserSessionListResponse {
  sessions: UserSession[];
  total: number;
  current_session_id: number | null;
}

/**
 * Get all active sessions for the current user
 */
export async function getActiveSessions(): Promise<UserSessionListResponse> {
  const response = await api.get<UserSessionListResponse>(API_ENDPOINTS.SESSIONS.LIST);
  return response.data;
}

/**
 * Revoke a specific session by ID
 */
export async function revokeSession(sessionId: number): Promise<void> {
  await api.delete(API_ENDPOINTS.SESSIONS.REVOKE(sessionId));
}

/**
 * Revoke all other sessions except the current one
 */
export async function revokeAllOtherSessions(currentSessionId?: number): Promise<void> {
  await api.post(API_ENDPOINTS.SESSIONS.REVOKE_ALL, {
    current_session_id: currentSessionId || null,
  });
}
