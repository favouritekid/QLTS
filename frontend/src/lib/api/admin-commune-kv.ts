/**
 * Admin Commune KV API Client (PR-A).
 *
 * Mirrors `Backend_FastAPI/app/routers/admin_vn_locality.py` commune CRUD.
 * All endpoints sit behind `require_admin`. Base: `/api/v2/admin/vn-locality`.
 */

import { api } from "@/lib/api/client"

import type {
  CommuneAreaCreate,
  CommuneAreaListResponse,
  CommuneAreaResponse,
  CommuneAreaUpdate,
  CommuneReplaceArea,
  CsvImportResponse,
} from "@/lib/zod/commune-kv"

const BASE = "/api/v2/admin/vn-locality"

export interface ListCommunesParams {
  province?: string | null
  q?: string | null
  activeOnly?: boolean
  page?: number
  pageSize?: number
}

export async function listCommunes(
  params: ListCommunesParams = {},
): Promise<CommuneAreaListResponse> {
  const { data } = await api.get<CommuneAreaListResponse>(`${BASE}/communes`, {
    params: {
      // province = TÊN tỉnh (vn_commune_area_map.province là text), KHÔNG mã.
      province: params.province || undefined,
      q: params.q || undefined,
      active_only: params.activeOnly ?? true,
      page: params.page ?? 1,
      page_size: params.pageSize ?? 50,
    },
  })
  return data
}

export async function createCommune(
  payload: CommuneAreaCreate,
): Promise<CommuneAreaResponse> {
  const { data } = await api.post<CommuneAreaResponse>(
    `${BASE}/communes`,
    payload,
  )
  return data
}

export async function updateCommune(
  id: number,
  payload: CommuneAreaUpdate,
): Promise<CommuneAreaResponse> {
  const { data } = await api.patch<CommuneAreaResponse>(
    `${BASE}/communes/${id}`,
    payload,
  )
  return data
}

/** Đổi KV temporal — trả dòng active MỚI (BE retire dòng cũ). */
export async function replaceCommuneArea(
  id: number,
  payload: CommuneReplaceArea,
): Promise<CommuneAreaResponse> {
  const { data } = await api.post<CommuneAreaResponse>(
    `${BASE}/communes/${id}/replace-area`,
    payload,
  )
  return data
}

export async function retireCommune(
  id: number,
): Promise<CommuneAreaResponse> {
  const { data } = await api.delete<CommuneAreaResponse>(
    `${BASE}/communes/${id}`,
  )
  return data
}

export async function importCommuneCsv(
  file: File,
): Promise<CsvImportResponse> {
  const fd = new FormData()
  fd.append("file", file)
  const { data } = await api.post<CsvImportResponse>(
    `${BASE}/communes/import`,
    fd,
    { headers: { "Content-Type": "multipart/form-data" } },
  )
  return data
}

export const adminCommuneKvApi = {
  listCommunes,
  createCommune,
  updateCommune,
  replaceCommuneArea,
  retireCommune,
  importCommuneCsv,
}

export default adminCommuneKvApi
