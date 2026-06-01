/**
 * useAdmissionPaths Hook
 * 
 * React Query hooks for Admission Path data fetching.
 * 
 * Phase B.1: Create hook for LeadApplicationForm to fetch paths with criteria.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { 
  getPathsForOffering, 
  getAdmissionPath,
  createAdmissionPath,
  updateAdmissionPath,
  activateAdmissionPath,
  deactivateAdmissionPath,

  updateCriteria,
  updatePathDocuments,
  getCoverageMatrix,
  getPathDocuments,
} from "@/lib/api/admission-paths"
import type { 
  AdmissionPathCreate, 
  AdmissionPathUpdate,
  AdmissionCriteriaCreate,
  AdmissionPathDocumentUpsert,
} from "@/lib/zod/admission-path"

// ============================================
// QUERY KEYS
// ============================================

export const admissionPathKeys = {
  all: ["admission-paths"] as const,
  // `lists()` factory đã gỡ (PR matrix-funnel cleanup): sau khi PR-2 bỏ màn
  // list legacy + useAdmissionPathsByAcademicInfo, KHÔNG còn query nào dưới
  // prefix .lists(); readiness sống dưới coverageMatrix (đã nằm dưới .all).
  forOffering: (offeringId: number) => [...admissionPathKeys.all, "for-offering", offeringId] as const,
  details: () => [...admissionPathKeys.all, "detail"] as const,
  detail: (pathId: number) => [...admissionPathKeys.details(), pathId] as const,
  coverageMatrix: (academicInfoId: number) => [...admissionPathKeys.all, "coverage-matrix", academicInfoId] as const,
  documents: (pathId: number) => [...admissionPathKeys.all, "documents", pathId] as const,
}

// ============================================
// READ HOOKS
// ============================================

/**
 * Hook to fetch ACTIVE admission paths for an offering.
 * 
 * Used by LeadApplicationForm to:
 * - Populate "Phương thức xét tuyển" dropdown
 * - Initialize subject scores based on path.criteria.subject_groups
 */
export function useAdmissionPathsForOffering(offeringId: number | undefined) {
  return useQuery({
    queryKey: admissionPathKeys.forOffering(offeringId ?? 0),
    queryFn: () => getPathsForOffering(offeringId!),
    enabled: !!offeringId,
    staleTime: 5 * 60 * 1000, // 5 minutes
  })
}

/**
 * Hook to fetch single path by ID.
 * staleTime: 0 ensures fresh data in wizard edit mode
 */
export function useAdmissionPath(pathId: number | undefined) {
  return useQuery({
    queryKey: admissionPathKeys.detail(pathId ?? 0),
    queryFn: () => getAdmissionPath(pathId!),
    enabled: !!pathId,
    staleTime: 0, // Always fetch fresh data for wizard
    refetchOnMount: true, // Refetch when component mounts
  })
}

/**
 * Hook to fetch coverage matrix for paths audit.
 */
export function useCoverageMatrix(academicInfoId: number | undefined) {
  return useQuery({
    queryKey: admissionPathKeys.coverageMatrix(academicInfoId ?? 0),
    queryFn: () => getCoverageMatrix(academicInfoId!),
    enabled: !!academicInfoId,
  })
}

// ============================================
// MUTATION HOOKS
// ============================================

/**
 * Hook to fetch resolved documents for a path.
 */
export function usePathDocuments(pathId: number | undefined) {
  return useQuery({
    queryKey: admissionPathKeys.documents(pathId ?? 0),
    queryFn: () => getPathDocuments(pathId!),
    enabled: !!pathId,
    staleTime: 0, // Always fresh for wizard
  })
}

/**
 * Hook to create admission path.
 */
export function useCreateAdmissionPath() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (data: AdmissionPathCreate) => createAdmissionPath(data),
    onSuccess: () => {
      // Invalidate toàn bộ admission-paths: list + coverage-matrix (readiness mode
      // dùng admissionPathKeys.coverageMatrix, KHÔNG nằm dưới .lists()).
      queryClient.invalidateQueries({ queryKey: admissionPathKeys.all })
      // Invalidate academic infos to update admission_status (READY → CONFIGURED)
      queryClient.invalidateQueries({ queryKey: ["academic-infos"] })
      // Invalidate quota matrix (by-major + by-year) — màn chính của Phase 3 sau
      // khi gỡ lối cũ. Raw literal = quotaMatrixKeys.all, tránh circular import
      // (useQuotaMatrix đã import admissionPathKeys từ file này).
      queryClient.invalidateQueries({ queryKey: ["quota-matrix"] })
    },
  })
}

/**
 * Hook to update admission path.
 */
export function useUpdateAdmissionPath() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ pathId, data }: { pathId: number; data: AdmissionPathUpdate }) =>
      updateAdmissionPath(pathId, data),
    onSuccess: (updatedPath) => {
      // Immediately update cache with fresh data to avoid stale prop issue
      queryClient.setQueryData(admissionPathKeys.detail(updatedPath.id), updatedPath)
      // Invalidate admission-path derived views. After PR-2 removed the legacy
      // list screen, readiness lives under coverageMatrix (dưới .all), không
      // còn query nào dưới .lists() → chỉ cần .all (phủ detail/coverage/docs).
      queryClient.invalidateQueries({ queryKey: admissionPathKeys.all })
      queryClient.invalidateQueries({ queryKey: ["quota-matrix"] })
    },
  })
}

/**
 * Hook to update admission criteria.
 */
export function useUpdateCriteria() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ pathId, data }: { pathId: number; data: AdmissionCriteriaCreate }) =>
      updateCriteria(pathId, data),
    onSuccess: (updatedPath) => {
      // Immediately update cache with fresh data to avoid stale prop issue
      queryClient.setQueryData(admissionPathKeys.detail(updatedPath.id), updatedPath)
      // Invalidate related queries — .all phủ coverage matrix (readiness).
      queryClient.invalidateQueries({ queryKey: admissionPathKeys.all })
      // criteria_code hiển thị trên by-major PathMatrixCell (key ["quota-matrix"],
      // KHÔNG nằm dưới .all) → phải invalidate riêng nếu không ô by-major stale.
      queryClient.invalidateQueries({ queryKey: ["quota-matrix"] })
    },
  })
}

/**
 * Hook to update path documents.
 */
export function useUpdatePathDocuments() {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: ({ pathId, data }: { pathId: number; data: AdmissionPathDocumentUpsert[] }) => {
      return updatePathDocuments(pathId, data);
    },
    onSuccess: (_result, variables) => {
      // Do NOT setQueryData for detail — result is ResolvedDocumentListResponse, not AdmissionPathResponse
      queryClient.invalidateQueries({ queryKey: admissionPathKeys.detail(variables.pathId) })
      queryClient.invalidateQueries({ queryKey: admissionPathKeys.documents(variables.pathId) })
      queryClient.invalidateQueries({ queryKey: admissionPathKeys.all })
      queryClient.invalidateQueries({ queryKey: ["quota-matrix"] })
    },
    onError: (error) => {
      console.error("useUpdatePathDocuments: Mutation error:", error);
    }
  })
}

/**
 * Hook to activate admission path (Admin only).
 */
export function useActivateAdmissionPath() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (pathId: number) => activateAdmissionPath(pathId),
    onSuccess: (updatedPath) => {
      queryClient.invalidateQueries({ queryKey: admissionPathKeys.detail(updatedPath.id) })
      // .all phủ forOffering + coverage matrix (activated paths xuất hiện ở đó)
      queryClient.invalidateQueries({ queryKey: admissionPathKeys.all })
      // status hiển thị trên by-major PathMatrixCell (chấm màu) — key
      // ["quota-matrix"] KHÔNG nằm dưới .all → invalidate riêng ở hook để
      // không phụ thuộc call-site (LifecycleTab) bù tay.
      queryClient.invalidateQueries({ queryKey: ["quota-matrix"] })
      // Invalidate academic infos to update path_count and admission_status
      queryClient.invalidateQueries({ queryKey: ["academic-infos"] })
    },
  })
}

/**
 * Hook to deactivate admission path (Admin only).
 */
export function useDeactivateAdmissionPath() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (pathId: number) => deactivateAdmissionPath(pathId),
    onSuccess: (updatedPath) => {
      queryClient.invalidateQueries({ queryKey: admissionPathKeys.detail(updatedPath.id) })
      queryClient.invalidateQueries({ queryKey: admissionPathKeys.all })
      // status hiển thị trên by-major PathMatrixCell (chấm màu) — key
      // ["quota-matrix"] KHÔNG nằm dưới .all → invalidate riêng ở hook.
      queryClient.invalidateQueries({ queryKey: ["quota-matrix"] })
      // Invalidate academic infos to update path_count and admission_status
      queryClient.invalidateQueries({ queryKey: ["academic-infos"] })
    },
  })
}
