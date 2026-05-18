/**
 * VnSchool API client (Q9 #07 Phase D.0b)
 *
 * Wraps GET /api/v2/vn-school/search for candidate FE dropdown.
 * Backend service: app/services/vn_school_service.py.
 */
import { api } from "@/lib/api/client"

export interface VnSchoolSearchItem {
  id: number
  moet_school_code: string
  moet_province_code: string
  name: string
  address: string | null
  province: string
  district: string | null
  level: string
  is_dtnt: boolean
  current_kv: string | null
}

export interface VnSchoolSearchResponse {
  items: VnSchoolSearchItem[]
  total: number
  limit: number
  offset: number
}

export interface VnSchoolSearchParams {
  q: string
  level?: string
  province?: string
  limit?: number
  offset?: number
}

export const vnSchoolApi = {
  async search(params: VnSchoolSearchParams): Promise<VnSchoolSearchResponse> {
    const { data } = await api.get<VnSchoolSearchResponse>(
      "/api/v2/vn-school/search",
      {
        params: {
          q: params.q,
          level: params.level,
          province: params.province,
          limit: params.limit ?? 20,
          offset: params.offset ?? 0,
        },
      }
    )
    return data
  },
}
