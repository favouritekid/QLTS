/**
 * Tiện ích CHỈ cho test GĐ1b giao diện (không được import từ mã ứng dụng): dựng QueryClient riêng để test đọc được
 * trạng thái cache (vd đã làm mới chi tiết hồ sơ chưa), dữ liệu giả không có dữ liệu cá nhân.
 */
import type { ReactElement } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render } from "@testing-library/react"

export const API = "http://localhost:8000"
export const B1 = "3f2b8c1e-5d4a-4c3b-9a1e-0b2c3d4e5f60"
export const B2 = "7c9e6679-7425-40de-944b-e07fc1f90ae7"

export function renderWithClient(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  const utils = render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>)
  return { queryClient, ...utils }
}

/** Một giấy GĐ1b đủ trường; mọi cờ TẮT — test bật đúng cờ cần. */
export function giayGia(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    code: "hoc_ba_thpt",
    label: "Học bạ THPT",
    status: "paper_submitted",
    is_extra: false,
    document_id: null,
    actual_submission_format: "original",
    verified_format: null,
    document_row_id: 11,
    row_version: 3,
    can_verify: false,
    can_reject: false,
    can_reset: false,
    can_view_history: false,
    verify_block_reason: null,
    requires_ack: false,
    reset_requires_reason: false,
    reset_keeps_evidence: false,
    ...over,
  }
}

export function loGia(over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    batch_id: B1,
    status: "completed",
    created_at: "2026-11-17T08:00:00Z",
    started_at: "2026-11-17T08:01:00Z",
    finished_at: "2026-11-17T08:01:05Z",
    finalized_at: null,
    finalized_by_user_id: null,
    finalize_reason: null,
    counts: { profiles: 2, recorded: 1, error: 1, not_processed: 0, pending: 0 },
    items: [
      { profile_id: 5, document_row_id: 11, document_type_code: "cccd", result: "recorded", reason_code: null, message: null },
      {
        profile_id: 6,
        document_row_id: 12,
        document_type_code: "hoc_ba_thpt",
        result: "error",
        reason_code: "version_changed",
        message: "server",
      },
    ],
    can_execute: false,
    can_finalize: false,
    ...over,
  }
}
