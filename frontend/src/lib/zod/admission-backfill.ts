/**
 * Phase 3 PR-3D-B FE Wave B Bundle 3 — Zod schemas cho admin backfill queue.
 *
 * Mirror Backend Pydantic schemas
 * (`app/schemas/admission_backfill_exception.py` — BE-2 LIVE prod):
 * - AdmissionBackfillExceptionResponse
 * - BackfillExceptionListResponse (envelope với pagination)
 * - BackfillExceptionResolveRequest
 * - BackfillExceptionBulkResolveRequest
 * - BackfillBulkResolveResponse (counters)
 */
import { z } from "zod"

export const admissionBackfillExceptionResponseSchema = z.object({
  id: z.number(),
  profile_id: z.number(),
  exception_type: z.string(),
  details: z.record(z.string(), z.unknown()),
  created_at: z.string(),
  resolved_at: z.string().nullable().optional(),
  resolved_by_user_id: z.number().nullable().optional(),
  resolved_by_username: z.string().nullable().optional(),
  resolution_notes: z.string().nullable().optional(),
})
export type AdmissionBackfillException = z.infer<
  typeof admissionBackfillExceptionResponseSchema
>

export const backfillExceptionListResponseSchema = z.object({
  items: z.array(admissionBackfillExceptionResponseSchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  offset: z.number().int().nonnegative(),
})
export type BackfillExceptionListResponse = z.infer<
  typeof backfillExceptionListResponseSchema
>

export const backfillExceptionResolveRequestSchema = z.object({
  resolution_notes: z.string().min(5).max(2000),
})
export type BackfillExceptionResolveRequest = z.infer<
  typeof backfillExceptionResolveRequestSchema
>

export const backfillExceptionBulkResolveRequestSchema = z.object({
  exception_ids: z.array(z.number().int().positive()).min(1).max(500),
  resolution_notes: z.string().min(5).max(2000),
})
export type BackfillExceptionBulkResolveRequest = z.infer<
  typeof backfillExceptionBulkResolveRequestSchema
>

export const backfillBulkResolveResponseSchema = z.object({
  requested: z.number(),
  resolved: z.number(),
  skipped_already_resolved: z.number(),
  missing: z.number(),
  missing_ids: z.array(z.number()).default([]),
})
export type BackfillBulkResolveResponse = z.infer<
  typeof backfillBulkResolveResponseSchema
>

export interface BackfillListFilters {
  exception_type?: string
  is_resolved?: boolean
  profile_id?: number
  created_from?: string
  created_to?: string
  limit?: number
  offset?: number
}
