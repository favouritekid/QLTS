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
  listAdmissionPaths,
  createAdmissionPath,
  updateAdmissionPath,
  activateAdmissionPath,
  deactivateAdmissionPath,
  getAcademicYears,
  getCoverageMatrix,
} from "@/lib/api/admission-paths"
import type { 
  AdmissionPathCreate, 
  AdmissionPathUpdate,
} from "@/lib/zod/admission-path"

// ============================================
// QUERY KEYS
// ============================================

export const admissionPathKeys = {
  all: ["admission-paths"] as const,
  lists: () => [...admissionPathKeys.all, "list"] as const,
  list: (academicInfoId: number) => [...admissionPathKeys.lists(), academicInfoId] as const,
  forOffering: (offeringId: number) => [...admissionPathKeys.all, "for-offering", offeringId] as const,
  details: () => [...admissionPathKeys.all, "detail"] as const,
  detail: (pathId: number) => [...admissionPathKeys.details(), pathId] as const,
  years: () => [...admissionPathKeys.all, "years"] as const,
  coverageMatrix: (academicInfoId: number) => [...admissionPathKeys.all, "coverage-matrix", academicInfoId] as const,
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
 * Hook to list paths by academic info ID.
 * Used by Config Console's PathsList component.
 */
export function useAdmissionPathsByAcademicInfo(academicInfoId: number | undefined) {
  return useQuery({
    queryKey: admissionPathKeys.list(academicInfoId ?? 0),
    queryFn: () => listAdmissionPaths(academicInfoId!),
    enabled: !!academicInfoId,
  })
}

/**
 * Hook to fetch single path by ID.
 */
export function useAdmissionPath(pathId: number | undefined) {
  return useQuery({
    queryKey: admissionPathKeys.detail(pathId ?? 0),
    queryFn: () => getAdmissionPath(pathId!),
    enabled: !!pathId,
  })
}

/**
 * Hook to fetch academic years.
 */
export function useAcademicYears() {
  return useQuery({
    queryKey: admissionPathKeys.years(),
    queryFn: getAcademicYears,
    staleTime: 30 * 60 * 1000, // 30 minutes (rarely changes)
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
 * Hook to create admission path.
 */
export function useCreateAdmissionPath() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: (data: AdmissionPathCreate) => createAdmissionPath(data),
    onSuccess: (_newPath) => {
      // Invalidate list queries
      queryClient.invalidateQueries({ queryKey: admissionPathKeys.lists() })
      // Invalidate academic infos to update admission_status (READY → CONFIGURED)
      queryClient.invalidateQueries({ queryKey: ["academic-infos"] })
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
      // Invalidate specific path and list queries
      queryClient.invalidateQueries({ queryKey: admissionPathKeys.detail(updatedPath.id) })
      queryClient.invalidateQueries({ queryKey: admissionPathKeys.lists() })
    },
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
      queryClient.invalidateQueries({ queryKey: admissionPathKeys.lists() })
      // Also invalidate forOffering since activated paths appear there
      queryClient.invalidateQueries({ queryKey: admissionPathKeys.all })
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
      queryClient.invalidateQueries({ queryKey: admissionPathKeys.lists() })
      queryClient.invalidateQueries({ queryKey: admissionPathKeys.all })
      // Invalidate academic infos to update path_count and admission_status
      queryClient.invalidateQueries({ queryKey: ["academic-infos"] })
    },
  })
}
