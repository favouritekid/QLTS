/**
 * Zod schemas — công cụ ghép tên trường THCS gõ tay (owner 22-11).
 *
 * Mirror `Backend_FastAPI/app/schemas/thcs_school_mapping.py`. Nhóm chỉ mang tên
 * trường + số đếm (không dữ liệu cá nhân). Khoá nhóm (`normalized_name`) do BE
 * chuẩn hoá — FE gửi lại NGUYÊN chuỗi nhận được, không tự chuẩn hoá.
 */
import { z } from "zod"

import {
  schoolCreateSchema,
  schoolResponseSchema,
} from "@/lib/zod/vn-school-admin"

export const thcsNameVariantSchema = z.object({
  text: z.string(),
  row_count: z.number().int().min(0),
})

export const thcsGroupMappingSchema = z.object({
  school_id: z.number().int().positive(),
  school_name: z.string(),
  moet_school_code: z.string(),
  school_level: z.string(),
  school_is_active: z.boolean(),
  /** Trường còn hoạt động + đúng cấp ⇒ lượt áp ghép dùng được. */
  usable: z.boolean(),
  mapped_by_user_id: z.number().int(),
  mapped_at: z.string(),
})
export type ThcsGroupMapping = z.infer<typeof thcsGroupMappingSchema>

export const thcsNameGroupSchema = z.object({
  normalized_name: z.string(),
  variants: z.array(thcsNameVariantSchema),
  row_count: z.number().int().min(0),
  profile_count: z.number().int().min(0),
  eligible_profile_count: z.number().int().min(0),
  same_year_row_count: z.number().int().min(0),
  mapping: thcsGroupMappingSchema.nullable(),
})
export type ThcsNameGroup = z.infer<typeof thcsNameGroupSchema>

export const thcsNameGroupListResponseSchema = z.object({
  items: z.array(thcsNameGroupSchema),
  total: z.number().int().min(0),
  page: z.number().int().min(1),
  page_size: z.number().int().min(1),
  summary: z.object({
    group_count: z.number().int().min(0),
    mapped_group_count: z.number().int().min(0),
    row_count: z.number().int().min(0),
    profile_count: z.number().int().min(0),
    blank_name_row_count: z.number().int().min(0),
  }),
})
export type ThcsNameGroupListResponse = z.infer<
  typeof thcsNameGroupListResponseSchema
>

export const thcsMapRequestSchema = z.object({
  normalized_name: z.string().min(1).max(255),
  school_id: z.number().int().positive("Chọn trường trong danh mục"),
})
export type ThcsMapRequest = z.infer<typeof thcsMapRequestSchema>

export const thcsMappingResponseSchema = z.object({
  id: z.number().int().positive(),
  normalized_name: z.string(),
  school_id: z.number().int().positive(),
  mapped_by_user_id: z.number().int(),
  mapped_at: z.string(),
})
export type ThcsMappingResponse = z.infer<typeof thcsMappingResponseSchema>

/** Trường mới từ nhóm: luôn mã nội bộ NB (KHÔNG gửi moet_school_code). */
export const thcsCreateSchoolFromGroupSchema = z.object({
  normalized_name: z.string().min(1).max(255),
  school: schoolCreateSchema.omit({ moet_school_code: true }),
})
export type ThcsCreateSchoolFromGroup = z.infer<
  typeof thcsCreateSchoolFromGroupSchema
>

export const thcsCreateSchoolFromGroupResponseSchema = z.object({
  school: schoolResponseSchema,
  mapping: thcsMappingResponseSchema,
})
export type ThcsCreateSchoolFromGroupResponse = z.infer<
  typeof thcsCreateSchoolFromGroupResponseSchema
>

export const thcsMappingApplyRequestSchema = z.object({
  dry_run: z.boolean().default(true),
  expected_rows_to_change: z.number().int().min(0).optional(),
  expected_profiles_to_change: z.number().int().min(0).optional(),
})
export type ThcsMappingApplyRequest = z.input<
  typeof thcsMappingApplyRequestSchema
>

export const thcsMappingApplyResultSchema = z.object({
  dry_run: z.boolean(),
  applied: z.boolean(),
  /** Cờ cho phép chạy thật (BE). False ⇒ nút "Áp thật" bị khoá. */
  apply_enabled: z.boolean(),
  eligible_statuses: z.array(z.string()),
  /** Năm tuyển sinh lượt áp ghép được chạm (owner câu 2). */
  academic_year: z.number().int(),
  rows_to_change: z.number().int().min(0),
  profiles_to_change: z.number().int().min(0),
  /** Phần của hồ sơ NHÁP trong số sẽ đổi (owner câu 1: báo riêng). */
  draft_rows_to_change: z.number().int().min(0),
  draft_profiles_to_change: z.number().int().min(0),
  same_year_rows: z.number().int().min(0),
  same_year_profiles: z.number().int().min(0),
  /** Owner 23-11 câu 2: hồ sơ KV ấn định tay KHÔNG bị áp — chỉ liệt kê (chạy thử và chạy thật cùng vị từ). */
  skipped_manual_kv_override_profiles: z.number().int().min(0),
  skipped_manual_kv_override_rows: z.number().int().min(0),
  skipped_manual_kv_override_profile_ids: z.array(z.number().int()),
  skipped_status_profiles: z.number().int().min(0),
  skipped_status_rows: z.number().int().min(0),
  skipped_year_profiles: z.number().int().min(0),
  skipped_year_rows: z.number().int().min(0),
  skipped_decision_profiles: z.number().int().min(0),
  unmapped_rows: z.number().int().min(0),
  unusable_mappings: z.number().int().min(0),
})
export type ThcsMappingApplyResult = z.infer<typeof thcsMappingApplyResultSchema>
