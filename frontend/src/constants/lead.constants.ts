// src/constants/lead.constants.ts
/**
 * Centralized Lead Constants
 *
 * Single source of truth for lead-related enums and options.
 * Used across LeadFilters and other lead components.
 */

import type { LeadStatus, LeadSource } from "@/types/lead.types";

// =============================================================================
// LEAD STATUS OPTIONS
// =============================================================================

export interface LeadStatusOption {
  value: LeadStatus;
  label: string;
  color: string;
  description?: string;
}

export const LEAD_STATUS_OPTIONS: LeadStatusOption[] = [
  {
    value: "new",
    label: "Mới",
    color: "bg-info-500",
    description: "Lead mới chưa được xử lý",
  },
  {
    value: "assigned",
    label: "Đã phân công",
    color: "bg-purple-500",
    description: "Đã phân công cho tư vấn viên",
  },
  {
    value: "contacted",
    label: "Đã liên hệ",
    color: "bg-cyan-500",
    description: "Đã liên hệ với lead",
  },
  {
    value: "qualified",
    label: "Đủ điều kiện",
    color: "bg-success-500",
    description: "Lead đủ điều kiện chuyển đổi",
  },
  {
    value: "unqualified",
    label: "Không đủ điều kiện",
    color: "bg-muted-foreground",
    description: "Lead không đủ điều kiện",
  },
  {
    value: "converted",
    label: "Đã chuyển đổi",
    color: "bg-success-500",
    description: "Đã chuyển đổi thành sinh viên",
  },
  {
    value: "rejected",
    label: "Đã từ chối",
    color: "bg-error-500",
    description: "Lead bị từ chối",
  },
];

// ✅ PERFORMANCE: O(1) lookup Maps (pre-computed at module load)
// Replaces O(n) .find() calls with O(1) Map.get()
const LEAD_STATUS_MAP = new Map(
  LEAD_STATUS_OPTIONS.map((option) => [option.value, option])
);
const LEAD_STATUS_COLOR_MAP = new Map(
  LEAD_STATUS_OPTIONS.map((option) => [option.value, option.color])
);
const LEAD_STATUS_LABEL_MAP = new Map(
  LEAD_STATUS_OPTIONS.map((option) => [option.value, option.label])
);

// Helper to get status by value - O(1) lookup
export const getLeadStatusOption = (value: LeadStatus): LeadStatusOption | undefined =>
  LEAD_STATUS_MAP.get(value);

// Helper to get status color - O(1) lookup
export const getLeadStatusColor = (value: LeadStatus): string =>
  LEAD_STATUS_COLOR_MAP.get(value) ?? "bg-muted-foreground";

// Helper to get status label - O(1) lookup
export const getLeadStatusLabel = (value: LeadStatus): string =>
  LEAD_STATUS_LABEL_MAP.get(value) ?? value;

// =============================================================================
// LEAD SOURCE OPTIONS
// =============================================================================

export interface LeadSourceOption {
  value: LeadSource;
  label: string;
  icon?: string;
}

export const LEAD_SOURCE_OPTIONS: LeadSourceOption[] = [
  { value: "website", label: "Website" },
  { value: "referral", label: "Giới thiệu" },
  { value: "social_media", label: "Mạng xã hội" },
  { value: "walk_in", label: "Đến trực tiếp" },
  { value: "email", label: "Email" },
  { value: "phone", label: "Điện thoại" },
  { value: "event", label: "Sự kiện" },
  { value: "other", label: "Khác" },
];

// ✅ PERFORMANCE: O(1) lookup Maps for source options
const LEAD_SOURCE_MAP = new Map(
  LEAD_SOURCE_OPTIONS.map((option) => [option.value, option])
);
const LEAD_SOURCE_LABEL_MAP = new Map(
  LEAD_SOURCE_OPTIONS.map((option) => [option.value, option.label])
);

// Helper to get source by value - O(1) lookup
export const getLeadSourceOption = (value: LeadSource): LeadSourceOption | undefined =>
  LEAD_SOURCE_MAP.get(value);

// Helper to get source label - O(1) lookup
export const getLeadSourceLabel = (value: LeadSource): string =>
  LEAD_SOURCE_LABEL_MAP.get(value) ?? value;

// =============================================================================
// STATUS WORKFLOW HELPERS
// =============================================================================

/**
 * Status IDs that require additional information (complex disposition)
 * @deprecated These constants are no longer actively used
 */
export const COMPLEX_STATUS_IDS: LeadStatus[] = [
  "qualified",
  "unqualified",
  "converted",
  "rejected",
];

/**
 * Status IDs that can be scheduled for follow-up
 */
export const SCHEDULABLE_STATUS_IDS: LeadStatus[] = ["contacted", "qualified"];

// ✅ PERFORMANCE: O(1) lookup Sets for status checks
const COMPLEX_STATUS_SET = new Set(COMPLEX_STATUS_IDS);
const SCHEDULABLE_STATUS_SET = new Set(SCHEDULABLE_STATUS_IDS);

/**
 * Check if a status is complex (requires additional info) - O(1) lookup
 */
export const isComplexStatus = (status: LeadStatus): boolean =>
  COMPLEX_STATUS_SET.has(status);

/**
 * Check if a status is schedulable - O(1) lookup
 */
export const isSchedulableStatus = (status: LeadStatus): boolean =>
  SCHEDULABLE_STATUS_SET.has(status);

// =============================================================================
// LEAD SCORE COLOR & LABEL (Canonical — use everywhere)
// =============================================================================
// 4-tier system: ≥70 success, ≥50 info, ≥30 warning, <30 muted
// DO NOT duplicate this logic in components — import from here.

/**
 * Get score color classes (border variant for badges)
 */
export const getLeadScoreColor = (score: number): string => {
  if (score >= 70) return "bg-success-100 text-success-700 border-success-200";
  if (score >= 50) return "bg-info-100 text-info-700 border-info-200";
  if (score >= 30) return "bg-warning-100 text-warning-700 border-warning-200";
  return "bg-muted text-muted-foreground border-border";
};

/**
 * Get score color classes (text variant for inline display)
 */
export const getLeadScoreTextColor = (score: number): string => {
  if (score >= 70) return "text-success-600 bg-success-50";
  if (score >= 50) return "text-info-600 bg-info-50";
  if (score >= 30) return "text-warning-600 bg-warning-50";
  return "text-muted-foreground bg-muted";
};

/**
 * Get human-readable score label
 */
export const getLeadScoreLabel = (score: number): string => {
  if (score >= 70) return "Tiềm năng cao";
  if (score >= 50) return "Trung bình";
  if (score >= 30) return "Thấp";
  return "Rất thấp";
};

/**
 * Get short score label (for compact badges)
 */
export const getLeadScoreLabelShort = (score: number): string => {
  if (score >= 70) return "Cao";
  if (score >= 50) return "TB";
  if (score >= 30) return "Thấp";
  return "Yếu";
};

// =============================================================================
// EDUCATION LEVEL LABELS (Canonical — use everywhere)
// =============================================================================
// DO NOT duplicate this logic in components — import from here.

import type { EducationLevel } from "@/types/lead.types";

const EDUCATION_LEVEL_LABELS: Record<string, string> = {
  high_school: "THPT",
  diploma: "Trung cấp/Cao đẳng",
  bachelor: "Đại học",
  master: "Thạc sĩ",
  phd: "Tiến sĩ",
  other: "Khác",
};

/**
 * Get Vietnamese label for education level
 */
export const getEducationLevelLabel = (level: EducationLevel | string | null | undefined): string | null => {
  if (!level) return null;
  return EDUCATION_LEVEL_LABELS[level] || level;
};

// =============================================================================
// LEAD VALIDITY OPTIONS (CTV System)
// =============================================================================

export interface LeadValidityOption {
  value: string
  label: string
  color: string
}

export const LEAD_VALIDITY_OPTIONS: LeadValidityOption[] = [
  { value: "raw", label: "Chưa kiểm tra", color: "bg-gray-400" },
  { value: "duplicate", label: "Trùng lặp", color: "bg-orange-500" },
  { value: "invalid", label: "Không hợp lệ", color: "bg-red-500" },
  { value: "valid", label: "Hợp lệ", color: "bg-green-500" },
  { value: "qualified", label: "Đủ điều kiện", color: "bg-blue-500" },
]

export const LEAD_VALIDITY_MAP = new Map(
  LEAD_VALIDITY_OPTIONS.map((o) => [o.value, o])
)

export function getLeadValidityOption(value: string): LeadValidityOption | undefined {
  return LEAD_VALIDITY_MAP.get(value)
}

export function getLeadValidityLabel(value: string): string {
  return LEAD_VALIDITY_MAP.get(value)?.label ?? value
}

// =============================================================================
// STAGE BRANCHES — cây filter "Giai đoạn" 2 cấp (LEAD_STAGE_TREE_FILTER_PLAN)
// =============================================================================
// Cha = nhánh (gộp pipeline_stage theo "khâu lead dừng"), lá = consultation_status.
// CHỈ hardcode stage→nhánh ở đây; tên/màu/đếm của lá lấy runtime từ API
// (thin-client). Cây gửi consultation_status_id (KHÔNG phải pipeline_stage_id);
// vì lead.pipeline_stage_id sync TỪ consultation_status.stage_id nên chọn nhánh
// XẤP XỈ lọc theo stage — không khớp tuyệt đối nếu 2 cột lệch nhau.

export interface StageBranch {
  key: string
  label: string
  stageIds: string[] // pipeline_stage ids; [] = universal (stage_id == null)
}

export const STAGE_BRANCHES: StageBranch[] = [
  { key: "tu_van", label: "Tư vấn", stageIds: ["stg01", "stg02"] },
  { key: "ho_so", label: "Hồ sơ", stageIds: ["stg03", "stg04"] },
  { key: "hoc_phi", label: "Học phí", stageIds: ["stg05"] },
  { key: "nhap_hoc", label: "Đã nhập học", stageIds: ["stg06"] },
  { key: "khong_di_hoc", label: "Không đi học", stageIds: ["stg07"] },
  // "Hoạt động khác" = universal (stage_id null) + orphan (stage không thuộc nhánh)
  { key: "khac", label: "Hoạt động khác", stageIds: [] },
]

// Preset "Đã vào hồ sơ/tài chính" = nhánh Hồ sơ + Học phí + Đã nhập học (loại
// "Không đi học"). Derive từ STAGE_BRANCHES (1 nguồn) thay vì hardcode lại stage
// ids — đổi nhánh thì preset tự cập nhật, không lệch.
export const ONBOARDED_STAGE_IDS = STAGE_BRANCHES.filter((b) =>
  ["ho_so", "hoc_phi", "nhap_hoc"].includes(b.key),
).flatMap((b) => b.stageIds)
