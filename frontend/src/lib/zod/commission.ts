import { z } from "zod"

// Commission Policy Create
export const commissionPolicyCreateSchema = z.object({
  name: z.string()
    .min(1, "Tên chính sách không được để trống")
    .max(255, "Không được quá 255 ký tự")
    .trim(),
  description: z.string().optional().nullable().transform(v => v === "" ? null : v),
  trigger_status_id: z.string().min(1, "Vui lòng chọn trạng thái trigger"),
  calculation_type: z.enum(["fixed", "percentage"], {
    message: "Vui lòng chọn loại tính hoa hồng",
  }),
  fixed_amount: z.number().int("Số tiền phải là số nguyên").positive("Số tiền phải lớn hơn 0").optional().nullable(),
  percentage: z.number().positive("Phần trăm phải lớn hơn 0").max(100, "Phần trăm phải từ 0-100").optional().nullable(),
  unit_id: z.number().optional().nullable(),
  offering_id: z.number().optional().nullable(),
  effective_from: z.string().min(1, "Vui lòng chọn ngày bắt đầu"),
  effective_to: z.string().optional().nullable().transform(v => v === "" ? null : v),
  is_active: z.boolean().default(true),
}).refine(
  (data) => {
    if (data.calculation_type === "fixed") return data.fixed_amount != null && data.fixed_amount > 0
    return true
  },
  { message: "Vui lòng nhập số tiền cố định", path: ["fixed_amount"] }
).refine(
  (data) => {
    if (data.calculation_type === "percentage") return data.percentage != null && data.percentage > 0
    return true
  },
  { message: "Vui lòng nhập phần trăm hoa hồng", path: ["percentage"] }
)

export type CommissionPolicyCreateFormData = z.infer<typeof commissionPolicyCreateSchema>

// Commission Policy Update
export const commissionPolicyUpdateSchema = z.object({
  name: z.string().min(1).max(255).trim().optional(),
  description: z.string().optional().nullable().transform(v => v === "" ? null : v),
  trigger_status_id: z.string().min(1).optional(),
  calculation_type: z.enum(["fixed", "percentage"]).optional(),
  fixed_amount: z.number().positive("Số tiền phải lớn hơn 0").optional().nullable(),
  percentage: z.number().positive("Phần trăm phải lớn hơn 0").max(100, "Phần trăm phải từ 0-100").optional().nullable(),
  unit_id: z.number().optional().nullable(),
  offering_id: z.number().optional().nullable(),
  effective_from: z.string().optional(),
  effective_to: z.string().optional().nullable().transform(v => v === "" ? null : v),
  is_active: z.boolean().optional(),
})

export type CommissionPolicyUpdateFormData = z.infer<typeof commissionPolicyUpdateSchema>

// Commission Reject
export const commissionRejectSchema = z.object({
  rejection_reason: z.string()
    .min(1, "Vui lòng nhập lý do từ chối")
    .max(500, "Không được quá 500 ký tự"),
})

export type CommissionRejectFormData = z.infer<typeof commissionRejectSchema>

// Commission Pay
export const commissionPaySchema = z.object({
  payment_reference: z.string().max(255).optional().nullable().transform(v => v === "" ? null : v),
})

export type CommissionPayFormData = z.infer<typeof commissionPaySchema>
