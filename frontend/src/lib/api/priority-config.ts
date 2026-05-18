/**
 * Priority Config API Client — admin CRUD for KV/UT bonus rates.
 *
 * Mirrors `Backend_FastAPI/app/routers/admin_priority_config.py`. All
 * endpoints sit behind `require_admin` so a non-admin user hitting any
 * function will see a 403 from the backend.
 *
 * Endpoint base: `/api/v2/admin/priority-config`
 */

import { api } from "@/lib/api/client"

import type {
  PriorityAreaConfigCreate,
  PriorityAreaConfigResponse,
  PriorityAreaConfigUpdate,
  PriorityConfigCloneRequest,
  PriorityConfigCloneResponse,
  PriorityConfigSeedDefaultsRequest,
  PriorityConfigSeedDefaultsResponse,
  PriorityObjectConfigCreate,
  PriorityObjectConfigResponse,
  PriorityObjectConfigUpdate,
} from "@/lib/zod/priority-config"

const BASE = "/api/v2/admin/priority-config"

// ============================================
// AREAS (KV)
// ============================================

export async function listAreas(
  academicYear: number,
  activeOnly: boolean = true,
): Promise<PriorityAreaConfigResponse[]> {
  const response = await api.get<PriorityAreaConfigResponse[]>(
    `${BASE}/years/${academicYear}/areas`,
    { params: { active_only: activeOnly } },
  )
  return response.data
}

export async function createArea(
  academicYear: number,
  payload: PriorityAreaConfigCreate,
): Promise<PriorityAreaConfigResponse> {
  // BE forces academic_year = path param (router strips body value),
  // but we still post the full shape for Pydantic validation parity.
  const response = await api.post<PriorityAreaConfigResponse>(
    `${BASE}/years/${academicYear}/areas`,
    payload,
  )
  return response.data
}

export async function updateArea(
  areaId: number,
  payload: PriorityAreaConfigUpdate,
): Promise<PriorityAreaConfigResponse> {
  const response = await api.patch<PriorityAreaConfigResponse>(
    `${BASE}/areas/${areaId}`,
    payload,
  )
  return response.data
}

export async function retireArea(
  areaId: number,
): Promise<PriorityAreaConfigResponse> {
  const response = await api.delete<PriorityAreaConfigResponse>(
    `${BASE}/areas/${areaId}`,
  )
  return response.data
}

// ============================================
// OBJECTS (UT)
// ============================================

export async function listObjects(
  academicYear: number,
  activeOnly: boolean = true,
): Promise<PriorityObjectConfigResponse[]> {
  const response = await api.get<PriorityObjectConfigResponse[]>(
    `${BASE}/years/${academicYear}/objects`,
    { params: { active_only: activeOnly } },
  )
  return response.data
}

export async function createObject(
  academicYear: number,
  payload: PriorityObjectConfigCreate,
): Promise<PriorityObjectConfigResponse> {
  const response = await api.post<PriorityObjectConfigResponse>(
    `${BASE}/years/${academicYear}/objects`,
    payload,
  )
  return response.data
}

export async function updateObject(
  objectId: number,
  payload: PriorityObjectConfigUpdate,
): Promise<PriorityObjectConfigResponse> {
  const response = await api.patch<PriorityObjectConfigResponse>(
    `${BASE}/objects/${objectId}`,
    payload,
  )
  return response.data
}

export async function retireObject(
  objectId: number,
): Promise<PriorityObjectConfigResponse> {
  const response = await api.delete<PriorityObjectConfigResponse>(
    `${BASE}/objects/${objectId}`,
  )
  return response.data
}

// ============================================
// CLONE + SEED HELPERS
// ============================================

export async function cloneFromYear(
  payload: PriorityConfigCloneRequest,
): Promise<PriorityConfigCloneResponse> {
  const response = await api.post<PriorityConfigCloneResponse>(
    `${BASE}/clone`,
    payload,
  )
  return response.data
}

export async function seedTt052021Defaults(
  payload: PriorityConfigSeedDefaultsRequest,
): Promise<PriorityConfigSeedDefaultsResponse> {
  const response = await api.post<PriorityConfigSeedDefaultsResponse>(
    `${BASE}/seed-defaults`,
    payload,
  )
  return response.data
}

export const priorityConfigApi = {
  listAreas,
  createArea,
  updateArea,
  retireArea,
  listObjects,
  createObject,
  updateObject,
  retireObject,
  cloneFromYear,
  seedTt052021Defaults,
}

export default priorityConfigApi
