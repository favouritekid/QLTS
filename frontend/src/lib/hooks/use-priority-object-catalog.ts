/**
 * React Query hook — UT (đối tượng ưu tiên) catalog (Q9 #07 Phase E wireframe)
 *
 * Wraps `GET /api/v2/admissions/priority-objects/catalog?academic_year=`.
 * Catalog is org-wide reference data, ít thay đổi → stale time dài + cache key
 * per academic_year để FE share entries giữa multiple candidate forms.
 */
import { useQuery } from "@tanstack/react-query"

import {
  priorityObjectsApi,
  type PriorityObjectCatalogItem,
} from "../api/priority-objects"

export const priorityObjectCatalogQueryKeys = {
  all: ["priority-object-catalog"] as const,
  year: (academicYear: number) =>
    [...priorityObjectCatalogQueryKeys.all, academicYear] as const,
}

/**
 * Fetch UT catalog cho năm tuyển sinh.
 *
 * @param academicYear — VD 2026
 * @param enabled — opt-out (mặc định true)
 *
 * @example
 * const { data: catalog = [], isLoading } = useUtCatalog(2026)
 */
export function useUtCatalog(
  academicYear: number,
  enabled: boolean = true,
) {
  return useQuery<PriorityObjectCatalogItem[]>({
    queryKey: priorityObjectCatalogQueryKeys.year(academicYear),
    queryFn: () => priorityObjectsApi.getCatalog(academicYear),
    enabled: enabled && Number.isFinite(academicYear),
    staleTime: 5 * 60 * 1000, // 5min — catalog ít đổi
    retry: 1,
  })
}
