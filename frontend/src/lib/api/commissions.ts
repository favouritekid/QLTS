import { api } from "./client"
import type {
  CommissionPoliciesPage,
  CommissionPolicy,
  CommissionPolicyCreate,
  CommissionPolicyUpdate,
  CommissionRecord,
  CommissionRecordsPage,
  CommissionReject,
  CommissionPay,
  CommissionStats,
} from "@/types/commission.types"

// ============================================================================
// ADMIN: COMMISSION POLICIES
// ============================================================================

export async function getCommissionPolicies(params?: {
  skip?: number
  limit?: number
  is_active?: boolean
  trigger_status_id?: string
}): Promise<CommissionPoliciesPage> {
  const response = await api.get<CommissionPoliciesPage>("/api/admin/commission-policies", { params })
  return response.data
}

export async function getCommissionPolicy(id: number): Promise<CommissionPolicy> {
  const response = await api.get<CommissionPolicy>(`/api/admin/commission-policies/${id}`)
  return response.data
}

export async function createCommissionPolicy(data: CommissionPolicyCreate): Promise<CommissionPolicy> {
  const response = await api.post<CommissionPolicy>("/api/admin/commission-policies", data)
  return response.data
}

export async function updateCommissionPolicy(id: number, data: CommissionPolicyUpdate): Promise<CommissionPolicy> {
  const response = await api.put<CommissionPolicy>(`/api/admin/commission-policies/${id}`, data)
  return response.data
}

// ============================================================================
// ADMIN: COMMISSION RECORDS
// ============================================================================

export async function getCommissionRecords(params?: {
  skip?: number
  limit?: number
  status?: string
  collaborator_id?: number
}): Promise<CommissionRecordsPage> {
  const response = await api.get<CommissionRecordsPage>("/api/admin/commissions", { params })
  return response.data
}

export async function getCommissionRecord(id: number): Promise<CommissionRecord> {
  const response = await api.get<CommissionRecord>(`/api/admin/commissions/${id}`)
  return response.data
}

export async function approveCommission(id: number): Promise<CommissionRecord> {
  const response = await api.post<CommissionRecord>(`/api/admin/commissions/${id}/approve`)
  return response.data
}

export async function rejectCommission(id: number, data: CommissionReject): Promise<CommissionRecord> {
  const response = await api.post<CommissionRecord>(`/api/admin/commissions/${id}/reject`, data)
  return response.data
}

export async function payCommission(id: number, data?: CommissionPay): Promise<CommissionRecord> {
  const response = await api.post<CommissionRecord>(`/api/admin/commissions/${id}/pay`, data || {})
  return response.data
}

// ============================================================================
// CTV: OWN COMMISSIONS
// ============================================================================

export async function getMyCommissions(params?: {
  skip?: number
  limit?: number
  status?: string
}): Promise<CommissionRecordsPage> {
  const response = await api.get<CommissionRecordsPage>("/api/ctv/commissions", { params })
  return response.data
}

export async function getMyCommissionStats(): Promise<CommissionStats> {
  const response = await api.get<CommissionStats>("/api/ctv/commissions/stats")
  return response.data
}
