/**
 * API client cho màn đồng bộ ký túc xá.
 *
 * Mirrors `Backend_FastAPI/app/routers/admin_v2_dorm_sync.py`.
 * Base: `/api/v2/admin/dorm-sync`. Cả ba endpoint sau `require_admin`.
 */

import { AxiosError } from "axios"

import { api } from "@/lib/api/client"
import {
  DORM_SYNC_BLOCKED_CODE,
  dormSyncApplyRequestSchema,
  dormSyncApplySchema,
  dormSyncBlockedSchema,
  dormSyncContextSchema,
  dormSyncPreviewRequestSchema,
  dormSyncPreviewSchema,
  type DormSyncApplyResult,
  type DormSyncBlocked,
  type DormSyncContext,
  type DormSyncPreview,
} from "@/lib/zod/dorm-sync"

const BASE = "/api/v2/admin/dorm-sync"

/**
 * Lỗi chặn có payload MÁY ĐỌC ĐƯỢC.
 *
 * 🔴 Tách thành lớp riêng để nơi gọi bắt bằng `instanceof` chứ không đọc chuỗi.
 * `handleApiError` chung cố ý che `detail` của mã `CONFLICT`, nên nếu để lỗi
 * này rơi vào đó thì giao diện mất sạch thứ nó cần để rẽ nhánh.
 */
export class DormSyncBlockedError extends Error {
  readonly operationStatus: DormSyncBlocked["operation_status"]
  readonly nextAction: DormSyncBlocked["next_action"]

  constructor(payload: DormSyncBlocked) {
    super(payload.detail)
    this.name = "DormSyncBlockedError"
    this.operationStatus = payload.operation_status
    this.nextAction = payload.next_action
  }
}

/**
 * Nhận diện lỗi dorm-sync CÓ KIỂU. `null` = không phải của ta.
 *
 * ⚠️ Parse bằng Zod, không chỉ kiểm `error_code`. Một payload thiếu
 * `next_action` mà vẫn được nhận sẽ cho `undefined` đi vào nhánh rẽ, và nhánh
 * mặc định gần như chắc chắn là nhánh "cho thử lại" — đúng thứ phải chặn ở ca
 * `manual_reconcile`.
 */
export function parseDormSyncBlocked(error: unknown): DormSyncBlockedError | null {
  if (!(error instanceof AxiosError)) return null

  const data = error.response?.data
  if (!data || typeof data !== "object") return null
  if ((data as { error_code?: unknown }).error_code !== DORM_SYNC_BLOCKED_CODE) {
    return null
  }

  const parsed = dormSyncBlockedSchema.safeParse(data)
  if (!parsed.success) return null

  return new DormSyncBlockedError(parsed.data)
}

export async function getDormSyncContext(): Promise<DormSyncContext> {
  const { data } = await api.get(`${BASE}/context`)
  return dormSyncContextSchema.parse(data)
}

export async function previewDormSync(
  academicYear: number,
): Promise<DormSyncPreview> {
  // Payload CHÍNH XÁC: `{ academic_year }`. Backend `extra="forbid"`.
  const body = dormSyncPreviewRequestSchema.parse({ academic_year: academicYear })
  const { data } = await api.post(`${BASE}/preview`, body)
  return dormSyncPreviewSchema.parse(data)
}

export async function applyDormSync(
  previewToken: string,
): Promise<DormSyncApplyResult> {
  // Payload CHÍNH XÁC: `{ preview_token }` — năm học và `operation_id` đã nằm
  // trong phiếu do server ký; gửi kèm sẽ nhận 422.
  const body = dormSyncApplyRequestSchema.parse({ preview_token: previewToken })
  try {
    const { data } = await api.post(`${BASE}/apply`, body)
    return dormSyncApplySchema.parse(data)
  } catch (error) {
    // 🔴 Bắt lỗi CÓ KIỂU TRƯỚC. Lỗi không nhận diện được mới để nguyên cho nơi
    // gọi chuyển sang `handleApiError`.
    const blocked = parseDormSyncBlocked(error)
    if (blocked) throw blocked
    throw error
  }
}
