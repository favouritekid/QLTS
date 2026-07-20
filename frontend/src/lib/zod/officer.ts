import { z } from "zod";

/**
 * Contract cho bảng "điểm bận" (`GET /api/officer/distribution-panel`).
 *
 * Mirror nghiêm ngặt Pydantic `OfficerDistributionEntry` / `OfficerDistributionPanel`
 * (Backend_FastAPI/app/schemas/officer.py). Parse ở api client để lệch contract
 * nổ NGAY thay vì render số sai — mọi con số tải ở đây do engine chia lead tính,
 * frontend TUYỆT ĐỐI không tính lại.
 */
export const officerArchetypeSchema = z.object({
  key: z.string(),
  label: z.string(),
});

export const officerDistributionEntrySchema = z.object({
  rank: z.number().int(),
  user_id: z.number().int(),
  // Backend CỐ Ý không trả `username` (login-id đồng nghiệp = PII vô ích ở đây).
  full_name: z.string(),
  unit_id: z.number().int().nullable().optional(),
  unit_name: z.string().nullable().optional(),
  /** Chế độ chấm điểm của ĐƠN VỊ dòng này (per-unit). */
  scoring_mode: z.string().nullable().optional(),

  // --- Số liệu tải (nguyên bản từ engine) ---
  workload: z.number().int(), // Lead đang giữ
  max_capacity: z.number().int(), // Khả năng nhận
  weight: z.number().int(), // Ưu tiên kỳ cựu (×N)
  self_sourced: z.number().int(), // Lead tự tìm
  tuition_hold: z.number().int(), // Hồ sơ đã đóng tiền
  /** Phần GIAO tự-tìm ∩ đã-đóng-tiền — chỉ bị trừ MỘT lần. */
  overlap: z.number().int(),
  dist_load: z.number().int(), // Lead hệ thống tính
  /** = self_sourced + tuition_hold − overlap (KHÔNG phải phép cộng đơn thuần). */
  deducted: z.number().int(),
  real_util_pct: z.number(), // dist_load/cap  (%)
  fill_pct: z.number(), // workload/cap   (%) — chỗ đầy thật
  eff_util_pct: z.number(), // ĐIỂM BẬN = dist/(cap*weight) (%)
  score: z.number(),
  overload_gate_pct: z.number(), // (workload-tuition)/cap (%) — ngưỡng 80%

  // --- Cờ trạng thái ---
  overloaded: z.boolean(),
  at_capacity: z.boolean(),
  eligible_for_assignment: z.boolean(),
  availability_status: z.string(),

  // --- Diễn giải (backend tính) ---
  archetype: officerArchetypeSchema,
  diagnosis: z.string(),
  /** 🔒 Backend chỉ trả cho chính người đang xem. */
  boost: z.string().nullable().optional(),
  is_current_user: z.boolean(),
});

export const officerDistributionPanelSchema = z.object({
  unit_id: z.number().int().nullable().optional(),
  total_officers: z.number().int(),
  /** Tóm tắt: mode chung | "mixed" | null. Chính xác ở entries[].scoring_mode. */
  scoring_mode: z.string().nullable().optional(),
  flags_snapshot: z.record(z.string(), z.boolean()),
  entries: z.array(officerDistributionEntrySchema),
});

export type OfficerArchetype = z.infer<typeof officerArchetypeSchema>;
export type OfficerDistributionEntry = z.infer<
  typeof officerDistributionEntrySchema
>;
export type OfficerDistributionPanel = z.infer<
  typeof officerDistributionPanelSchema
>;
