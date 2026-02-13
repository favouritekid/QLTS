import { api } from "./client"
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
  PhoneCheckResponse,
} from "@/types/collaborator.types"

// ============================================================================
// ADMIN / MANAGER ENDPOINTS
// ============================================================================

export async function getCollaborators(params?: {
  skip?: number
  limit?: number
  status?: string
  unit_id?: number
  search?: string
  sort_by?: string
  order?: string
}): Promise<CollaboratorsPage> {
  const response = await api.get<CollaboratorsPage>("/api/collaborators", { params })
  return response.data
}

export async function getCollaborator(id: number): Promise<Collaborator> {
  const response = await api.get<Collaborator>(`/api/collaborators/${id}`)
  return response.data
}

export async function createCollaborator(data: CollaboratorCreate): Promise<Collaborator> {
  const response = await api.post<Collaborator>("/api/collaborators", data)
  return response.data
}

export async function updateCollaborator(id: number, data: CollaboratorUpdate): Promise<Collaborator> {
  const response = await api.put<Collaborator>(`/api/collaborators/${id}`, data)
  return response.data
}

export async function approveCollaborator(id: number): Promise<Collaborator> {
  const response = await api.post<Collaborator>(`/api/collaborators/${id}/approve`)
  return response.data
}

export async function suspendCollaborator(id: number): Promise<Collaborator> {
  const response = await api.post<Collaborator>(`/api/collaborators/${id}/suspend`)
  return response.data
}

// Claims (admin)
export async function getClaims(params?: {
  skip?: number
  limit?: number
  status?: string
  collaborator_id?: number
}): Promise<LeadClaimsPage> {
  const response = await api.get<LeadClaimsPage>("/api/collaborators/claims", { params })
  return response.data
}

export async function getClaim(id: number): Promise<LeadClaim> {
  const response = await api.get<LeadClaim>(`/api/collaborators/claims/${id}`)
  return response.data
}

export async function reviewClaim(id: number, data: LeadClaimReview): Promise<LeadClaim> {
  const response = await api.post<LeadClaim>(`/api/collaborators/claims/${id}/review`, data)
  return response.data
}

// ============================================================================
// CTV SELF-SERVICE ENDPOINTS
// ============================================================================

export async function getMyProfile(): Promise<Collaborator> {
  const response = await api.get<Collaborator>("/api/ctv/profile")
  return response.data
}

export async function getMyLeads(params?: {
  skip?: number
  limit?: number
}): Promise<{ total_count: number; leads: LeadForCTV[] }> {
  const response = await api.get("/api/ctv/leads", { params })
  return response.data
}

export async function submitLead(data: LeadClaimCreate): Promise<LeadClaim> {
  const response = await api.post<LeadClaim>("/api/ctv/leads/submit", data)
  return response.data
}

export async function checkPhone(phone: string): Promise<PhoneCheckResponse> {
  const response = await api.get<PhoneCheckResponse>("/api/ctv/leads/check-phone", { params: { phone } })
  return response.data
}

export async function getMyClaims(params?: {
  skip?: number
  limit?: number
}): Promise<LeadClaimsPage> {
  const response = await api.get<LeadClaimsPage>("/api/ctv/claims", { params })
  return response.data
}

export async function getMyStats(): Promise<CollaboratorStats> {
  const response = await api.get<CollaboratorStats>("/api/ctv/stats")
  return response.data
}

// Lead validity (admin/manager)
export async function updateLeadValidity(leadId: number, validity_status: string): Promise<unknown> {
  const response = await api.post(`/api/leads/${leadId}/validity`, { validity_status })
  return response.data
}
