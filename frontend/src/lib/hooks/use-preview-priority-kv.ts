/**
 * React Query hook — live KV preview (Q9 #07 Phase D.4)
 *
 * Debounced auto-fetch khi candidate edit cultural/vocational/history.
 * Stale time 0 — always fresh per form state. Keep previous data trong khi
 * fetching để avoid flicker badge.
 */
import { useQuery, keepPreviousData } from "@tanstack/react-query"
import { useEffect, useState } from "react"
import {
  priorityKvApi,
  type PreviewPriorityKvRequest,
  type PreviewPriorityKvResponse,
} from "../api/priority-kv"

export const priorityKvQueryKeys = {
  preview: (profileId: number, body: PreviewPriorityKvRequest) =>
    [
      "priority-kv-preview",
      profileId,
      body.cultural_education_level ?? null,
      body.vocational_qualification ?? null,
      body.area_resolution_basis ?? null,
      body.permanent_commune_code ?? null,
      JSON.stringify(body.academic_history ?? []),
      JSON.stringify(body.priority_object_codes ?? []),
    ] as const,
}

function useDebounced<T>(value: T, delay = 500): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delay)
    return () => clearTimeout(t)
  }, [value, delay])
  return debounced
}

/**
 * Live KV preview hook.
 *
 * @param profileId — admission profile ID
 * @param formState — current form snapshot (cultural/vocational/history/etc.)
 * @param enabled — opt-out flag (e.g., when form invalid)
 *
 * @example
 * const { data, isLoading } = usePreviewPriorityKv(profileId, {
 *   cultural_education_level: form.watch("cultural_education_level"),
 *   vocational_qualification: form.watch("vocational_qualification"),
 *   academic_history: form.watch("academic_history"),
 * })
 */
export function usePreviewPriorityKv(
  profileId: number,
  formState: PreviewPriorityKvRequest,
  enabled: boolean = true,
) {
  const debounced = useDebounced(formState, 500)

  return useQuery<PreviewPriorityKvResponse>({
    queryKey: priorityKvQueryKeys.preview(profileId, debounced),
    queryFn: () => priorityKvApi.preview(profileId, debounced),
    enabled: enabled && !!profileId,
    staleTime: 0,
    placeholderData: keepPreviousData,
    retry: 1,
  })
}
