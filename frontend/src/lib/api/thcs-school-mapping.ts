/**
 * API client — công cụ ghép tên trường THCS gõ tay (owner 22-11).
 *
 * Mirror `Backend_FastAPI/app/routers/admin_thcs_school_mapping.py` (danh mục,
 * `/api/v2/admin/vn-school/thcs-mapping`) và
 * `Backend_FastAPI/app/routers/admissions_thcs_school_mapping.py` (áp ghép,
 * `/api/v2/admissions/thcs-school-mapping/apply` — bị cần gạt đóng băng chặn).
 * Tất cả chỉ Admin.
 */

import { api } from "@/lib/api/client"

import type {
  ThcsCreateSchoolFromGroup,
  ThcsCreateSchoolFromGroupResponse,
  ThcsMappingApplyRequest,
  ThcsMappingApplyResult,
  ThcsMappingResponse,
  ThcsMapRequest,
  ThcsNameGroupListResponse,
} from "@/lib/zod/thcs-school-mapping"

const BASE = "/api/v2/admin/vn-school/thcs-mapping"
const APPLY = "/api/v2/admissions/thcs-school-mapping/apply"

export interface ListThcsGroupsParams {
  page?: number
  pageSize?: number
  /** true = đã ghép · false = chưa ghép · undefined = tất cả */
  mapped?: boolean
}

export async function listThcsGroups(
  params: ListThcsGroupsParams = {},
): Promise<ThcsNameGroupListResponse> {
  const { data } = await api.get<ThcsNameGroupListResponse>(`${BASE}/groups`, {
    params: {
      page: params.page ?? 1,
      page_size: params.pageSize ?? 50,
      mapped: params.mapped,
    },
  })
  return data
}

export async function mapThcsGroup(
  payload: ThcsMapRequest,
): Promise<ThcsMappingResponse> {
  const { data } = await api.post<ThcsMappingResponse>(
    `${BASE}/groups/map`,
    payload,
  )
  return data
}

export async function unmapThcsGroup(
  normalizedName: string,
): Promise<{ normalized_name: string; school_id: number }> {
  const { data } = await api.post<{ normalized_name: string; school_id: number }>(
    `${BASE}/groups/unmap`,
    { normalized_name: normalizedName },
  )
  return data
}

export async function createSchoolFromThcsGroup(
  payload: ThcsCreateSchoolFromGroup,
): Promise<ThcsCreateSchoolFromGroupResponse> {
  const { data } = await api.post<ThcsCreateSchoolFromGroupResponse>(
    `${BASE}/groups/create-school`,
    payload,
  )
  return data
}

/** Mặc định CHẠY THỬ (dry_run=true). Chạy thật cần cờ BE + số của lượt chạy thử. */
export async function applyThcsMapping(
  payload: ThcsMappingApplyRequest,
): Promise<ThcsMappingApplyResult> {
  const { data } = await api.post<ThcsMappingApplyResult>(APPLY, payload)
  return data
}

export const thcsSchoolMappingApi = {
  listThcsGroups,
  mapThcsGroup,
  unmapThcsGroup,
  createSchoolFromThcsGroup,
  applyThcsMapping,
}

export default thcsSchoolMappingApi
