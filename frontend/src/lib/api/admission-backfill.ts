/**
 * Phase 3 PR-3D-B FE Wave B Bundle 3 — Admin backfill queue API client.
 *
 * Wraps 4 BE-2 endpoints (all admin-only via require_admin, bypass Casbin
 * diamond DENY gotcha):
 *   - GET    /api/v2/admin/admission-backfill-exceptions
 *   - PATCH  /api/v2/admin/admission-backfill-exceptions/{id}/resolve
 *   - POST   /api/v2/admin/admission-backfill-exceptions/bulk-resolve
 *   - GET    /api/v2/admin/admission-backfill-exceptions/export.csv (binary)
 */
import { api } from "@/lib/api/client"
import {
  backfillBulkResolveResponseSchema,
  backfillExceptionBulkResolveRequestSchema,
  backfillExceptionListResponseSchema,
  backfillExceptionResolveRequestSchema,
  admissionBackfillExceptionResponseSchema,
  type AdmissionBackfillException,
  type BackfillBulkResolveResponse,
  type BackfillExceptionBulkResolveRequest,
  type BackfillExceptionListResponse,
  type BackfillExceptionResolveRequest,
  type BackfillListFilters,
} from "@/lib/zod/admission-backfill"

/**
 * GET /api/v2/admin/admission-backfill-exceptions — paginated list with filters.
 *
 * All filters compose AND. Newest-first sort.
 */
export async function listBackfillExceptions(
  filters: BackfillListFilters = {},
): Promise<BackfillExceptionListResponse> {
  const params: Record<string, string | number | boolean> = {}
  if (filters.exception_type !== undefined) {
    params.exception_type = filters.exception_type
  }
  if (filters.is_resolved !== undefined) {
    params.is_resolved = filters.is_resolved
  }
  if (filters.profile_id !== undefined) {
    params.profile_id = filters.profile_id
  }
  if (filters.created_from !== undefined) {
    params.created_from = filters.created_from
  }
  if (filters.created_to !== undefined) {
    params.created_to = filters.created_to
  }
  params.limit = filters.limit ?? 50
  params.offset = filters.offset ?? 0

  const response = await api.get<BackfillExceptionListResponse>(
    "/api/v2/admin/admission-backfill-exceptions",
    { params },
  )
  return backfillExceptionListResponseSchema.parse(response.data)
}

/**
 * PATCH /api/v2/admin/admission-backfill-exceptions/{id}/resolve
 *
 * Service rejects if already resolved with 400 (idempotent, NOT silent
 * re-touch of resolved_by_user_id).
 */
export async function resolveBackfillException(
  exceptionId: number,
  payload: BackfillExceptionResolveRequest,
): Promise<AdmissionBackfillException> {
  const validated = backfillExceptionResolveRequestSchema.parse(payload)
  const response = await api.patch<AdmissionBackfillException>(
    `/api/v2/admin/admission-backfill-exceptions/${exceptionId}/resolve`,
    validated,
  )
  return admissionBackfillExceptionResponseSchema.parse(response.data)
}

/**
 * POST /api/v2/admin/admission-backfill-exceptions/bulk-resolve
 *
 * Up to 500 exceptions resolved atomically with shared notes. Returns
 * counters: requested / resolved / skipped_already_resolved / missing /
 * missing_ids.
 */
export async function bulkResolveBackfillExceptions(
  payload: BackfillExceptionBulkResolveRequest,
): Promise<BackfillBulkResolveResponse> {
  const validated = backfillExceptionBulkResolveRequestSchema.parse(payload)
  const response = await api.post<BackfillBulkResolveResponse>(
    "/api/v2/admin/admission-backfill-exceptions/bulk-resolve",
    validated,
  )
  return backfillBulkResolveResponseSchema.parse(response.data)
}

/**
 * GET /api/v2/admin/admission-backfill-exceptions/export.csv
 *
 * Streams CSV. Returns the raw Blob — caller triggers browser download via
 * <a download> or `URL.createObjectURL`.
 */
export async function exportBackfillExceptionsCsv(
  filters: Pick<BackfillListFilters, "exception_type" | "is_resolved"> = {},
): Promise<Blob> {
  const params: Record<string, string | boolean> = {}
  if (filters.exception_type !== undefined) {
    params.exception_type = filters.exception_type
  }
  if (filters.is_resolved !== undefined) {
    params.is_resolved = filters.is_resolved
  }
  const response = await api.get(
    "/api/v2/admin/admission-backfill-exceptions/export.csv",
    { params, responseType: "blob" },
  )
  return response.data as Blob
}

export const admissionBackfillApi = {
  listBackfillExceptions,
  resolveBackfillException,
  bulkResolveBackfillExceptions,
  exportBackfillExceptionsCsv,
}
