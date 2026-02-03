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
