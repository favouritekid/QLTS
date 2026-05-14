/**
 * System Config API client (Phase 1 PR-1D / phase1_13).
 *
 * Mirrors backend ``app/routers/admin_v2_system_config.py``:
 *   GET    /api/v2/admin/system-config
 *   GET    /api/v2/admin/system-config/{key}
 *   PATCH  /api/v2/admin/system-config/{key}
 *
 * Sensitive keys MUST NOT live here (env / secrets). Service guard
 * allows read for any active user but write requires admin.
 */
import { api } from "@/lib/api/client"
import type {
  SystemConfigListResponse,
  SystemConfigResponse,
  SystemConfigUpdate,
} from "@/lib/zod/system-config"

const BASE = "/api/v2/admin/system-config"

export async function listSystemConfig(): Promise<SystemConfigListResponse> {
  const res = await api.get<SystemConfigListResponse>(BASE)
  return res.data
}

export async function getSystemConfig(key: string): Promise<SystemConfigResponse> {
  const res = await api.get<SystemConfigResponse>(`${BASE}/${encodeURIComponent(key)}`)
  return res.data
}

export async function updateSystemConfig(
  key: string,
  payload: SystemConfigUpdate
): Promise<SystemConfigResponse> {
  const res = await api.patch<SystemConfigResponse>(
    `${BASE}/${encodeURIComponent(key)}`,
    payload
  )
  return res.data
}
