// Collaborator (CTV) System Types

export type CollaboratorStatus = "pending" | "active" | "suspended" | "inactive"
export type LeadValidityStatus = "raw" | "duplicate" | "invalid" | "valid" | "qualified"
export type LeadClaimStatus = "pending" | "approved" | "rejected"

export interface CollaboratorShallow {
  id: number
  code: string
  full_name: string
  phone: string
}

export interface Collaborator {
  id: number
  code: string
  full_name: string
  phone: string
  email: string | null
  status: CollaboratorStatus
  unit_id: number
  user_id: number | null
  managed_by_officer_id: number | null
  id_card_number: string | null
  bank_account: string | null
  bank_name: string | null
  address: string | null
  notes: string | null
  created_at: string
  updated_at: string
  approved_at: string | null
  // Nested
  unit: { id: number; name: string; type: string; parent_id: number | null; is_active: boolean } | null
  managed_by_officer: { id: number; full_name: string | null; username: string } | null
}

export interface CollaboratorCreate {
  full_name: string
  phone: string
  email?: string | null
  unit_id: number
  user_id?: number | null
  managed_by_officer_id?: number | null
  id_card_number?: string | null
  bank_account?: string | null
  bank_name?: string | null
  address?: string | null
  notes?: string | null
}

export interface CollaboratorUpdate {
  full_name?: string
  phone?: string
  email?: string | null
  status?: CollaboratorStatus
  managed_by_officer_id?: number | null
  id_card_number?: string | null
  bank_account?: string | null
  bank_name?: string | null
  address?: string | null
  notes?: string | null
}

export interface CollaboratorsPage {
  total_count: number
  collaborators: Collaborator[]
}

// Lead Claim
export interface LeadForCTV {
  id: number
  full_name: string
  phone_masked: string
  status: string
  validity_status: string | null
  created_at: string
}

export interface LeadClaimData {
  full_name: string
  phone: string
  email?: string | null
  notes?: string | null
}

export interface LeadClaimCreate {
  lead_data: LeadClaimData
}

export interface LeadClaimReview {
  status: "approved" | "rejected"
  rejection_reason?: string | null
}

export interface LeadClaim {
  id: number
  collaborator_id: number
  lead_id: number
  status: LeadClaimStatus
  claim_data: LeadClaimData | null
  reviewed_by_id: number | null
  reviewed_at: string | null
  rejection_reason: string | null
  created_at: string
  lead: LeadForCTV | null
  collaborator: CollaboratorShallow | null
}

export interface LeadClaimsPage {
  total_count: number
  claims: LeadClaim[]
}

export interface CollaboratorStats {
  total_leads: number
  valid_leads: number
  qualified_leads: number
  converted_leads: number
  pending_claims: number
}

export interface PhoneCheckResponse {
  available: boolean
  message: string | null
}
