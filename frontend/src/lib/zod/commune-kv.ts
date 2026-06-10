/**
 * Zod schemas for admin commune KV CRUD (PR-A).
 *
 * Mirrors `Backend_FastAPI/app/schemas/vn_locality.py` commune admin shapes
 * + the migration CHECK regex on `area_code` so a typo fails Zod BEFORE the
 * round-trip. Reuses `AREA_CODE_REGEX` from priority-config (single source).
 *
 * Temporal model: đổi KV đi qua `/replace-area` (retire dòng cũ + insert mới),
 * KHÔNG sửa `area_code` qua PATCH.
 */
import { z } from "zod"

import { AREA_CODE_REGEX } from "@/lib/zod/priority-config"

const dateField = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}$/, "Định dạng phải là YYYY-MM-DD")

const areaCodeField = z
  .string()
  .regex(AREA_CODE_REGEX, "Mã KV không hợp lệ (VD: KV1, KV2-NT, KV3)")

// ==============================================================================
// CREATE
// ==============================================================================

export const communeAreaCreateSchema = z.object({
  commune_code: z.string().min(1, "Mã xã bắt buộc").max(20),
  province: z.string().min(1, "Tỉnh bắt buộc").max(100),
  district: z.string().max(100).optional(),
  ward: z.string().min(1, "Tên xã/phường bắt buộc").max(100),
  area_code: areaCodeField,
  effective_from: dateField.nullable().optional(),
})

export type CommuneAreaCreate = z.infer<typeof communeAreaCreateSchema>

// ==============================================================================
// UPDATE (PATCH metadata — KHÔNG có area_code/commune_code)
// ==============================================================================

export const communeAreaUpdateSchema = z.object({
  province: z.string().min(1).max(100).optional(),
  district: z.string().max(100).optional(),
  ward: z.string().min(1).max(100).optional(),
  // effective_to=null tường minh = re-activate (BE chặn nếu 2 active).
  effective_to: dateField.nullable().optional(),
})

export type CommuneAreaUpdate = z.infer<typeof communeAreaUpdateSchema>

// ==============================================================================
// REPLACE AREA (đổi KV temporal)
// ==============================================================================

export const communeReplaceAreaSchema = z.object({
  area_code: areaCodeField,
  effective_from: dateField.nullable().optional(),
})

export type CommuneReplaceArea = z.infer<typeof communeReplaceAreaSchema>

// ==============================================================================
// RESPONSE
// ==============================================================================

export const communeAreaResponseSchema = z.object({
  id: z.number().int().positive(),
  commune_code: z.string(),
  province: z.string(),
  district: z.string(),
  ward: z.string(),
  area_code: z.string(),
  effective_from: z.string(),
  effective_to: z.string().nullable(),
})

export type CommuneAreaResponse = z.infer<typeof communeAreaResponseSchema>

export const communeAreaListResponseSchema = z.object({
  items: z.array(communeAreaResponseSchema),
  total: z.number().int().min(0),
  page: z.number().int().min(1),
  page_size: z.number().int().min(1),
})

export type CommuneAreaListResponse = z.infer<
  typeof communeAreaListResponseSchema
>

export const csvImportResponseSchema = z.object({
  inserted: z.number().int().min(0),
  skipped_existing: z.number().int().min(0),
  error_rows: z.array(z.record(z.string(), z.unknown())),
})

export type CsvImportResponse = z.infer<typeof csvImportResponseSchema>
