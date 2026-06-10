// src/lib/api/administrative.ts
/**
 * API client for administrative nodes (provinces, districts, wards).
 *
 * Two explicit modes:
 * - "current": 34 provinces, 2-level (province → ward), post 01/07/2025
 * - "legacy":  63 provinces, 3-level (province → district → ward), pre 01/07/2025
 */

import { api } from "./client"

export type AddressMode = "current" | "legacy"

export interface Province {
  code: string
  name: string
}

export interface District {
  code: string
  name: string
  province_code: string
}

export interface Ward {
  code: string
  name: string
  province_code: string
  district_code: string | null
}

export interface ResolvedWard {
  input_code: string
  current_code: string | null
  current_name: string | null
  /** Province (current 2-level era) the resolved commune belongs to — for showing
   *  the full standardized address "Xã X, Tỉnh Y". */
  current_province_name: string | null
  resolved: boolean
}

export const administrativeApi = {
  getProvinces: async (mode: AddressMode = "current"): Promise<Province[]> => {
    const { data } = await api.get<Province[]>("/api/administrative/provinces", {
      params: { mode },
    })
    return data
  },

  /** Districts only exist in legacy mode. */
  getDistricts: async (provinceCode: string): Promise<District[]> => {
    const { data } = await api.get<District[]>("/api/administrative/districts", {
      params: { province_code: provinceCode },
    })
    return data
  },

  getWards: async (
    provinceCode: string,
    mode: AddressMode = "current",
    districtCode?: string | null,
  ): Promise<Ward[]> => {
    const params: Record<string, string> = {
      province_code: provinceCode,
      mode,
    }
    if (districtCode) {
      params.district_code = districtCode
    }
    const { data } = await api.get<Ward[]>("/api/administrative/wards", { params })
    return data
  },

  /**
   * PR-3: resolve any ward code (current or legacy 3-tier) → canonical CURRENT
   * commune. Used when an officer picks an address (esp. from an old document)
   * so the UI can show the current commune; the BE also canonicalizes on save.
   */
  resolveWard: async (code: string): Promise<ResolvedWard> => {
    const { data } = await api.get<ResolvedWard>(
      "/api/administrative/resolve-ward",
      { params: { code } },
    )
    return data
  },
}
