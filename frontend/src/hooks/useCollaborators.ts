import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AxiosError } from "axios"
import { toast } from "sonner"
import * as collaboratorsApi from "@/lib/api/collaborators"
import type {
  Collaborator,
  CollaboratorCreate,
  CollaboratorUpdate,
  CollaboratorsPage,
  CollaboratorStats,
  LeadClaim,
  LeadClaimCreate,
  LeadClaimReview,
  LeadClaimsPage,
  LeadForCTV,
} from "@/types/collaborator.types"

// ============================================================================
// QUERY KEYS
// ============================================================================

export const collaboratorKeys = {
  all: ["collaborators"] as const,
  lists: () => [...collaboratorKeys.all, "list"] as const,
  list: (params?: Record<string, unknown>) => [...collaboratorKeys.lists(), params] as const,
  details: () => [...collaboratorKeys.all, "detail"] as const,
  detail: (id: number) => [...collaboratorKeys.details(), id] as const,
}

export const claimKeys = {
  all: ["claims"] as const,
  lists: () => [...claimKeys.all, "list"] as const,
  list: (params?: Record<string, unknown>) => [...claimKeys.lists(), params] as const,
  details: () => [...claimKeys.all, "detail"] as const,
  detail: (id: number) => [...claimKeys.details(), id] as const,
}

export const ctvKeys = {
  profile: ["ctv", "profile"] as const,
  leads: (params?: Record<string, unknown>) => ["ctv", "leads", params] as const,
  claims: (params?: Record<string, unknown>) => ["ctv", "claims", params] as const,
  stats: ["ctv", "stats"] as const,
}

// ============================================================================
// ADMIN QUERIES
// ============================================================================

export function useCollaborators(params?: Record<string, unknown>) {
  return useQuery<CollaboratorsPage>({
    queryKey: collaboratorKeys.list(params),
    queryFn: () => collaboratorsApi.getCollaborators(params as any),
    staleTime: 1000 * 5,
  })
}

export function useCollaborator(id: number) {
  return useQuery<Collaborator>({
    queryKey: collaboratorKeys.detail(id),
    queryFn: () => collaboratorsApi.getCollaborator(id),
    enabled: !!id,
  })
}

export function useClaims(params?: Record<string, unknown>) {
  return useQuery<LeadClaimsPage>({
    queryKey: claimKeys.list(params),
    queryFn: () => collaboratorsApi.getClaims(params as any),
    staleTime: 1000 * 5,
  })
}

// ============================================================================
// ADMIN MUTATIONS
// ============================================================================

export function useCreateCollaborator() {
  const queryClient = useQueryClient()
  return useMutation<Collaborator, AxiosError<{ detail: string }>, CollaboratorCreate>({
    mutationFn: collaboratorsApi.createCollaborator,
    onSuccess: () => {
      toast.success("Tạo cộng tác viên thành công")
      queryClient.invalidateQueries({ queryKey: collaboratorKeys.lists() })
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || "Lỗi tạo cộng tác viên")
    },
  })
}

export function useUpdateCollaborator() {
  const queryClient = useQueryClient()
  return useMutation<Collaborator, AxiosError<{ detail: string }>, { id: number; data: CollaboratorUpdate }>({
    mutationFn: ({ id, data }) => collaboratorsApi.updateCollaborator(id, data),
    onSuccess: (_, { id }) => {
      toast.success("Cập nhật thành công")
      queryClient.invalidateQueries({ queryKey: collaboratorKeys.detail(id) })
      queryClient.invalidateQueries({ queryKey: collaboratorKeys.lists() })
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || "Lỗi cập nhật")
    },
  })
}

export function useApproveCollaborator() {
  const queryClient = useQueryClient()
  return useMutation<Collaborator, AxiosError<{ detail: string }>, number>({
    mutationFn: collaboratorsApi.approveCollaborator,
    onSuccess: () => {
      toast.success("Đã duyệt CTV")
      queryClient.invalidateQueries({ queryKey: collaboratorKeys.lists() })
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || "Lỗi duyệt CTV")
    },
  })
}

export function useSuspendCollaborator() {
  const queryClient = useQueryClient()
  return useMutation<Collaborator, AxiosError<{ detail: string }>, number>({
    mutationFn: collaboratorsApi.suspendCollaborator,
    onSuccess: () => {
      toast.success("Đã đình chỉ CTV")
      queryClient.invalidateQueries({ queryKey: collaboratorKeys.lists() })
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || "Lỗi đình chỉ CTV")
    },
  })
}

export function useReviewClaim() {
  const queryClient = useQueryClient()
  return useMutation<LeadClaim, AxiosError<{ detail: string }>, { id: number; data: LeadClaimReview }>({
    mutationFn: ({ id, data }) => collaboratorsApi.reviewClaim(id, data),
    onSuccess: () => {
      toast.success("Đã xử lý claim")
      queryClient.invalidateQueries({ queryKey: claimKeys.lists() })
      queryClient.invalidateQueries({ queryKey: collaboratorKeys.lists() })
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || "Lỗi xử lý claim")
    },
  })
}

// ============================================================================
// CTV SELF-SERVICE QUERIES
// ============================================================================

export function useCTVProfile() {
  return useQuery<Collaborator>({
    queryKey: ctvKeys.profile,
    queryFn: collaboratorsApi.getMyProfile,
  })
}

export function useCTVLeads(params?: Record<string, unknown>) {
  return useQuery<{ total_count: number; leads: LeadForCTV[] }>({
    queryKey: ctvKeys.leads(params),
    queryFn: () => collaboratorsApi.getMyLeads(params as any),
    staleTime: 1000 * 5,
  })
}

export function useCTVClaims(params?: Record<string, unknown>) {
  return useQuery<LeadClaimsPage>({
    queryKey: ctvKeys.claims(params),
    queryFn: () => collaboratorsApi.getMyClaims(params as any),
    staleTime: 1000 * 5,
  })
}

export function useCTVStats() {
  return useQuery<CollaboratorStats>({
    queryKey: ctvKeys.stats,
    queryFn: collaboratorsApi.getMyStats,
  })
}

// CTV MUTATIONS

export function useSubmitLead() {
  const queryClient = useQueryClient()
  return useMutation<LeadClaim, AxiosError<{ detail: string }>, LeadClaimCreate>({
    mutationFn: collaboratorsApi.submitLead,
    onSuccess: () => {
      toast.success("Gửi lead thành công")
      queryClient.invalidateQueries({ queryKey: ctvKeys.leads() })
      queryClient.invalidateQueries({ queryKey: ctvKeys.claims() })
      queryClient.invalidateQueries({ queryKey: ctvKeys.stats })
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || "Lỗi gửi lead")
    },
  })
}

// Lead validity mutation (admin/manager)
export function useUpdateLeadValidity() {
  const queryClient = useQueryClient()
  return useMutation<unknown, AxiosError<{ detail: string }>, { leadId: number; validity_status: string }>({
    mutationFn: ({ leadId, validity_status }) => collaboratorsApi.updateLeadValidity(leadId, validity_status),
    onSuccess: () => {
      toast.success("Cập nhật trạng thái hợp lệ thành công")
      // Invalidate lead queries
      queryClient.invalidateQueries({ queryKey: ["leads"] })
    },
    onError: (error) => {
      toast.error(error.response?.data?.detail || "Lỗi cập nhật")
    },
  })
}
