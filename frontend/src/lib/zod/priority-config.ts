/**
 * Zod schemas for priority_area_config + priority_object_config
 * admin CRUD (Q9 #07 PR3 admin FE).
 *
 * Mirrors `Backend_FastAPI/app/schemas/priority_config.py` Pydantic
 * shapes + the migration phase1_08b CHECK regex constraints so a typo
 * fails Zod BEFORE the round-trip and never hits a PG 500.
 *
 * Code values (TT 05/2021-BLĐTBXH Phụ lục 01):
 * - area_code: KV1 / KV2-NT / KV2 / KV3 (HYPHEN, not underscore)
 * - group_code: UT1 / UT2 (extensible UT3+)
 * - sub_code:   2-digit numeric '01'..'07' (extensible)
 *
 * NB: `bonus_points` arrives as a `Decimal` JSON encoding from the BE
 * — Pydantic serialises Numeric(4,2) as a number; FE keeps it as
 * `number` (Zod will fail loudly if the BE ever emits a string).
 */
import { z } from "zod"

// ==============================================================================
// CODE REGEX CONSTANTS — single source of truth for FE validation
// ==============================================================================

export const AREA_CODE_REGEX = /^KV[1-9](-NT)?$/
export const GROUP_CODE_REGEX = /^UT[1-9]$/
export const SUB_CODE_REGEX = /^[0-9]{2}$/

// ==============================================================================
// PRIORITY AREA CONFIG
// ==============================================================================

const academicYearField = z
  .number()
  .int()
  .min(2020, "Năm học tối thiểu 2020")
  .max(2100, "Năm học tối đa 2100")

const bonusPointsField = z
  .number()
  .min(0, "Điểm cộng không âm")
  .max(99.99, "Điểm cộng tối đa 99.99")
  // Mirror Pydantic decimal_places=2: enforce ≤ 2 fractional digits on
  // the wire. Multiplying by 100 + rounding catches floating-point
  // garbage like 0.123 without false positives on 0.75 / 1.5 / 2.
  .refine((v) => Math.round(v * 100) === v * 100, {
    message: "Tối đa 2 chữ số thập phân",
  })

const dateField = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}$/, "Định dạng phải là YYYY-MM-DD")

export const priorityAreaConfigBaseSchema = z.object({
  academic_year: academicYearField,
  area_code: z
    .string()
    .regex(AREA_CODE_REGEX, "Mã KV không hợp lệ (VD: KV1, KV2-NT, KV3)"),
  area_name: z.string().min(1, "Tên KV bắt buộc").max(100),
  bonus_points: bonusPointsField,
  description: z.string().nullable().optional(),
  effective_from: dateField.nullable().optional(),
  effective_to: dateField.nullable().optional(),
})

export type PriorityAreaConfigBase = z.infer<typeof priorityAreaConfigBaseSchema>

/** Create payload — same shape as base. */
export const priorityAreaConfigCreateSchema = priorityAreaConfigBaseSchema

export type PriorityAreaConfigCreate = z.infer<typeof priorityAreaConfigCreateSchema>

/**
 * PATCH payload — all fields optional. BE applies via
 * `model_dump(exclude_unset=True)` so omitted keys leave the column
 * untouched.
 */
export const priorityAreaConfigUpdateSchema = z.object({
  area_name: z.string().min(1).max(100).optional(),
  bonus_points: bonusPointsField.optional(),
  description: z.string().nullable().optional(),
  effective_to: dateField.nullable().optional(),
})

export type PriorityAreaConfigUpdate = z.infer<typeof priorityAreaConfigUpdateSchema>

/** Response — server-side fields included. */
export const priorityAreaConfigResponseSchema = priorityAreaConfigBaseSchema.extend({
  id: z.number().int().positive(),
  created_at: z.string(),
  updated_at: z.string(),
})

export type PriorityAreaConfigResponse = z.infer<typeof priorityAreaConfigResponseSchema>

// ==============================================================================
// PRIORITY OBJECT CONFIG (UT đối tượng — group_code + sub_code)
// ==============================================================================

export const priorityObjectConfigBaseSchema = z.object({
  academic_year: academicYearField,
  group_code: z
    .string()
    .regex(GROUP_CODE_REGEX, "Mã nhóm UT không hợp lệ (VD: UT1, UT2)"),
  sub_code: z
    .string()
    .regex(SUB_CODE_REGEX, "sub_code phải là 2 chữ số (VD: 01, 04, 07)"),
  description: z.string().min(1, "Mô tả bắt buộc"),
  bonus_points: bonusPointsField,
  evidence_doc_type: z.string().max(100).nullable().optional(),
  effective_from: dateField.nullable().optional(),
  effective_to: dateField.nullable().optional(),
})

export type PriorityObjectConfigBase = z.infer<typeof priorityObjectConfigBaseSchema>

export const priorityObjectConfigCreateSchema = priorityObjectConfigBaseSchema

export type PriorityObjectConfigCreate = z.infer<typeof priorityObjectConfigCreateSchema>

export const priorityObjectConfigUpdateSchema = z.object({
  description: z.string().min(1).optional(),
  bonus_points: bonusPointsField.optional(),
  evidence_doc_type: z.string().max(100).nullable().optional(),
  effective_to: dateField.nullable().optional(),
})

export type PriorityObjectConfigUpdate = z.infer<typeof priorityObjectConfigUpdateSchema>

export const priorityObjectConfigResponseSchema = priorityObjectConfigBaseSchema.extend({
  id: z.number().int().positive(),
  created_at: z.string(),
  updated_at: z.string(),
})

export type PriorityObjectConfigResponse = z.infer<typeof priorityObjectConfigResponseSchema>

// ==============================================================================
// CLONE + SEED REQUESTS
// ==============================================================================

export const priorityConfigCloneRequestSchema = z
  .object({
    from_year: academicYearField,
    to_year: academicYearField,
  })
  .refine((d) => d.from_year !== d.to_year, {
    message: "from_year và to_year phải khác nhau",
    path: ["to_year"],
  })

export type PriorityConfigCloneRequest = z.infer<typeof priorityConfigCloneRequestSchema>

export const priorityConfigCloneResponseSchema = z.object({
  cloned_areas: z.number().int().min(0),
  cloned_objects: z.number().int().min(0),
})

export type PriorityConfigCloneResponse = z.infer<typeof priorityConfigCloneResponseSchema>

export const priorityConfigSeedDefaultsRequestSchema = z.object({
  academic_year: academicYearField,
})

export type PriorityConfigSeedDefaultsRequest = z.infer<
  typeof priorityConfigSeedDefaultsRequestSchema
>

export const priorityConfigSeedDefaultsResponseSchema = z.object({
  inserted_areas: z.number().int().min(0),
  inserted_objects: z.number().int().min(0),
  skipped_existing: z.boolean(),
})

export type PriorityConfigSeedDefaultsResponse = z.infer<
  typeof priorityConfigSeedDefaultsResponseSchema
>
