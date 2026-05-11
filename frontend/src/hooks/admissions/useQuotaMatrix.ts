// frontend/src/hooks/admissions/useQuotaMatrix.ts
// Phase 2 v8.2 PR-2D.1 v2 — React Query hooks cho quota matrix.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  getPathMatrixByMajor,
  getQuotaMatrix,
  updatePathQuota,
  type AdmissionPathQuotaUpdate,
} from "@/lib/api/quota-matrix"

import { admissionPathKeys } from "./useAdmissionPaths"

export const quotaMatrixKeys = {
  all: ["quota-matrix"] as const,
  byYear: (year: number) => [...quotaMatrixKeys.all, "year", year] as const,
  byMajor: (academicInfoId: number) =>
    [...quotaMatrixKeys.all, "major", academicInfoId] as const,
}

export function usePathMatrixByMajor(academicInfoId: number | undefined) {
  return useQuery({
    queryKey: quotaMatrixKeys.byMajor(academicInfoId ?? 0),
    queryFn: () => getPathMatrixByMajor(academicInfoId!),
    enabled: !!academicInfoId,
    staleTime: 30 * 1000,
  })
}

export function useQuotaMatrix(academicYear: number | undefined) {
  return useQuery({
    queryKey: quotaMatrixKeys.byYear(academicYear ?? 0),
    queryFn: () => getQuotaMatrix(academicYear!),
    enabled: !!academicYear,
    staleTime: 30 * 1000, // 30s
  })
}

export function useUpdatePathQuota() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      pathId,
      data,
    }: {
      pathId: number
      data: AdmissionPathQuotaUpdate
    }) => updatePathQuota(pathId, data),
    onSuccess: (_result, variables) => {
      // Invalidate path detail to refetch fresh quota — fixes drawer reopen
      // showing stale empty inputs after save (parity với
      // useUpdatePathDocuments:199-200 pattern; useUpdateAdmissionPath
      // dùng setQueryData được vì BE return full path, ở đây response
      // shape untyped nên invalidate an toàn hơn).
      queryClient.invalidateQueries({
        queryKey: admissionPathKeys.detail(variables.pathId),
      })
      queryClient.invalidateQueries({ queryKey: quotaMatrixKeys.all })
    },
  })
}
