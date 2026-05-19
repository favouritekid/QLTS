/**
 * React Query hook for VnSchool search (Q9 #07 Phase D.0b)
 *
 * Use trong candidate FE AcademicHistoryTab dropdown autocomplete.
 * Debounced via consumer side (use-debounce or manual setState debounce).
 */
import { useQuery, keepPreviousData } from "@tanstack/react-query"
import {
  vnSchoolApi,
  type VnSchoolSearchParams,
  type VnSchoolSearchResponse,
} from "../api/vn-school"

export const vnSchoolQueryKeys = {
  search: (params: VnSchoolSearchParams) =>
    [
      "vn-school",
      "search",
      params.q,
      params.level ?? null,
      params.province ?? null,
      params.limit ?? 20,
      params.offset ?? 0,
    ] as const,
}

/**
 * Search VnSchool entries (diacritic-insensitive).
 *
 * Query MUST be >= 2 chars; otherwise hook stays disabled.
 *
 * @example
 * const { data, isLoading } = useVnSchoolSearch({ q: debouncedQ, level: "THPT" })
 */
export function useVnSchoolSearch(params: VnSchoolSearchParams) {
  const enabled = !!params.q && params.q.length >= 2
  return useQuery<VnSchoolSearchResponse>({
    queryKey: vnSchoolQueryKeys.search(params),
    queryFn: () => vnSchoolApi.search(params),
    enabled,
    staleTime: 1000 * 60 * 5, // 5 min cache (school directory is read-mostly)
    placeholderData: keepPreviousData,
  })
}
