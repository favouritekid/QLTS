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
}
