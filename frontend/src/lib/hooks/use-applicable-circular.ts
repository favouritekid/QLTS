/**
 * React Query mutation hook — đổi thông tư áp dụng (V3).
 *
 * Cache parity như `use-priority-override.ts`: setQueryData + invalidate
 * detail key, và làm mới preview KV (câu căn cứ + cảnh báo đi theo thông tư).
 */
import { useMutation, useQueryClient } from "@tanstack/react-query"

import { applicableCircularApi } from "@/lib/api/applicable-circular"
import { admissionsKeys } from "@/hooks/admissions/useAdmissions"
import type {
  AdmissionProfileResponse,
  ApplicableCircularChangeRequest,
} from "@/lib/zod/admissions"

export function useChangeApplicableCircular(profileId: number) {
  const queryClient = useQueryClient()

  return useMutation<AdmissionProfileResponse, Error, ApplicableCircularChangeRequest>({
    mutationFn: (body) => applicableCircularApi.change(profileId, body),
    onSuccess: async (updated) => {
      const detailKey = admissionsKeys.detail(profileId)
      queryClient.setQueryData(detailKey, updated)
      await queryClient.invalidateQueries({ queryKey: detailKey })
      await queryClient.invalidateQueries({
        predicate: (query) =>
          Array.isArray(query.queryKey) &&
          query.queryKey[0] === "priority-kv-preview" &&
          query.queryKey[1] === profileId,
      })
    },
  })
}
