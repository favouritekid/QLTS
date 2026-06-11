/**
 * Zod schemas for admin vn_school + KV assignment CRUD (PR-B).
 *
 * Mirror `Backend_FastAPI/app/schemas/vn_locality.py` (school admin). Reuse
 * `AREA_CODE_REGEX` + `csvImportResponseSchema` (single source). DELETE school =
 * deactivate (BE); KV assignment quản lý qua sub-resource.
 */
import { z } from "zod"

import { AREA_CODE_REGEX } from "@/lib/zod/priority-config"

export {
  csvImportResponseSchema,
  type CsvImportResponse,
} from "@/lib/zod/commune-kv"

export const VN_SCHOOL_LEVELS = [
  "THCS",
  "THPT",
  "THCS_THPT",
  "TRUNG_HOC_NGHE",
  "OTHER",
] as const
export type VnSchoolLevel = (typeof VN_SCHOOL_LEVELS)[number]

export const VN_SCHOOL_LEVEL_LABELS: Record<VnSchoolLevel, string> = {
  THCS: "THCS",
  THPT: "THPT",
  THCS_THPT: "Liên cấp THCS-THPT",
  TRUNG_HOC_NGHE: "Trung học nghề",
  OTHER: "Khác",
}

const kvCodeField = z
  .string()
  .regex(AREA_CODE_REGEX, "Mã KV không hợp lệ (VD: KV1, KV2-NT, KV3)")
const yearField = z.number().int().min(2000).max(2100)

// --- school ---

export const schoolCreateSchema = z.object({
  moet_school_code: z.string().min(1, "Mã trường MOET bắt buộc").max(10),
  moet_province_code: z.string().min(1, "Mã tỉnh MOET bắt buộc").max(3),
  moet_district_code: z.string().max(5).optional(),
  name: z.string().min(1, "Tên trường bắt buộc").max(255),
  address: z.string().optional(),
  province: z.string().min(1, "Tỉnh bắt buộc").max(100),
  district: z.string().max(100).optional(),
  ward: z.string().max(100).optional(),
  level: z.enum(VN_SCHOOL_LEVELS),
  is_dtnt: z.boolean().default(false),
})
export type SchoolCreate = z.infer<typeof schoolCreateSchema>

export const schoolUpdateSchema = z.object({
  moet_district_code: z.string().max(5).optional(),
  name: z.string().min(1).max(255).optional(),
  address: z.string().optional(),
  province: z.string().min(1).max(100).optional(),
  district: z.string().max(100).optional(),
  ward: z.string().max(100).optional(),
  level: z.enum(VN_SCHOOL_LEVELS).optional(),
  is_dtnt: z.boolean().optional(),
})
export type SchoolUpdate = z.infer<typeof schoolUpdateSchema>

export const schoolResponseSchema = z.object({
  id: z.number().int().positive(),
  moet_school_code: z.string(),
  moet_province_code: z.string(),
  moet_district_code: z.string().nullable(),
  name: z.string(),
  address: z.string().nullable(),
  province: z.string(),
  district: z.string().nullable(),
  ward: z.string().nullable(),
  level: z.string(),
  is_dtnt: z.boolean(),
  is_active: z.boolean(),
  current_kv: z.string().nullable(),
})
export type SchoolResponse = z.infer<typeof schoolResponseSchema>

export const schoolListResponseSchema = z.object({
  items: z.array(schoolResponseSchema),
  total: z.number().int().min(0),
  page: z.number().int().min(1),
  page_size: z.number().int().min(1),
})
export type SchoolListResponse = z.infer<typeof schoolListResponseSchema>

export const schoolProvinceSchema = z.object({
  moet_province_code: z.string(),
  province: z.string(),
})
export type SchoolProvince = z.infer<typeof schoolProvinceSchema>

// --- KV assignment ---

export const kvAssignmentCreateSchema = z
  .object({
    kv_code: kvCodeField,
    effective_from_year: yearField,
    effective_to_year: yearField.nullable().optional(),
    source: z.string().min(1).max(50).default("manual_admin"),
    notes: z.string().nullable().optional(),
  })
  .refine(
    (d) =>
      d.effective_to_year == null ||
      d.effective_to_year >= d.effective_from_year,
    { message: "Năm kết thúc phải >= năm bắt đầu", path: ["effective_to_year"] },
  )
export type KvAssignmentCreate = z.infer<typeof kvAssignmentCreateSchema>

export const kvAssignmentUpdateSchema = z
  .object({
    kv_code: kvCodeField.optional(),
    effective_from_year: yearField.optional(),
    effective_to_year: yearField.nullable().optional(),
    source: z.string().min(1).max(50).optional(),
    notes: z.string().nullable().optional(),
  })
  // Chỉ kiểm khi CẢ HAI năm có mặt (nhất quán với create — FE form luôn gửi cả 2).
  .refine(
    (d) =>
      d.effective_from_year == null ||
      d.effective_to_year == null ||
      d.effective_to_year >= d.effective_from_year,
    { message: "Năm kết thúc phải >= năm bắt đầu", path: ["effective_to_year"] },
  )
export type KvAssignmentUpdate = z.infer<typeof kvAssignmentUpdateSchema>

export const kvAssignmentResponseSchema = z.object({
  id: z.number().int().positive(),
  school_id: z.number().int().positive(),
  kv_code: z.string(),
  effective_from_year: z.number().int(),
  effective_to_year: z.number().int().nullable(),
  source: z.string(),
  notes: z.string().nullable(),
})
export type KvAssignmentResponse = z.infer<typeof kvAssignmentResponseSchema>
