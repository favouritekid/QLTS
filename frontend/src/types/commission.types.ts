// Commission System Types

import type { CollaboratorShallow } from "./collaborator.types"

export type CommissionRecordStatus = "pending" | "approved" | "paid" | "rejected" | "cancelled"
export type CalculationType = "fixed" | "percentage"

// Policy
export interface CommissionPolicy {
  id: number
  name: string
  description: string | null
  trigger_status_id: string
  calculation_type: CalculationType
  fixed_amount: number | null
  percentage: number | null
  unit_id: number | null
  offering_id: number | null
  effective_from: string
  effective_to: string | null
  is_active: boolean
  created_by_id: number | null
  created_at: string
  updated_at: string
  unit: { id: number; name: string; type: string; parent_id: number | null; is_active: boolean } | null
}

export interface CommissionPolicyCreate {
  name: string
  description?: string | null
  trigger_status_id: string
  calculation_type: CalculationType
  fixed_amount?: number | null
  percentage?: number | null
  unit_id?: number | null
  offering_id?: number | null
  effective_from: string
  effective_to?: string | null
  is_active?: boolean
}

export interface CommissionPolicyUpdate {
  name?: string
  description?: string | null
  trigger_status_id?: string
  calculation_type?: CalculationType
  fixed_amount?: number | null
  percentage?: number | null
  unit_id?: number | null
  offering_id?: number | null
  effective_from?: string
  effective_to?: string | null
  is_active?: boolean
}

export interface CommissionPoliciesPage {
  total_count: number
  policies: CommissionPolicy[]
}

// Record
export interface CommissionPolicyShallow {
  id: number
  name: string
  calculation_type: string
}

export interface LeadShallow {
  id: number
  full_name: string | null
  phone: string | null
}

export interface CommissionRecord {
  id: number
  collaborator_id: number
  lead_id: number
  policy_id: number
  amount: number
  calculation_detail: Record<string, unknown> | null
  status: CommissionRecordStatus
  trigger_status_id: string
  triggered_at: string
  approved_by_id: number | null
  approved_at: string | null
  rejected_by_id: number | null
  rejected_at: string | null
  rejection_reason: string | null
  cancelled_at: string | null
  cancelled_by_id: number | null
  cancellation_reason: string | null
  paid_at: string | null
  paid_by_id: number | null
  payment_reference: string | null
  created_at: string
  // Nested
  collaborator: CollaboratorShallow | null
  lead: LeadShallow | null
  policy: CommissionPolicyShallow | null
}

export interface CommissionRecordsPage {
  total_count: number
  records: CommissionRecord[]
}

export interface CommissionReject {
  rejection_reason: string
}

export interface CommissionPay {
  payment_reference?: string | null
}

export interface CommissionStats {
  total_earned: number
  total_pending: number
  total_paid: number
  total_rejected: number
  record_count: number
}
