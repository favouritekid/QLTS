import { z } from "zod"

// Collaborator Create
export const collaboratorCreateSchema = z.object({
  full_name: z.string()
    .min(1, "Họ tên không được để trống")
    .max(255, "Không được quá 255 ký tự")
    .trim(),
  phone: z.string()
    .min(1, "Số điện thoại không được để trống")
    .max(20, "Không được quá 20 ký tự")
    .trim(),
  email: z.union([
    z.string().email("Email không hợp lệ"),
    z.literal(""),
  ]).optional().nullable().transform(v => v === "" ? null : v),
  unit_id: z.number({ error: "Vui lòng chọn đơn vị" }),
  user_id: z.number().optional().nullable(),
  managed_by_officer_id: z.number().optional().nullable(),
  id_card_number: z.string().max(20).optional().nullable().transform(v => v === "" ? null : v),
  bank_account: z.string().max(50).optional().nullable().transform(v => v === "" ? null : v),
  bank_name: z.string().max(100).optional().nullable().transform(v => v === "" ? null : v),
  address: z.string().max(500).optional().nullable().transform(v => v === "" ? null : v),
  notes: z.string().optional().nullable().transform(v => v === "" ? null : v),
})

export type CollaboratorCreateFormData = z.infer<typeof collaboratorCreateSchema>

// Collaborator Update
export const collaboratorUpdateSchema = collaboratorCreateSchema.partial()
export type CollaboratorUpdateFormData = z.infer<typeof collaboratorUpdateSchema>

// Lead Claim Data
export const leadClaimDataSchema = z.object({
  full_name: z.string()
    .min(1, "Họ tên không được để trống")
    .max(255)
    .trim(),
  phone: z.string()
    .min(1, "Số điện thoại không được để trống")
    .max(20)
    .trim(),
  email: z.union([
    z.string().email("Email không hợp lệ"),
    z.literal(""),
  ]).optional().nullable().transform(v => v === "" ? null : v),
  notes: z.string().max(500).optional().nullable().transform(v => v === "" ? null : v),
})

export type LeadClaimFormData = z.infer<typeof leadClaimDataSchema>

// Claim Review
export const leadClaimReviewSchema = z.object({
  status: z.enum(["approved", "rejected"]),
  rejection_reason: z.string().max(500).optional().nullable(),
}).refine(
  (data) => data.status !== "rejected" || (data.rejection_reason && data.rejection_reason.trim().length > 0),
  { message: "Vui lòng nhập lý do từ chối", path: ["rejection_reason"] }
)

export type LeadClaimReviewFormData = z.infer<typeof leadClaimReviewSchema>
