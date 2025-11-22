// src/types/tuition-discount.types.ts

/**
 * Types for Tuition Discount Policy Management
 */

// =============================================================================
// ENUMS
// =============================================================================

export type DiscountType = "amount" | "percentage";

// =============================================================================
// JSON FIELD TYPES
// =============================================================================

/**
 * Phạm vi áp dụng chính sách
 */
export interface ApplicableScope {
  all_programs?: boolean;           // Áp dụng tất cả chương trình
  degree_levels?: string[];         // Danh sách trình độ (vd: ["Cao đẳng"])
  major_program_ids?: number[];     // Danh sách ID ngành
  major_program_codes?: string[];   // Danh sách mã ngành
  is_heavy_only?: boolean;          // Chỉ ngành nặng nhọc, độc hại
  offering_ids?: number[];          // Danh sách ID loại hình đào tạo
}

/**
 * Điều kiện đối tượng sinh viên
 */
export interface TargetCriteria {
  priority_types?: string[];        // Loại đối tượng ưu tiên
  regions?: string[];               // Vùng miền
  min_gpa?: number;                 // Điểm TB tối thiểu
  gender?: string;                  // Giới tính
  age_max?: number;                 // Tuổi tối đa
}

// =============================================================================
// MAIN TYPES
// =============================================================================

/**
 * Base interface cho TuitionDiscountPolicy
 */
export interface TuitionDiscountPolicyBase {
  code: string;
  name: string;
  description?: string | null;
  discount_type: DiscountType;
  discount_value: number;
  valid_from?: string | null;       // ISO date string
  valid_to?: string | null;         // ISO date string
  applicable_scope: ApplicableScope;
  target_criteria: TargetCriteria;
  is_stackable: boolean;
  priority: number;
  max_usage?: number | null;
  is_active: boolean;
}

/**
 * Full TuitionDiscountPolicy with DB fields
 */
export interface TuitionDiscountPolicy extends TuitionDiscountPolicyBase {
  id: number;
  current_usage: number;
  created_at: string;
  updated_at: string;
  created_by_user_id?: number | null;
  updated_by_user_id?: number | null;

  // Computed fields
  is_expired?: boolean;
  is_within_validity?: boolean;
  has_quota_remaining?: boolean;
}

/**
 * Policy with creator info
 */
export interface TuitionDiscountPolicyWithCreator extends TuitionDiscountPolicy {
  created_by_name?: string | null;
  updated_by_name?: string | null;
}

// =============================================================================
// CREATE / UPDATE TYPES
// =============================================================================

/**
 * Create payload
 */
export interface TuitionDiscountPolicyCreate {
  code: string;
  name: string;
  description?: string | null;
  discount_type: DiscountType;
  discount_value: number;
  valid_from?: string | null;
  valid_to?: string | null;
  applicable_scope?: ApplicableScope;
  target_criteria?: TargetCriteria;
  is_stackable?: boolean;
  priority?: number;
  max_usage?: number | null;
  is_active?: boolean;
}

/**
 * Update payload (all fields optional)
 */
export interface TuitionDiscountPolicyUpdate {
  name?: string;
  description?: string | null;
  discount_type?: DiscountType;
  discount_value?: number;
  valid_from?: string | null;
  valid_to?: string | null;
  applicable_scope?: ApplicableScope;
  target_criteria?: TargetCriteria;
  is_stackable?: boolean;
  priority?: number;
  max_usage?: number | null;
  is_active?: boolean;
}

// =============================================================================
// LIST / PAGINATION
// =============================================================================

export interface TuitionDiscountPolicyListResponse {
  items: TuitionDiscountPolicy[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// =============================================================================
// DISCOUNT CALCULATION
// =============================================================================

export interface DiscountCalculationRequest {
  tuition_fee: number;
  major_program_id?: number;
  major_program_code?: string;
  offering_id?: number;
  is_heavy_program?: boolean;
  student_priority_type?: string;
  student_region?: string;
  student_gpa?: number;
}

export interface AppliedDiscount {
  policy_id: number;
  policy_code: string;
  policy_name: string;
  discount_type: DiscountType;
  discount_value: number;
  discount_amount: number;
}

export interface DiscountCalculationResponse {
  original_tuition: number;
  total_discount: number;
  final_tuition: number;
  applied_policies: AppliedDiscount[];
}

// =============================================================================
// HELPER CONSTANTS
// =============================================================================

export const DISCOUNT_TYPE_LABELS: Record<DiscountType, string> = {
  amount: "Số tiền (VNĐ)",
  percentage: "Phần trăm (%)",
};

export const PRIORITY_TYPE_OPTIONS = [
  { value: "con_thuong_binh", label: "Con thương binh" },
  { value: "con_liet_si", label: "Con liệt sĩ" },
  { value: "ho_ngheo", label: "Hộ nghèo" },
  { value: "ho_can_ngheo", label: "Hộ cận nghèo" },
  { value: "dan_toc_thieu_so", label: "Dân tộc thiểu số" },
  { value: "mo_coi", label: "Mồ côi" },
  { value: "khuyet_tat", label: "Khuyết tật" },
];

export const REGION_OPTIONS = [
  { value: "mien_nui", label: "Miền núi" },
  { value: "vung_sau", label: "Vùng sâu" },
  { value: "vung_xa", label: "Vùng xa" },
  { value: "bien_gioi", label: "Biên giới" },
  { value: "hai_dao", label: "Hải đảo" },
];
