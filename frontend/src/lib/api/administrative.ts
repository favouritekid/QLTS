// src/lib/api/administrative.ts
/**
 * API client for administrative nodes (provinces, districts, wards).
 * Supports adaptive 2-level/3-level address selection.
 */

import { api } from "./client";

// Types
export interface Province {
  code: string;
  name: string;
  valid_from: string;
  valid_to: string | null;
  is_current: boolean;
}

export interface District {
  code: string;
  name: string;
  province_code: string;
}

export interface Ward {
  code: string;
  name: string;
  province_code: string;
  district_code: string | null;  // NULL for 2-level structure
}

export const administrativeApi = {
  /**
   * Get all selectable provinces/cities, including legacy province codes
   * needed for historical 3-level household-address lookup.
   */
  getProvinces: async (): Promise<Province[]> => {
    const { data } = await api.get<Province[]>(`/api/administrative/provinces`);
    return data;
  },

  /**
   * Get districts under a province.
   * Only returns districts for OLD (3-level) structure.
   * If empty, skip district selection and go directly to wards.
   */
  getDistricts: async (provinceCode: string): Promise<District[]> => {
    const { data } = await api.get<District[]>(`/api/administrative/districts`, {
      params: { province_code: provinceCode }
    });
    return data;
  },

  /**
   * Get wards based on selection mode.
   * 
   * @param provinceCode - Required province code
   * @param districtCode - Optional district code
   *   - If provided: Returns wards under that district (3-level)
   *   - If null/undefined: Returns wards directly under province (2-level)
   */
  getWards: async (provinceCode: string, districtCode?: string | null): Promise<Ward[]> => {
    const params: Record<string, string> = { province_code: provinceCode };
    if (districtCode) {
      params.district_code = districtCode;
    }
    const { data } = await api.get<Ward[]>(`/api/administrative/wards`, { params });
    return data;
  },
};
