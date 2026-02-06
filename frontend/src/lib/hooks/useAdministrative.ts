// src/lib/hooks/useAdministrative.ts
/**
 * React Query hooks for administrative nodes.
 * Provides data fetching for adaptive address selection.
 */

import { useQuery } from "@tanstack/react-query";
import { administrativeApi, Province, District, Ward } from "../api/administrative";

// Query keys for cache management
export const administrativeQueryKeys = {
  provinces: ["administrative", "provinces"] as const,
  districts: (provinceCode: string) => ["administrative", "districts", provinceCode] as const,
  wards: (provinceCode: string, districtCode?: string | null) => 
    ["administrative", "wards", provinceCode, districtCode ?? "province-level"] as const,
};

/**
 * Fetch all provinces.
 */
export function useProvinces() {
  return useQuery<Province[]>({
    queryKey: administrativeQueryKeys.provinces,
    queryFn: () => administrativeApi.getProvinces(),
    staleTime: 1000 * 60 * 60, // 1 hour - provinces rarely change
  });
}

/**
 * Fetch districts under a province.
 * Only fetches when provinceCode is provided.
 * 
 * @param provinceCode - Province code to fetch districts for
 * @returns Districts or empty array if province uses 2-level structure
 */
export function useDistricts(provinceCode: string | undefined) {
  return useQuery<District[]>({
    queryKey: administrativeQueryKeys.districts(provinceCode!),
    queryFn: () => administrativeApi.getDistricts(provinceCode!),
    enabled: !!provinceCode,
    staleTime: 1000 * 60 * 60, // 1 hour
  });
}

/**
 * Fetch wards based on selection mode.
 * 
 * Adaptive Logic:
 * - If districtCode is provided: 3-level wards under district
 * - If districtCode is null/undefined: 2-level wards under province
 * 
 * @param provinceCode - Required province code
 * @param districtCode - Optional district code (null for 2-level)
 */
export function useWards(
  provinceCode: string | undefined, 
  districtCode?: string | null
) {
  return useQuery<Ward[]>({
    queryKey: administrativeQueryKeys.wards(provinceCode!, districtCode),
    queryFn: () => administrativeApi.getWards(provinceCode!, districtCode),
    enabled: !!provinceCode,
    staleTime: 1000 * 60 * 30, // 30 minutes
  });
}
