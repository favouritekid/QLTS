import { api } from "./client"
import { API_ENDPOINTS } from "./endpoints"
import type {
  OverpaymentApplyRequest,
  OverpaymentFilters,
  OverpaymentRecord,
  OverpaymentRefundRequest,
  OverpaymentWriteOffRequest,
} from "@/types/finance.types"

export interface OverpaymentPaginatedResponse {
  items: OverpaymentRecord[]
  total: number
  page: number
  page_size: number
}

export async function getOverpayments(filters?: OverpaymentFilters): Promise<OverpaymentPaginatedResponse> {
  const response = await api.get<OverpaymentPaginatedResponse>(API_ENDPOINTS.FINANCE.OVERPAYMENTS.LIST, {
    params: filters,
  })
  return response.data
}

export async function getOverpayment(id: number): Promise<OverpaymentRecord> {
  const response = await api.get<OverpaymentRecord>(API_ENDPOINTS.FINANCE.OVERPAYMENTS.DETAIL(id))
  return response.data
}

export async function applyOverpayment(id: number, data: OverpaymentApplyRequest): Promise<OverpaymentRecord> {
  const response = await api.post<OverpaymentRecord>(API_ENDPOINTS.FINANCE.OVERPAYMENTS.APPLY(id), data)
  return response.data
}

export async function refundOverpayment(id: number, data: OverpaymentRefundRequest): Promise<OverpaymentRecord> {
  const response = await api.post<OverpaymentRecord>(API_ENDPOINTS.FINANCE.OVERPAYMENTS.REFUND(id), data)
  return response.data
}

export async function writeOffOverpayment(id: number, data: OverpaymentWriteOffRequest): Promise<OverpaymentRecord> {
  const response = await api.post<OverpaymentRecord>(API_ENDPOINTS.FINANCE.OVERPAYMENTS.WRITE_OFF(id), data)
  return response.data
}

export const overpaymentsApi = {
  getOverpayments,
  getOverpayment,
  applyOverpayment,
  refundOverpayment,
  writeOffOverpayment,
}
