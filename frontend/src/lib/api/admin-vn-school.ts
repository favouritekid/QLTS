/**
 * Admin VN School API Client (PR-B).
 *
 * Mirrors `Backend_FastAPI/app/routers/admin_vn_school.py`. All `require_admin`.
 * Base: `/api/v2/admin/vn-school`. DELETE school = deactivate (BE).
 */

import { api } from "@/lib/api/client"

import type {
  CsvImportResponse,
  KvAssignmentCreate,
  KvAssignmentResponse,
  KvAssignmentUpdate,
  SchoolCreate,
  SchoolListResponse,
  SchoolProvince,
  SchoolResponse,
  SchoolUpdate,
} from "@/lib/zod/vn-school-admin"

const BASE = "/api/v2/admin/vn-school"

export interface ListSchoolsParams {
  moetProvinceCode?: string | null
  level?: string | null
  q?: string | null
  activeOnly?: boolean
  page?: number
  pageSize?: number
}

export async function listSchools(
  params: ListSchoolsParams = {},
): Promise<SchoolListResponse> {
  const { data } = await api.get<SchoolListResponse>(`${BASE}/schools`, {
    params: {
      moet_province_code: params.moetProvinceCode || undefined,
      level: params.level || undefined,
      q: params.q || undefined,
      active_only: params.activeOnly ?? true,
      page: params.page ?? 1,
      page_size: params.pageSize ?? 50,
    },
  })
  return data
}

export async function listSchoolProvinces(): Promise<SchoolProvince[]> {
  const { data } = await api.get<SchoolProvince[]>(`${BASE}/provinces`)
  return data
}

export async function createSchool(
  payload: SchoolCreate,
): Promise<SchoolResponse> {
  const { data } = await api.post<SchoolResponse>(`${BASE}/schools`, payload)
  return data
}

export async function updateSchool(
  id: number,
  payload: SchoolUpdate,
): Promise<SchoolResponse> {
  const { data } = await api.patch<SchoolResponse>(
    `${BASE}/schools/${id}`,
    payload,
  )
  return data
}

/** DELETE = deactivate (is_active=false). */
export async function deactivateSchool(id: number): Promise<SchoolResponse> {
  const { data } = await api.delete<SchoolResponse>(`${BASE}/schools/${id}`)
  return data
}

export async function importSchoolCsv(file: File): Promise<CsvImportResponse> {
  const fd = new FormData()
  fd.append("file", file)
  const { data } = await api.post<CsvImportResponse>(
    `${BASE}/schools/import`,
    fd,
    { headers: { "Content-Type": "multipart/form-data" } },
  )
  return data
}

// --- KV assignment ---

export async function listKvAssignments(
  schoolId: number,
): Promise<KvAssignmentResponse[]> {
  const { data } = await api.get<KvAssignmentResponse[]>(
    `${BASE}/schools/${schoolId}/kv`,
  )
  return data
}

export async function addKvAssignment(
  schoolId: number,
  payload: KvAssignmentCreate,
): Promise<KvAssignmentResponse> {
  const { data } = await api.post<KvAssignmentResponse>(
    `${BASE}/schools/${schoolId}/kv`,
    payload,
  )
  return data
}

export async function updateKvAssignment(
  assignmentId: number,
  payload: KvAssignmentUpdate,
): Promise<KvAssignmentResponse> {
  const { data } = await api.patch<KvAssignmentResponse>(
    `${BASE}/kv/${assignmentId}`,
    payload,
  )
  return data
}

export async function deleteKvAssignment(assignmentId: number): Promise<void> {
  await api.delete(`${BASE}/kv/${assignmentId}`)
}

export const adminVnSchoolApi = {
  listSchools,
  listSchoolProvinces,
  createSchool,
  updateSchool,
  deactivateSchool,
  importSchoolCsv,
  listKvAssignments,
  addKvAssignment,
  updateKvAssignment,
  deleteKvAssignment,
}

export default adminVnSchoolApi
