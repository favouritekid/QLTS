import { api } from "./client"
import { API_ENDPOINTS } from "./endpoints"
import type {
  RefundCreateRequest,
  RefundFilters,
  RefundProcessRequest,
  RefundRequest,
  RefundsSummary,
} from "@/types/finance.types"

export interface RefundPaginatedResponse {
  items: RefundRequest[]
  total: number
  page: number
  page_size: number
  /** Page-level capability: officer/accountant/admin may create (manager is approver-only). */
  can_create: boolean
  /** Đếm + tổng tiền theo trạng thái trên toàn phạm vi, không theo bộ lọc đang chọn. */
  summary: RefundsSummary
}

export interface RefundRejectRequest {
  rejection_reason: string
}

export async function getRefunds(filters?: RefundFilters): Promise<RefundPaginatedResponse> {
  const response = await api.get<RefundPaginatedResponse>(API_ENDPOINTS.FINANCE.REFUNDS.LIST, {
    params: filters,
  })
  return response.data
}

export async function getRefund(id: number): Promise<RefundRequest> {
  const response = await api.get<RefundRequest>(API_ENDPOINTS.FINANCE.REFUNDS.DETAIL(id))
  return response.data
}

export async function createRefund(data: RefundCreateRequest): Promise<RefundRequest> {
  const response = await api.post<RefundRequest>(API_ENDPOINTS.FINANCE.REFUNDS.CREATE, data)
  return response.data
}

export async function approveRefund(id: number): Promise<RefundRequest> {
  const response = await api.post<RefundRequest>(API_ENDPOINTS.FINANCE.REFUNDS.APPROVE(id))
  return response.data
}

export async function rejectRefund(id: number, data: RefundRejectRequest): Promise<RefundRequest> {
  const response = await api.post<RefundRequest>(API_ENDPOINTS.FINANCE.REFUNDS.REJECT(id), data)
  return response.data
}

export async function processRefund(id: number, data: RefundProcessRequest): Promise<RefundRequest> {
  const response = await api.post<RefundRequest>(API_ENDPOINTS.FINANCE.REFUNDS.PROCESS(id), data)
  return response.data
}

export const refundsApi = {
  getRefunds,
  getRefund,
  createRefund,
  approveRefund,
  rejectRefund,
  processRefund,
}
