// src/lib/hooks/useAdministrative.ts
/**
 * React Query hooks for administrative nodes.
 *
 * All province/ward hooks accept an explicit `mode` ("current" | "legacy")
 * so the frontend never mixes the two administrative snapshots.
 */

import { useQuery } from "@tanstack/react-query"
import {
  administrativeApi,
  type AddressMode,
  type Province,
  type District,
  type Ward,
  type ResolvedWard,
} from "../api/administrative"

export const administrativeQueryKeys = {
  provinces: (mode: AddressMode) => ["administrative", "provinces", mode] as const,
  districts: (provinceCode: string) =>
    ["administrative", "districts", provinceCode] as const,
  wards: (provinceCode: string, mode: AddressMode, districtCode?: string | null) =>
    ["administrative", "wards", provinceCode, mode, districtCode ?? "none"] as const,
  resolveWard: (code: string | null | undefined) =>
    ["administrative", "resolve-ward", code ?? "none"] as const,
}

export function useProvinces(mode: AddressMode) {
  return useQuery<Province[]>({
    queryKey: administrativeQueryKeys.provinces(mode),
    queryFn: () => administrativeApi.getProvinces(mode),
    staleTime: 1000 * 60 * 60, // 1 hour
  })
}

/** Districts only exist in legacy mode. */
export function useDistricts(provinceCode: string | undefined, enabled = true) {
  return useQuery<District[]>({
    queryKey: administrativeQueryKeys.districts(provinceCode!),
    queryFn: () => administrativeApi.getDistricts(provinceCode!),
    enabled: !!provinceCode && enabled,
    staleTime: 1000 * 60 * 60,
  })
}

export function useWards(
  provinceCode: string | undefined,
  mode: AddressMode,
  districtCode?: string | null,
) {
  return useQuery<Ward[]>({
    queryKey: administrativeQueryKeys.wards(provinceCode!, mode, districtCode),
    queryFn: () => administrativeApi.getWards(provinceCode!, mode, districtCode),
    enabled: !!provinceCode,
    staleTime: 1000 * 60 * 30,
  })
}

/**
 * Resolve a ward code (current OR legacy 3-tier) → canonical CURRENT-era commune
 * (code + name). Keyed on the code so it auto-fetches both on load (hydrate an
 * existing profile's `permanent_commune_code`) and whenever the officer re-picks
 * — no imperative state needed. Disabled (returns no data) when `code` is empty.
 *
 * Drives the "→ Xã X (hiện hành)" badge so the officer always sees which current
 * commune an old/legacy ward maps to, instead of a generic "đã chuẩn hóa" hint.
 */
export function useResolveWard(code: string | null | undefined) {
  return useQuery<ResolvedWard>({
    queryKey: administrativeQueryKeys.resolveWard(code),
    queryFn: () => administrativeApi.resolveWard(code!),
    enabled: !!code,
    staleTime: 1000 * 60 * 30,
  })
}
