// src/constants/lead.constants.ts
/**
 * Centralized Lead Constants
 *
 * Single source of truth for lead-related enums and options.
 * Used across LeadFilters, QuickDisposition, and other lead components.
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
    label: "New",
    color: "bg-blue-500",
    description: "Lead mới chưa được xử lý",
  },
  {
    value: "assigned",
    label: "Assigned",
    color: "bg-purple-500",
    description: "Đã phân công cho tư vấn viên",
  },
  {
    value: "contacted",
    label: "Contacted",
    color: "bg-cyan-500",
    description: "Đã liên hệ với lead",
  },
  {
    value: "qualified",
    label: "Qualified",
    color: "bg-emerald-500",
    description: "Lead đủ điều kiện chuyển đổi",
  },
  {
    value: "unqualified",
    label: "Unqualified",
    color: "bg-gray-500",
    description: "Lead không đủ điều kiện",
  },
  {
    value: "converted",
    label: "Converted",
    color: "bg-green-500",
    description: "Đã chuyển đổi thành sinh viên",
  },
  {
    value: "rejected",
    label: "Rejected",
    color: "bg-red-500",
    description: "Lead bị từ chối",
  },
];

// Helper to get status by value
export const getLeadStatusOption = (value: LeadStatus): LeadStatusOption | undefined =>
  LEAD_STATUS_OPTIONS.find((option) => option.value === value);

// Helper to get status color
export const getLeadStatusColor = (value: LeadStatus): string =>
  getLeadStatusOption(value)?.color ?? "bg-gray-400";

// Helper to get status label
export const getLeadStatusLabel = (value: LeadStatus): string =>
  getLeadStatusOption(value)?.label ?? value;

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
  { value: "referral", label: "Referral" },
  { value: "social_media", label: "Social Media" },
  { value: "walk_in", label: "Walk-in" },
  { value: "email", label: "Email" },
  { value: "phone", label: "Phone" },
  { value: "event", label: "Event" },
  { value: "other", label: "Other" },
];

// Helper to get source by value
export const getLeadSourceOption = (value: LeadSource): LeadSourceOption | undefined =>
  LEAD_SOURCE_OPTIONS.find((option) => option.value === value);

// Helper to get source label
export const getLeadSourceLabel = (value: LeadSource): string =>
  getLeadSourceOption(value)?.label ?? value;

// =============================================================================
// STATUS WORKFLOW HELPERS (for QuickDisposition)
// =============================================================================

/**
 * Status IDs that require additional information (complex disposition)
 * Used by QuickDisposition to determine which statuses need extra forms
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

/**
 * Check if a status is complex (requires additional info)
 */
export const isComplexStatus = (status: LeadStatus): boolean =>
  COMPLEX_STATUS_IDS.includes(status);

/**
 * Check if a status is schedulable
 */
export const isSchedulableStatus = (status: LeadStatus): boolean =>
  SCHEDULABLE_STATUS_IDS.includes(status);
